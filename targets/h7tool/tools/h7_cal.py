"""Raw ADC code to volts for the H7's two scope channels, applied on the host (invariant 2: no DSP on the device).

The factory calibration of this unit (data/factory_cal_d428-9.json, read from its registers 0xC000-0xC07F) is, per
channel and gain code, two points (x1, y1) and (x2, y2): code x1 is y1 volts (zero) and code x2 is y2 volts. Volts
are the straight line through them. It is the calibration the stock firmware applies, so it is only as good as
our firmware's ADC setting matching the stock's (same sampling time, no oversampling, offset calibration at start);
`offset_correction` lets a measured zero replace the factory one once it is known (docs/17).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "data", "factory_cal_d428-9.json")
GAINS = 8
FULL_SCALE_V = (14.3, 7.1, 3.56, 1.78, 0.89, 0.44, 0.22, 0.11)       # approximate +- range per gain code (docs/05)


class Calibration:
    def __init__(self, table, zero_override=None):
        self.t = table
        self.zero = dict(zero_override or {})           # {(channel, gain): code that is 0 V}, from a measurement

    @classmethod
    def load(cls, path=DEFAULT, zero_override=None):
        with open(path) as f:
            return cls(json.load(f)["table"], zero_override)

    def _p(self, ch, gain):
        if not (ch in (1, 2) and 0 <= gain < GAINS):
            raise ValueError(f"channel {ch} gain {gain}")
        return self.t[f"ch{ch}_gain{gain}"]

    def codes_per_volt(self, ch, gain):
        p = self._p(ch, gain)
        return (p["x2"] - p["x1"]) / (p["y2"] - p["y1"])

    def zero_code(self, ch, gain):
        """The code that is 0 V: a measured override if one was given, else the factory line's."""
        if (ch, gain) in self.zero:
            return self.zero[(ch, gain)]
        p = self._p(ch, gain)
        return p["x1"] - p["y1"] * self.codes_per_volt(ch, gain)

    def volts(self, ch, gain, code):
        """Volts for a raw 16-bit code (a number or a numpy array)."""
        return (code - self.zero_code(ch, gain)) / self.codes_per_volt(ch, gain)
