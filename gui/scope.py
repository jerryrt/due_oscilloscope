"""The trace.

pyqtgraph because it is the only mature Python plotting library that
sustains interactive redraw at these rates - `docs/toolchain.md` chose
it and ruled out matplotlib for exactly that reason.

The widget never sees a raw sample stream: `gui.stream.minmax` reduces
the window to one min/max pair per pixel column before anything is
drawn, and inserts NaN where the data is discontinuous so the line
breaks instead of lying.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from . import stream


#: One colour per channel, and they must stay distinguishable in a
#: screenshot pasted into a message - which is what happens to every
#: trace in this project's history.
CHANNEL_COLOURS = {7: "#2e86de", 6: "#e67e22"}


class ScopeView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=False)     # speed over prettiness
        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "Volts")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setYRange(0.0, stream.VREF_V)
        # connect="finite" is what makes a NaN a break in the line
        # rather than a point at zero.
        #
        # One curve per channel, created up front. The board captures A0
        # and A1 in the same frames and drawing only one of them hid the
        # thing they are captured together *for*: the demultiplexing
        # check. `docs/frontend.md` lists "2ch with DAC1 at mid scale: A1
        # tone < a few codes" as a self-test, and the device's own
        # console says "A1 must read flat, or demux is wrong" - neither
        # is checkable on a display that shows one channel at a time.
        self.curves = {}
        for tag, colour in CHANNEL_COLOURS.items():
            self.curves[tag] = self.plot.plot(
                pen=pg.mkPen(colour, width=1), connect="finite",
                name=stream.LABELS.get(tag, str(tag)))
        # The source channel's curve, for callers that still want one.
        self.curve = self.curves[stream.CH_A0]
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.plot)
        self.columns = 1200
        self.last_triggered = False
        # The sweep as drawn, so the measurements describe the trace on
        # screen rather than a second one taken a moment later.
        self.last_sweep = stream.Sweep(np.empty(0, dtype=np.uint16),
                                       np.empty(0, dtype=bool))
        self._view = "time"

        # Two draggable verticals. Off by default: a cursor sitting on a
        # trace that nobody put there reads as a feature of the signal.
        self.cursors = [
            pg.InfiniteLine(angle=90, movable=True,
                            pen=pg.mkPen("#95a5a6", width=1,
                                         style=QtCore.Qt.DashLine))
            for _ in range(2)]
        for c in self.cursors:
            c.setZValue(10)
        self.cursors_on = False

    def set_cursors(self, on):
        """Show or hide the pair, placing them somewhere useful.

        A quarter and three quarters of the *visible* range rather than
        at the edges: a cursor on the boundary is indistinguishable from
        the axis, and the first thing anyone does is drag it inward.
        """
        if on == self.cursors_on:
            return
        self.cursors_on = on
        if on:
            (x0, x1), _y = self.plot.viewRange()
            span = x1 - x0
            for c, frac in zip(self.cursors, (0.25, 0.75)):
                c.setPos(x0 + span * frac)
                self.plot.addItem(c, ignoreBounds=True)
        else:
            for c in self.cursors:
                self.plot.removeItem(c)

    def cursor_reading(self):
        """What the pair measures, in whatever units the axis is in.

        Returns a dict, or None when the cursors are off.

        The y values are read off the *drawn* curve rather than
        re-derived from the samples, so the number agrees with the
        picture even where the picture is a min/max envelope. A reading
        that disagreed with the pixels beside it would be worse than no
        reading.
        """
        if not self.cursors_on:
            return None
        a, b = (float(c.value()) for c in self.cursors)
        lo, hi = (a, b) if a <= b else (b, a)
        out = {"view": self._view, "x1": lo, "x2": hi, "dx": hi - lo,
               "y1": None, "y2": None, "dy": None, "inverse": None}
        if out["dx"] > 0 and self._view == "time":
            out["inverse"] = 1.0 / out["dx"]
        xs, ys = self.curve.getData()
        if xs is not None and len(xs) > 1:
            out["y1"] = _sample_at(xs, ys, lo)
            out["y2"] = _sample_at(xs, ys, hi)
            if out["y1"] is not None and out["y2"] is not None:
                out["dy"] = out["y2"] - out["y1"]
        return out

    def _axes_for_time(self):
        if self._view == "time":
            return
        self._view = "time"
        self.plot.setLabel("left", "Volts")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setYRange(0.0, stream.VREF_V)
        self.plot.setTitle(None)

    def _draw_xy(self, rings, source, ring, sweep):
        """One channel against the other. The loopback bench's view."""
        other_tag = (stream.CH_A1 if source == stream.CH_A0
                     else stream.CH_A0)
        other = rings.get(other_tag)
        if self._view != "xy":
            self._view = "xy"
            self.plot.setLabel("bottom",
                               f"{stream.LABELS.get(source, source)} (V)")
            self.plot.setLabel("left",
                               f"{stream.LABELS.get(other_tag, other_tag)} (V)")
            self.plot.setXRange(0.0, stream.VREF_V, padding=0)
            self.plot.setYRange(0.0, stream.VREF_V)
        for tag, curve in self.curves.items():
            if tag != source:
                curve.setData([], [])
        if other is None or sweep.empty:
            self.curve.setData([], [])
            self.plot.setTitle("needs both channels")
            return 0
        ys, _b = stream.window_like(other, ring, sweep)
        if ys.size == 0:
            self.curve.setData([], [])
            self.plot.setTitle("channels out of step")
            return 0
        self.plot.setTitle(None)
        x, y = stream.xy_points(sweep.samples, ys, sweep.breaks)
        self.curves[source].setData(x, y)
        self.curve = self.curves[source]
        return int(sweep.samples.size)

    def _draw_spectrum(self, sweep, rate_hz, fft_window):
        """The spectrum, or the reason there is not one.

        A refusal blanks the curve and writes why across the plot. It
        does not leave the previous spectrum up: a stale curve under a
        live-looking axis is exactly the lie the health panel exists to
        prevent, and it is worse here than in the time domain because a
        spectrum carries no visible sign of being old.
        """
        if self._view != "spectrum":
            self._view = "spectrum"
            self.plot.setLabel("left", "dBFS")
            self.plot.setLabel("bottom", "Frequency", units="Hz")
            self.plot.setYRange(-120.0, 0.0)

        freqs, db, note = stream.spectrum(sweep, rate_hz, fft_window)
        if freqs is None:
            self.curve.setData([], [])
            self.plot.setTitle(note or "no spectrum")
            return 0
        self.plot.setTitle(None)
        self.curve.setData(freqs, db)
        self.plot.setXRange(0.0, float(freqs[-1]), padding=0)
        return int(sweep.samples.size)

    def draw(self, rings, source, window_s, rate_hz, trig=None,
             view="time", fft_window="hann"):
        """Draw every channel that has data; measure and trigger on one.

        `rings` is tag -> ChannelRing and `source` is the tag the
        trigger and the measurements follow - which is what a scope's
        trigger-source selector is, rather than a "which one do I look
        at" switch.

        The other channels are drawn from the *same* sample offset as
        the source rather than triggered independently. They were
        captured in the same frames, so sliding them separately would
        put two moments on one time axis and invite reading a phase
        difference that is an artefact of the display.
        """
        ring = rings.get(source)
        if ring is None:
            return 0
        n = int(max(1, window_s * rate_hz))
        sweep = stream.select(ring, n, trig)
        self.last_triggered = sweep.triggered
        if not sweep.empty:
            self.last_sweep = sweep
        if view == "spectrum":
            return self._draw_spectrum(sweep, rate_hz, fft_window)
        if view == "xy":
            return self._draw_xy(rings, source, ring, sweep)
        self._axes_for_time()
        if sweep.empty:
            # Normal mode with no edge: hold the previous trace rather
            # than blanking. A scope that clears its screen every time
            # it fails to trigger is unreadable, and the caller is told
            # which happened through last_triggered.
            return 0
        cols = min(self.columns, max(2, self.plot.width() or self.columns))
        drawn = 0
        span = 0.0
        for tag, curve in self.curves.items():
            other = rings.get(tag)
            if other is None:
                curve.setData([], [])
                continue
            if tag == source:
                samples, breaks = sweep.samples, sweep.breaks
            else:
                # The same window, taken from the same place in the
                # ring, so the two channels share one time axis.
                samples, breaks = stream.window_like(other, ring, sweep)
            if samples.size == 0:
                curve.setData([], [])
                continue
            x, y = stream.minmax(samples, cols, breaks)
            if x.size == 0:
                curve.setData([], [])
                continue
            # x comes back in sample indices; show it as time.
            t = x / float(max(1, rate_hz))
            volts = stream.codes_to_volts(np.nan_to_num(y, nan=np.nan))
            curve.setData(t, volts)
            span = max(span, float(t[-1]))
            drawn = max(drawn, int(samples.size))
        if drawn:
            self.plot.setXRange(0, max(span, 1e-6), padding=0)
        return drawn


def _sample_at(xs, ys, x):
    """The drawn y nearest x, or None if x is off the ends.

    Nearest rather than interpolated. The curve is already a min/max
    envelope with two points per pixel column, so interpolating between
    them would invent a value between a column's minimum and its
    maximum - which is not a value the signal ever took.
    """
    if x < xs[0] or x > xs[-1]:
        return None
    i = int(np.argmin(np.abs(np.asarray(xs) - x)))
    v = ys[i]
    return None if v != v else float(v)          # NaN is a break, not a level
