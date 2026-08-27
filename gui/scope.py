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
from PySide6 import QtWidgets

from . import stream


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
        self.curve = self.plot.plot(pen=pg.mkPen("#2e86de", width=1),
                                    connect="finite")
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

    def _axes_for_time(self):
        if self._view == "time":
            return
        self._view = "time"
        self.plot.setLabel("left", "Volts")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setYRange(0.0, stream.VREF_V)
        self.plot.setTitle(None)

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

    def draw(self, ring, window_s, rate_hz, trig=None, view="time",
             fft_window="hann"):
        n = int(max(1, window_s * rate_hz))
        sweep = stream.select(ring, n, trig)
        self.last_triggered = sweep.triggered
        if not sweep.empty:
            self.last_sweep = sweep
        if view == "spectrum":
            return self._draw_spectrum(sweep, rate_hz, fft_window)
        self._axes_for_time()
        if sweep.empty:
            # Normal mode with no edge: hold the previous trace rather
            # than blanking. A scope that clears its screen every time
            # it fails to trigger is unreadable, and the caller is told
            # which happened through last_triggered.
            return 0
        samples, breaks = sweep.samples, sweep.breaks
        cols = min(self.columns, max(2, self.plot.width() or self.columns))
        x, y = stream.minmax(samples, cols, breaks)
        if x.size == 0:
            return 0
        # x comes back in sample indices; show it as time.
        t = x / float(max(1, rate_hz))
        volts = stream.codes_to_volts(np.nan_to_num(y, nan=np.nan))
        self.curve.setData(t, volts)
        self.plot.setXRange(0, max(t[-1], 1e-6), padding=0)
        return samples.size
