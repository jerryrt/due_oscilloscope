"""What this board's converters actually are, and where that is kept.

`calibration.json` at the repository root is the one home for the
measured constants that describe the analog path: the DAC's output span,
and ADVREF - the reference the DAC and the ADC *share*, which is why the
board cannot measure it and an external instrument had to.

**These used to live in `tests/baseline.json` and that was wrong.** Not
because the numbers were wrong - they are the same numbers, moved
unchanged - but because four things outside the test suite were reaching
into a test fixture to get them: `host/receive.py`, `gui/stream.py`,
`gui/awg.py` and `tools/dso_metrics.py`. Every volt the front end drew
came out of a file whose stated job is regression tolerances, and the
day someone treated that file as the suite's own working state, the
application's Y axis would have moved with it.

The split that now holds:

    calibration.json    what the hardware IS - measured against an
                        instrument that is not the ADC, changes when
                        the board or the bench changes
    tests/baseline.json what this board's behaviour is EXPECTED to be -
                        rates, tolerances, spreads, floors

A tolerance is a claim about a measurement; a calibration constant is
the measurement. `docs/measurement-suite.md` argues the same split from
the other end, and Phase 0 is where the record needed a home anyway.

**One home, not two.** The rule that got invariant 3 rescoped applies
here too: two copies of one number is the failure, and this file exists
so there is one. `dso_metrics.py` used to carry a third copy of the DAC
span as a bench note, 26-60 mV from the other two, and every "codes"
figure it printed was about 4% out because of it.

Accessors come in two flavours on purpose. `advref_mv()` and
`dac_span_mv()` return `(value, source)` and never raise, because a
display refusing to start over an unreadable file helps nobody and a
reading that says which number it used can be attributed afterwards.
`require()` raises, for a tool that is about to measure something and
would otherwise silently produce figures scaled by a guess.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PATH = os.path.join(REPO, "calibration.json")

#: The datasheet's "1/6 to 5/6 of ADVREF", in millivolts. A fallback
#: should be a *specification*, not another measurement's leftovers -
#: the retired ADC-derived pair (546-2760) reads about 32 mV low at the
#: bottom because it folds the ADC's own offset into the DAC's span.
NOMINAL_SPAN_MV = (545, 2725)

#: What `host/` and `tests/` assumed before an instrument settled it.
#: High by 0.91%, which was reported as an ADC gain error until two
#: independent routes agreed on 3270 mV.
NOMINAL_ADVREF_MV = 3300

_cache = None


def load(path=None):
    """The calibration record. Raises if it cannot be read."""
    global _cache
    if path is None and _cache is not None:
        return _cache
    with open(path or PATH) as f:
        data = json.load(f)
    if path is None:
        _cache = data
    return data


def require(path=None):
    """The record, with a message a measuring tool can act on."""
    try:
        return load(path)
    except Exception as e:
        raise SystemExit(
            f"cannot read the calibration record at {path or PATH}: {e}. "
            f"These are measured constants and this tool will not guess "
            f"one - every figure it prints would be scaled by the guess.")


def advref_mv(path=None):
    """ADVREF in millivolts, and where the number came from.

    The DAC->ADC loop is ratiometric - the DAC's reference *is* the
    ADC's, datasheet Table 46-39's note - so the board cannot measure
    this and never will. It comes from outside or it is an assumption.
    """
    try:
        return int(load(path)["adc_transfer"]["advref_mv"]), "measured"
    except Exception:                                        # noqa: BLE001
        return NOMINAL_ADVREF_MV, "assumed (calibration.json unreadable)"


def dac_span_mv(path=None):
    """The DAC's output span in millivolts, and where it came from.

    Measured with the scope on the pin, not through the ADC.
    """
    try:
        d = load(path)["dac_mv"]
        return int(d["span_lo"]), int(d["span_hi"]), "measured"
    except Exception:                                        # noqa: BLE001
        return NOMINAL_SPAN_MV[0], NOMINAL_SPAN_MV[1], "nominal"
