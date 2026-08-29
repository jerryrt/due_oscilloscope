"""Serial transport, one seam, two backends.

`host/` was POSIX-only: raw termios, `os.read`/`os.write` on a bare fd,
and `select.select` to wait on the sample and console ports together.
None of that exists on Windows, so none of `host/`, the daemon, the Qt
front end or `tests/` ran there.

This is the seam. Everything above it works in terms of `Port` and
`wait_any`; everything platform-specific is below.

**The POSIX backend is the original code, moved rather than rewritten.**
That is deliberate and not laziness. This project's measured history
depends on exact write semantics - "a constant 512 bytes per write()"
is the fix for the macOS byte loss, and "the payload must go out in one
blocking write" is part of the condition objective 0c hangs in. A
rewrite that merely looked equivalent would invalidate every figure
taken on that host. macOS is the porting target now; it must not move.

The Windows backend is pyserial, which is a declared dependency
(requirements-dev.txt) and is what the tools under tools/ already use.

Waiting on several ports at once is the one thing the two backends do
genuinely differently. POSIX keeps `select`. Windows has no selectable
handle for a COM port, so `wait_any` polls `in_waiting` on a short
sleep. That costs a wakeup per interval and cannot be helped, but the
interval is bounded by the caller's timeout and the poll is cheap.
"""
from __future__ import annotations

import os
import sys
import time

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")

# Windows serial receive/transmit buffer request. 4 MB of receive holds
# about 2.2 s at the full in-spec capture rate, against the 2.2 ms the
# platform default gives. See _WindowsPort.__init__.
RX_BUFFER = 4 * 1024 * 1024
TX_BUFFER = 1 * 1024 * 1024

if WINDOWS:
    import serial                                            # noqa: F401
else:
    import fcntl
    import select
    import struct
    import termios


# --------------------------------------------------------------------- POSIX


class _PosixPort:
    """The original raw-termios port, unchanged in behaviour."""

    def __init__(self, dev, baud=None, dtr=False):
        self.dev = dev
        self.fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        if baud:
            a[4] = a[5] = getattr(termios, "B%d" % baud)
        a[6][termios.VMIN] = 0
        a[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        try:
            if dtr:
                fcntl.ioctl(self.fd, termios.TIOCMBIS,
                            struct.pack("I", termios.TIOCM_DTR |
                                        termios.TIOCM_RTS))
            elif LINUX:
                # Linux has no callout node, and that is the whole of
                # this branch.
                #
                # docs/hardware.md says "always /dev/cu.*, never
                # /dev/tty.*", scoped to macOS. The reason is that cu.*
                # is the callout device and does not touch modem
                # control lines; tty.* is the dial-in device and does.
                # Linux ships only /dev/ttyACM0, which behaves like
                # tty.*: the tty layer raises DTR and RTS in
                # tty_port_open() before userspace sees the fd, so
                # passing dtr=False is not enough - nothing has been
                # asserted *by us* and the lines are high anyway.
                #
                # On the Due those two lines are wired to the 16U2's
                # RESET and ERASE. So an ordinary open of the
                # programming port erases the flash and drops the board
                # into SAM-BA, which is what it did here: the board ran
                # Track B for 39 s, ports.py opened the console, and it
                # came back as 03eb:6124 with a blank chip. Measured on
                # the Linux bench 2026-08-29 - cleared, the same open
                # returns the identity line and the board keeps running.
                #
                # HUPCL is already absent from c_cflag above, so close()
                # does not pulse them again on the way out.
                fcntl.ioctl(self.fd, termios.TIOCMBIC,
                            struct.pack("I", termios.TIOCM_DTR |
                                        termios.TIOCM_RTS))
        except OSError:
            pass

    def fileno(self):
        return self.fd

    def read(self, n):
        try:
            return os.read(self.fd, n)
        except BlockingIOError:
            return b""

    def write(self, data):
        return os.write(self.fd, data)

    def set_blocking(self, blocking):
        fl = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        if blocking:
            fl &= ~os.O_NONBLOCK
        else:
            fl |= os.O_NONBLOCK
        fcntl.fcntl(self.fd, fcntl.F_SETFL, fl)

    def flush_input(self):
        self._flush(termios.TCIFLUSH)

    def flush_output(self):
        self._flush(termios.TCOFLUSH)

    def flush_both(self):
        self._flush(termios.TCIOFLUSH)

    def _flush(self, which):
        try:
            termios.tcflush(self.fd, which)
        except (OSError, termios.error):
            # termios.error is not an OSError - it derives straight from
            # Exception - so it has to be named separately or a flush on
            # a port that has gone away takes the process down.
            pass

    def close(self):
        os.close(self.fd)


# ------------------------------------------------------------------- Windows


class _WindowsPort:
    """pyserial, presenting the same surface.

    pyserial's own timeout would block; every caller here expects a read
    that returns what is available and nothing more, because they drive
    their own timing through wait_any. So reads are sized to in_waiting.
    """

    def __init__(self, dev, baud=None, dtr=False):
        self.dev = dev
        self._s = serial.Serial()
        self._s.port = dev
        self._s.baudrate = baud or 115200
        self._s.timeout = 0
        self._s.write_timeout = None
        # Opening asserts DTR by default, which resets the Due through
        # the 16U2 on the programming port. host/ports.py opens with DTR
        # low unless it asks otherwise, so match that rather than the
        # pyserial default.
        self._s.dtr = bool(dtr)
        self._s.rts = bool(dtr)
        self._s.open()
        self._blocking = False
        self._buf = bytearray()

        # Windows gives a COM port a 4096-byte receive buffer by default.
        # At the full in-spec capture rate of 1.82 MB/s that is 2.2 ms of
        # headroom, so any scheduling delay past two milliseconds drops
        # bytes - which arrives at the host as a frame sequence gap and
        # looks exactly like a device fault. Ask for something that holds
        # a comfortable fraction of a second instead.
        #
        # This is not tuning. Without it the stream is not continuous,
        # and invariant 5 says discontinuous data must never be presented
        # as continuous - here it would not even be counted, because the
        # loss happens above the device and below the frame numbering.
        try:
            self._s.set_buffer_size(rx_size=RX_BUFFER, tx_size=TX_BUFFER)
        except Exception:                                    # noqa: BLE001
            # Advisory: the driver may refuse or ignore the request.
            pass

    def fileno(self):
        return None                      # no selectable handle on Windows

    def pump(self):
        """Move whatever the driver holds into our own buffer.

        This is the important one. `in_waiting` only *asks*; it does not
        drain. Polling it while a writer thread holds the GIL lets the
        driver's receive buffer back up, the device's bulk IN stops being
        consumed, and the ADC ring overruns on the board - a host-side
        stall that arrives looking like a device fault, with the device's
        own overrun counter as the only clue.

        So the wait drains instead of asking, and the data lands here.
        """
        try:
            avail = self._s.in_waiting
            if avail:
                self._buf += self._s.read(avail)
        except Exception:                                    # noqa: BLE001
            pass
        return len(self._buf)

    def read(self, n):
        if len(self._buf) < n:
            self.pump()
        if not self._buf and self._blocking:
            # Blocking mode is for the drain loops that want to sit until
            # data arrives; bounded, so a dead port cannot hang a run.
            end = time.monotonic() + 0.5
            while not self._buf and time.monotonic() < end:
                time.sleep(0.0005)
                self.pump()
        if not self._buf:
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:len(out)]
        return out

    def write(self, data):
        return self._s.write(data) or 0

    def set_blocking(self, blocking):
        self._blocking = bool(blocking)

    def flush_input(self):
        try:
            self._s.reset_input_buffer()
        except Exception:                                    # noqa: BLE001
            pass

    def flush_output(self):
        try:
            self._s.reset_output_buffer()
        except Exception:                                    # noqa: BLE001
            pass

    def flush_both(self):
        self.flush_input()
        self.flush_output()

    @property
    def in_waiting(self):
        try:
            return len(self._buf) + self._s.in_waiting
        except Exception:                                    # noqa: BLE001
            return len(self._buf)

    def close(self):
        self._s.close()


Port = _WindowsPort if WINDOWS else _PosixPort


def open_raw(dev, baud=None, dtr=False):
    """Open a port raw: no line discipline, no echo, no translation."""
    return Port(dev, baud, dtr)


def wait_any(ports, timeout):
    """Return the subset of `ports` with data waiting.

    Replaces `select.select([fd, cfd], [], [], t)`. Accepts Ports and
    tolerates None entries, because several callers watch a console port
    that may not exist.
    """
    live = [p for p in ports if p is not None]
    if not live:
        if timeout:
            time.sleep(timeout)
        return []

    if not WINDOWS:
        fds = {p.fileno(): p for p in live}
        r, _, _ = select.select(list(fds), [], [], timeout)
        return [fds[fd] for fd in r]

    # No selectable handle, so this polls - but it drains as it polls
    # rather than merely asking, because a driver buffer that is not
    # emptied stalls the device (see _WindowsPort.pump). The sleep is
    # short relative to the timeouts callers pass (0.05-0.2 s), so the
    # added latency is well under a millisecond.
    end = time.monotonic() + (timeout or 0)
    while True:
        ready = [p for p in live if p.pump()]
        if ready or time.monotonic() >= end:
            return ready
        time.sleep(0.0005)


def outq_bytes(port):
    """Bytes the kernel still holds in the tty output queue, or None.

    TIOCOUTQ reports the tty layer only - it reads 0 while tens to
    hundreds of KB sit in the CDC driver below it, which is why feeding
    closed on it does not work (objective 0a). Kept because the older
    measurements used it and it is still a useful witness; None on
    Windows, which has no equivalent and no caller that needs one.
    """
    if WINDOWS:
        return None
    try:
        buf = fcntl.ioctl(port.fileno(), termios.TIOCOUTQ,
                          struct.pack("I", 0))
        return struct.unpack("I", buf)[0]
    except (OSError, AttributeError):
        return None
