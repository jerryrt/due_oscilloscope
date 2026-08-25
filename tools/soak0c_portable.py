#!/usr/bin/env python3
"""Objective 0c, reproduced without any POSIX-only code.

The macOS reproducer (tools/soak0c.py) goes through host/measure.py,
which is termios and fcntl and will not import on Windows. This one uses
pyserial and nothing else, so the same experiment can be run on Windows
or Linux - which is the open question: 0c is believed to be macOS's
CDC-ACM close path, and if that is right this script should *not* wedge
anywhere else. Nobody has checked, and a belief nobody has checked is
what the last three weeks of this objective were made of.

What it does, per cycle: open the native sample port, start playback on
the board, write 256 KB, and close **without stopping playback** - then
time the close. On macOS that hangs roughly one cycle in three, forever,
holding the port until the board is detached. Closing after stopping
playback does not hang, and that contrast is the whole experiment.

    pip install pyserial
    python tools/soak0c_portable.py                # autodetect
    python tools/soak0c_portable.py --cycles 40
    python tools/soak0c_portable.py --console COM4 --native COM5

On a wedge it asks the board to detach and re-attach its USB port
(console `=400Z`), which on macOS releases the host in 0.01-0.23 s. If
your OS never wedges, you will simply see 40 clean closes and that is
the result worth reporting.

One detail that is not cosmetic, and cost two invalid runs to find: the
payload goes out in **one blocking write**. pyserial keeps a POSIX fd
non-blocking and feeds the tty queue in select-sized chunks, and that
never wedged in 65 cycles on a host where the blocking version wedges
one cycle in four. Windows' WriteFile blocks anyway, so this only has to
be forced on POSIX - but it means "how much is outstanding at close" is
part of the condition, not just "something is outstanding".

Verified faithful on macOS: 6 wedges in 25 cycles, all 6 recovered,
against 9 in 30 for the POSIX original.
"""
import argparse
import os
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:                                          # noqa: BLE001
    sys.exit("needs pyserial:  pip install pyserial")

VID = 0x2341
PID_CONSOLE = 0x003D          # programming port (the 16U2)
PID_NATIVE = 0x003E           # native port, SAM3X's own USB

# RC 65 and RC 130 against the 39 MHz timer clock. Written out rather
# than computed so this file needs nothing from host/.
DAC_HZ = 39_000_000 // 65     # 600000
ADC_HZ = 39_000_000 // 130    # 300000

WEDGE_S = 3.0                 # a healthy close is milliseconds
PAYLOAD = bytes(256 * 1024)   # inside the 55-450 KB a CDC driver buffers


def find_ports(console=None, native=None):
    """(console, native-sample). Identified by USB VID/PID, which works
    the same on every OS - unlike "the port that answers"."""
    if console and native:
        return console, native

    cons = [p for p in list_ports.comports()
            if p.vid == VID and p.pid == PID_CONSOLE]
    nats = [p for p in list_ports.comports()
            if p.vid == VID and p.pid == PID_NATIVE]

    # The board presents two CDC functions on the native port: samples
    # on interfaces 0/1 and commands on 2/3. Windows spells that MI_00
    # and MI_02 in the hwid; elsewhere the lower interface sorts first.
    def is_sample(p):
        h = (p.hwid or "").upper()
        return "MI_00" in h or "MI_01" in h

    if len(nats) > 1:
        preferred = [p for p in nats if is_sample(p)]
        nats = preferred or sorted(nats, key=lambda p: (p.location or "",
                                                        p.device))
    if not console:
        if not cons:
            sys.exit("no programming port found (VID 2341 PID 003D); "
                     "pass --console")
        console = cons[0].device
    if not native:
        if not nats:
            sys.exit("no native port found (VID 2341 PID 003E); "
                     "pass --native")
        native = nats[0].device
    return console, native


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=40)
    ap.add_argument("--console")
    ap.add_argument("--native")
    ap.add_argument("--stop-first", action="store_true",
                    help="stop playback before closing - the control "
                         "arm, which does not wedge on macOS")
    args = ap.parse_args()

    console_dev, native_dev = find_ports(args.console, args.native)
    print(f"console (programming) : {console_dev}")
    print(f"native  (samples)     : {native_dev}")
    print(f"mode                  : "
          f"{'stop before close' if args.stop_first else 'close while playing'}")

    con = serial.Serial(console_dev, 115200, timeout=0.2)
    time.sleep(2.0)                      # opening it resets the board
    con.reset_input_buffer()

    def cmd(text):
        con.write(text.encode())
        con.flush()

    wedges = recovered = 0
    worst = 0.0
    for cycle in range(args.cycles):
        try:
            nat = serial.Serial(native_dev, 115200, timeout=0.2,
                                write_timeout=None)
        except serial.SerialException as e:
            print(f"  cycle {cycle}: open failed: {e}")
            break
        nat.reset_input_buffer()

        # Write the way Windows already does. pyserial keeps a POSIX fd
        # non-blocking and feeds the tty queue in select-sized chunks;
        # WriteFile on Windows blocks until the whole buffer is queued.
        # That difference matters here - the macOS reproducer issues one
        # blocking 256 KB write and wedges roughly one cycle in three,
        # and the chunked version did not wedge in 40 - so the fd is
        # made blocking where that is possible, to keep the experiment
        # the same experiment on every OS.
        if hasattr(nat, "fd") and nat.fd is not None:
            try:
                os.set_blocking(nat.fd, True)
            except (AttributeError, OSError):
                pass

        cmd(f"={DAC_HZ},{ADC_HZ},2P")
        time.sleep(0.3)
        try:
            nat.write(PAYLOAD)
        except Exception as e:                               # noqa: BLE001
            print(f"  cycle {cycle}: write failed: {e!r}")

        if args.stop_first:
            cmd("0")
            time.sleep(0.2)

        done = threading.Event()

        def _close(port=nat):
            try:
                port.close()
            finally:
                done.set()

        threading.Thread(target=_close, daemon=True).start()
        t0 = time.time()
        if done.wait(WEDGE_S):
            cost = time.time() - t0
            worst = max(worst, cost)
            if not args.stop_first:
                cmd("0")
                time.sleep(0.15)
            continue

        wedges += 1
        print(f"  cycle {cycle}: close() has not returned in {WEDGE_S}s "
              f"- this is objective 0c")
        cmd("=400Z")                     # software unplug
        freed = done.wait(15.0)
        cost = time.time() - t0
        recovered += 1 if freed else 0
        print(f"    detach -> released={freed} after {cost:.2f} s")
        if not freed:
            print("    NOT RECOVERED; the port is held by a stuck thread")
            break
        time.sleep(2.5)                  # let it re-enumerate
        console_dev, native_dev = find_ports(args.console, args.native)
        cmd("0")
        time.sleep(0.2)

    print(f"\n{args.cycles} cycles attempted, {wedges} wedged, "
          f"{recovered} recovered by software detach")
    print(f"worst healthy close: {worst:.3f} s")
    if wedges == 0:
        print("NO WEDGE on this OS - which is the interesting result. "
              "macOS wedges roughly one cycle in three in this mode.")
    con.close()


if __name__ == "__main__":
    main()
