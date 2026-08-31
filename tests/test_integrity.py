"""
Domain 2: signal integrity.

The most important domain and the easiest to under-build, because the
counters have been clean while the signal was wrong: a run with
seq_gaps=0, crc_bad=0 and under=0 has coexisted with badly degraded
data more than once. Everything here judges the samples themselves.

Because the host authored the waveform, any discrepancy in what comes
back is a fault in the path rather than an unknown property of a signal.
"""

import pytest

import measure
from helpers import (assert_fresh, assert_no_underruns, assert_slew,
                     assert_stream_clean, assert_tone, loop_cmd, record,
                     shared_run, window, window_purity)

pytestmark = [pytest.mark.scope, pytest.mark.awg]

# The DAC carries ~20 mV - about 25 codes - of standing noise on every
# sample, and that is the number issue #5's closure compared its 1-8
# code displacement against. So it is also the number at which the
# displacement stops being invisible, which is the only property that
# made it ignorable. Measured on the macOS bench 2026-08-29: 14.4 codes
# worst of six interleaved draws, in both ACR states.
DISPLACEMENT_VISIBLE_CODES = 25.0

# The DAC's span as it reaches the ADC, measured rather than nominal -
# the DAC is not rail to rail and the loop is ratiometric. The bound
# above applies only against a signal of about this size, because the
# displacement grows as the generator's amplitude falls.
DAC_FULL_SPAN_CODES = 2750

TONE = 1000.0


@pytest.mark.smoke
def test_device_generated_waveform_is_continuous(board, seconds,
                                                calibration):
    """The control for everything below, and it must stay green.

    `M` drives the DAC from the device's own flash sine through the same
    DACC, PDC, trigger, ADC, framing and USB IN path as a host-fed run,
    with the host removed from the DAC side entirely. If this is clean
    and a host-fed run is not, the fault is in the host -> DAC path and
    nowhere else - which is how the lost-sample defect below was
    localised in one step.
    """
    secs = window(seconds, 3.0)
    res = measure.run_capture(board, preset="M", seconds=secs)
    assert_fresh(res, secs)
    assert_stream_clean(res)

    ps = res.stream
    vals = ps.series[measure.CH_A0]
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)

    # Do not judge the maximum step. This test once compared the largest
    # step against slew_limit() * 3, which is the wrong model twice over:
    # `gen` emits a staircase, so the honest ceiling is the ~38-code DAC
    # step and not the 16.85-code derivative of a continuous sine, which
    # left the "3x margin" at 1.3x of real headroom. Issue #5 then sat
    # under it for a whole session.
    #
    # Nor threshold the count, which is what replaced it. Issue #5 is
    # open, its amplitude tracks the binary, and a detector with a line
    # at STEP_SPLICE_CODES works only while the artifact is far from it.
    # On 2026-08-26 a build landed with the artifact at 47-48 codes
    # against a line at 45: only some wraps crossed, the selected subset
    # was irregular, `periodic` went false, the xfail below stopped
    # applying and the test failed hard - caused by the detector sitting
    # on top of the signal, not by anything changing in the device. Any
    # rebuild can put it there again.
    #
    # So identify the state and report its amplitude, which is the rule
    # this project arrived at for issue #5 generally. pair_fold() is the
    # instrument for this channel: gen holds each DAC level for two ADC
    # samples, so differencing within the pair cancels the staircase by
    # construction and leaves a one-sample event at full height, with no
    # threshold anywhere in it.
    vals = vals[start:]
    census = measure.level_census(vals)
    fold = measure.pair_fold(vals)
    record(calibration, "device_waveform", {
        "census": census["count"],
        "fold_peak": round(fold["peak"], 2),
        "fold_z": round(fold["z"], 1),
        "fold_control_z": round(fold["control_z"], 1),
        "fold_phase": fold["peak_phase"],
    })

    # A level is only a level while the two clocks are locked. If the
    # pairing broke, the differencing measured the staircase instead of
    # cancelling it and nothing below can be read.
    assert fold["hold_ok"], (
        f"the DAC hold did not survive: pair spread {fold['pair_spread']:.1f} "
        f"codes, so pair_fold() is measuring the waveform rather than the "
        f"artifact and this run cannot be judged")

    # Locked to the table wrap and not to a period it was not given - a
    # real lock is a high z against a low control_z. That is issue #5:
    # known, open, made at a DAC output pin, and expected to be here.
    if fold["z"] >= measure.FOLD_Z_DIRTY and fold["control_z"] < measure.FOLD_Z_DIRTY:
        # Bound the amplitude, which this arm did not do and was
        # documented as doing. Issue #5 closed on "1-8 codes against
        # the DAC's ~25 code standing noise, so no user can see it",
        # and docs/awg.md promised that a *grown* displacement would
        # fail a run rather than hide under the tolerance. Nothing here
        # ever looked at the number: the artifact went from 1-8 codes
        # at closure to 14.4 on this bench eleven days later, in both
        # ACR states, and every run xfailed exactly as before.
        #
        # The trip point is the closing argument's own criterion rather
        # than a fresh invention. What made the artifact ignorable was
        # that it sits under the noise every sample already carries, so
        # the guard fires when it stops doing so. A bench that trips
        # this should reopen #5, not raise the number.
        # Only against a full-scale signal. The displacement is not a
        # fixed number of codes - it grows as the generator's amplitude
        # falls, reaching 35 codes at quarter scale where full scale
        # gives 14 - so a bound in codes means something only at the
        # amplitude the closing record was taken at. A run at reduced
        # amplitude is not comparable and must not be failed by this.
        span = max(vals) - min(vals)
        if span >= 0.9 * DAC_FULL_SPAN_CODES:
            assert abs(fold["peak"]) < DISPLACEMENT_VISIBLE_CODES, (
                f"issue #5's displacement has reached "
                f"{fold['peak']:+.1f} codes at phase {fold['peak_phase']} "
                f"(z {fold['z']:.1f}, control {fold['control_z']:.1f}) "
                f"against a full-scale signal, which is no longer under "
                f"the ~{DISPLACEMENT_VISIBLE_CODES:.0f} code standing "
                f"noise the issue was closed against. That is the "
                f"reopening condition #5 recorded for itself")
        # "largest", not "the": the profile carries several displaced
        # samples per wrap and fold_profile reports the biggest bin.
        # Calling the argmax "the displacement" is what let two benches
        # read this statistic and disagree - see docs/awg.md and
        # tools/issue5_sites.py for the whole profile.
        pytest.xfail(
            f"issue #5: samples near the DAC table wrap displaced, "
            f"largest {fold['peak']:+.1f} codes at phase "
            f"{fold['peak_phase']}, z {fold['z']:.1f} against a control "
            f"of {fold['control_z']:.1f} ({census['count']} steps over "
            f"{census['threshold']} codes). A DAC output pin, not a "
            f"splice - see docs/awg.md")

    # Nothing is locked to the wrap, so whatever the census still sees is
    # not issue #5 and has to be accounted for.
    assert census["count"] == 0, (
        f"the device's own waveform shows {census['count']} steps above "
        f"{census['threshold']} codes (largest {census['max_step']:.1f}, "
        f"nothing occupies {census['gap'][0]}..{census['gap'][1]}) and "
        f"nothing is locked to the table wrap (fold z {fold['z']:.1f}, "
        f"control {fold['control_z']:.1f}), so this is not issue #5; the "
        f"fault is in the capture path, not in anything the host sends")


@pytest.mark.smoke
def test_no_sample_step_exceeds_the_waveform_slope(board, seconds, baseline,
                                                   calibration, run_cache):
    """Invariant 5, tested directly and without any spectral analysis.

    Data spliced across two points in time still passes its header CRC
    and still looks like a signal. What it cannot do is respect the
    derivative of the sine that was sent: the largest step between
    consecutive samples of one channel is 2*pi*f*A/fs, and a splice
    lands somewhere else on the waveform and jumps.
    """
    secs = window(seconds, 3.0)
    res = shared_run(run_cache, measure.run_loop, board, dac_sps=200000,
                     adc_hz=200000, channels=2, tone=TONE, seconds=secs)
    assert_fresh(res, secs)
    assert_stream_clean(res)

    amplitude = baseline["amplitude"]["full_scale_codes"]
    fs = res.stream.declared_rate_hz
    got = res.stream.max_slew(measure.CH_A0, from_us=measure.SETTLE_US)
    limit = measure.slew_limit(res.tone_hz, amplitude, fs) * 3.0

    # Same discrimination the ramp test makes, for the same reason. The
    # device's byte accounting is exact - the deficit is 0 on every
    # healthy run, measured - so a device short by a whole multiple of
    # 128 bytes is macOS's CDC-ACM output path dropping chunks it
    # counted in write(), which is objective 0b and not this test's
    # defect. A sine cannot say how many samples went missing, but the
    # byte counts can, and 64 samples skipped at 200 ksps is a 115
    # degree phase jump - a step of up to 2314 codes in this tone, which
    # is the size these failures come in.
    deficit = res.host_tx_bytes - (res.play.bytes_in or 0)
    if got > limit and res.play.bytes_in and deficit > 0 and \
            deficit % 128 == 0:
        pytest.xfail(
            f"host dropped {deficit} B in whole 128-byte chunks, so the DAC "
            f"skipped {deficit // 2} samples: macOS's output path, not the "
            f"device. A {got}-code step is what that does to this tone. "
            f"See docs/status.md")
    # 3.0, the helper's documented default, not the 1.6 this carried
    # while it was an xfail and the margin was never exercised. The
    # measurement is bimodal, not noisy: 49-51 codes when the DAC update
    # clock and the ADC trigger stay locked, 88-92 when they beat. The
    # beat looks like this around the largest step
    #
    #   d=-42  d=+1  d=-88  d=-43
    #
    # - one sample repeats, the next spans two DAC updates, and the pair
    # sums to the two-update slope with the sine's phase intact either
    # side. Nothing is lost; ~700 of them appear in a 3 s run when the
    # beat is present and none when it is not. The device-only control
    # above measures the same thing with the host removed (38-43 against
    # an analytic 17) and has always used 3.0. A splice is orders of
    # magnitude clear of either line.
    got = assert_slew(res, measure.CH_A0, res.tone_hz, amplitude, fs,
                      margin=3.0)
    record(calibration, "slew_a0", {
        "max_step": got,
        "deficit_bytes": deficit,
        "analytic": round(measure.slew_limit(res.tone_hz, amplitude, fs), 1)})


def test_tone_amplitude_per_window(board, seconds, baseline, calibration,
                                   run_cache):
    """Purity judged per window, never over the whole run.

    At 453,488 sps a whole-run Goertzel reads 232 codes against a
    theoretical 1370.5 while nearly every window reads above 1360: one
    phase discontinuity cancels the average, so a per-run number reports
    a collapse that is not happening.
    """
    secs = window(seconds, 3.0)
    res = shared_run(run_cache, measure.run_loop, board, dac_sps=200000,
                     adc_hz=200000, channels=2, tone=TONE, seconds=secs)
    assert_fresh(res, secs)
    assert_no_underruns(res)

    amp = baseline["amplitude"]
    median, amps = window_purity(res, measure.CH_A0)
    assert amps, "no full window of samples on A0"
    record(calibration, "tone_windows_200k", {
        "median": round(median, 1), "min": round(min(amps), 1),
        "max": round(max(amps), 1), "n": len(amps),
        "theoretical": amp["full_scale_codes"]})
    assert median >= amp["window_floor_codes"], (
        f"median window amplitude {median:.1f} codes below the "
        f"{amp['window_floor_codes']} floor over {len(amps)} windows")
    assert median <= amp["full_scale_codes"] * 1.02, (
        f"median window amplitude {median:.1f} exceeds the theoretical "
        f"full-scale {amp['full_scale_codes']}; the analysis is wrong, not "
        f"the signal")


def test_every_window_reaches_the_amplitude_floor(board, seconds, baseline,
                                                  run_cache):
    """The median says the signal is right; this says it is right *all
    the time*.

    Separated from the median deliberately. The median is robust and
    stays a strict assertion, so a real collapse still fails loudly. The
    fraction is what the lost-sample defect breaks: 4-5 events in a 3 s
    run corrupt up to 5 of about 53 windows, which lands within a
    percent of the 90% requirement either way.
    """
    secs = window(seconds, 3.0)
    res = shared_run(run_cache, measure.run_loop, board, dac_sps=200000,
                     adc_hz=200000, channels=2, tone=TONE, seconds=secs)
    assert_fresh(res, secs)
    amp = baseline["amplitude"]
    assert_tone(res, measure.CH_A0, amp["window_floor_codes"],
                fraction=amp["window_fraction"])


def test_the_other_channel_stays_flat(board, seconds, baseline, run_cache):
    """A1 carries no tone.

    DAC1 is never driven with the waveform, so a tone on A1 means the
    channel tags are being read wrong and the whole capture is
    attributed to the wrong pins. It also bounds multiplexer bleed: one
    sample-and-hold behind a 16:1 mux carries residual charge from the
    previously converted channel.
    """
    secs = window(seconds, 3.0)
    res = shared_run(run_cache, measure.run_loop, board, dac_sps=200000,
                     adc_hz=200000, channels=2, tone=TONE, seconds=secs)
    assert_fresh(res, secs)

    ceiling = baseline["amplitude"]["crosstalk_ceiling_codes"]
    median, amps = window_purity(res, measure.CH_A1)
    assert amps, "no windows on A1"
    assert median <= ceiling, (
        f"A1 carries {median:.1f} codes at the tone frequency against a "
        f"{ceiling} code ceiling; either the tags are being demultiplexed "
        f"wrongly or the multiplexer is bleeding")


def test_recovered_frequency_is_the_one_sent(board, seconds, run_cache):
    """A rate error hides behind a good amplitude.

    The Goertzel is evaluated with the header's declared rate, so if the
    header lies about the rate the peak lands at the wrong frequency
    while the amplitude at that wrong frequency still looks perfect.
    """
    secs = window(seconds, 3.0)
    res = shared_run(run_cache, measure.run_loop, board, dac_sps=200000,
                     adc_hz=200000, channels=2, tone=TONE, seconds=secs)
    assert_fresh(res, secs)

    fs = res.stream.declared_rate_hz
    samples = res.stream.settled[measure.CH_A0]
    assert len(samples) > 4096, "not enough settled samples to resolve a peak"

    sent = res.tone_hz
    cands = [sent * k for k in (0.90, 0.95, 0.98, 1.0, 1.02, 1.05, 1.10)]
    mags = [(measure.goertzel(samples, fs, f), f) for f in cands]
    best = max(mags)[1]
    assert abs(best - sent) < 1e-6, (
        f"the energy is at {best:.1f} Hz, not the {sent:.1f} Hz that was "
        f"sent: " + ", ".join(f"{f:.0f}Hz={m:.0f}" for m, f in mags))


@pytest.mark.smoke
def test_no_tone_when_playback_is_stopped(board, seconds):
    """The negative control, and the test that would have caught the
    "frozen DAC".

    With nothing driving DAC0 the capture must show no tone at all. A
    run that still reports one is reading frames from a previous stream
    out of the kernel buffer, and every number computed from it
    describes the past.
    """
    secs = window(seconds, 2.0)
    res = measure.run_capture(board, preset=loop_cmd(200000, 2), seconds=secs)
    assert_fresh(res, secs)

    fs = res.stream.declared_rate_hz
    samples = res.stream.settled[measure.CH_A0]
    mag = measure.goertzel(samples, fs, TONE)
    assert mag < 20.0, (
        f"A0 shows {mag:.1f} codes at {TONE:.0f} Hz with nothing feeding "
        f"DAC0. Either this is stale data from an earlier run or the DAC is "
        f"still emitting a waveform nobody sent it.")


@pytest.mark.parametrize("code", [512, 1024, 2048, 3072, 3583])
def test_dc_transfer_tracks_the_code(board, baseline, calibration, code):
    """A constant on DAC0 must arrive at A0 as the matching level.

    Needs no tone and no spectral analysis, so it separates an analog
    fault from a timing one: if A0 does not move with the code, the DAC
    is not consuming host data at all.
    """
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           dc=code, seconds=1.5)
    assert_fresh(res, 1.5)
    # Settled samples only: playback starts from a ring primed with
    # mid-scale silence, so the head of the run is that, not the code.
    vals = res.stream.settled[measure.CH_A0]
    assert vals, "no settled samples"
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)

    # ADVREF, not a nominal 3300. The loop is ratiometric - the DAC's
    # reference IS the ADC's - so the board cannot measure its own
    # reference and this constant was an assumption, not a measurement.
    # The scope settled it at 3270 mV by two independent routes agreeing
    # to 0.1 mV, so a nominal 3300 reads every millivolt here 0.91% high.
    import calibration as cal
    advref, _ = cal.advref_mv()
    mv = mean * advref / 4095.0
    lo, hi, _ = cal.dac_span_mv()
    record(calibration, f"dc_{code}", {"mean_code": round(mean, 1),
                                       "mv": round(mv, 1)})
    assert lo - 60 <= mv <= hi + 60, (
        f"DAC code {code} arrived at {mv:.0f} mV, outside the measured "
        f"{lo}-{hi} mV span the DAC actually reaches")
    assert spread < 200, (
        f"a constant code produced a {spread} code spread on A0; that is "
        f"not a DC level")


def test_dc_levels_are_monotonic(board, baseline, calibration):
    """Rising codes must produce rising volts, in order."""
    got = []
    for code in (512, 2048, 3583):
        res = measure.run_loop(board, dac_sps=200000, adc_hz=200000,
                               channels=2, dc=code, seconds=1.2)
        assert_fresh(res, 1.2)
        vals = res.stream.settled[measure.CH_A0]
        got.append((code, sum(vals) / len(vals)))
    record(calibration, "dc_monotonic",
           [[c, round(m, 1)] for c, m in got])
    means = [m for _, m in got]
    assert means == sorted(means), (
        f"DAC codes {[c for c, _ in got]} produced A0 means {means}, which "
        f"are not in order; the transfer is not monotonic")


def test_host_fed_ramp_loses_no_samples(board, seconds, calibration):
    """How many samples went missing, not just that the output jumped.

    A sine says the output moved when it should not have. A ramp says by
    how much: every sample encodes its own position, so a discontinuity
    divides straight into a number of samples skipped or repeated.

    This is the test that found the non-atomic read of DEVDMASTATUS.
    Before that fix it measured 3-13 events per 3 s run at 200 ksps,
    losing 6-185 samples (12-370 bytes) a time, always forward, with
    under=0, seq_gaps=0, crc_bad=0 and resync=0 throughout. Every loss
    was smaller than one slot, which is what named the culprit.

    What is left is the host's, and is reported as an xfail rather than
    asserted away: on a loaded machine macOS drops whole 128-byte chunks
    from the tty output queue, having counted them in write(). Roughly
    one 3 s run in eight under load, none at all on a quiet one.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           ramp=measure.RAMP_STEP, seconds=secs)
    assert_fresh(res, secs)
    assert_stream_clean(res)
    assert_no_underruns(res)

    events = measure.ramp_discontinuities(res.stream)
    lost = [n for _, n in events if n > 0]
    repeated = [-n for _, n in events if n < 0]
    deficit = res.host_tx_bytes - (res.play.bytes_in or 0)
    record(calibration, "ramp_events", {
        "n": len(events), "lost": sorted(lost, reverse=True)[:8],
        "repeated": sorted(repeated, reverse=True)[:8],
        "deficit_bytes": deficit})

    # Three classes, and only one of them is this test's own defect.
    #
    #   noise      |n| <= JITTER samples. The analysis flags anything
    #              outside [-2, 4]. Values of exactly +3 and -3 turn up
    #              in matched pairs, and a ring can only ever skip
    #              forward, so a matched pair is not data loss. It is
    #              also not a drifting sampling instant, which is what
    #              this comment used to say: issue #24 measured it as
    #              one sample per DAC table wrap arriving ~17-30 codes
    #              low, which the position arithmetic reports as a jump
    #              out and a jump straight back. See docs/awg.md.
    #   host drop  whole multiples of 128 bytes. macOS's CDC-ACM output
    #              path discards ~128-byte chunks from a pressured tty
    #              queue with write() having counted them. Open, and
    #              reported as an xfail below.
    #   anything else - a forward jump of an arbitrary size - is the
    #              device losing data it received, which is the defect
    #              this test was written for. That fails outright.
    JITTER = 4
    real = [n for n in lost if n > JITTER]
    big_repeat = [n for n in repeated if n > JITTER]

    # Bidirectional jitter - forward and backward events in matched
    # volume - is issue #24's class, not a loss: a ring can only skip
    # forward, so a matched pair is one sample whose *value* is wrong
    # (~17-30 codes low, once per DAC table wrap) counted twice, not a
    # sample that moved. A #24 storm must not hide under the loss
    # tolerance below, nor nearly move that bound, which it did once -
    # see #20. The name is kept because the issue is; "jitter" is what
    # it looked like, not what it is.
    if real and big_repeat:
        fwd, back = sum(real), sum(big_repeat)
        if min(fwd, back) * 5 >= max(fwd, back):
            pytest.xfail(
                f"bidirectional jitter: {len(real)} forward / "
                f"{len(big_repeat)} backward events, {fwd} vs {back} "
                f"samples - matched pairs, so one wrong-valued sample "
                f"per DAC table wrap counted twice, not a loss. "
                f"Issue #24")

    # A backward event barely over the allowance is #24's class at its
    # smallest - one low sample whose forward twin fell inside
    # +-JITTER - and not a slot re-emit (a slot is 256 samples). Kept visible as an xfail; the hard assert below stays
    # for anything approaching slot scale.
    slot_repeat = [n for n in big_repeat if n > 2 * JITTER]
    assert not slot_repeat, (
        f"the DAC repeated {sum(slot_repeat)} samples across "
        f"{len(slot_repeat)} points with under=0; a repeat that is not "
        f"counted as an underrun is the ring emitting a slot twice")
    if big_repeat and not real:
        pytest.xfail(
            f"boundary jitter: {len(big_repeat)} backward events of "
            f"{big_repeat} samples, forward twin inside the +-{JITTER} "
            f"allowance. Issue #24's class at its smallest - a low "
            f"sample, not a moved one")

    stray = [n * 2 for n in real if (n * 2) % 128]

    # Issue #20, settled within tolerance rather than to a mechanism:
    # the device loses forward-only runs of ~10 bytes while capture IN
    # DMA is armed, at a per-host, hour-scale-varying rate, invisibly
    # to every device counter (deficit stays 0 - do not read under=0
    # as integrity). The agreed bound is 1% of the window's bytes;
    # everything recorded on current firmware across both benches sits
    # under 0.01% per window (worst characterized: 0.64%). Above the
    # bound - or losses in a new size class - this fails and #20
    # reopens.
    if stray:
        lost_bytes = sum(n * 2 for n in real if (n * 2) % 128)
        assert lost_bytes <= res.host_tx_bytes // 100, (
            f"device-class loss {lost_bytes} B is over 1% of the "
            f"{res.host_tx_bytes} B window: outside #20's settled "
            f"tolerance - reopen #20")
        pytest.xfail(
            f"device lost {lost_bytes} B in {len(stray)} forward events "
            f"(~10 B class), within #20's 1% tolerance. deficit={deficit}")

    if real:
        pytest.xfail(
            f"host dropped {sum(real) * 2} bytes in {len(real)} chunks of "
            f"128, device short by {deficit} B: macOS's CDC-ACM output "
            f"path, not the device. See docs/status.md")


# Rates whose feed genuinely oversupplies, so the surplus is shed.
#
# The host's USB stack discards bytes write() has counted, silently.
# Two separable causes were measured:
#
#   How the writes are issued. Writing a constant 512 bytes is
#   lossless; writing "whatever is due" - the same sizes, the same
#   pacing - loses 0.45-0.65% at every rate above 200 ksps. The feeder
#   writes a constant size for that reason, and it took five of the
#   seven rates here from losing to exact.
#
#   Genuine oversupply, which no write policy can fix. At 886,363 and
#   1,000,000 sps the converter runs slow by 1.58% and 2.35% - measured
#   against the device's own clock - so the host feeds more than the
#   device can take and the excess is discarded rather than queued.
#   The deficits, 1.35% and 2.15%, are those figures. These rates
#   report under=0 while losing the most of any rate in the ladder,
#   which is why this test exists and the underrun counter cannot
#   stand in for it.
#
# Issue #48 has since named the cause and it is `DACC_MR_REFRESH`:
# setting it to 2 or 3 clears every affected rate and restoring 1 brings
# them all back (p = 3.3e-11 across the ladder), the effect appears with
# no USB in the DAC path at all, and it reproduces on both tracks and
# both hosts. So these two are not special rates - they are two points
# inside a band running roughly 750,000 to 1,300,000 sps, and they are
# the two this parametrisation happens to sample. The deficits are
# quantised: every rate loses an integer number of conversions out of
# 256, which is 4/256 at RC 44 and 6/256 at RC 39.
OVERSUPPLIED = {44, 39}

# Rates where a small residual loss survives the constant-size feed.
#
# The constant-size write took RC 32 from 49,664 B lost per 3 s run to
# 0 B in most runs and 384 B - three chunks - in others. That is a 130x
# reduction and not a fix: something still drops occasionally at the
# top of the ladder, and it is the intermittency the original 0b entry
# described, now confined to the two fastest rates.
#
# Handled by outcome rather than by mark, so a clean run passes and
# reports: this turns green by itself when the residual is fixed.
#
# **RC 32 carries two different losses and they should not be confused.**
# The 384 B here is the host residual this comment describes. Separately,
# RC 32 sits at the upper edge of #48's band and takes one of two modes
# per run - 0 or 16 conversions lost per 256 - and the 16 mode sheds
# about 450,000 B in a 3 s run, three orders of magnitude more. A run
# that loses 384 B and a run that loses 450 kB at this rate are not the
# same defect measured twice; the first is macOS's chunk drop and the
# second is the converter delivering 15/16 of its programmed rate.
#
# RC 28 is outside that band and measures clean device-side (n = 0), so
# whatever it loses here is the host's alone.
RESIDUAL = {32, 28}


@pytest.mark.parametrize("rc", [195, 98, 65, 44, 39, 32, 28])
def test_device_receives_every_byte_the_host_sent(board, seconds,
                                                  calibration, rc):
    """Byte accounting with the pipeline drained, which is the only way
    it means anything.

    play_bytes_in is exact, so it can answer whether the device received
    what the host wrote - but only once everything in flight has
    arrived. Read straight after the feeder stops, the 55 to 450 KB
    still in the CDC driver reads as a loss and the comparison is
    worthless. Here the feed stops, the device keeps draining bulk OUT,
    and the counters are read afterwards.

    That the shortfall is real rather than still in flight was checked
    by reading the device once a second for six seconds after the feed
    stopped: play_bytes_in and play_consumed both freeze while
    play_underruns climbs. The device sits starved with an empty ring
    and the bytes never arrive.

    A loss here is invisible to every other instrument in this suite.
    The device cannot flag it - invariant 5 makes it count and report
    what *it* drops, and these bytes never reached it - so the DAC
    emits a discontinuity with under=0 and every counter green.
    """
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0),
                           drain_s=1.5)
    assert not res.refused, f"RC {rc} ({hz} sps) was refused\n{res.console}"
    assert res.drained

    deficit = res.host_deficit
    record(calibration, f"host_deficit_rc{rc}", {
        "hz": hz, "tx": res.host_tx_bytes, "in": res.play.bytes_in,
        "deficit": deficit,
        "pct": round(deficit / res.host_tx_bytes * 100, 4) if res.host_tx_bytes
               else None})

    # A loss that is not a whole number of 128-byte chunks is not the
    # host's documented drop, and would be the device losing data it
    # received - a different and worse defect. That fails outright at
    # every rate, including the ones expected to lose bytes.
    assert deficit % 128 == 0, (
        f"RC {rc} lost {deficit} B, which is not a whole number of "
        f"128-byte chunks: that is the device losing data it received, "
        f"not the host's chunk drop. Read play_partial and docs/usb.md")

    if deficit and rc in OVERSUPPLIED:
        pytest.xfail(
            f"RC {rc} ({hz} sps): host lost {deficit} B "
            f"({deficit / res.host_tx_bytes * 100:.2f}%) feeding a "
            f"converter that runs slow. See OVERSUPPLIED")
    if deficit and rc in RESIDUAL:
        pytest.xfail(
            f"RC {rc} ({hz} sps): host lost {deficit} B "
            f"({deficit // 128} chunks) - the residual the constant-size "
            f"feed did not remove. See RESIDUAL")

    assert deficit == 0, (
        f"RC {rc} ({hz} sps) lost {deficit} B ({deficit // 128} chunks "
        f"of 128) that write() counted. This rate is byte-exact with a "
        f"constant-size feed; a loss here means the feeder stopped "
        f"writing a constant size, or the oversupply that affects "
        f"RC 44 and 39 has spread. Read Feeder.WRITE_SIZE")
