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
                     window, window_purity)

pytestmark = [pytest.mark.scope, pytest.mark.awg]

TONE = 1000.0


@pytest.mark.smoke
def test_device_generated_waveform_is_continuous(board, seconds, baseline):
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
    step = max(abs(vals[i] - vals[i - 1]) for i in range(start + 1, len(vals)))

    # gen's tone is the trigger rate over 512.
    tone = ps.declared_rate_hz / 512.0
    limit = measure.slew_limit(tone, baseline["amplitude"]["full_scale_codes"],
                               ps.declared_rate_hz) * 3.0
    assert step <= limit, (
        f"the device's own waveform shows a {step} code step against a "
        f"{limit:.0f} code limit; the fault is in the capture path, not in "
        f"anything the host sends")


@pytest.mark.xfail(strict=False, reason=(
    "host-fed playback loses samples: 4-5 events per 3 s at 200 ksps, "
    "6-185 samples each, with under=0 and every other counter clean. "
    "See test_host_fed_ramp_loses_no_samples and docs/status.md"))
@pytest.mark.smoke
def test_no_sample_step_exceeds_the_waveform_slope(board, seconds, baseline,
                                                   calibration):
    """Invariant 5, tested directly and without any spectral analysis.

    Data spliced across two points in time still passes its header CRC
    and still looks like a signal. What it cannot do is respect the
    derivative of the sine that was sent: the largest step between
    consecutive samples of one channel is 2*pi*f*A/fs, and a splice
    lands somewhere else on the waveform and jumps.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=TONE, seconds=secs)
    assert_fresh(res, secs)
    assert_stream_clean(res)

    amplitude = baseline["amplitude"]["full_scale_codes"]
    fs = res.stream.declared_rate_hz
    got = assert_slew(res, measure.CH_A0, res.tone_hz, amplitude, fs,
                      margin=1.6)
    record(calibration, "slew_a0", {
        "max_step": got,
        "analytic": round(measure.slew_limit(res.tone_hz, amplitude, fs), 1)})


def test_tone_amplitude_per_window(board, seconds, baseline, calibration):
    """Purity judged per window, never over the whole run.

    At 453,488 sps a whole-run Goertzel reads 232 codes against a
    theoretical 1370.5 while nearly every window reads above 1360: one
    phase discontinuity cancels the average, so a per-run number reports
    a collapse that is not happening.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=TONE, seconds=secs)
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


@pytest.mark.xfail(strict=False, reason=(
    "each lost-sample event corrupts the window it lands in, and there "
    "are enough of them to sit on the 90% boundary. See "
    "test_host_fed_ramp_loses_no_samples and docs/status.md"))
def test_every_window_reaches_the_amplitude_floor(board, seconds, baseline):
    """The median says the signal is right; this says it is right *all
    the time*.

    Separated from the median deliberately. The median is robust and
    stays a strict assertion, so a real collapse still fails loudly. The
    fraction is what the lost-sample defect breaks: 4-5 events in a 3 s
    run corrupt up to 5 of about 53 windows, which lands within a
    percent of the 90% requirement either way.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=TONE, seconds=secs)
    assert_fresh(res, secs)
    amp = baseline["amplitude"]
    assert_tone(res, measure.CH_A0, amp["window_floor_codes"],
                fraction=amp["window_fraction"])


def test_the_other_channel_stays_flat(board, seconds, baseline):
    """A1 carries no tone.

    DAC1 is never driven with the waveform, so a tone on A1 means the
    channel tags are being read wrong and the whole capture is
    attributed to the wrong pins. It also bounds multiplexer bleed: one
    sample-and-hold behind a 16:1 mux carries residual charge from the
    previously converted channel.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=TONE, seconds=secs)
    assert_fresh(res, secs)

    ceiling = baseline["amplitude"]["crosstalk_ceiling_codes"]
    median, amps = window_purity(res, measure.CH_A1)
    assert amps, "no windows on A1"
    assert median <= ceiling, (
        f"A1 carries {median:.1f} codes at the tone frequency against a "
        f"{ceiling} code ceiling; either the tags are being demultiplexed "
        f"wrongly or the multiplexer is bleeding")


def test_recovered_frequency_is_the_one_sent(board, seconds):
    """A rate error hides behind a good amplitude.

    The Goertzel is evaluated with the header's declared rate, so if the
    header lies about the rate the peak lands at the wrong frequency
    while the amplitude at that wrong frequency still looks perfect.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=TONE, seconds=secs)
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

    mv = mean * 3300.0 / 4095.0
    lo, hi = baseline["dac_mv"]["span_lo"], baseline["dac_mv"]["span_hi"]
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


@pytest.mark.xfail(strict=False, reason=(
    "samples written by the host do not all reach the DAC; the loss is "
    "invisible to every counter on both sides. See docs/status.md"))
def test_host_fed_ramp_loses_no_samples(board, seconds, calibration):
    """How many samples went missing, not just that the output jumped.

    A sine says the output moved when it should not have. A ramp says by
    how much: every sample encodes its own position, so a discontinuity
    divides straight into a number of samples skipped or repeated.

    Measured today, 200 ksps, three 3 s runs: 4-5 events each, losing
    6-185 samples (12-370 bytes) a time, always forward - data missing,
    never repeated - with under=0, seq_gaps=0, crc_bad=0, resync=0 and
    the device's own generator driving the same path perfectly cleanly.
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
    record(calibration, "ramp_events", {
        "n": len(events), "lost": sorted(lost, reverse=True)[:8],
        "repeated": sorted(repeated, reverse=True)[:8]})
    assert not events, (
        f"{len(events)} discontinuities in a host-fed ramp: "
        f"{sum(lost)} samples lost, {sum(repeated)} repeated, largest gap "
        f"{max(lost or [0])} samples ({max(lost or [0]) * 2} bytes). Every "
        f"device counter is clean, so nothing downstream can tell this "
        f"happened.")
