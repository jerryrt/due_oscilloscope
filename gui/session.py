"""The daemon connection, and every way it can go wrong.

Split out of `app.py` because the window was doing two jobs and only one
of them was Qt. Thirteen `try:` blocks lived there, five of them
catching bare `Exception`, and each ended in its own hand-written status
message - so `docs/frontend.md` rule 4, "refusals come from the device",
was implemented five times and the five did not agree. Some caught
`Refused` and showed `e.message`, some caught `Exception` and showed
`str(e)`, and the waveform path caught nothing at all.

The distinction this module exists to keep is between three outcomes,
not one:

  * a **reply** - the daemon did the thing;
  * a **refusal** - the device said no, and its own message names the
    limit. Rule 4 says show that message. The link is fine;
  * a **loss** - the daemon is gone. Not a refusal, must not read as
    one, and the window has to be told to stop drawing.

Everything here is signals out and plain calls in, so the window never
touches `daemon.client` and this file never touches a widget. That is
also what makes it testable without a QApplication.
"""

from __future__ import annotations

import os
import sys

from PySide6 import QtCore

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))

from daemon import client as clientmod          # noqa: E402


#: Frames held for the display before the client's own deque drops the
#: oldest. 512 is about 1.5 s at the full rate - long enough to ride out
#: a repaint, and the daemon is already designed to drop toward a slow
#: client and count it.
FRAME_CAPACITY = 512


class DaemonSession(QtCore.QObject):
    """One daemon connection, or none.

    Deliberately not a wrapper that re-raises: a front end cannot do
    anything useful with an exception in a slot, and the five call sites
    that used to catch their own proved it by each inventing a different
    answer. Calls return the reply or `None`, and what went wrong comes
    out as a signal that exactly one place in the window renders.
    """

    #: The daemon accepted us. Carries its device block and the role we
    #: were actually granted, which is not always the one asked for.
    connected = QtCore.Signal(dict, str)
    #: We never got there. Carries a message worth putting in a dialog.
    connect_failed = QtCore.Signal(str)
    #: The link is down. Empty reason means we closed it on purpose;
    #: anything else is why it went away underneath us.
    disconnected = QtCore.Signal(str)
    #: The device said no, and this is its own message. The link is up.
    refused = QtCore.Signal(str, str)
    #: A `status` reply, already unwrapped.
    status = QtCore.Signal(dict)
    #: A `counters` reply, already unwrapped.
    counters = QtCore.Signal(dict)
    #: One heartbeat the device sent unasked, and whether the daemon
    #: reads it as a stalled main loop. Pushed, not polled - so it can
    #: arrive while nothing is being asked, which is the whole point.
    heartbeat = QtCore.Signal(dict, bool)
    #: Any other event the daemon pushed: `started`, `stopped`,
    #: `recording`, `recorded`, `device_error`, `error`, `awg_ok`.
    #: Carries the event name and the whole object.
    event = QtCore.Signal(str, dict)

    def __init__(self, host="127.0.0.1", port=45454, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.client = None
        self.device = {}
        self.role = None

    # -- the link ----------------------------------------------------
    @property
    def is_open(self):
        return self.client is not None

    def point_at(self, host, port):
        """Aim at a different daemon, dropping any current link.

        Its own method because "where this session connects" is state a
        caller reads back - `Open recording` moves it to a daemon the
        window started, `Connect to ...` moves it home - and poking the
        two attributes from outside would leave a live socket pointing
        somewhere the fields no longer describe.
        """
        self.close()
        self.host = host
        self.port = port

    def open(self, role="control", quiet=False):
        """Connect and say hello. True if there is a link afterwards.

        `quiet` suppresses `connect_failed` for a caller that is
        retrying on purpose: a daemon the window has just started needs
        a moment to bind, and a dialog per attempt would be five
        dialogs for one success.
        """
        if self.client is not None:
            return True
        try:
            c = clientmod.Client(self.host, self.port, timeout=5.0,
                                 frame_capacity=FRAME_CAPACITY)
            c.connect()
            hello = c.hello(role)
        except (OSError, clientmod.ClientError) as e:
            if not quiet:
                self.connect_failed.emit(
                    f"Could not reach a daemon at {self.host}:{self.port}"
                    f"\n\n{e}\n\n"
                    f"Start one with:  python3 -m daemon --fake")
            return False
        self.client = c
        self.device = hello.get("device", {})
        self.role = hello.get("role", "observer")
        self.connected.emit(self.device, self.role)
        return True

    def close(self, reason=""):
        """Drop the link. Idempotent, and safe from inside a failed call.

        `reason` is empty when we closed it and populated when it closed
        under us, because those are different things to tell a user and
        the window used to have to work out which had happened from
        which method it was standing in.
        """
        c, self.client = self.client, None
        if c is None:
            return
        try:
            c.close()
        except Exception:                                # noqa: BLE001
            # Already gone is the normal case here, and there is nothing
            # to recover: the link is down either way, and raising out
            # of a teardown would strand the window half-connected.
            pass
        self.device = {}
        self.role = None
        self.disconnected.emit(reason)

    # -- talking to it -----------------------------------------------
    def call(self, op, **kw):
        """One command. The reply, or None if it did not happen.

        A refusal is reported and swallowed; a dead link is reported,
        swallowed, and closes the session, because every caller after
        the first would otherwise fail the same way in turn.
        """
        return self._call(op, kw, quiet=False)

    def call_quiet(self, op, **kw):
        """The same, without reporting a refusal.

        For the poll path only. `counters` costs the board a console
        round trip and may legitimately refuse while playback runs; a
        refusal there is a dash on a panel, not something to say out
        loud four times a second. A lost link is still reported - that
        one is never routine.
        """
        return self._call(op, kw, quiet=True)

    def _call(self, op, kw, quiet):
        c = self.client
        if c is None:
            return None
        try:
            return c.call(op, **kw)
        except clientmod.Refused as e:                   # before ClientError
            if not quiet:
                self.refused.emit(op, e.message)
            return None
        except (clientmod.ClientError, OSError) as e:
            self.close(f"daemon stopped answering ({e})")
            return None

    def drain_events(self):
        """Hand over everything the daemon pushed since the last call.

        The client's receive thread has been sorting these into
        `client.events` all along - frames to one deque, replies matched
        by id, and anything with no id here, because nobody asked for
        it. **Nothing in the window ever read that deque**, so every
        `device_error`, every refused waveform and now every heartbeat
        expired in it when the 1024 wrapped.

        Drained on the existing timer rather than from the receive
        thread: Qt signals must be emitted where the widgets live.
        """
        c = self.client
        if c is None:
            return
        while True:
            try:
                obj = c.events.popleft()
            except IndexError:
                break
            name = obj.get("event") or ""
            if name == "heartbeat":
                self.heartbeat.emit(obj.get("beat") or {},
                                    bool(obj.get("stalled")))
            self.event.emit(name, obj)

    def poll(self):
        """`status`, then `counters`. Emits what came back.

        Two calls rather than one because the daemon keeps them apart on
        purpose: `status` is answerable from the host alone and costs the
        device nothing, which is what makes polling it safe at all, and
        `counters` is the one that can cost a console round trip.
        """
        self.drain_events()
        st = self.call_quiet("status")
        if st is None:
            return
        self.status.emit(st.get("status") or {})
        ct = self.call_quiet("counters")
        if ct is not None:
            self.counters.emit(ct.get("counters") or {})

    def send_awg(self, blob):
        """Push a waveform. True if it reached the socket.

        The refusal for this one comes back as an `error` *event* rather
        than a reply, so it surfaces through the daemon's event stream
        and not here - what this can report is only whether the bytes
        left.
        """
        c = self.client
        if c is None:
            return False
        try:
            c.send_awg(blob)
            return True
        except (clientmod.ClientError, OSError) as e:
            self.close(f"daemon stopped answering ({e})")
            return False

    # -- the frame stream --------------------------------------------
    @property
    def frames(self):
        """The client's bounded deque, for the drain loop to pop from.

        Handed over rather than wrapped: the display drains it inside
        one timer tick and anything between here and there would be work
        on the path that must not stall.
        """
        return self.client.frames if self.client else ()

    @property
    def frames_received(self):
        return self.client.frames_received if self.client else 0
