"""The device's own playback instruments, tested as instruments.

Everything here checks the *measuring apparatus*, not the signal. That
distinction earned its own file: objective 0l spent a session being
theorised about as ISR re-entry when it was a counter left out of the
reset block, and the reason nothing caught it is that no test had ever
asked whether the device's counters describe one run or several.

The rule these enforce is the one the 0-series keeps re-learning: an
instrument that has not been checked against an independent one is not
evidence, however green it reads.
"""

import statistics

import pytest

import measure
from helpers import record, window


@pytest.mark.smoke
def test_playback_counters_describe_one_run_not_several(board, seconds):
    """Every playback counter is reset by play_start.

    play_endtx_seen was not, so the `O` line reported a total
    accumulated since boot while consumed and run_us were per-run, and
    the second run in a session reported an endtx that no reading could
    reconcile. It looked rate-dependent - objective 0l recorded it as
    such - because the ratio is a function of how many runs preceded,
    not of the rate.

    The ENDTX handler takes exactly one of the two branches per entry,
    so this identity is structural rather than statistical, and it holds
    at any rate. Testing it on the *second* run is the whole point: the
    first run passes even with the bug present.
    """
    hz = measure.hz_for(65)
    secs = window(seconds, 2.0)

    first = measure.run_play(board, dac_sps=hz, seconds=secs)
    assert not first.refused, first.console
    second = measure.run_play(board, dac_sps=hz, seconds=secs)
    assert not second.refused, second.console

    for label, res in (("first", first), ("second", second)):
        endtx = res.occ.endtx
        consumed = res.occ.consumed
        under = res.play.underruns
        assert endtx is not None and consumed is not None, (
            f"{label} run reported no occupancy line\n{res.report}")
        assert endtx == consumed + under, (
            f"{label} run: endtx {endtx} != consumed {consumed} + "
            f"underruns {under}. A counter is surviving play_start.")

    # The direct statement of the defect: two runs of the same length
    # must report the same order of magnitude, not a running total.
    assert second.occ.endtx < first.occ.endtx * 1.5, (
        f"second run's endtx {second.occ.endtx} is close to the sum of "
        f"both runs ({first.occ.endtx} + its own) - it is cumulative")


@pytest.mark.parametrize("rc", [65, 44, 39])
def test_the_converter_holds_one_rate_for_a_whole_run(board, seconds,
                                                      calibration, rc):
    """The per-window rate is flat, so a whole-run figure means something.

    play_run_us over play_consumed is an average, and an average is only
    the rate if the rate did not move. RC 44 reads one of two discrete
    rates from run to run - -1.56% or -2.34% of nominal, never anything
    between - which is exactly the situation where an average would be a
    number the converter never held.

    Measured: the state is latched at play_start and held. Across twelve
    runs the median of the first third and of the last third agreed to
    0.000 pp every time, and the spread across ~160 windows was
    0.010-0.021 pp, which is the resolution of the trace rather than
    movement in the converter.
    """
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0))
    assert not res.refused, res.console

    rates = res.occ.window_rates()
    assert len(rates) >= 20, (
        f"RC {rc}: {len(rates)} rate windows, too few to judge flatness\n"
        f"{res.report}")

    nominal = hz * 2.0
    devs = [(r / nominal - 1) * 100 for r in rates]
    spread = max(devs) - min(devs)
    third = len(devs) // 3
    step = statistics.median(devs[-third:]) - statistics.median(devs[:third])

    record(calibration, f"converter_rate_rc{rc}", {
        "hz": hz, "windows": len(rates),
        "median_pct": round(statistics.median(devs), 3),
        "spread_pp": round(spread, 3), "step_pp": round(step, 3)})

    # Generous against the measured 0.02 pp: this is a regression guard
    # on the instrument and on the latching, not a tightening ratchet.
    assert spread < 0.25, (
        f"RC {rc}: per-window rate spans {spread:.3f} pp "
        f"({min(devs):+.2f}..{max(devs):+.2f}) - the converter moved "
        f"during the run, so no whole-run rate describes it")
    assert abs(step) < 0.10, (
        f"RC {rc}: rate stepped {step:+.3f} pp from the first third of "
        f"the run to the last - the state is not latched at play_start")


@pytest.mark.parametrize("rc", [65, 39])
def test_the_two_rate_estimators_agree(board, seconds, rc):
    """Whole-run counters against a trace taken during the run.

    device_byte_rate() divides a counter by a run timer read after the
    stop; traced_byte_rate() spans two timestamps taken while playing.
    They share the device's clock and nothing else, so agreement is
    evidence and disagreement localises the fault to whichever one the
    shutdown can reach.
    """
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0))
    assert not res.refused, res.console

    whole = res.occ.device_byte_rate()
    traced = res.occ.traced_byte_rate()
    assert whole and traced, f"RC {rc}: an estimator returned nothing"

    diff = abs(traced / whole - 1) * 100
    assert diff < 0.20, (
        f"RC {rc}: whole-run {whole:.0f} B/s against traced {traced:.0f} "
        f"B/s, {diff:.3f}% apart - one of them is measuring the shutdown")


def test_the_rate_trace_survives_a_drained_run(board, seconds):
    """A drained run reports the deficit *and* the converter's rate.

    The occupancy histogram cannot survive a drain: the device
    accumulates it until playback stops, so it spans the starvation the
    drain creates by design. The rate trace can, because it is keyed on
    consumed rather than on ENDTX - a starved device consumes nothing
    and so writes no further samples.

    That is what makes objective 0i measurable at all. The oversupply
    claim is that the deficit equals the fraction by which the converter
    runs slow, and comparing two runs cannot test it when the converter
    picks a state per run.
    """
    hz = measure.hz_for(44)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0),
                           drain_s=1.5)
    assert not res.refused, res.console
    assert res.drained
    assert res.host_deficit is not None

    assert res.occ.rate_us, (
        "a drained run reported no rate trace, so the deficit and the "
        f"converter rate cannot be read from one run\n{res.report}")
    rates = res.occ.window_rates()
    assert len(rates) >= 20, f"only {len(rates)} windows survived the drain"

    # The histogram must still be withheld: it spans the starvation.
    assert not res.occ.buckets, (
        "the occupancy histogram was reported for a drained run, where "
        "it describes the shutdown rather than the run")


@pytest.mark.parametrize("rc", [65, 44, 39])
def test_the_deficit_is_the_oversupply(board, seconds, calibration, rc):
    """What the host loses is what the converter could not take.

    Objective 0i's claim, and until the rate trace survived a drained
    run it could only be checked across rates - which is weak evidence,
    because rate is confounded with everything else that varies with
    rate.

    RC 44 turns it into a controlled experiment. It picks one of two
    converter states per run at the same commanded rate, with the same
    feed and the same write policy, so the state is the only thing that
    moves. Measured over eight runs: seven took the fast state and lost
    1.35% against a converter 1.56% slow; the one that took the slow
    state lost 2.13% against a converter 2.34% slow. The difference held
    at -0.21 pp across both. The deficit follows the converter, not the
    rate.

    That -0.21 pp offset is consistent to 0.01 pp and is *not*
    explained. It is left out of the assertion deliberately: this test
    is here to hold the relationship, and pinning an unexplained
    constant would turn a measurement into a requirement.
    """
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0),
                           drain_s=1.5)
    assert not res.refused, res.console
    assert res.drained

    traced = res.occ.traced_byte_rate()
    assert traced, f"RC {rc}: the drained run reported no rate trace"

    nominal = hz * 2.0
    slow_pct = (1 - traced / nominal) * 100
    deficit_pct = res.host_deficit / res.host_tx_bytes * 100

    record(calibration, f"oversupply_rc{rc}", {
        "hz": hz, "slow_pct": round(slow_pct, 3),
        "deficit_pct": round(deficit_pct, 3),
        "diff_pp": round(deficit_pct - slow_pct, 3),
        "lost_bytes": res.host_deficit})

    assert deficit_pct == pytest.approx(slow_pct, abs=0.5), (
        f"RC {rc}: lost {deficit_pct:.2f}% against a converter "
        f"{slow_pct:.2f}% slow. These track each other - a gap means "
        f"the loss is no longer just the surplus the converter refused")

    if rc == 65:
        # The control. An exact converter oversupplies nothing, so a
        # loss here would be a different defect wearing 0i's clothes.
        assert deficit_pct < 0.1, (
            f"RC {rc} is byte-exact by measurement, but lost "
            f"{deficit_pct:.3f}% ({res.host_deficit} B)")


@pytest.mark.parametrize("rc", [65, 44, 39])
def test_the_carrier_reports_what_the_console_trace_reports(board, seconds,
                                                            calibration, rc):
    """Playback status over bulk IN agrees with the console `O` trace.

    These are the two ends of objective 0i's carrier problem. The rate
    loop cannot be closed over the console - polling `B` at 20 Hz took
    RC 65 from 6 underruns to 30 when the ring was short, because a
    printf holds the main loop - so the signal goes out on the native
    port's bulk IN, which is idle in play-only.

    The console trace is then the oracle for it. They share the device's
    clock and nothing else: one is a record emitted from the main loop
    every 20 ms, the other is an array sampled in the ENDTX handler and
    read out afterwards. Measured agreement is 0.001 to 0.018 pp.
    """
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=window(seconds, 3.0),
                           drain_s=1.5)
    assert not res.refused, res.console

    assert len(res.stats) > 20, (
        f"RC {rc}: only {len(res.stats)} status records arrived over bulk "
        f"IN - the carrier is not delivering")

    carrier = measure.playstat_rate(res.stats)
    traced = res.occ.traced_byte_rate()
    assert carrier and traced, f"RC {rc}: carrier={carrier} traced={traced}"

    nominal = hz * 2.0
    cp = (1 - carrier / nominal) * 100
    tp = (1 - traced / nominal) * 100
    record(calibration, f"carrier_rc{rc}", {
        "hz": hz, "records": len(res.stats),
        "carrier_pct": round(cp, 3), "trace_pct": round(tp, 3),
        "delta_pp": round(cp - tp, 4)})

    assert cp == pytest.approx(tp, abs=0.10), (
        f"RC {rc}: carrier says the converter is {cp:+.2f}% off nominal, "
        f"the console trace says {tp:+.2f}% - {cp-tp:+.3f} pp apart. One "
        f"of the two is not measuring the converter")


@pytest.mark.smoke
def test_the_carrier_stays_silent_in_loop_mode(board, seconds):
    """Nothing splices status records into a capture stream.

    In loop mode bulk IN carries frames and the IN endpoint is on DMA.
    Writing a record there would be wrong twice over: the FIFO path and
    DMA must never share an endpoint - `stream.c` says so and it has
    wedged the endpoint before - and a record spliced between frames
    would put 28 bytes of non-sample data inside the sample stream,
    which invariant 5 exists to prevent.

    The emitter is gated on `stream_in_in_use()`. This is the test of
    that gate. Framing integrity is the observable proxy: injected bytes
    would show up as a CRC failure or a sequence gap, because a frame
    parser that swallowed them would be reading payload out of step.
    """
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           seconds=window(seconds, 2.0))
    assert not res.refused, res.console
    assert res.frames > 0, "no frames captured, so the gate proves nothing"
    assert res.crc_bad == 0, (
        f"{res.crc_bad} frames failed CRC - something is writing bulk IN "
        f"while the stream owns it")
    assert res.seq_gaps == 0, (
        f"{res.seq_gaps} sequence gaps - the frame stream is not intact")
