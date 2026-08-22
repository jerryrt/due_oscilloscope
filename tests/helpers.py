"""
Assertions shared by every domain.

The rules encoded here each cost real debugging time to learn and are
requirements on the suite, not style: judge tone purity per window and
never over a whole run, and prove every measurement is this run's data
before believing a single number in it.
"""

import statistics

import pytest

import measure

# Default streaming window. Long enough for the settled second that the
# ring priming costs, plus something to judge.
RUN_SECONDS = 3.0


def window(seconds_opt, default=RUN_SECONDS):
    return default if seconds_opt is None else seconds_opt


def loop_cmd(adc_hz, channels=2, dac_sps=200000):
    """The console command that starts a capture at an arbitrary rate.

    `L` is the only command that takes one; the numbered presets are
    fixed. It starts playback too, which underruns with no host feeding
    it - harmless here, and counted rather than concealed, which is the
    point of the underrun counter.
    """
    return f"={dac_sps},{adc_hz},{channels}L"


def assert_fresh(res, seconds=None):
    """Prove the capture is this run's before anything is computed on it.

    Stale kernel-buffered frames from a previous run once manufactured a
    frozen DAC and cost a full session. Sequence numbers near zero and
    device timestamps spanning the host's own window are the proof.
    """
    ps = res.stream
    assert ps.frames > 0, "no frames arrived at all"
    assert ps.first_seq <= 10, (
        f"capture starts at seq {ps.first_seq}, not near 0: this is stale "
        f"data from an earlier stream, so nothing computed from it is about "
        f"this run")
    want = seconds if seconds is not None else res.elapsed_s
    assert ps.dev_span_s >= 0.5 * want, (
        f"device timestamps span {ps.dev_span_s:.2f} s of a {want:.2f} s "
        f"host window: the stream did not run for the window it was "
        f"measured over")


def assert_stream_clean(res):
    """The counters that must be zero for the data to be continuous."""
    ps = res.stream
    assert ps.crc_bad == 0, f"{ps.crc_bad} frame headers failed CRC"
    assert ps.seq_gaps == 0, (
        f"{ps.seq_gaps} sequence gaps ({ps.dropped_frames} frames lost): "
        f"the stream is discontinuous")


def assert_no_underruns(res):
    under = res.play.underruns
    assert under is not None, "device did not report play counters"
    assert under == 0, (
        f"{under} playback underruns: the DAC repeated a buffer, so the "
        f"waveform on the wire is not the one the host sent")


def window_purity(res, tag, size=8192):
    """Per-window tone amplitude: (median, list of amplitudes).

    Never a whole-run figure. At 453,488 sps a whole-run Goertzel reads
    232 codes against a theoretical 1370.5 while nearly every window
    reads above 1360, because one phase discontinuity cancels the
    average - a per-run number reports collapses that are not happening.
    """
    amps = [a for _, a in res.stream.window_amplitudes(
                              tag, res.tone_hz, size=size,
                              from_us=measure.SETTLE_US)]
    if not amps:
        return 0.0, []
    return statistics.median(amps), amps


def assert_tone(res, tag, floor, fraction=0.90, size=8192):
    """Median window amplitude at or above `floor`, and at least
    `fraction` of windows above it too."""
    median, amps = window_purity(res, tag, size=size)
    assert amps, f"no full window of samples on tag {tag}"
    good = sum(1 for a in amps if a >= floor)
    assert median >= floor, (
        f"median window amplitude {median:.1f} codes below the {floor} "
        f"floor over {len(amps)} windows")
    assert good >= fraction * len(amps), (
        f"only {good}/{len(amps)} windows reached {floor} codes "
        f"(median {median:.1f})")
    return median


def assert_slew(res, tag, tone_hz, amplitude, fs_hz, margin=3.0):
    """No step larger than a clean sine of this amplitude can take.

    This is invariant 5 tested directly and without any spectral
    analysis: data spliced across two points in time still passes its
    header CRC, and shows up here as a step no derivative allows.

    The margin is 3x rather than something tight because the DAC clock
    and the ADC trigger are separate TC channels at the same rate but
    free running against each other, so two DAC updates can fall between
    consecutive samples of one channel. The device-generated control
    measures 39 codes against an analytic 17 for exactly that reason.
    A splice is three orders of magnitude clear of this, not a few
    percent.
    """
    limit = measure.slew_limit(tone_hz, amplitude, fs_hz) * margin
    got = res.stream.max_slew(tag, from_us=measure.SETTLE_US)
    assert got <= limit, (
        f"largest step on tag {tag} is {got} codes against an analytic "
        f"limit of {limit:.0f} ({margin}x "
        f"{measure.slew_limit(tone_hz, amplitude, fs_hz):.0f}): the samples "
        f"are spliced from two points in time")
    return got


def only_tags(res, mask):
    """Every sample carried a tag the configured mask allows."""
    want = {i for i in range(16) if mask & (1 << i)}
    got = set(res.stream.per_channel)
    assert got <= want, (
        f"samples arrived tagged {sorted(got - want)}, which the channel "
        f"mask {mask:#06x} does not enable")
    return got


def record(calibration, key, value):
    calibration[key] = value
    return value


def approx_rate(measured, declared, tol=0.005):
    assert declared > 0
    ratio = measured / declared
    assert abs(ratio - 1.0) <= tol, (
        f"measured {measured:.0f} Hz against a declared {declared} Hz "
        f"(ratio {ratio:.4f}, tolerance {tol})")
    return ratio
