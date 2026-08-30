"""The window: a live trace, a health panel, and the controls G1 needs.

The shape follows `docs/frontend.md`. Frames arrive on the client's own
thread into a bounded deque; a Qt timer drains it and redraws. Nothing
blocks the event loop, and nothing in the daemon waits for the display:
if this window stalls, the daemon drops frames toward it, counts them,
and keeps streaming. The count is on screen for that reason.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))

from . import stream                        # noqa: E402
from .session import DaemonSession          # noqa: E402
from .health import HealthPanel             # noqa: E402
from .measure_panel import MeasurePanel     # noqa: E402
from .notice import NoticeBar               # noqa: E402
from .replay_bar import ReplayBar           # noqa: E402
from .awg import AwgPanel                   # noqa: E402
from .scope import ScopeView                # noqa: E402

# Spans offered in the timebase box, in seconds. Named for the control
# rather than "windows", which in this module already means the FFT
# window function.
TIMEBASES = [("1 ms", 0.001), ("5 ms", 0.005), ("20 ms", 0.02),
             ("100 ms", 0.1), ("500 ms", 0.5), ("2 s", 2.0)]

#: What the plot can show. One list, so the combo box and the View menu
#: cannot come to hold different ideas of what the options are.
VIEWS = [("Time", "time"), ("Spectrum", "spectrum"), ("XY", "xy")]

# Capture presets the firmware carries; the rate it actually produces
# comes back in the frame header, which is what gets displayed.
PRESETS = [("50 kHz", "1"), ("100 kHz", "2"), ("200 kHz", "3"),
           ("400 kHz", "4"), ("max in-spec", "5")]

#: Off free-runs the way this window always has. Auto triggers when
#: it can and free-runs when it cannot, which is the usable default.
#: Normal holds the last trace rather than drawing an untriggered
#: one, which is what you want when the edge is the question.
TRIGGER_MODES = [("Off", "off"), ("Auto", "auto"), ("Normal", "normal")]


def free_port():
    """A port nothing is listening on, for a daemon we are about to start.

    Racy in principle and not in practice: the daemon binds immediately,
    and the alternative - a fixed second port - collides with the last
    replay this window opened rather than with a stranger.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def describe_source(dev):
    """Moved to `stream.describe_source`; re-exported for callers.

    Kept as a name here because tests and `__main__` import it from this
    module, and because "where does app.py get its strings" should have
    one answer rather than two spellings of it.
    """
    return stream.describe_source(dev)


class MainWindow(QtWidgets.QMainWindow):
    # Frames decoded per redraw. At 30 Hz this keeps up with about
    # 3,600 frames a second, comfortably above the ~442 the full rate
    # produces, while bounding the work one tick can do.
    MAX_DRAIN = 120

    def __init__(self, host="127.0.0.1", port=45454, parent=None):
        super().__init__(parent)
        self.setWindowTitle("due_oscilloscope")
        self.resize(1100, 660)

        self.host = host
        self.port = port
        #: Where this window was pointed when it started. `Open
        #: recording` moves it to a daemon it spawned itself, and this
        #: is what Device > Connect to ... comes back to.
        self.home = (host, port)
        self.replay_child = None

        # The daemon connection, and every way it can go wrong. The
        # window asks it for things and renders what comes back on the
        # signals; it never touches `daemon.client` itself.
        self.session = DaemonSession(host, port, parent=self)
        self.session.connected.connect(self._on_connected)
        self.session.connect_failed.connect(self._on_connect_failed)
        self.session.disconnected.connect(self._on_disconnected)
        self.session.refused.connect(self._on_refused)
        self.session.status.connect(self._on_status)
        self.session.counters.connect(self._on_counters)
        self.session.heartbeat.connect(self._on_heartbeat)
        self.session.event.connect(self._on_event)

        # Everything one run accumulates, in one object with one
        # `reset()`. See `stream.AcquisitionState` for what having it in
        # two places cost.
        self.acq = stream.AcquisitionState()

        # Whether the daemon is serving a recording rather than a
        # board. Not part of the run state: it changes what may be asked
        # of the source, not what a run accumulates, and it is settled
        # at connect time.
        self.replaying = False

        # What the *device* is doing, from its own status. Not what the
        # buttons were last told to ask for - Run/Stop has to do the
        # other thing to whatever is actually happening.
        self.device_running = False

        # Whether the end of the current recording has been announced.
        # Once per run: `at_end` stays true until something starts it
        # again, and repeating the notice every poll would be noise.
        self._said_end = False

        self._build_panels()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_controls()
        self._build_layout()
        self._build_timers()
        self.statusBar().showMessage(f"not connected ({host}:{port})")

    # -- construction --------------------------------------------------
    #
    # Split by what it builds rather than left in one 156-line method.
    # This is the first thing anyone reads, and "where is the trigger
    # level set up" should not be a scroll.

    def _build_panels(self):
        self.scope = ScopeView()
        self.health = HealthPanel()
        self.measure = MeasurePanel()
        self.awg = AwgPanel()
        self.awg.requested.connect(self.awg_requested)

        # Where a refusal goes, now that there is somewhere for it to
        # stay. See `gui/notice.py`.
        self.notice = NoticeBar()
        # Counted from construction, not from connect: a beat can
        # arrive on the first drain after `hello`, before the
        # connect handler has run.
        self._hb_seen = 0

        # Only ever shown while the source is a recording: a board has
        # no position, and a progress bar against one would be inventing
        # a number.
        self.replay_bar = ReplayBar()
        self.replay_bar.restart.connect(self.restart_replay)
        self.replay_bar.hide()

    def _build_actions(self):
        """The verbs, once each.

        A `QAction` rather than a button because the same verb appears
        in the menu, on the toolbar and on a keyboard shortcut, and one
        object in three places cannot drift the way three objects do -
        enabling it once disables it everywhere.

        **Every shortcut carries Ctrl, including the ones a bench scope
        would give a bare key.** A bare Space or `[` belongs to whatever
        widget has focus: Space opens a focused combo box and a digit
        types into the trigger-level spin box. A shortcut that works
        until you click a control is worse than one that reads as
        slightly formal.
        """
        def action(text, slot, shortcut=None, checkable=False, tip=None):
            act = QtGui.QAction(text, self)
            if shortcut:
                act.setShortcut(shortcut)
            if tip:
                act.setToolTip(tip)
                act.setStatusTip(tip)
            if checkable:
                act.setCheckable(True)
                act.toggled.connect(slot)
            else:
                act.triggered.connect(slot)
            return act

        self.act_connect = action("&Connect", self.toggle_connect, "Ctrl+K")
        self.act_start = action("&Start", self.start_capture, "Ctrl+Return")
        self.act_stop = action("Sto&p", self.stop_capture, "Ctrl+.")
        self.act_run = action("&Run / Stop", self.toggle_run, "Ctrl+Space",
                              tip="Start if the device is idle, stop if it "
                                  "is running")
        self.act_start.setEnabled(False)
        self.act_stop.setEnabled(False)

        # Recording is the *daemon's*, not this window's, and that is
        # the point: docs/frontend.md says "the daemon writes the file,
        # not the GUI", because a recording that stops when a display is
        # closed or drops what a slow display dropped is not a record of
        # the run. This only asks.
        self.act_record = action("&Record...", self.toggle_record, "Ctrl+R",
                                 checkable=True)
        self.act_record.setEnabled(False)

        # Export is this window's, and only ever of what is on screen.
        self.act_export = action("&Export CSV...", self.export_csv, "Ctrl+E")

        self.act_open = action("&Open recording...", self.open_recording,
                               "Ctrl+O",
                               tip="Start a daemon replaying a recorded "
                                   "file, and connect to it")
        self.act_home = action(f"Connect to {self.home[0]}:{self.home[1]}",
                               self.connect_home)
        self.act_quit = action("&Quit", self.close, "Ctrl+Q")

        self.act_cursors = action("C&ursors", self.scope_cursors, "Ctrl+U",
                                  checkable=True)

        self.act_views = [
            action(label, (lambda _=None, k=key: self.set_view(k)),
                   f"Ctrl+{n}")
            for n, (label, key) in enumerate(VIEWS, start=1)]
        self.act_shorter = action("S&horter timebase",
                                  lambda: self.step_timebase(-1), "Ctrl+[")
        self.act_longer = action("&Longer timebase",
                                 lambda: self.step_timebase(+1), "Ctrl+]")
        self.act_about = action("&About", self.about)

    def _build_menus(self):
        bar = self.menuBar()
        f = bar.addMenu("&File")
        f.addAction(self.act_open)
        f.addSeparator()
        f.addAction(self.act_record)
        f.addAction(self.act_export)
        f.addSeparator()
        f.addAction(self.act_quit)

        d = bar.addMenu("&Device")
        d.addAction(self.act_connect)
        d.addSeparator()
        d.addAction(self.act_start)
        d.addAction(self.act_stop)
        d.addAction(self.act_run)
        d.addSeparator()
        d.addAction(self.act_home)

        v = bar.addMenu("&View")
        for act in self.act_views:
            v.addAction(act)
        v.addSeparator()
        v.addAction(self.act_cursors)
        v.addSeparator()
        v.addAction(self.act_shorter)
        v.addAction(self.act_longer)

        bar.addMenu("&Help").addAction(self.act_about)

    def _build_toolbar(self):
        """The five verbs, and only those.

        They used to sit in the control row under the plot, where
        fifteen widgets competed for 1100 px. Moving them up frees about
        two fifths of that row for the controls that actually describe
        what is on screen.
        """
        bar = QtWidgets.QToolBar("Main", self)
        bar.setMovable(False)
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        bar.addAction(self.act_connect)
        bar.addSeparator()
        bar.addAction(self.act_start)
        bar.addAction(self.act_stop)
        bar.addSeparator()
        bar.addAction(self.act_record)
        bar.addAction(self.act_export)
        self.addToolBar(bar)
        self.toolbar = bar

    def _build_controls(self):
        # Both channels are drawn; this picks which one the trigger and
        # the measurements follow. That is what a scope's trigger-source
        # selector is, rather than a "which one do I look at" switch.
        self.channel = QtWidgets.QComboBox()
        for tag, label in sorted(stream.LABELS.items(), reverse=True):
            self.channel.addItem(label, tag)

        # `timebase`, not `window`: this module already uses "window" for
        # the FFT window function, and one name for two things in the
        # same call - `scope.draw(..., window_s, ..., fft_window)` - is a
        # trap for whoever reads it next.
        self.timebase = QtWidgets.QComboBox()
        for label, secs in TIMEBASES:
            self.timebase.addItem(label, secs)
        self.timebase.setCurrentIndex(2)

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

        # Time or spectrum. One plot rather than two, because the
        # rendering budget is one 1200-column redraw per 33 ms and a
        # second live plot halves it - docs/frontend.md sizes the UI
        # around that.
        self.view_box = QtWidgets.QComboBox()
        for label, key in VIEWS:
            self.view_box.addItem(label, key)

        self.fft_window = QtWidgets.QComboBox()
        for w in stream.FFT_WINDOWS:
            self.fft_window.addItem(w.capitalize(), w)
        self.fft_window.setToolTip(
            "Rectangular is exact only when the window holds a whole "
            "number of cycles, and smears the tone everywhere else.")

        # The draggable trigger line (issue #8's B6). Two controls, one
        # level: the spin box and the line echo each other, and the
        # echo terminates because ScopeView.set_trigger_line treats a
        # sub-resolution difference as the same value. Mode and view
        # changes re-decide whether the line belongs on the plot at all.
        self.trig_level.valueChanged.connect(self._sync_trig_line)
        self.trig_mode.currentIndexChanged.connect(self._sync_trig_line)
        self.view_box.currentIndexChanged.connect(self._sync_trig_line)
        self.scope.trig_line.sigPositionChanged.connect(
            self._trig_line_dragged)
        self._sync_trig_line()

        # The menu's cursor action, wearing a button. One checkable
        # thing, so the tick and the button can never disagree.
        self.cursor_button = QtWidgets.QToolButton()
        self.cursor_button.setDefaultAction(self.act_cursors)

    def _build_layout(self):
        def separator():
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.VLine)
            line.setFrameShadow(QtWidgets.QFrame.Sunken)
            return line

        # Three groups, in the order a scope is set up: what is being
        # looked at, what holds it still, and how it is drawn. They used
        # to run flat, fifteen widgets deep with the buttons among them,
        # and nothing said where one idea ended and the next began.
        controls = QtWidgets.QHBoxLayout()
        groups = (
            (QtWidgets.QLabel("Source"), self.channel,
             QtWidgets.QLabel("Timebase"), self.timebase,
             QtWidgets.QLabel("Rate"), self.preset),
            (QtWidgets.QLabel("Trigger"), self.trig_mode,
             self.trig_slope, self.trig_level, self.trig_state),
            (QtWidgets.QLabel("View"), self.view_box, self.fft_window,
             self.cursor_button),
        )
        for i, group in enumerate(groups):
            if i:
                controls.addWidget(separator())
            for w in group:
                controls.addWidget(w)
        controls.addStretch(1)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.scope, 1)
        left.addWidget(self.notice)
        left.addWidget(self.replay_bar)
        left.addLayout(controls)

        side = QtWidgets.QVBoxLayout()
        side.addWidget(self.health)
        side.addWidget(self.measure)
        side.addWidget(self.awg)
        side.addStretch(1)

        body = QtWidgets.QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(side)

        central = QtWidgets.QWidget()
        central.setLayout(body)
        self.setCentralWidget(central)

    def _build_timers(self):
        # Draw at 30 Hz; poll the daemon's own numbers at 4 Hz. Status
        # is answerable from the host alone - it costs the device
        # nothing - which is why polling it is safe at all.
        self.draw_timer = QtCore.QTimer(self)
        self.draw_timer.timeout.connect(self.tick)
        self.draw_timer.start(33)
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.poll_status)
        self.status_timer.start(250)

    # -- view controls -------------------------------------------------
    def set_view(self, key):
        i = self.view_box.findData(key)
        if i >= 0:
            self.view_box.setCurrentIndex(i)

    def step_timebase(self, delta):
        """One step along the timebase list, and stop at the ends.

        Wrapping would take the 1 ms setting to 2 s on one keypress,
        which on a rolling display looks like the signal changed.
        """
        i = self.timebase.currentIndex() + delta
        if 0 <= i < self.timebase.count():
            self.timebase.setCurrentIndex(i)

    def about(self):
        QtWidgets.QMessageBox.about(
            self, "due_oscilloscope",
            "A front end for the Due capture daemon.\n\n"
            "The daemon owns the device and this window draws what it "
            "sends; `docs/frontend.md` says why they are separate "
            "processes, and \"Where a change goes\" says which module "
            "a change belongs in.")

    # -- what this run has accumulated ---------------------------------
    #
    # Read-only forwards onto `self.acq`. This is the window's read
    # surface - what the health panel, the export header and the
    # headless tests ask it - and read-only is the point: there is one
    # writer, and `AcquisitionState.reset()` is the whole answer to what
    # a new run clears.
    rings = property(lambda self: self.acq.rings)
    rate_hz = property(lambda self: self.acq.rate_hz)
    frames_shown = property(lambda self: self.acq.frames_shown)
    seq_gaps = property(lambda self: self.acq.seq_gaps)
    last_seq = property(lambda self: self.acq.last_seq)
    overruns = property(lambda self: self.acq.overruns)

    # -- connection ---------------------------------------------------
    #
    # The window's half of this is presentation only. `DaemonSession`
    # owns the socket and decides what is a refusal and what is a lost
    # link; every method below either asks it for something or renders
    # one of its signals.
    def toggle_connect(self):
        if self.session.is_open:
            self.disconnect_from_daemon()
        else:
            self.connect_to_daemon()

    def connect_to_daemon(self):
        self.notice.clear()
        self.session.open("control")

    @property
    def client(self):
        """The session's client, or None.

        Read-only, and the window's own code does not use it: it is here
        because "is there a link" and "how many frames has it seen" are
        questions the headless tests ask of the window, and routing them
        through one property is what keeps the session the only writer.
        """
        return self.session.client

    def _on_connected(self, dev, role):
        self._hb_seen = 0
        self.health.set("link", f"{self.host}:{self.port}")
        self.health.set("source", describe_source(dev))
        self.health.set("role", role)
        self.act_connect.setText("&Disconnect")
        self.act_start.setEnabled(role == "control")
        # Recording is the daemon's and needs no control role - an
        # observer may record what it is watching.
        self.act_record.setEnabled(True)
        self.act_stop.setEnabled(role == "control")
        self.set_replay(dev)
        self.session.call("subscribe", frames=True)
        self.statusBar().showMessage(
            f"connected to {dev.get('kind', '?')} device")

    def _on_connect_failed(self, message):
        self.notice.error(message)

    def _on_refused(self, op, message):
        """Rule 4 in one place: the device's own message, naming the limit.

        The message is rendered here and nowhere else. What a caller
        still owns is repairing its own widget - a checkable button that
        asked for something and did not get it has to come back up - and
        it learns that from `call()` returning None rather than by
        catching an exception and inventing its own wording, which is
        what the five call sites here used to do five different ways.

        It goes to the notice bar and not to a dialog. A refusal here
        names a limit worth reading twice - the rate the hardware will
        actually make, the offset that would fit - and a modal is the
        one presentation that cannot be read twice. The status bar gets
        it too, and loses it to the next poll, which is what the status
        bar is for.
        """
        self.notice.error(f"{op} refused: {message}")
        self.statusBar().showMessage(f"{op} refused: {message}")

    def set_replay(self, dev):
        """Shut off the controls a recording has nothing to answer with.

        A replay has no generator and no rate to be asked for: the
        samples are at the rate they were taken at, and the frame
        headers say so. Leaving the generator panel live would let a
        waveform be uploaded that nothing plays, and leaving the preset
        box live would suggest a rate this source can be moved to.
        Greyed out is the honest state, not a disabled feature.
        """
        replay = dev.get("kind") == "file"
        self.replaying = replay
        self.awg.setEnabled(not replay)
        self.preset.setEnabled(not replay)
        self.replay_bar.setVisible(replay)
        self.replay_bar.reset()
        if not replay:
            self.setWindowTitle("due_oscilloscope")
            return
        self.setWindowTitle(f"due_oscilloscope - replaying "
                            f"{dev.get('path', '?')}")
        trunc = dev.get("truncated_bytes") or 0
        dropped = dev.get("recorded_dropped") or 0
        notes = []
        if dropped:
            notes.append(f"{dropped:,} frames were dropped when it was "
                         f"recorded")
        if trunc:
            notes.append(f"{trunc:,} trailing bytes are not a whole frame")
        if notes:
            # Said once, on connect, rather than left to be noticed in a
            # counter. A hole in the source is not a fault of the trace
            # on screen, and the two are easy to confuse - and it stays
            # on screen, because it is true for as long as this
            # recording is the source.
            self.notice.info("About this recording: " + "; ".join(notes) + ".")

    def disconnect_from_daemon(self):
        self.session.close()

    def restart_replay(self):
        """Play the recording again from the beginning.

        Stop first: `start` on a device that is already running is
        refused, by the fake and by the board alike, and a replay that
        has not reached its end is still running.
        """
        self.session.call("stop")
        self.replay_bar.reset()
        self.start_capture()

    def _on_disconnected(self, reason):
        self.act_connect.setText("&Connect")
        self.act_start.setEnabled(False)
        self.act_record.setEnabled(False)
        self.act_stop.setEnabled(False)
        self.act_record.setChecked(False)
        self.device_running = False
        self.health.set("link", "-")
        self.health.set("source", "-")
        self.replaying = False
        self.awg.setEnabled(True)
        self.preset.setEnabled(True)
        self.replay_bar.hide()
        self.replay_bar.reset()
        self.setWindowTitle("due_oscilloscope")
        # The reason when the link went away underneath us, the bare
        # word when we closed it. Which of the two happened is the
        # session's to know; the window used to infer it from which of
        # its own methods it happened to be standing in.
        self.statusBar().showMessage(reason or "disconnected")

    # -- device -------------------------------------------------------
    def start_capture(self):
        if not self.session.is_open:
            return
        # A new run answers whatever the last one was refused for. A
        # notice that outlived the thing it was about would be the same
        # defect as a counter that did.
        self.notice.clear()
        self._said_end = False
        self.acq.reset()
        # No preset and no rate when the source is a recording: it has
        # one rate, it is in the frames, and asking for another would be
        # asking the file to convert.
        extra = ({} if self.replaying else
                 {"preset": self.preset.currentData(),
                  "adc_hz": 200000, "channels": 2})
        self.session.call("start", mode="capture", **extra)

    def stop_capture(self):
        self.session.call("stop")

    def toggle_run(self):
        """Whatever the device is doing, do the other thing.

        Off the device's own `running`, not off which button was pressed
        last: a replay that reached the end of its file stopped without
        anyone asking, and a Run key that argued with that would be
        asking the daemon to start something already started.
        """
        if self.device_running:
            self.stop_capture()
        else:
            self.start_capture()

    # -- the loop -----------------------------------------------------
    def tick(self):
        if not self.session.is_open:
            return
        frames = self.session.frames
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
            self.acq.ingest(f)
        tag = self.channel.currentData()
        if self.acq.ring(tag) is not None:
            trig = self.trigger()
            view = self.view_box.currentData()
            self.fft_window.setEnabled(view == "spectrum")
            self.scope.draw(self.acq.rings, tag,
                            self.timebase.currentData(),
                            self.acq.rate_hz, trig, view,
                            self.fft_window.currentData())
            self.trig_state.setText(self.trigger_state_text())
            # Measured over the sweep that was drawn, not over a fresh
            # one: a number beside a trace has to describe that trace.
            self.measure.update_from(
                stream.measure(self.scope.last_sweep, self.acq.rate_hz))
            self.measure.set_cursor(self.cursor_text())

    def toggle_record(self, on):
        """Ask the daemon to start or stop writing frames.

        The frames go to disk exactly as the device sent them - header,
        CRC and all - so a recording can be replayed through the same
        parser that read it live. A CSV of what the screen happened to
        show would not be that.
        """
        if not self.session.is_open:
            self.act_record.setChecked(False)
            return
        if not on:
            reply = self.session.call("record.stop")
            if reply is None:                    # already reported
                return
            side = reply.get("sidecar", {})
            self.act_record.setText("&Record...")
            self.statusBar().showMessage(
                f"recorded {side.get('frames', 0):,} frames, "
                f"{side.get('bytes', 0):,} bytes, "
                f"{side.get('dropped', 0):,} dropped")
            return

        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Record frames to", "capture.due",
            "Frame recordings (*.due);;All files (*)")
        if not path:
            self.act_record.setChecked(False)
            return
        if self.session.call("record.start", path=path) is None:
            self.act_record.setChecked(False)
            return
        self.act_record.setText("Stop &recording")
        self.statusBar().showMessage(f"recording to {path}")

    def export_csv(self):
        """Write the sweep on screen, in the units on screen.

        Deliberately only what is displayed, and it says so in the
        header. Exporting "the last two seconds" from the ring instead
        would hand back samples the user never saw and never triggered
        on, and a file that does not match the picture it came from is
        the kind of evidence that gets argued about later.
        """
        sweep = self.scope.last_sweep
        if sweep.empty:
            self.statusBar().showMessage("nothing on screen to export")
            return
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export the visible sweep", "sweep.csv",
            "CSV (*.csv);;All files (*)")
        if not path:
            return
        try:
            n = self._write_csv(path, sweep)
        except OSError as e:
            self.statusBar().showMessage(f"export failed: {e}")
            return
        self.statusBar().showMessage(f"exported {n:,} samples to {path}")

    def _write_csv(self, path, sweep):
        """The sweep as displayed. See `stream.write_csv`."""
        return stream.write_csv(path, sweep,
                                source=self.channel.currentData(),
                                rings=self.rings, rate_hz=self.rate_hz)

    def scope_cursors(self, on):
        self.scope.set_cursors(bool(on))
        # cursor_text(), not cursor_reading(): the panel takes the
        # formatted string and the reading is a dict.
        self.measure.set_cursor(self.cursor_text())

    def cursor_text(self):
        """The reading, formatted. See `stream.cursor_text`."""
        return stream.cursor_text(self.scope.cursor_reading())

    def awg_requested(self, shape, hz, vpp, offset, running):
        """Build the waveform, send it, and drive the loop.

        `loop` rather than `play`: the point of a generator on a
        loopback bench is seeing what came back, and loop mode feeds
        DAC0 and captures at the same time. docs/frontend.md's Safety
        section is why there is no other mode here - DAC0 to A0 over a
        jumper is the whole of it.
        """
        if not self.session.is_open:
            return
        if not running:
            if self.session.call("stop") is not None:
                self.statusBar().showMessage("generator stopped")
            return

        lo, hi, why = self.awg.code_range()
        if why is not None:                              # already shown
            return
        try:
            import measure as measuremod
        except ImportError:
            self.statusBar().showMessage("host/measure.py not importable")
            return

        # The rate the *device* will make, not the one typed. Rule 1:
        # rate controls snap to an integer RC and display what the
        # hardware makes - the frame header is what the display trusts,
        # and the AWG's own rate is the same kind of number.
        dac_sps = 200000
        blob, actual_hz = measuremod.build_arb(
            shape, hz, dac_sps, lo_code=lo, hi_code=hi, cycles=20)

        # Play starts the device, so it clears the last run exactly as
        # Start does. Without this the rings, the sequence-gap count and
        # the discontinuity count carried across and the previous run's
        # samples were drawn as this one's - rule 2's own failure, the
        # one that manufactured a "frozen DAC" that was not happening,
        # reachable from a button.
        #
        # After the local checks and not before them: a request the
        # panel itself refuses never reaches the device, so there is no
        # new run to make room for.
        self.acq.reset()
        if not self.session.send_awg(blob):
            self.awg.run_btn.setChecked(False)
            return
        if self.session.call("start", mode="loop", dac_sps=dac_sps,
                             adc_hz=dac_sps, channels=2) is None:
            self.awg.run_btn.setChecked(False)
            return
        self.statusBar().showMessage(
            f"{shape} {actual_hz:,.1f} Hz, {vpp:.3f} Vpp at {offset:.3f} V "
            f"(codes {lo}-{hi})")

    def _sync_trig_line(self, *_):
        """Show the trigger level on the plot when it means something.

        Off means there is no trigger to show. Spectrum and XY change
        the axes out from under a level expressed in volts-at-time, so
        the line leaves with them.
        """
        show = (self.trig_mode.currentData() != "off"
                and self.view_box.currentData() == "time")
        self.scope.set_trigger_line(
            self.trig_level.value() if show else None)

    def _trig_line_dragged(self):
        """The line moved (a drag, or anything else that setPos's it);
        the spin box follows. The spin rounds to its three decimals and
        echoes back through _sync_trig_line, where the sub-resolution
        guard ends the round trip."""
        self.trig_level.setValue(float(self.scope.trig_line.value()))

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
        """What the sweep did. See `stream.trigger_state_text`."""
        return stream.trigger_state_text(self.trig_mode.currentData(),
                                         self.scope.last_triggered)

    def ingest(self, f):
        """One decoded frame into the run state.

        Kept as a method because the headless tests drive the window
        this way, and because "what this window does with a frame" is a
        reasonable thing to be able to call. The logic itself lives in
        `stream.AcquisitionState.ingest`, where the gap and
        discontinuity rules can be exercised without a widget.
        """
        return self.acq.ingest(f)

    def _on_heartbeat(self, beat, stalled):
        """One beat the device sent unasked.

        This is the only thing in the window that can distinguish "the
        board's main loop has stopped" from "the board is gone". The
        beat is emitted from a timer interrupt while `loop_passes` comes
        from the main loop, so a beat that keeps arriving with a frozen
        count is the stall reporting itself - see issue #33, where every
        other channel went dark together because all of them were
        answered by the loop that had stopped.
        """
        self._hb_seen += 1
        if stalled:
            self.health.set("beat", f"STALLED seq {beat.get('seq', '?')}",
                            alarm=True)
            # Persistent, not the status bar: the 4 Hz poll would
            # overwrite it inside 250 ms, which is what `notice.py`
            # exists for.
            self.notice.error(
                "the board's main loop has stopped - beats are still "
                "arriving from its timer, and loop_passes is frozen. "
                "Only a reset clears this.")
        else:
            self.health.set("beat", f"seq {beat.get('seq', '?')}")

    def _on_event(self, name, obj):
        """Everything else the daemon pushed.

        Nothing read these before: the client sorted them into a deque
        and the window never drained it, so a refused waveform and a
        `device_error` both expired there. `error` and `device_error`
        are the two that carry something a poll cannot reconstruct.
        """
        if name == "device_error":
            self.notice.error(f"device: {obj.get('message', '')}")
        elif name == "error" and obj.get("id") is None:
            # Unsolicited errors only. One carrying an id is a reply and
            # already surfaces through the call that asked.
            self.notice.error(f"daemon: {obj.get('message', '')}")

    def poll_status(self):
        """Ask; the answers arrive on `_on_status` and `_on_counters`.

        Two questions rather than one because the daemon keeps them
        apart on purpose: `status` is answerable from the host alone and
        costs the device nothing, which is what makes polling it at 4 Hz
        safe, while `counters` can cost a console round trip.
        """
        self.session.poll()

    def _on_status(self, st):
        self.device_running = bool(st.get("running"))
        self.health.set("mode", st.get("mode") or "idle")
        self.health.set("rate", f"{self.acq.rate_hz:,} Hz")
        self.health.set("frames",
                        f"{self.acq.frames_shown:,} / "
                        f"{st.get('frames_read', 0):,}")
        mine = [c for c in st.get("clients", []) if c.get("role") == "control"]
        self.health.set("dropped", mine[0]["dropped"] if mine else 0)
        self.health.set("gaps", self.acq.seq_gaps)
        self.health.set("breaks",
                        self.acq.discontinuities(self.channel.currentData()))
        self.health.set("overruns", self.acq.overruns)
        j = st.get("jitter", {})
        for key in ("read_gap", "feed", "fanout"):
            summary = j.get(key)
            self.health.set(key,
                            f"{summary['max_us']:,} us" if summary else "-")
        rec = st.get("recording")
        self.health.set("recording",
                        f"{rec['frames']:,} frames" if rec else "no")
        # Cleared here and filled by `_on_counters` a moment later, in
        # the same tick. `counters` is the call that can refuse while
        # playback runs, and a stale underrun count left on screen from
        # the last successful poll is exactly the kind of number this
        # panel exists to stop showing.
        self.awg.underruns.setText("-")

    def _on_counters(self, ct):
        # The generator's own number, and the only one that says the
        # host kept up. under=0 has coexisted with a badly wrong signal
        # in this project before, which is why it sits next to the
        # controls that cause it rather than in a log.
        self.awg.underruns.setText(f"{ct.get('underruns', 0):,}")
        if not self.replaying:
            return
        self.replay_bar.set_position(ct)
        # A recording ends on its own, which on a board only ever
        # happens because something went wrong. Said out loud so a
        # stopped trace is not read as a fault.
        #
        # Off the daemon's own `at_end` rather than off watching
        # `running` go false: a short recording can be over before the
        # first status poll, and an edge nobody was there to see is an
        # end that never gets announced.
        if ct.get("at_end") and not self._said_end:
            self._said_end = True
            self.notice.info("End of the recording. Restart to play it "
                             "again, or open another.")

    # -- opening a recording -------------------------------------------
    #
    # The window starts a daemon and connects to it; it does not read the
    # file. That is the same rule as "the daemon writes the file, not the
    # GUI" - the daemon owns the source, and a front end that could swap
    # it underneath a running recorder is the confusion the split exists
    # to prevent. What this adds is only that you no longer have to leave
    # the program to do it.
    def open_recording(self):
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open a recording", "",
            "Frame recordings (*.due *.frames);;All files (*)")
        if path:
            self.notice.clear()
            self.replay(path)

    def replay(self, path):
        """Start a daemon serving `path`, and point this window at it."""
        self._stop_replay_child()
        port = free_port()
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            child = subprocess.Popen(
                [sys.executable, "-m", "daemon", "--file",
                 os.path.abspath(path), "--host", "127.0.0.1",
                 "--port", str(port)],
                cwd=os.path.join(root, "host"),
                stderr=subprocess.PIPE, text=True)
        except OSError as e:                             # no interpreter
            self.notice.error(f"Cannot replay: {e}")
            return
        self.replay_child = child

        self.session.point_at("127.0.0.1", port)
        self.host, self.port = "127.0.0.1", port
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            # The daemon refuses an unreadable recording, a sidecar
            # declaring another frame geometry, or a file that holds no
            # whole frame - and it does all three *before* binding a
            # port, so a child that has exited is carrying the useful
            # message and "could not reach a daemon" would bury it.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    err = (child.stderr.read() or "").strip()
                    self.replay_child = None
                    self.notice.error(
                        "Cannot replay: "
                        + (err or f"the daemon exited with "
                                  f"{child.returncode}"))
                    return
                if self.session.open("control", quiet=True):
                    return
                time.sleep(0.1)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._stop_replay_child()
        self.notice.error(f"Cannot replay: the daemon started but never "
                          f"answered on port {port}")

    def connect_home(self):
        """Back to the daemon this window was pointed at when it started."""
        self._stop_replay_child()
        self.host, self.port = self.home
        self.session.point_at(*self.home)
        self.session.open("control")

    def _stop_replay_child(self):
        child, self.replay_child = self.replay_child, None
        if child is None:
            return
        if self.session.is_open and self.port != self.home[1]:
            self.session.close()
        child.terminate()
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            child.kill()

    def closeEvent(self, event):
        self.disconnect_from_daemon()
        # A replay daemon this window started is this window's to end.
        # Leaving it holding a port would make the next Open recording
        # look like it worked and connect to the previous file.
        self._stop_replay_child()
        super().closeEvent(event)
