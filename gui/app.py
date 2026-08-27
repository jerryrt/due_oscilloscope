"""The window: a live trace, a health panel, and the controls G1 needs.

The shape follows `docs/frontend.md`. Frames arrive on the client's own
thread into a bounded deque; a Qt timer drains it and redraws. Nothing
blocks the event loop, and nothing in the daemon waits for the display:
if this window stalls, the daemon drops frames toward it, counts them,
and keeps streaming. The count is on screen for that reason.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PySide6 import QtCore, QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))

from daemon import client as clientmod      # noqa: E402

from . import stream                        # noqa: E402
from .health import HealthPanel             # noqa: E402
from .measure_panel import MeasurePanel     # noqa: E402
from .scope import ScopeView                # noqa: E402

# Windows offered in the timebase box, in seconds.
WINDOWS = [("1 ms", 0.001), ("5 ms", 0.005), ("20 ms", 0.02),
           ("100 ms", 0.1), ("500 ms", 0.5), ("2 s", 2.0)]

# Capture presets the firmware carries; the rate it actually produces
# comes back in the frame header, which is what gets displayed.
PRESETS = [("50 kHz", "1"), ("100 kHz", "2"), ("200 kHz", "3"),
           ("400 kHz", "4"), ("max in-spec", "5")]

#: Off free-runs the way this window always has. Auto triggers when
#: it can and free-runs when it cannot, which is the usable default.
#: Normal holds the last trace rather than drawing an untriggered
#: one, which is what you want when the edge is the question.
TRIGGER_MODES = [("Off", "off"), ("Auto", "auto"), ("Normal", "normal")]


class MainWindow(QtWidgets.QMainWindow):
    # Frames decoded per redraw. At 30 Hz this keeps up with about
    # 3,600 frames a second, comfortably above the ~442 the full rate
    # produces, while bounding the work one tick can do.
    MAX_DRAIN = 120

    def __init__(self, host="127.0.0.1", port=45454, parent=None):
        super().__init__(parent)
        self.setWindowTitle("due_oscilloscope")
        self.resize(1100, 620)

        self.client = None
        self.host = host
        self.port = port

        self.rings = {}                 # tag -> ChannelRing
        self.rate_hz = 200000
        self.frames_shown = 0
        self.seq_gaps = 0
        self.last_seq = None
        self.overruns = 0

        self.scope = ScopeView()
        self.health = HealthPanel()
        self.measure = MeasurePanel()

        self.channel = QtWidgets.QComboBox()
        for tag, label in sorted(stream.LABELS.items(), reverse=True):
            self.channel.addItem(label, tag)

        self.window_box = QtWidgets.QComboBox()
        for label, secs in WINDOWS:
            self.window_box.addItem(label, secs)
        self.window_box.setCurrentIndex(2)

        self.preset = QtWidgets.QComboBox()
        for label, key in PRESETS:
            self.preset.addItem(label, key)

        # Trigger. Software, on captured samples - docs/frontend.md
        # keeps an external trigger *input* disabled until the Phase 3
        # analog front end exists, and says a warning label is not
        # sufficient. Nothing here reaches a pin.
        self.trig_mode = QtWidgets.QComboBox()
        for label, key in TRIGGER_MODES:
            self.trig_mode.addItem(label, key)
        self.trig_mode.setCurrentIndex(1)              # auto

        self.trig_slope = QtWidgets.QComboBox()
        self.trig_slope.addItem("Rising", True)
        self.trig_slope.addItem("Falling", False)

        # Volts, because that is what the trace is labelled in; the one
        # conversion lives in stream.volts_to_codes.
        self.trig_level = QtWidgets.QDoubleSpinBox()
        self.trig_level.setRange(0.0, stream.VREF_V)
        self.trig_level.setDecimals(3)
        self.trig_level.setSingleStep(0.05)
        self.trig_level.setSuffix(" V")
        self.trig_level.setValue(stream.VREF_V / 2.0)

        # Whether it is actually triggering, which is not the same as
        # what the mode box says. Auto free-runs when it finds no edge,
        # and a scope that does that silently is how a moving trace gets
        # blamed on the signal.
        self.trig_state = QtWidgets.QLabel("--")
        self.trig_state.setMinimumWidth(56)

        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        for b in (self.start_btn, self.stop_btn):
            b.setEnabled(False)
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(self.stop_capture)

        controls = QtWidgets.QHBoxLayout()
        for w in (QtWidgets.QLabel("Channel"), self.channel,
                  QtWidgets.QLabel("Window"), self.window_box,
                  QtWidgets.QLabel("Rate"), self.preset,
                  QtWidgets.QLabel("Trigger"), self.trig_mode,
                  self.trig_slope, self.trig_level, self.trig_state):
            controls.addWidget(w)
        controls.addStretch(1)
        for b in (self.connect_btn, self.start_btn, self.stop_btn):
            controls.addWidget(b)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.scope, 1)
        left.addLayout(controls)

        side = QtWidgets.QVBoxLayout()
        side.addWidget(self.health)
        side.addWidget(self.measure)
        side.addStretch(1)

        body = QtWidgets.QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(side)

        central = QtWidgets.QWidget()
        central.setLayout(body)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"not connected ({host}:{port})")

        # Draw at 30 Hz; poll the daemon's own numbers at 4 Hz. Status
        # is answerable from the host alone - it costs the device
        # nothing - which is why polling it is safe at all.
        self.draw_timer = QtCore.QTimer(self)
        self.draw_timer.timeout.connect(self.tick)
        self.draw_timer.start(33)
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.poll_status)
        self.status_timer.start(250)

    # -- connection ---------------------------------------------------
    def toggle_connect(self):
        if self.client is None:
            self.connect_to_daemon()
        else:
            self.disconnect_from_daemon()

    def connect_to_daemon(self):
        try:
            c = clientmod.Client(self.host, self.port, timeout=5.0,
                                 frame_capacity=512)
            c.connect()
            hello = c.hello("control")
        except (OSError, clientmod.ClientError) as e:
            QtWidgets.QMessageBox.warning(
                self, "No daemon",
                f"Could not reach a daemon at {self.host}:{self.port}\n\n"
                f"{e}\n\nStart one with:  python3 -m daemon --fake")
            return
        self.client = c
        self.health.set("link", f"{self.host}:{self.port}")
        self.health.set("role", hello.get("role", "?"))
        self.connect_btn.setText("Disconnect")
        self.start_btn.setEnabled(hello.get("role") == "control")
        self.stop_btn.setEnabled(hello.get("role") == "control")
        c.subscribe()
        self.statusBar().showMessage(
            f"connected to {hello.get('device', {}).get('kind', '?')} device")

    def disconnect_from_daemon(self):
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None
        self.connect_btn.setText("Connect")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.health.set("link", "-")
        self.statusBar().showMessage("disconnected")

    # -- device -------------------------------------------------------
    def start_capture(self):
        if self.client is None:
            return
        self.reset_counters()
        try:
            self.client.call("start", mode="capture",
                             preset=self.preset.currentData(),
                             adc_hz=200000, channels=2)
        except clientmod.Refused as e:
            # The device's own refusal, with the limit it names.
            QtWidgets.QMessageBox.warning(self, "Refused", e.message)

    def stop_capture(self):
        if self.client is None:
            return
        try:
            self.client.call("stop")
        except clientmod.Refused as e:
            self.statusBar().showMessage(f"stop refused: {e.message}")

    def reset_counters(self):
        self.rings.clear()
        self.frames_shown = 0
        self.seq_gaps = 0
        self.last_seq = None
        self.overruns = 0

    # -- the loop -----------------------------------------------------
    def tick(self):
        if self.client is None:
            return
        frames = self.client.frames
        got = 0
        # Bounded, and not as a nicety: an unbounded drain loop against
        # a producer faster than the display never returns, and the
        # event loop it is running on never runs again. The daemon is
        # already designed to drop toward a slow client and count it, so
        # leaving frames in the queue is the behaviour that was planned
        # for - hanging is not.
        while got < self.MAX_DRAIN:
            try:
                buf = frames.popleft()
            except IndexError:
                break
            f = stream.decode(buf)
            if f is None:
                continue
            got += 1
            self.ingest(f)
        if got:
            self.frames_shown += got
        tag = self.channel.currentData()
        ring = self.rings.get(tag)
        if ring is not None:
            trig = self.trigger()
            self.scope.draw(ring, self.window_box.currentData(), self.rate_hz,
                            trig)
            self.trig_state.setText(self.trigger_state_text())
            # Measured over the sweep that was drawn, not over a fresh
            # one: a number beside a trace has to describe that trace.
            self.measure.update_from(
                stream.measure(self.scope.last_sweep, self.rate_hz))

    def trigger(self):
        """The trigger the controls currently describe, or None."""
        mode = self.trig_mode.currentData()
        if mode == "off":
            return None
        return stream.Trigger(
            level=stream.volts_to_codes(self.trig_level.value()),
            rising=bool(self.trig_slope.currentData()),
            mode=mode)

    def trigger_state_text(self):
        """What the sweep did, not what was asked for.

        "Auto" and "triggering" are different states and the difference
        is the whole reason this label exists: auto falls back to
        free-running when it finds no edge, and a trace that moves for
        that reason looks exactly like a trace that moves because the
        signal is wrong.
        """
        if self.trig_mode.currentData() == "off":
            return "free"
        return "TRIG" if self.scope.last_triggered else "searching"

    def ingest(self, f):
        if f.rate_hz and f.rate_hz != self.rate_hz:
            self.rate_hz = f.rate_hz
            for r in self.rings.values():
                r.set_rate(f.rate_hz)
        if self.last_seq is not None and f.seq != self.last_seq + 1:
            # A gap here is the daemon dropping toward us, which it
            # counts too - both numbers are on the panel so they can be
            # compared rather than confused.
            self.seq_gaps += 1
        self.last_seq = f.seq
        self.overruns = max(self.overruns, f.overrun_count)
        for tag, codes in f.channels.items():
            ring = self.rings.get(tag)
            if ring is None:
                ring = stream.ChannelRing(seconds=2.0, rate_hz=self.rate_hz)
                self.rings[tag] = ring
            ring.append(codes, discontinuous=f.discontinuous)

    def poll_status(self):
        if self.client is None:
            return
        try:
            st = self.client.call("status")["status"]
        except (clientmod.ClientError, OSError):
            # Disconnect first: it sets its own message, and the useful
            # one is the reason rather than the consequence.
            self.disconnect_from_daemon()
            self.statusBar().showMessage("daemon stopped answering")
            return
        self.health.set("mode", st.get("mode") or "idle")
        self.health.set("rate", f"{self.rate_hz:,} Hz")
        self.health.set("frames",
                        f"{self.frames_shown:,} / {st.get('frames_read', 0):,}")
        mine = [c for c in st.get("clients", []) if c.get("role") == "control"]
        self.health.set("dropped", mine[0]["dropped"] if mine else 0)
        self.health.set("gaps", self.seq_gaps)
        tag = self.channel.currentData()
        ring = self.rings.get(tag)
        self.health.set("breaks", ring.discontinuities if ring else 0)
        self.health.set("overruns", self.overruns)
        j = st.get("jitter", {})
        for key, name in (("read_gap", "read_gap"), ("feed", "feed"),
                          ("fanout", "fanout")):
            s = j.get(name)
            self.health.set(key, f"{s['max_us']:,} us" if s else "-")
        rec = st.get("recording")
        self.health.set("recording",
                        f"{rec['frames']:,} frames" if rec else "no")

    def closeEvent(self, event):
        self.disconnect_from_daemon()
        super().closeEvent(event)
