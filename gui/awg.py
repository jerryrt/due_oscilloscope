"""The generator panel: volts in, DAC codes out, and a refusal between.

The mapping is the whole content of this file, and it is where the
interesting mistake lives. **The DAC is not rail-to-rail** - CLAUDE.md
lists that among the facts that are easy to get wrong, because writing
zero does not give ground. It spans roughly 578 to 2771 mV, measured
with a scope on the pin.

So a request for "2 V peak-to-peak centred on 1.6 V" is satisfiable and
"3 V peak-to-peak centred on 1.65 V" is not, and the difference is not
obvious from any control on the panel. A generator that silently clamps
the second one produces a clipped waveform that looks like a converter
defect - which this project has spent whole sessions distinguishing from
real ones. So it refuses and says what it can do instead.

The span comes from `calibration.json`, which holds what the scope
measured on this board. `docs/frontend.md` still quotes 546-2760 mV in
its feature list; that pair is the retired ADC-derived one, low by about
the ADC's own offset, and is not what this uses.
"""

from __future__ import annotations

import os
import sys

from PySide6 import QtCore, QtWidgets


SHAPES = ("sine", "square", "triangle", "ramp")

def dac_span_mv():
    """The DAC's output span in millivolts, and where it came from.

    From `calibration.json` through `host/calibration.py`, which owns
    the fallback too: the datasheet's nominal pair, not the retired
    ADC-derived one, because a fallback should be a specification rather
    than another measurement's leftovers.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "host"))
    import calibration
    return calibration.dac_span_mv()


def plan(amplitude_vpp, offset_v, lo_mv, hi_mv):
    """Turn volts into a DAC code range, or say why not.

    Returns (lo_code, hi_code, None) or (None, None, reason).

    Refuses rather than clamping. A clamped waveform is a clipped one,
    and a clipped waveform on this bench looks exactly like the
    converter misbehaving - which is a diagnosis this project has paid
    for more than once.
    """
    half = amplitude_vpp * 500.0                       # mV, half of Vpp
    want_lo = offset_v * 1000.0 - half
    want_hi = offset_v * 1000.0 + half

    if amplitude_vpp <= 0:
        return None, None, "amplitude must be above zero"
    span_mv = hi_mv - lo_mv
    if amplitude_vpp * 1000.0 > span_mv:
        return None, None, (
            f"{amplitude_vpp:.3f} V peak-to-peak is more than the DAC's "
            f"{span_mv / 1000.0:.3f} V span")
    if want_lo < lo_mv - 0.5 or want_hi > hi_mv + 0.5:
        # Name the offset that would fit, because that is the number the
        # user is actually looking for.
        centre = (lo_mv + hi_mv) / 2000.0
        room_lo = (lo_mv + half) / 1000.0
        room_hi = (hi_mv - half) / 1000.0
        return None, None, (
            f"{amplitude_vpp:.3f} Vpp at {offset_v:.3f} V would need "
            f"{want_lo / 1000.0:.3f}-{want_hi / 1000.0:.3f} V; the DAC "
            f"reaches {lo_mv / 1000.0:.3f}-{hi_mv / 1000.0:.3f}. "
            f"Offset {room_lo:.3f}-{room_hi:.3f} V fits (centre "
            f"{centre:.3f})")

    per_code = (hi_mv - lo_mv) / 4095.0
    lo_code = int(round((want_lo - lo_mv) / per_code))
    hi_code = int(round((want_hi - lo_mv) / per_code))
    return max(0, lo_code), min(4095, hi_code), None


def plan_h7(amplitude_vpp, offset_v, mv_per_code, limit_codes):
    """The H7's version of `plan`: volts about 0 V, one sample code per DAC step, refused outside the owner's swing cap.

    Returns (lo_code, hi_code, None) or (None, None, reason), in the Due-style 12-bit sample codes the daemon takes (2048 is 0 V; the daemon
    re-centres them on the H7's own zero), so the waveform builder is the same one. Refuses and never clamps, for the same reason `plan` does.
    """
    if amplitude_vpp <= 0:
        return None, None, "amplitude must be above zero"
    per_v = 1000.0 / mv_per_code
    half = amplitude_vpp / 2.0
    limit_v = limit_codes / per_v
    if half > limit_v + 1e-9:
        return None, None, (f"{amplitude_vpp:.3f} Vpp is more than the +-{limit_v:.3f} V swing cap ({limit_codes} codes) allows: "
                            f"{2 * limit_v:.3f} Vpp at most")
    if abs(offset_v) + half > limit_v + 1e-9:
        room = limit_v - half
        return None, None, (f"{amplitude_vpp:.3f} Vpp at {offset_v:.3f} V would need {offset_v - half:.3f} to {offset_v + half:.3f} V; "
                            f"the cap reaches +-{limit_v:.3f} V. Offset {-room:.3f} to {room:.3f} V fits")
    lo = 2048 + int(round((offset_v - half) * per_v))
    hi = 2048 + int(round((offset_v + half) * per_v))
    # Rounding to whole codes may land one past the cap at the very edge; step back in rather than hand the host a refusal.
    lo = max(lo, 2048 - limit_codes); hi = min(hi, 2048 + limit_codes)
    return lo, hi, None


class AwgPanel(QtWidgets.QGroupBox):
    """Shape, frequency, amplitude and offset. Loopback only.

    docs/frontend.md's Safety section: everything here is DAC0 to A0 over
    a jumper. Nothing on this board is 5 V tolerant and there is no
    protection of any kind, so this panel offers no external output and
    no control that reads as "connect your signal here".
    """

    #: (shape, hz, vpp, offset, run) - the window does the talking.
    requested = QtCore.Signal(str, float, float, float, bool)

    def __init__(self, parent=None):
        super().__init__("Generator (DAC0 -> A0)", parent)
        lo, hi, source = dac_span_mv()
        self.lo_mv, self.hi_mv, self.span_source = lo, hi, source

        self.shape = QtWidgets.QComboBox()
        for s in SHAPES:
            self.shape.addItem(s.capitalize(), s)

        self.hz = QtWidgets.QDoubleSpinBox()
        self.hz.setRange(1.0, 20000.0)
        self.hz.setDecimals(1)
        self.hz.setValue(1000.0)
        self.hz.setSuffix(" Hz")

        self.vpp = QtWidgets.QDoubleSpinBox()
        self.vpp.setRange(0.001, 3.3)
        self.vpp.setDecimals(3)
        self.vpp.setSingleStep(0.1)
        self.vpp.setValue(1.5)
        self.vpp.setSuffix(" Vpp")

        self.offset = QtWidgets.QDoubleSpinBox()
        self.offset.setRange(0.0, 3.3)
        self.offset.setDecimals(3)
        self.offset.setSingleStep(0.05)
        self.offset.setValue((lo + hi) / 2000.0)
        self.offset.setSuffix(" V")

        self.run_btn = QtWidgets.QPushButton("Play")
        self.run_btn.setCheckable(True)
        self.run_btn.toggled.connect(self._emit)

        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #c0392b;")
        # Reserve the height a wrapped refusal needs. Without it the
        # label is clipped by the panel below the fold and the message
        # loses its last line - which is the line naming the offset that
        # would work, and therefore the only actionable part of it. A
        # truncated explanation is worse than a bare "no", because it
        # reads as the whole answer.
        self.note.setMinimumHeight(72)
        self.note.setAlignment(QtCore.Qt.AlignTop)

        self.underruns = QtWidgets.QLabel("-")
        self._gen = None                                   # the H7's generator description, None for a Due

        form = QtWidgets.QFormLayout(self)
        form.addRow("Shape", self.shape)
        form.addRow("Frequency", self.hz)
        form.addRow("Amplitude", self.vpp)
        form.addRow("Offset", self.offset)
        form.addRow("", self.run_btn)
        form.addRow("Underruns", self.underruns)
        form.addRow("", self.note)
        self.span_label = QtWidgets.QLabel(f"DAC span {lo}-{hi} mV, {source}")
        form.addRow("", self.span_label)

        for w in (self.shape, self.hz, self.vpp, self.offset):
            if isinstance(w, QtWidgets.QComboBox):
                w.currentIndexChanged.connect(lambda _i: self._validate())
            else:
                w.valueChanged.connect(lambda _v: self._validate())
        self._validate()

    def set_device(self, desc):
        """Take the generator's mapping from the device's description: a Due's has none and gets the DAC0 span it always had; a
        description with a `generator` entry (the H7's) makes the panel work in volts about 0 V inside that device's swing cap (docs/20, G2)."""
        gen = (desc or {}).get("generator")
        if gen == self._gen:
            return
        self._gen = gen
        if gen:
            limit_v = gen["swing_limit_codes"] * gen["mv_per_code"] / 1000.0
            self.setTitle(f"Generator ({gen.get('output', 'output')})")
            self.vpp.setRange(0.001, 2 * limit_v)
            self.offset.setRange(-limit_v, limit_v)
            self.offset.setValue(0.0)
            self.vpp.setValue(min(self.vpp.value(), 1.0))
            self.span_label.setText(f"swing +-{limit_v:.3f} V ({gen['swing_limit_codes']} codes of {gen['mv_per_code']} mV), the owner's cap")
        else:
            self.setTitle("Generator (DAC0 -> A0)")
            self.vpp.setRange(0.001, 3.3)
            self.offset.setRange(0.0, 3.3)
            self.offset.setValue((self.lo_mv + self.hi_mv) / 2000.0)
            self.span_label.setText(f"DAC span {self.lo_mv}-{self.hi_mv} mV, {self.span_source}")
        self._validate()

    def code_range(self):
        """(lo, hi, reason) for the current settings."""
        if self._gen:
            return plan_h7(self.vpp.value(), self.offset.value(), self._gen["mv_per_code"], self._gen["swing_limit_codes"])
        return plan(self.vpp.value(), self.offset.value(),
                    self.lo_mv, self.hi_mv)

    def _validate(self):
        _lo, _hi, why = self.code_range()
        self.note.setText(why or "")
        self.run_btn.setEnabled(why is None)
        if why is not None and self.run_btn.isChecked():
            self.run_btn.setChecked(False)
            # And say so. Issue #37: the text is only written in
            # `_emit`, so unchecking here left the button reading "Stop"
            # while the panel showed values the device had refused and a
            # *previous* waveform went on playing. Three statements, two
            # of them wrong, and the button was the loudest.
            self.run_btn.setText("Play")

    def _emit(self, running):
        _lo, _hi, why = self.code_range()
        if why is not None:
            self.run_btn.setChecked(False)
            return
        self.run_btn.setText("Stop" if running else "Play")
        self.requested.emit(self.shape.currentData(), self.hz.value(),
                            self.vpp.value(), self.offset.value(), running)
