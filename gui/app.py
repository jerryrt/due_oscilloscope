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

from . import stream                        # noqa: E402
from .session import DaemonSession          # noqa: E402
from .health import HealthPanel             # noqa: E402
from .measure_panel import MeasurePanel     # noqa: E402
from .awg import AwgPanel                   # noqa: E402
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


def describe_source(dev):
    """One line naming where the samples come from.

    The panel already said which host and port; what it never said is
    what is on the other end. That mattered less when the only two
    answers were a board and the synthetic device, and matters now that
    a third answer is somebody else's bench an hour ago.
    """
    kind = dev.get("kind", "?")
    if kind == "file":
        rec = dev.get("recorded") or {}
        track = rec.get("track")
        n = dev.get("frames")
        bit = f"{n:,} frames" if isinstance(n, int) else "recording"
        return (f"{dev.get('path', 'recording')} ({bit}"
                + (f", track {track}" if track and track != "fake" else "")
                + ")")
    track = dev.get("track")
    return f"{kind}" + (f" (track {track})" if track else "")


class MainWindow(QtWidgets.QMainWindow):
    # Frames decoded per redraw. At 30 Hz this keeps up with about
    # 3,600 frames a second, comfortably above the ~442 the full rate
    # produces, while bounding the work one tick can do.
    MAX_DRAIN = 120

    #: Refusals worth interrupting for, rather than a line in the status
    #: bar that the next message overwrites. A rate the hardware will
    #: not make is a decision the user has to change before anything
    #: else can happen; a refused `stop` is information. One set rather
    #: than a choice made separately at each call site, because those
    #: five sites used to disagree.
    LOUD_REFUSALS = {"start"}

    def __init__(self, host="127.0.0.1", port=45454, parent=None):
        super().__init__(parent)
        self.setWindowTitle("due_oscilloscope")
        self.resize(1100, 620)

        self.host = host
        self.port = port

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

        # Everything one run accumulates, in one object with one
        # `reset()`. See `stream.AcquisitionState` for what having it in
        # two places cost.
        self.acq = stream.AcquisitionState()

        # Whether the daemon is serving a recording rather than a
        # board. Not part of the run state: it changes what may be asked
        # of the source, not what a run accumulates, and it is settled
        # at connect time.
        self.replaying = False

        self.scope = ScopeView()
        self.health = HealthPanel()
        self.measure = MeasurePanel()
        self.awg = AwgPanel()
        self.awg.requested.connect(self.awg_requested)

        # Both channels are drawn; this picks which one the trigger and
        # the measurements follow. That is what a scope's trigger-source
        # selector is, rather than a "which one do I look at" switch.
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

        # Time or spectrum. One plot rather than two, because the
        # rendering budget is one 1200-column redraw per 33 ms and a
        # second live plot halves it - docs/frontend.md sizes the UI
        # around that.
        self.view_box = QtWidgets.QComboBox()
        self.view_box.addItem("Time", "time")
        self.view_box.addItem("Spectrum", "spectrum")
        self.view_box.addItem("XY", "xy")

        self.cursor_btn = QtWidgets.QCheckBox("Cursors")
        self.cursor_btn.toggled.connect(self.scope_cursors)

        # Recording is the *daemon's*, not this window's, and that is
        # the point: docs/frontend.md says "the daemon writes the file,
        # not the GUI", because a recording that stops when a display
        # is closed or drops what a slow display dropped is not a
        # record of the run. This button only asks.
        self.record_btn = QtWidgets.QPushButton("Record...")
        self.record_btn.setCheckable(True)
        self.record_btn.toggled.connect(self.toggle_record)
        self.record_btn.setEnabled(False)

        # Export is this window's, and only ever of what is on screen.
        self.export_btn = QtWidgets.QPushButton("Export CSV...")
        self.export_btn.clicked.connect(self.export_csv)

        self.fft_window = QtWidgets.QComboBox()
        for w in stream.FFT_WINDOWS:
            self.fft_window.addItem(w.capitalize(), w)
        self.fft_window.setToolTip(
            "Rectangular is exact only when the window holds a whole "
            "number of cycles, and smears the tone everywhere else.")

        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        for b in (self.start_btn, self.stop_btn):
            b.setEnabled(False)
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(self.stop_capture)

        controls = QtWidgets.QHBoxLayout()
        for w in (QtWidgets.QLabel("Source"), self.channel,
                  QtWidgets.QLabel("Window"), self.window_box,
                  QtWidgets.QLabel("Rate"), self.preset,
                  QtWidgets.QLabel("Trigger"), self.trig_mode,
                  self.trig_slope, self.trig_level, self.trig_state,
                  QtWidgets.QLabel("View"), self.view_box, self.fft_window,
                  self.cursor_btn):
            controls.addWidget(w)
        controls.addStretch(1)
        for b in (self.record_btn, self.export_btn,
                  self.connect_btn, self.start_btn, self.stop_btn):
            controls.addWidget(b)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.scope, 1)
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
        self.health.set("link", f"{self.host}:{self.port}")
        self.health.set("source", describe_source(dev))
        self.health.set("role", role)
        self.connect_btn.setText("Disconnect")
        self.start_btn.setEnabled(role == "control")
        # Recording is the daemon's and needs no control role - an
        # observer may record what it is watching.
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(role == "control")
        self.set_replay(dev)
        self.session.call("subscribe", frames=True)
        self.statusBar().showMessage(
            f"connected to {dev.get('kind', '?')} device")

    def _on_connect_failed(self, message):
        QtWidgets.QMessageBox.warning(self, "No daemon", message)

    def _on_refused(self, op, message):
        """Rule 4 in one place: the device's own message, naming the limit.

        The message is rendered here and nowhere else. What a caller
        still owns is repairing its own widget - a checkable button that
        asked for something and did not get it has to come back up - and
        it learns that from `call()` returning None rather than by
        catching an exception and inventing its own wording, which is
        what the five call sites here used to do five different ways.
        """
        if op in self.LOUD_REFUSALS:
            QtWidgets.QMessageBox.warning(self, "Refused", message)
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
            # on screen, and the two are easy to confuse.
            QtWidgets.QMessageBox.information(
                self, "About this recording", "; ".join(notes) + ".")

    def disconnect_from_daemon(self):
        self.session.close()

    def _on_disconnected(self, reason):
        self.connect_btn.setText("Connect")
        self.start_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.record_btn.setChecked(False)
        self.health.set("link", "-")
        self.health.set("source", "-")
        self.replaying = False
        self.awg.setEnabled(True)
        self.preset.setEnabled(True)
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
                            self.window_box.currentData(),
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
            self.record_btn.setChecked(False)
            return
        if not on:
            reply = self.session.call("record.stop")
            if reply is None:                    # already reported
                return
            side = reply.get("sidecar", {})
            self.record_btn.setText("Record...")
            self.statusBar().showMessage(
                f"recorded {side.get('frames', 0):,} frames, "
                f"{side.get('bytes', 0):,} bytes, "
                f"{side.get('dropped', 0):,} dropped")
            return

        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Record frames to", "capture.frames",
            "Frame log (*.frames);;All files (*)")
        if not path:
            self.record_btn.setChecked(False)
            return
        if self.session.call("record.start", path=path) is None:
            self.record_btn.setChecked(False)
            return
        self.record_btn.setText("Stop recording")
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
        source = self.channel.currentData()
        other_tag = (stream.CH_A1 if source == stream.CH_A0
                     else stream.CH_A0)
        other = self.rings.get(other_tag)
        ys, _b = (stream.window_like(other, self.rings.get(source), sweep)
                  if other is not None
                  else (np.empty(0, dtype=np.uint16), None))

        v0 = stream.codes_to_volts(sweep.samples)
        v1 = stream.codes_to_volts(ys) if ys.size == sweep.samples.size else None
        dt = 1.0 / float(max(1, self.rate_hz))

        with open(path, "w", newline="") as f:
            # Provenance in the file, not in the filename. A column of
            # volts is meaningless without the reference it was scaled
            # by, and this project has an ADVREF that moved by 0.91%
            # once already.
            f.write(f"# due_oscilloscope, the sweep as displayed\n")
            f.write(f"# rate_hz={self.rate_hz} source={stream.LABELS.get(source, source)}\n")
            f.write(f"# advref_mv={stream.ADVREF_MV} ({stream.ADVREF_SOURCE})\n")
            f.write(f"# triggered={sweep.triggered}\n")
            head = ["t_s", f"{stream.LABELS.get(source, source)}_V"]
            if v1 is not None:
                head.append(f"{stream.LABELS.get(other_tag, other_tag)}_V")
            head.append("break")
            f.write(",".join(head) + "\n")
            for i in range(sweep.samples.size):
                row = [f"{i * dt:.9g}", f"{float(v0[i]):.6f}"]
                if v1 is not None:
                    row.append(f"{float(v1[i]):.6f}")
                # A discontinuity is a column, not a missing row: the
                # reader has to be able to see the join rather than
                # infer it from a time step.
                row.append("1" if (sweep.breaks is not None
                                   and bool(sweep.breaks[i])) else "0")
                f.write(",".join(row) + "\n")
        return int(sweep.samples.size)

    def scope_cursors(self, on):
        self.scope.set_cursors(bool(on))
        # cursor_text(), not cursor_reading(): the panel takes the
        # formatted string and the reading is a dict.
        self.measure.set_cursor(self.cursor_text())

    def cursor_text(self):
        """The pair's reading, formatted for whichever view is up.

        The units follow the axis rather than being assumed: the same
        two lines measure seconds in the time view and hertz in the
        spectrum, and labelling a frequency difference "dt" would be a
        small lie that a screenshot carries a long way.
        """
        r = self.scope.cursor_reading()
        if r is None:
            return None
        if r["view"] == "spectrum":
            out = [f"df {r['dx']:,.1f} Hz"]
            if r["dy"] is not None:
                out.append(f"dA {r['dy']:+.2f} dB")
        elif r["view"] == "xy":
            out = [f"dX {r['dx']:.4f} V"]
            if r["dy"] is not None:
                out.append(f"dY {r['dy']:+.4f} V")
        else:
            out = [f"dt {r['dx'] * 1e6:,.2f} us"]
            if r["inverse"]:
                out.append(f"1/dt {r['inverse']:,.1f} Hz")
            if r["dy"] is not None:
                out.append(f"dV {r['dy']:+.4f} V")
        return "   ".join(out)

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
        """One decoded frame into the run state.

        Kept as a method because the headless tests drive the window
        this way, and because "what this window does with a frame" is a
        reasonable thing to be able to call. The logic itself lives in
        `stream.AcquisitionState.ingest`, where the gap and
        discontinuity rules can be exercised without a widget.
        """
        return self.acq.ingest(f)

    def poll_status(self):
        """Ask; the answers arrive on `_on_status` and `_on_counters`.

        Two questions rather than one because the daemon keeps them
        apart on purpose: `status` is answerable from the host alone and
        costs the device nothing, which is what makes polling it at 4 Hz
        safe, while `counters` can cost a console round trip.
        """
        self.session.poll()

    def _on_status(self, st):
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

    def closeEvent(self, event):
        self.disconnect_from_daemon()
        super().closeEvent(event)
