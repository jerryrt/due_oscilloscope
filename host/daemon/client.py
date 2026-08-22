"""A client for the daemon: what the GUI will use, and what the API
tests drive the server with.

Deliberately synchronous on the command side - `call()` sends and waits
for the reply with its id - while frames arrive on a background thread
into a bounded deque. That is the same split the GUI wants: commands are
a conversation, frames are a firehose you sample.
"""

from __future__ import annotations

import collections
import socket
import threading
import time

from . import protocol as proto


class ClientError(RuntimeError):
    pass


class Refused(ClientError):
    """The daemon refused: a rate past a limit, a missing owner, an op
    that does not exist. Carries the code so a caller can branch."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Client:
    def __init__(self, host="127.0.0.1", port=45454, *, timeout=5.0,
                 frame_capacity=4096):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.frames = collections.deque(maxlen=frame_capacity)
        self.events = collections.deque(maxlen=1024)
        self.frames_received = 0
        self._replies = {}
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._rx = None
        self._next_id = 1
        self.error = None

    # -- lifecycle ---------------------------------------------------
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(0.2)
        self._rx = threading.Thread(target=self._recv_loop, daemon=True,
                                    name="client-rx")
        self._rx.start()
        return self

    def close(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        if self._rx and self._rx.is_alive():
            self._rx.join(2.0)

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- receive -----------------------------------------------------
    def _recv_loop(self):
        dec = proto.Decoder()
        while not self._stop.is_set():
            try:
                data = self.sock.recv(262144)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            try:
                msgs = dec.feed(data)
            except proto.ProtocolError as e:
                self.error = str(e)
                break
            for mtype, body in msgs:
                if mtype == proto.T_FRAME:
                    self.frames_received += 1
                    self.frames.append(body)
                    with self._cv:
                        self._cv.notify_all()
                    continue
                obj = proto.decode_json(body)
                with self._cv:
                    rid = obj.get("id")
                    if rid is not None:
                        self._replies[rid] = obj
                    else:
                        self.events.append(obj)
                    self._cv.notify_all()

    # -- send --------------------------------------------------------
    def call(self, op, **kw):
        """Send a command and return its reply. Raises Refused on an
        error event, so a caller that ignores errors cannot mistake one
        for success."""
        with self._cv:
            rid = self._next_id
            self._next_id += 1
        msg = dict(kw)
        msg["op"] = op
        msg["id"] = rid
        self.sock.sendall(proto.encode_json(proto.T_CMD, msg))
        end = time.time() + self.timeout
        with self._cv:
            while rid not in self._replies:
                if time.time() >= end:
                    raise ClientError(f"no reply to {op} within "
                                      f"{self.timeout}s")
                self._cv.wait(0.05)
            reply = self._replies.pop(rid)
        if reply.get("event") == "error":
            raise Refused(reply.get("code", "error"),
                          reply.get("message", ""))
        return reply

    def send_awg(self, data):
        self.sock.sendall(proto.encode(proto.T_AWG, data))

    def send_raw(self, blob):
        """Whatever bytes the caller wants on the wire, framing included
        or not. For tests that need to misbehave."""
        self.sock.sendall(blob)

    # -- convenience -------------------------------------------------
    def hello(self, role="observer"):
        return self.call("hello", role=role)

    def subscribe(self, frames=True):
        return self.call("subscribe", frames=frames)

    def wait_frames(self, n, timeout=5.0):
        """Block until `n` frames have arrived, and return them."""
        end = time.time() + timeout
        with self._cv:
            while self.frames_received < n:
                if time.time() >= end:
                    raise ClientError(
                        f"{self.frames_received} frames in {timeout}s, "
                        f"wanted {n}")
                self._cv.wait(0.05)
        return list(self.frames)

    def wait_event(self, name, timeout=5.0):
        end = time.time() + timeout
        with self._cv:
            while True:
                for e in list(self.events):
                    if e.get("event") == name:
                        self.events.remove(e)
                        return e
                if time.time() >= end:
                    raise ClientError(f"no {name!r} event within {timeout}s")
                self._cv.wait(0.05)
