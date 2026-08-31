"""
Assertions shared by every domain.

The rules encoded here each cost real debugging time to learn and are
requirements on the suite, not style: judge tone purity per window and
never over a whole run, and prove every measurement is this run's data
before believing a single number in it.
"""

import statistics

import sys

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


# Does this host's serial stack buffer ahead of the device?
#
# macOS's CDC driver holds 55-450 KB below the tty layer, runs ahead of
# the device, and silently discards what it cannot place - which is
# objective 0a/0b/0i, and the reason a deficit exists there at all.
# Windows' usbser.sys applies backpressure to the writer instead, so no
# backlog forms and nothing is discarded: measured 0 B lost at every rate
# from 200,000 to 1,392,857 sps, across four write policies.
#
# So a test that asserts a deficit EXISTS is characterising one host, not
# the device. Byte conservation is the invariant and is asserted
# everywhere; the deficit relationship is asserted only where there is a
# deficit to relate. See docs/windows.md and CLAUDE.md's tier table.
BUFFERING_HOST = sys.platform == "darwin"


def needs_a_buffering_host(what):
    """Skip a test whose subject is the host's own oversupply.

    Not an xfail: nothing here is broken and nothing is expected to
    start working. The condition the test exists to observe does not
    occur on this platform.
    """
    if not BUFFERING_HOST:
        pytest.skip(
            f"{what} needs a host that buffers ahead of the device. "
            f"{sys.platform} applies backpressure instead, so there is no "
            f"oversupply to measure - see docs/windows.md")


def assert_fresh(res, seconds=None):
    """Prove the capture is this run's before anything is computed on it.

    Stale kernel-buffered frames from a previous run once manufactured a
    frozen DAC and cost a full session. Sequence numbers near zero and
    device timestamps spanning the host's own window are the proof.
    """
    ps = res.stream
    assert ps.frames > 0, "no frames arrived at all"
    # Frames a run deliberately discarded while settling are not stale
    # data - they are this run's, read and thrown away on purpose so the
    # device's ADC ring is not left to overrun. Allow for them, and no
    # more: the check exists to catch a previous run's leftovers.
    settled = getattr(res, "settle_frames", 0)
    assert ps.first_seq <= 10 + settled, (
        f"capture starts at seq {ps.first_seq}, not near 0 "
        f"({settled} frames were discarded while settling): this is stale "
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


def assert_no_underruns(res, tolerance=0):
    """Zero is the requirement: an underrun means the DAC repeated a
    buffer, so the wire did not carry what the host sent.

    `tolerance` exists only while the sample-loss defect is open. Host
    -fed playback sporadically underruns two or three times at rates
    that pass 5/5 on their own, while a rate that genuinely starves
    gives 15 to 50, so a small tolerance separates the known defect's
    tail from a collapse and keeps the ladders usable as a gate. It is
    passed explicitly by the ladders and by nothing else.
    """
    under = res.play.underruns
    assert under is not None, "device did not report play counters"
    assert under <= tolerance, (
        f"{under} playback underruns: the DAC repeated a buffer, so the "
        f"waveform on the wire is not the one the host sent"
        + (f" (tolerating {tolerance} at a rate that starves)"
           if tolerance else ""))
    assert_spans_whole(res)


def assert_spans_whole(res):
    """No OUT DMA span ended anywhere but on a slot edge.

    The tripwire for the defect that lost samples silently for a
    fortnight. A stream span is armed with a length that lands exactly
    on a slot boundary and nothing is allowed to end it early, so a
    span that finished elsewhere means the device read its own progress
    wrong - and the next span then resumes behind the data already in
    SRAM and overwrites it. Nothing else on either side notices.
    """
    partial = res.play.partial
    if partial is None:
        return          # firmware predating the counter
    assert partial == 0, (
        f"{partial} OUT DMA spans ended off a slot edge; each one "
        f"overwrites data already landed, losing up to a slot of samples "
        f"with every counter clean")


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


def shared_run(cache, fn, board, **kw):
    """One board run, serving every test that asks for the same one.

    Several tests state a claim *about a single run* - the per-window
    rate is flat within a run, two rate estimators agree on a run, the
    bulk-IN carrier and the console `O` trace describe the same run, A0
    carries the tone *while* A1 stays flat - and each was starting its
    own three-second run to read a different field of the same result.
    Eight runs at three distinct parameter sets in `test_play_counters`,
    five runs at one in `test_integrity`; between them a half of the
    suite's clock.

    Sharing them is not a speed-for-coverage trade. Taking the two sides
    of an agreement claim from two different board runs is the *weaker*
    test, and at RC 44 it is misleading: the converter latches one of two
    discrete states per run (issue #48), so two runs at one commanded
    rate can be two different converters. This makes the comparison
    within-run by construction. The time it saves is the side effect.

    A key is the run function plus its parameters, so a test that
    varies any of them gets its own run and nothing has to be
    remembered about who shares with whom.

    **Do not use it where a test wants two independent runs.**
    `test_playback_counters_describe_one_run_not_several` is exactly
    that - its subject is whether the counters are per-run or cumulative
    - and it calls `measure.run_play` directly for that reason.

    The cost of sharing, stated so a failure is not misread: when a
    shared run is bad, every test keyed to it fails together. That is
    one measurement failing several assertions, not several
    measurements agreeing. Check the key before concluding a defect
    reproduced.
    """
    key = (fn.__name__,) + tuple(sorted((k, repr(v)) for k, v in kw.items()))
    if key not in cache:
        cache[key] = fn(board, **kw)
    return cache[key]
