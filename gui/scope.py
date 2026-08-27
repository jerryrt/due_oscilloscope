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

    def draw(self, ring, window_s, rate_hz, trig=None):
        n = int(max(1, window_s * rate_hz))
        sweep = stream.select(ring, n, trig)
        self.last_triggered = sweep.triggered
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
