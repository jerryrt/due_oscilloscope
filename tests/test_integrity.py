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
    #   noise      |n| <= JITTER samples. A0 is captured at half the DAC
    #              rate, so a clean interval reads 2, and the analysis
    #              flags anything outside [-2, 4]. Values of exactly +3
    #              and -3 turn up in matched pairs, which is a sampling
    #              instant drifting across a boundary and not data: a
    #              ring can only ever skip forward.
    #   host drop  whole multiples of 128 bytes. macOS's CDC-ACM output
    #              path discards ~128-byte chunks from a pressured tty
    #              queue with write() having counted them. Open, and
    #              reported as an xfail below.
    #   anything else - a forward jump of an arbitrary size - is the
    #              device losing data it received, which is the defect
    #              this test was written for. That fails outright.
    JITTER = 4
    real = [n for n in lost if n > JITTER]
    stray = [n * 2 for n in real if (n * 2) % 128]
    assert not stray, (
        f"{len(stray)} of {len(real)} losses are not whole 128-byte "
        f"chunks ({stray[:8]} bytes): an arbitrary forward jump is the "
        f"device losing data it received, not the host's chunk drop. "
        f"Read play_partial and docs/status.md")

    big_repeat = [n for n in repeated if n > JITTER]
    assert not big_repeat, (
        f"the DAC repeated {sum(big_repeat)} samples across "
        f"{len(big_repeat)} points with under=0; a repeat that is not "
        f"counted as an underrun is the ring emitting a slot twice")

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
