"""The daemon: one device, many clients, one owner.

Responsibilities, in the order they matter:

1. **Keep the device drained.** A CDC device must keep draining bulk
   OUT even when nothing consumes it, or macOS's `close()` waits on
   write URBs that never complete and the host process hangs holding
   the port. The reader thread runs whether or not a client is
   listening, and dropping a frame is always preferred to blocking.
2. **Never let a client stall the stream.** Each client has a bounded
   outbound queue and its own sender thread. A client that stops reading
   loses frames, counted and reported; it does not slow the device, the
   recorder, or anyone else.
3. **One owner at a time.** Two front ends issuing rate changes into one
   device console is a confusion designed out here rather than debugged
   later. Others may attach and watch.

Recording is the daemon's job for the same reason as (1): a capture has
to survive the front end. See `docs/frontend.md`.
"""

from __future__ import annotations

# How often the accept loop wakes to check whether it has been stopped.
# Short enough that teardown is not noticeable, long enough that an idle
# daemon is not spinning: 5 wakeups a second against a loop that does
# nothing else.
ACCEPT_TIMEOUT_S = 0.2

import collections
import gc
import json
import os
import socket
import threading
import time

import jitter

from . import device as devmod
from . import protocol as proto
from . import rates as ratemod

DEFAULT_PORT = 45454

# Frames held per client before the oldest are dropped. 64 frames is
# 256 KB, about a third of a second at the full rate - long enough to
# ride out a repaint, short enough that a wedged client is obvious.
CLIENT_QUEUE_FRAMES = 64

# The recorder's queue is deeper: its stall is an fsync or an indexer,
# which is bursty rather than sustained.
RECORD_QUEUE_FRAMES = 512


def _sendmsg_all(sock, hdr, body):
    """Send header and body as two buffers, handling a partial send.

    `sendmsg` writes what it can and reports how much, so a large frame
    on a full socket buffer comes back short and the rest has to be
    re-offered. Getting this wrong corrupts the stream rather than
    slowing it, which is why it is one function with one job.
    """
    parts = [hdr, body]
    sent = sock.sendmsg(parts)
    total = len(hdr) + len(body)
    while sent < total:
        if sent < len(hdr):
            parts = [memoryview(hdr)[sent:], body]
        else:
            parts = [memoryview(body)[sent - len(hdr):]]
        sent += sock.sendmsg(parts)


class _Session(threading.Thread):
    """One connected client: a receive loop here, a sender thread, and a
    bounded queue between them."""

    def __init__(self, server, conn, addr):
        super().__init__(daemon=True, name=f"session-{addr}")
        self.server = server
        self.conn = conn
        self.addr = addr
        self.role = "observer"
        self.subscribed = False
        self.dropped = 0
        self.sent_frames = 0
        self.hello = False
        # Two queues, not one of (type, body) pairs. A tuple per frame
        # is a container object per frame, and container churn is what
        # the cycle collector scans - the frame bytes themselves are not
        # even tracked by it. At 442 frames a second the tuples are the
        # allocation that matters.
        self._events = collections.deque()
        self._frames = collections.deque()
        self._hdr = {}
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._sender = threading.Thread(target=self._send_loop, daemon=True,
                                        name=f"sender-{addr}")

    # -- outbound ----------------------------------------------------
    def put_frame(self, frame):
        """Queue one device frame, dropping the oldest if full.

        Dropping the *oldest* rather than the newest is deliberate: a
        client that fell behind wants to catch up with what is happening
        now, not to replay what it missed.

        The frame is queued as it arrived. Its 8-byte header is added at
        send time from a per-length cache, so nothing here concatenates
        a header onto 4 KB of payload once per client per frame.
        """
        with self._cv:
            if self._stop.is_set():
                return
            while len(self._frames) >= self.server.client_queue_frames:
                self._frames.popleft()
                self.dropped += 1
            self._frames.append(frame)
            self._cv.notify()

    def put_message(self, blob):
        """Queue an already-encoded message. Never dropped."""
        with self._cv:
            if self._stop.is_set():
                return
            self._events.append(blob)
            self._cv.notify()

    def event(self, name, **kw):
        obj = dict(kw)
        obj["event"] = name
        self.put_message(proto.encode_json(proto.T_EVT, obj))

    def _frame_header(self, n):
        hdr = self._hdr.get(n)
        if hdr is None:
            hdr = proto.HDR.pack(proto.MAGIC, proto.T_FRAME, 0, n)
            self._hdr[n] = hdr
        return hdr

    def _send_loop(self):
        """Events first, then frames.

        A reply must not queue behind four hundred frames a client has
        not read yet, and a frame is the thing that may be dropped.
        """
        sendmsg = getattr(self.conn, "sendmsg", None)
        while not self._stop.is_set():
            frame = blob = None
            with self._cv:
                while not self._events and not self._frames \
                        and not self._stop.is_set():
                    self._cv.wait(0.2)
                if self._stop.is_set():
                    return
                if self._events:
                    blob = self._events.popleft()
                else:
                    frame = self._frames.popleft()
            try:
                if blob is not None:
                    self.conn.sendall(blob)
                else:
                    hdr = self._frame_header(len(frame))
                    if sendmsg is not None:
                        _sendmsg_all(self.conn, hdr, frame)
                    else:
                        # Windows has no sendmsg; pay the copy there.
                        self.conn.sendall(hdr + frame)
                    self.sent_frames += 1
            except OSError:
                self.close()
                return

    # -- inbound -----------------------------------------------------
    def run(self):
        self._sender.start()
        dec = proto.Decoder()
        try:
            while not self._stop.is_set():
                try:
                    data = self.conn.recv(65536)
                except OSError:
                    break
                if not data:
                    break
                try:
                    msgs = dec.feed(data)
                except proto.ProtocolError as e:
                    # Framing is gone; there is nothing to recover to.
                    self.event("error", code="protocol", message=str(e))
                    time.sleep(0.05)
                    break
                for mtype, body in msgs:
                    self.server.handle(self, mtype, body)
        finally:
            self.close()
            self.server.forget(self)

    def close(self):
        if self._stop.is_set():
            return
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass

    def jitter(self):
        """Where the latency actually is, host-side.

        `read_gap` is the interval between reads that returned data - a
        long one means the reader was descheduled while the kernel
        buffer filled. `fanout` is what one frame costs to hand to every
        client and the recorder, which is the work that competes with
        the reader for the same thread.

        `feed` comes from the writer when playback is running, and is
        the one with a deadline: the device ring drains in about 18 ms
        at the full rate.
        """
        out = {"read_gap": self.read_gap.summary(),
               "fanout": self.fanout.summary()}
        feeder = getattr(self.device, "feeder", None)
        if feeder is not None and getattr(feeder, "gap", None) is not None:
            out["feed"] = feeder.gap.summary()
        return out

    def status(self):
        return {"addr": f"{self.addr[0]}:{self.addr[1]}", "role": self.role,
                "subscribed": self.subscribed, "dropped": self.dropped,
                "frames_sent": self.sent_frames}


class _Recorder:
    """Frames to disk, verbatim, behind a bounded queue.

    The queue is what keeps a disk stall off the USB path: if the writer
    cannot keep up, frames are dropped from the *record* and counted.
    A recording with a hole in it says so - in the sidecar and in every
    status reply - because a file that quietly omits a frame is data
    that will later be read as continuous.
    """

    def __init__(self, path, meta, maxlen=RECORD_QUEUE_FRAMES):
        self.path = path
        self.meta = meta
        self.frames = 0
        self.bytes = 0
        self.dropped = 0
        self.error = None
        self._q = collections.deque(maxlen=None)
        self._max = maxlen
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._fh = open(path, "wb")
        self._t0 = time.time()
        self._th = threading.Thread(target=self._run, daemon=True,
                                    name="recorder")
        self._th.start()

    def put(self, frame):
        with self._cv:
            if self._stop.is_set():
                return
            if len(self._q) >= self._max:
                self._q.popleft()
                self.dropped += 1
            self._q.append(frame)
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._q and not self._stop.is_set():
                    self._cv.wait(0.2)
                if not self._q and self._stop.is_set():
                    return
                frame = self._q.popleft()
            try:
                self._fh.write(frame)
                self.frames += 1
                self.bytes += len(frame)
            except OSError as e:
                self.error = str(e)
                return

    def stop(self):
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        self._th.join(5.0)
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
        except OSError:
            pass
        self._fh.close()
        side = dict(self.meta)
        side.update({"frames": self.frames, "bytes": self.bytes,
                     "dropped": self.dropped, "error": self.error,
                     "started_unix": self._t0, "stopped_unix": time.time(),
                     "path": os.path.basename(self.path)})
        with open(self.path + ".json", "w") as f:
            json.dump(side, f, indent=2, sort_keys=True)
        return side

    def jitter(self):
        """Where the latency actually is, host-side.

        `read_gap` is the interval between reads that returned data - a
        long one means the reader was descheduled while the kernel
        buffer filled. `fanout` is what one frame costs to hand to every
        client and the recorder, which is the work that competes with
        the reader for the same thread.

        `feed` comes from the writer when playback is running, and is
        the one with a deadline: the device ring drains in about 18 ms
        at the full rate.
        """
        out = {"read_gap": self.read_gap.summary(),
               "fanout": self.fanout.summary()}
        feeder = getattr(self.device, "feeder", None)
        if feeder is not None and getattr(feeder, "gap", None) is not None:
            out["feed"] = feeder.gap.summary()
        return out

    def status(self):
        return {"path": self.path, "frames": self.frames, "bytes": self.bytes,
                "dropped": self.dropped, "error": self.error}


class Server:
    """The daemon proper.

    Binds all interfaces by default, with no authentication, on the
    stated assumption of a trusted network (`docs/frontend.md`). The
    address is a parameter precisely so that assumption can be revisited
    with a config change rather than a rewrite.
    """

    def __init__(self, device, host="0.0.0.0", port=DEFAULT_PORT, *,
                 client_queue_frames=CLIENT_QUEUE_FRAMES, tune_gc=False):
        self.device = device
        self.host = host
        self.port = port
        self.client_queue_frames = client_queue_frames
        self.sessions = []
        self.controller = None
        self.recorder = None
        self._lock = threading.RLock()
        self._sock = None
        self._stop = threading.Event()
        self._accept = None
        self._reader = None
        self._splitter = devmod.FrameSplitter()
        self.frames_read = 0
        self.started_unix = None
        # Latency, not rate. Every failure this project has had was a
        # late wakeup at a moment when a buffer was empty, and an
        # average hides exactly that.
        self.read_gap = jitter.Histogram("device-read-gap")
        self.fanout = jitter.Histogram("fanout")
        # The waveform a client uploaded, held for the next play. The
        # device loops it; the daemon does not generate signals.
        self.waveform = b""
        self._description = None
        # Off by default: importing a library must not change the
        # collector of whatever process happens to load it. The daemon
        # process turns it on for itself.
        self.tune_gc = tune_gc
        self._gc_was_enabled = None

    # -- lifecycle ---------------------------------------------------
    def start(self):
        if self.tune_gc:
            # Reference counting still frees promptly; it is the cycle
            # detector that pauses, and the streaming path is built not
            # to make cycles. freeze() moves everything alive now out of
            # the generations so a later collection has less to walk.
            gc.collect()
            gc.freeze()
            self._gc_was_enabled = gc.isenabled()
            gc.disable()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # A timeout, so the accept loop can notice stop() on every
        # platform - see _accept_loop.
        self._sock.settimeout(ACCEPT_TIMEOUT_S)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self.started_unix = time.time()
        self._accept = threading.Thread(target=self._accept_loop, daemon=True,
                                        name="accept")
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name="device-reader")
        self._accept.start()
        self._reader.start()
        return self

    @property
    def address(self):
        return (self.host, self.port)

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        with self._lock:
            sessions = list(self.sessions)
            rec = self.recorder
            self.recorder = None
        for s in sessions:
            s.close()
        if rec:
            rec.stop()
        for th in (self._accept, self._reader):
            if th and th.is_alive():
                th.join(3.0)
        try:
            self.device.close()
        except Exception:                            # noqa: BLE001
            pass
        if self._gc_was_enabled:
            gc.enable()
            gc.unfreeze()
            self._gc_was_enabled = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- plumbing ----------------------------------------------------
    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                # The wake-up. stop() closes the listening socket from
                # another thread, and whether that wakes a thread already
                # blocked in accept() is undefined by POSIX: BSD and macOS
                # return EBADF, Linux leaves the thread blocked until a
                # connection actually arrives. So the accept times out
                # instead and re-checks _stop.
                #
                # Measured before this: every daemon teardown on Linux
                # burned the full 3.0 s join in stop(), 47 tests spent
                # ~140 s of a 188 s run waiting, and
                # test_the_server_leaves_no_threads_behind failed outright.
                continue
            except OSError:
                return
            conn.settimeout(None)          # inherit nothing from the listener
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s = _Session(self, conn, addr)
            with self._lock:
                self.sessions.append(s)
            s.start()

    def _read_loop(self):
        """Drain the device forever, whoever is or is not listening."""
        last_read = None
        while not self._stop.is_set():
            try:
                data = self.device.read(timeout=0.2)
            except Exception as e:                   # noqa: BLE001
                self.broadcast_event("device_error", message=str(e))
                time.sleep(0.2)
                continue
            if not data:
                continue
            now = time.monotonic()
            if last_read is not None:
                self.read_gap.add(now - last_read)
            last_read = now
            for frame in self._splitter.feed(data):
                self.frames_read += 1
                with self._lock:
                    targets = [s for s in self.sessions if s.subscribed]
                    rec = self.recorder
                for s in targets:
                    s.put_frame(frame)
                if rec is not None:
                    rec.put(frame)
                self.fanout.add(time.monotonic() - now)

    def forget(self, session):
        with self._lock:
            if session in self.sessions:
                self.sessions.remove(session)
            if self.controller is session:
                self.controller = None

    def broadcast_event(self, name, **kw):
        with self._lock:
            targets = list(self.sessions)
        for s in targets:
            s.event(name, **kw)

    # -- dispatch ----------------------------------------------------
    def handle(self, session, mtype, body):
        if mtype == proto.T_AWG:
            return self._handle_awg(session, body)
        if mtype != proto.T_CMD:
            session.event("error", code="bad_type",
                          message=f"clients may not send "
                                  f"{proto.TYPE_NAMES.get(mtype, mtype)}")
            return
        try:
            msg = proto.decode_json(body)
        except proto.ProtocolError as e:
            session.event("error", code="bad_json", message=str(e))
            return
        op = msg.get("op")
        rid = msg.get("id")
        fn = OPS.get(op)
        if fn is None:
            session.event("error", id=rid, code="unknown_op",
                          message=f"no such op {op!r}")
            return
        if op in MUTATING and session is not self.controller:
            session.event("error", id=rid, code="not_control",
                          message=f"{op} needs control; another client holds "
                                  f"it" if self.controller else
                                  f"{op} needs control; ask for it in hello")
            return
        try:
            result = fn(self, session, msg) or {}
        except (ratemod.RateError, devmod.DeviceError) as e:
            session.event("error", id=rid, code="refused", message=str(e))
            return
        except Exception as e:                       # noqa: BLE001
            session.event("error", id=rid, code="internal",
                          message=f"{type(e).__name__}: {e}")
            return
        session.event(result.pop("event", "ok"), id=rid, **result)

    def _handle_awg(self, session, body):
        if session is not self.controller:
            session.event("error", code="not_control",
                          message="waveform upload needs control")
            return
        # The daemon holds the waveform; the device is handed it when
        # playback starts. Writing it to the port on arrival would put
        # samples on the wire before the DAC was armed to consume them.
        #
        # Replace rather than append: a client uploading a waveform is
        # describing what to play, not adding to a queue.
        self.waveform = body
        sink = getattr(self.device, "write_awg", None)
        if sink is not None:
            try:
                sink(body)
            except devmod.DeviceError as e:
                # A device that has no generator says so, and the reply
                # is the refusal rather than a dead session. This path
                # is not wrapped by `handle`'s dispatch guard, so
                # without this a refusal here takes the connection down
                # instead of answering it.
                self.waveform = b""
                session.event("error", code="refused", message=str(e))
                return
        session.event("awg_ok", bytes=len(body), held=len(self.waveform))

    # -- state -------------------------------------------------------
    def description(self):
        """The device description, asked for once.

        It is cached because finding the track means asking for the
        banner, and the banner is a long console print that costs
        eleven underruns while playback runs. Nothing on a poll path may
        pay that, and the answer cannot change without a reflash.
        """
        if self._description is None:
            self._description = self.device.describe()
        return dict(self._description)

    def jitter(self):
        """Where the latency actually is, host-side.

        `read_gap` is the interval between reads that returned data - a
        long one means the reader was descheduled while the kernel
        buffer filled. `fanout` is what one frame costs to hand to every
        client and the recorder, which is the work that competes with
        the reader for the same thread.

        `feed` comes from the writer when playback is running, and is
        the one with a deadline: the device ring drains in about 18 ms
        at the full rate.
        """
        out = {"read_gap": self.read_gap.summary(),
               "fanout": self.fanout.summary()}
        feeder = getattr(self.device, "feeder", None)
        if feeder is not None and getattr(feeder, "gap", None) is not None:
            out["feed"] = feeder.gap.summary()
        return out

    def status(self):
        with self._lock:
            sessions = [s.status() for s in self.sessions]
            rec = self.recorder.status() if self.recorder else None
            ctl = self.controller.status()["addr"] if self.controller else None
        return {
            "protocol": proto.PROTOCOL_VERSION,
            "uptime_s": round(time.time() - (self.started_unix or time.time()), 3),
            "device": self.description(),
            "running": bool(getattr(self.device, "running", False)),
            "mode": getattr(self.device, "mode", None),
            "rates": getattr(self.device, "rates", None),
            "frames_read": self.frames_read,
            "discarded_bytes": self._splitter.discarded,
            "controller": ctl,
            "clients": sessions,
            "recording": rec,
            "waveform_bytes": len(self.waveform),
            "stats": self.device.stats(),
            "jitter": self.jitter(),
            # Costs the device nothing: beats arrive unbidden, so this
            # is the newest one already in hand. `status` asking the
            # device nothing is a documented property and this keeps it.
            "heartbeat": self.device.heartbeat_state(),
        }

    def on_heartbeat(self, hb, stalled):
        """One beat from the device, on the pump thread.

        Broadcast to every client, and to *every* client rather than
        only subscribers: a subscriber is someone who wants sample
        frames, and whether the board's main loop is alive is not a
        sample. An observer watching a board it does not stream from is
        exactly who needs this.
        """
        self.broadcast_event("heartbeat", beat=hb, stalled=bool(stalled))


# -- operations ------------------------------------------------------
# Each takes (server, session, msg) and returns a dict of reply fields.
# Anything in MUTATING requires control.

def _op_hello(srv, ses, msg):
    want = msg.get("role", "observer")
    if want not in ("control", "observer"):
        raise devmod.DeviceError(f"unknown role {want!r}")
    with srv._lock:
        if want == "control":
            if srv.controller is None:
                srv.controller = ses
                ses.role = "control"
            elif srv.controller is ses:
                pass
            else:
                ses.role = "observer"
        else:
            ses.role = "observer"
    ses.hello = True
    return {"event": "hello", "role": ses.role,
            "protocol": proto.PROTOCOL_VERSION,
            "granted": ses.role == want,
            "device": srv.description()}


def _op_ping(srv, ses, msg):
    return {"event": "pong", "t": time.time()}


def _op_status(srv, ses, msg):
    return {"event": "status", "status": srv.status()}


def _op_heartbeat(srv, ses, msg):
    """Turn the device's beat on or off, and name its cadence.

    Mutating, because it changes what the board does with its own
    timer. The device clamps the period and the reply carries what it
    actually took, so a client never has to assume its ask was honoured.

    Off by default is the firmware's decision and this does not
    second-guess it: a board that pushes at a host which never asked is
    a board deciding for itself what the wire carries.
    """
    period = msg.get("period_ms")
    if period is not None:
        period = int(period)
    state = srv.device.heartbeat(period, sink=srv.on_heartbeat)
    if not state:
        raise devmod.DeviceError(
            "this device has no heartbeat: no control channel, or "
            "firmware predating it")
    return {"event": "heartbeat", "heartbeat": srv.device.heartbeat_state(),
            "device": state}


def _op_counters(srv, ses, msg):
    """The device's own counters, asked for explicitly.

    Not folded into `status`, because status is a poll path and this
    costs a console round trip. `status` is answerable from the host
    alone and stays free.
    """
    return {"event": "counters", "counters": srv.device.counters()}


def _op_trace(srv, ses, msg):
    """The playback occupancy histogram and the converter's rate trace.

    Its own operation rather than part of `counters`: a different device
    command, a far longer reply, and a different question. `counters`
    asks what went wrong; this asks what rate the converter actually
    held, which the whole-run figure cannot answer because it averages a
    converter that changes state with one that does not.
    """
    return {"event": "trace", "trace": srv.device.trace()}


def _op_caps(srv, ses, msg):
    return {"event": "caps", "rates": ratemod.describe(),
            "device": srv.description(),
            "modes": list(devmod.MODES)}


def _op_rate(srv, ses, msg):
    """Snap without touching the device: what would this rate become?"""
    out = {"event": "rate"}
    if "adc_hz" in msg:
        rc, hz = ratemod.check_capture(msg["adc_hz"],
                                       int(msg.get("channels", 2)))
        out["adc"] = {"requested": msg["adc_hz"], "rc": rc, "actual_hz": hz}
    if "dac_sps" in msg:
        rc, hz = ratemod.check_dac(msg["dac_sps"])
        out["dac"] = {"requested": msg["dac_sps"], "rc": rc, "actual_hz": hz}
    return out


def _op_subscribe(srv, ses, msg):
    ses.subscribed = bool(msg.get("frames", True))
    return {"event": "subscribed", "frames": ses.subscribed}


def _op_start(srv, ses, msg):
    mode = msg.get("mode", "capture")
    channels = int(msg.get("channels", 2))
    adc_hz = msg.get("adc_hz")
    dac_sps = msg.get("dac_sps")
    actual = {}
    if mode in ("capture", "loop") and adc_hz:
        rc, hz = ratemod.check_capture(adc_hz, channels)
        actual["adc"] = {"rc": rc, "actual_hz": hz}
        adc_hz = hz
    if mode in ("play", "loop") and dac_sps:
        rc, hz = ratemod.check_dac(dac_sps)
        actual["dac"] = {"rc": rc, "actual_hz": hz}
        dac_sps = hz
    waveform = None
    if mode in ("play", "loop"):
        waveform = srv.waveform or None
    srv.device.start(mode, dac_sps=dac_sps, adc_hz=adc_hz, channels=channels,
                     waveform=waveform, preset=msg.get("preset"))
    srv.broadcast_event("started", mode=mode, rates=actual)
    return {"event": "started", "mode": mode, "rates": actual}


def _op_stop(srv, ses, msg):
    srv.device.stop()
    srv.broadcast_event("stopped")
    return {"event": "stopped"}


def _op_record_start(srv, ses, msg):
    path = msg.get("path")
    if not path:
        raise devmod.DeviceError("record.start needs a path")
    with srv._lock:
        if srv.recorder is not None:
            raise devmod.DeviceError(
                f"already recording to {srv.recorder.path}")
        meta = {"device": srv.description(),
                "rates": getattr(srv.device, "rates", None),
                "mode": getattr(srv.device, "mode", None),
                "frame_bytes": devmod.FRAME_BYTES,
                "protocol": proto.PROTOCOL_VERSION,
                "note": "frames are stored exactly as the device sent them"}
        srv.recorder = _Recorder(path, meta)
    srv.broadcast_event("recording", path=path)
    return {"event": "recording", "path": path}


def _op_record_stop(srv, ses, msg):
    with srv._lock:
        rec = srv.recorder
        srv.recorder = None
    if rec is None:
        raise devmod.DeviceError("not recording")
    side = rec.stop()
    srv.broadcast_event("recorded", **{k: side[k] for k in
                                       ("frames", "bytes", "dropped")})
    return {"event": "recorded", "sidecar": side}


def _op_console(srv, ses, msg):
    text = msg.get("text")
    if not text:
        raise devmod.DeviceError("console needs text")
    board = getattr(srv.device, "board", None)
    if board is None:
        raise devmod.DeviceError("this device has no console")
    board.cmd(text)
    return {"event": "console", "sent": text}


OPS = {
    "hello": _op_hello,
    "ping": _op_ping,
    "status": _op_status,
    "counters": _op_counters,
    "trace": _op_trace,
    "caps": _op_caps,
    "rate": _op_rate,
    "subscribe": _op_subscribe,
    "start": _op_start,
    "stop": _op_stop,
    "record.start": _op_record_start,
    "record.stop": _op_record_stop,
    "console": _op_console,
    "heartbeat": _op_heartbeat,
}

# Ops that change the device or the daemon's state. Everything else is
# readable by any observer.
MUTATING = {"start", "stop", "record.start", "record.stop", "console",
            "heartbeat"}
