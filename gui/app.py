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

    def __init__(self, host="127.0.0.1", port=45454, parent=None):
        super().__init__(parent)
        self.setWindowTitle("due_oscilloscope")
        self.resize(1100, 620)

        self.client = None
        self.host = host
        self.port = port

        self.rings = {}                 # tag -> ChannelRing
        # Whether the daemon is serving a recording rather than a
        # board. It changes what may be asked of it, not how anything
        # here draws: the frames are the same frames.
        self.replaying = False
        self.rate_hz = 200000
        self.frames_shown = 0
        self.seq_gaps = 0
        self.last_seq = None
        self.overruns = 0

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
        dev = hello.get("device", {})
        self.health.set("link", f"{self.host}:{self.port}")
        self.health.set("source", describe_source(dev))
        self.health.set("role", hello.get("role", "?"))
        self.connect_btn.setText("Disconnect")
        self.start_btn.setEnabled(hello.get("role") == "control")
        # Recording is the daemon's and needs no control role - an
        # observer may record what it is watching.
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(hello.get("role") == "control")
        self.set_replay(dev)
        c.subscribe()
        self.statusBar().showMessage(
            f"connected to {dev.get('kind', '?')} device")

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
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None
        self.connect_btn.setText("Connect")
        self.start_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.health.set("link", "-")
        self.health.set("source", "-")
        self.replaying = False
        self.awg.setEnabled(True)
        self.preset.setEnabled(True)
        self.setWindowTitle("due_oscilloscope")
        self.statusBar().showMessage("disconnected")

    # -- device -------------------------------------------------------
    def start_capture(self):
        if self.client is None:
            return
        self.reset_counters()
        try:
            # No preset and no rate when the source is a recording: it
            # has one rate, it is in the frames, and asking for another
            # would be asking the file to convert.
            extra = ({} if self.replaying else
                     {"preset": self.preset.currentData(),
                      "adc_hz": 200000, "channels": 2})
            self.client.call("start", mode="capture", **extra)
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
        if self.rings.get(tag) is not None:
            trig = self.trigger()
            view = self.view_box.currentData()
            self.fft_window.setEnabled(view == "spectrum")
            self.scope.draw(self.rings, tag, self.window_box.currentData(),
                            self.rate_hz, trig, view,
                            self.fft_window.currentData())
            self.trig_state.setText(self.trigger_state_text())
            # Measured over the sweep that was drawn, not over a fresh
            # one: a number beside a trace has to describe that trace.
            self.measure.update_from(
                stream.measure(self.scope.last_sweep, self.rate_hz))
            self.measure.set_cursor(self.cursor_text())

    def toggle_record(self, on):
        """Ask the daemon to start or stop writing frames.

        The frames go to disk exactly as the device sent them - header,
        CRC and all - so a recording can be replayed through the same
        parser that read it live. A CSV of what the screen happened to
        show would not be that.
        """
        if self.client is None:
            self.record_btn.setChecked(False)
            return
        if not on:
            try:
                side = self.client.call("record.stop")["sidecar"]
                self.record_btn.setText("Record...")
                self.statusBar().showMessage(
                    f"recorded {side.get('frames', 0):,} frames, "
                    f"{side.get('bytes', 0):,} bytes, "
                    f"{side.get('dropped', 0):,} dropped")
            except Exception as e:                       # noqa: BLE001
                self.statusBar().showMessage(f"stop recording failed: {e}")
            return

        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Record frames to", "capture.frames",
            "Frame log (*.frames);;All files (*)")
        if not path:
            self.record_btn.setChecked(False)
            return
        try:
            self.client.call("record.start", path=path)
        except Exception as e:                           # noqa: BLE001
            self.record_btn.setChecked(False)
            self.statusBar().showMessage(f"record refused: {e}")
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
        if self.client is None:
            return
        if not running:
            try:
                self.client.call("stop")
                self.statusBar().showMessage("generator stopped")
            except Exception as e:                       # noqa: BLE001
                self.statusBar().showMessage(f"stop refused: {e}")
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
        try:
            self.client.send_awg(blob)
            self.client.call("start", mode="loop", dac_sps=dac_sps,
                             adc_hz=dac_sps, channels=2)
        except Exception as e:                           # noqa: BLE001
            self.awg.run_btn.setChecked(False)
            self.statusBar().showMessage(f"generator refused: {e}")
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
        if f.rate_hz and f.rate_hz != self.rate_hz:
            self.rate_hz = f.rate_hz
            for r in self.rings.values():
                r.set_rate(f.rate_hz)
        gap = self.last_seq is not None and f.seq != self.last_seq + 1
        if gap:
            # A gap here is the daemon dropping toward us, which it
            # counts too - both numbers are on the panel so they can be
            # compared rather than confused.
            self.seq_gaps += 1
        self.last_seq = f.seq
        self.overruns = max(self.overruns, f.overrun_count)

        # **A missed frame is a discontinuity, exactly like an overrun.**
        #
        # Only f.discontinuous - the device's own overrun flag - used to
        # reach the ring, so frames dropped *between the daemon and this
        # window* were counted on the health panel and then drawn across
        # as though the samples either side were adjacent. Rule 3 says
        # never join across a discontinuity and invariant 5 says never
        # present discontinuous data as continuous; a sequence gap is
        # one, and it is the *expected* one rather than a rare fault:
        # rule 5 has the daemon drop toward a slow client by design.
        #
        # Found by validating against the board rather than the
        # synthetic device, which never drops anything. Seven gaps in a
        # six-second run, with the trace joined across every one and the
        # measurements computed over the join.
        for tag, codes in f.channels.items():
            ring = self.rings.get(tag)
            if ring is None:
                ring = stream.ChannelRing(seconds=2.0, rate_hz=self.rate_hz)
                self.rings[tag] = ring
            ring.append(codes, discontinuous=(f.discontinuous or gap))

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
        # The generator's own number, and the only one that says the
        # host kept up. under=0 has coexisted with a badly wrong signal
        # in this project before, which is why it sits next to the
        # controls that cause it rather than in a log.
        try:
            ct = self.client.call("counters")["counters"]
            self.awg.underruns.setText(f"{ct.get('underruns', 0):,}")
        except Exception:                                # noqa: BLE001
            self.awg.underruns.setText("-")

        rec = st.get("recording")
        self.health.set("recording",
                        f"{rec['frames']:,} frames" if rec else "no")

    def closeEvent(self, event):
        self.disconnect_from_daemon()
        super().closeEvent(event)
