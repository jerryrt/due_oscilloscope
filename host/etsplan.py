"""Choosing the DAC and ADC RC for an equivalent-time PRBS capture.

The reasons are in `docs/ets-mode.md`; this is the rule they add up to, so a
tool can refuse a pair instead of a reader remembering it.

The pattern period is `L * rc_dac` timer ticks (`L` = 127 for PRBS7), and the
ADC samples at ticks `k * rc_adc`.

* **Two boards, each with its own crystal.** Use an even ADC RC: the ADC
  clock edge comes every 2 ticks, and an odd RC puts alternate triggers at
  different phases of it, so odd and even samples differ by one tick
  (22.2 ns). Keep the ADC RC coprime with the period, or at least sharing no
  more than a factor of 2: the samples land only on every `gcd`-th source
  tick, and at 4 the block matches of `etsperiod` degrade from 0.2 ticks of
  scatter to 1.1. 127 is odd, so an even `rc_dac` makes the period even and
  every even ADC RC shares a factor of 2 with it, and 4 for the unlucky ones
  (RC 44 and 48 at RC 28). An odd `rc_dac` makes the period odd, and every
  even ADC RC is then coprime with it.
* **One board, one clock.** The fold must reach every tick, so the ADC RC has
  to be coprime with the period, whatever its parity; with an even period
  that forces an odd RC, and the odd-sample offset is then corrected on the
  host (`ets_cross.py resolution`).
"""
import math

import eqtime
import etsperiod

#: Patterns are PRBS7, 127 symbols; `length` carries another.
PRBS7_LENGTH = 127
#: The playback floor, `PLAY_MIN_RC` in drivers/play.h.
PLAY_MIN_RC = 28
#: One channel's ADC trigger floor, `ACQ_MIN_RC_1CH` in drivers/acq.h.
ADC_MIN_RC_1CH = 44
#: The independent-clock default: the smallest odd DAC RC the playback allows
#: and the even ADC RC beside it that measured best.
INDEPENDENT_DEFAULT = (29, 46)
#: The same-board default phase 0 used.
SAME_BOARD_DEFAULT = (28, 45)


def period_ticks(rc_dac, length=PRBS7_LENGTH):
    return length * rc_dac


def lands(rc):
    """Whether the device's rate-to-RC rounding returns `rc` for its own rate."""
    hz = eqtime.TC_CLOCK_HZ // rc
    return eqtime.TC_CLOCK_HZ // hz == rc


def check_pair(rc_dac, rc_adc, same_board, length=PRBS7_LENGTH):
    """What is wrong with this pair, and what to know about it.

    Returns `{problems, notes, gcd, period}`. A pair with any problem should
    be refused; notes are advice.
    """
    problems, notes = [], []
    period = period_ticks(rc_dac, length)
    g = math.gcd(rc_adc, period)
    if rc_dac < PLAY_MIN_RC:
        problems.append("DAC RC %d is below the playback floor %d" % (rc_dac, PLAY_MIN_RC))
    if rc_adc < ADC_MIN_RC_1CH:
        problems.append("ADC RC %d is below the one-channel floor %d" % (rc_adc, ADC_MIN_RC_1CH))
    if not lands(rc_dac) or not lands(rc_adc):
        problems.append("an RC does not survive the device's rate rounding")
    if same_board:
        if g != 1:
            problems.append("on one clock the ADC RC must be coprime with the period "
                            "%d: the fold would miss ticks (common factor %d)" % (period, g))
        if rc_adc % 2:
            notes.append("odd ADC RC: odd and even samples differ by one tick; "
                         "ets_cross.py resolution measures and corrects it")
    else:
        if g > etsperiod.MAX_LATTICE_GCD:
            problems.append("ADC RC %d shares a factor of %d with the period %d: the "
                            "samples land only on every %dth source tick"
                            % (rc_adc, g, period, g))
        if rc_adc % 2:
            notes.append("odd ADC RC: odd and even samples differ by one tick (the ADC "
                         "start snaps to its own clock); use an even RC, or correct it "
                         "on the host")
        if rc_dac % 2 and rc_adc % 2 == 0 and g == 1:
            notes.append("odd DAC RC with an even ADC RC: the best pairing")
        if rc_dac % 2 == 0 and g == etsperiod.MAX_LATTICE_GCD:
            notes.append("an even DAC RC makes the period even, so every even ADC RC "
                         "shares a factor of 2 with it; an odd DAC RC avoids that")
    return {"problems": problems, "notes": notes, "gcd": g, "period": period}


def _nearest(start, ok, lo, step=1, span=4096):
    """The value nearest `start`, lower first on a tie, that `ok` accepts."""
    for d in range(0, span):
        for v in (start - d * step, start + d * step):
            if v >= lo and ok(v):
                return v
    raise ValueError("no acceptable RC near %d" % start)


def plan(rc_dac=None, symbol_rate_hz=None, same_board=False, rc_adc=None,
         length=PRBS7_LENGTH):
    """A DAC and ADC RC for the capture, from a wanted rate if one is given.

    `rc_dac` or `symbol_rate_hz` picks the symbol rate (the playback floor if
    neither); with independent clocks an even DAC RC moves up to the next odd
    one. `rc_adc` is the ADC RC to start the search from. Returns the pair
    with its `check_pair` verdict and the rates it gives.
    """
    default = SAME_BOARD_DEFAULT if same_board else INDEPENDENT_DEFAULT
    if rc_dac is None:
        rc_dac = (round(eqtime.TC_CLOCK_HZ / symbol_rate_hz) if symbol_rate_hz
                  else default[0])
    rc_dac = max(rc_dac, PLAY_MIN_RC)
    if not same_board and rc_dac % 2 == 0:
        rc_dac += 1
    while not lands(rc_dac):
        rc_dac += 2 if not same_board else 1
    period = period_ticks(rc_dac, length)
    want = rc_adc if rc_adc else default[1]
    if not same_board:
        want += want % 2

    def ok(r):
        if not lands(r):
            return False
        if same_board:
            return math.gcd(r, period) == 1
        return r % 2 == 0 and math.gcd(r, period) <= 1

    try:
        rc_adc = _nearest(want, ok, ADC_MIN_RC_1CH, 1 if same_board else 2)
    except ValueError:
        rc_adc = _nearest(want + want % 2, lambda r: r % 2 == 0 and lands(r)
                          and math.gcd(r, period) <= etsperiod.MAX_LATTICE_GCD,
                          ADC_MIN_RC_1CH, 2)
    verdict = check_pair(rc_dac, rc_adc, same_board, length)
    return {"rc_dac": rc_dac, "rc_adc": rc_adc, "same_board": same_board,
            "symbol_hz": eqtime.TC_CLOCK_HZ / rc_dac,
            "adc_hz": eqtime.TC_CLOCK_HZ / rc_adc, **verdict}
