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
from helpers import needs_a_buffering_host, record, shared_run, window


@pytest.mark.smoke
def test_playback_counters_describe_one_run_not_several(board, seconds, track):
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
    # Both tracks: the identity is read off the `O` occupancy line, and
    # both bind `O`.

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
                                                      calibration,
                                                      run_cache, rc):
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
    res = shared_run(run_cache, measure.run_play, board, dac_sps=hz,
                     seconds=window(seconds, 3.0))
    assert not res.refused, res.console

    if not res.occ.rate_us:
        pytest.skip("PLAY_RATE_TRACE_ENABLED is 0 - the ENDTX rate trace "
                    "is off by default because it perturbs the path it "
                    "measures; build with it on to re-check this")
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
def test_the_two_rate_estimators_agree(board, seconds, run_cache, rc):
    """Whole-run counters against a trace taken during the run.

    device_byte_rate() divides the device's own counters by its own run
    timer, read over the console after the stop. playstat_rate() spans
    timestamped records that came off bulk IN while the run was still
    going. Different sampling site, different transport, same clock - so
    agreement is evidence, and disagreement says which of the two the
    shutdown reached.
    """
    hz = measure.hz_for(rc)
    res = shared_run(run_cache, measure.run_play, board, dac_sps=hz,
                     seconds=window(seconds, 3.0))
    assert not res.refused, res.console

    whole = res.occ.device_byte_rate()
    carrier = measure.playstat_rate(res.stats)
    assert whole and carrier, f"RC {rc}: an estimator returned nothing"

    diff = abs(carrier / whole - 1) * 100
    assert diff < 0.20, (
        f"RC {rc}: whole-run counters say {whole:.0f} B/s, the bulk-IN "
        f"carrier says {carrier:.0f} B/s, {diff:.3f}% apart")


def test_the_carrier_survives_a_drained_run(board, seconds):
    """A drained run reports the deficit *and* the converter's rate.

    The occupancy histogram cannot survive a drain: the device
    accumulates it until playback stops, so it spans the starvation the
    drain creates by design, and run_play withholds it. The bulk-IN
    carrier does survive, because run_play slices the records at the
    moment the feeder stopped - what arrives after that describes the
    shutdown.

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

    assert measure.playstat_rate(res.stats), (
        "a drained run reported no usable carrier, so the deficit and the "
        f"converter rate cannot be read from one run\n{res.report}")

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

    traced = measure.playstat_rate(res.stats)
    assert traced, f"RC {rc}: the drained run reported no usable carrier"

    nominal = hz * 2.0
    slow_pct = (1 - traced / nominal) * 100
    deficit_pct = res.host_deficit / res.host_tx_bytes * 100

    record(calibration, f"oversupply_rc{rc}", {
        "hz": hz, "slow_pct": round(slow_pct, 3),
        "deficit_pct": round(deficit_pct, 3),
        "diff_pp": round(deficit_pct - slow_pct, 3),
        "lost_bytes": res.host_deficit})

    from helpers import BUFFERING_HOST
    if BUFFERING_HOST:
        assert deficit_pct == pytest.approx(slow_pct, abs=0.5), (
            f"RC {rc}: lost {deficit_pct:.2f}% against a converter "
            f"{slow_pct:.2f}% slow. These track each other - a gap means "
            f"the loss is no longer just the surplus the converter refused")
    else:
        # The relationship needs a deficit to relate. This host applies
        # backpressure, so there is none - and that is the stronger
        # claim, so assert it: byte conservation is the invariant, the
        # deficit relationship is a characterisation of one host.
        #
        # The converter is still slow here (RC 44 and 39 measure 1.6% by
        # the device's own runus), which is what makes this the right
        # assertion rather than a weaker one: the device-side half of
        # objective 0i is present and nothing is lost anyway.
        assert deficit_pct < 0.1, (
            f"RC {rc}: this host does not oversupply, so nothing should "
            f"be lost at all - but {deficit_pct:.3f}% "
            f"({res.host_deficit} B) is missing against a converter "
            f"{slow_pct:.2f}% slow")

    if rc == 65:
        # The control. An exact converter oversupplies nothing, so a
        # loss here would be a different defect wearing 0i's clothes.
        assert deficit_pct < 0.1, (
            f"RC {rc} is byte-exact by measurement, but lost "
            f"{deficit_pct:.3f}% ({res.host_deficit} B)")


@pytest.mark.parametrize("rc", [65, 44, 39])
def test_the_carrier_reports_what_the_console_trace_reports(board, seconds,
                                                            calibration,
                                                            run_cache, rc):
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
    # Undrained deliberately. A drain starves the device by design, and
    # run_play then withholds the occupancy line - the oracle - because
    # it would describe the shutdown. The deficit is not wanted here.
    hz = measure.hz_for(rc)
    res = shared_run(run_cache, measure.run_play, board, dac_sps=hz,
                     seconds=window(seconds, 3.0))
    assert not res.refused, res.console

    assert len(res.stats) > 20, (
        f"RC {rc}: only {len(res.stats)} status records arrived over bulk "
        f"IN - the carrier is not delivering")

    carrier = measure.playstat_rate(res.stats)
    traced = res.occ.device_byte_rate()
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


# -- the carrier's parser, with no board ------------------------------
#
# These run anywhere. The estimator has been wrong three times in ways
# that only showed up against hardware, so the shapes that broke it are
# reproduced here directly and cost nothing to check.

def _rec(consumed, underruns, dev_us, bytes_in=0, version=1, crc=None):
    """One status record, built exactly as lib/due_shared/src/playstat.h emits it."""
    import struct, zlib
    body = struct.pack("<4sB3sIIII", b"DUEP", version, b"\0\0\0",
                       consumed, underruns, bytes_in, dev_us)
    if crc is None:
        crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack("<I", crc)


def test_parse_playstats_reads_a_record_the_device_would_send():
    got = measure.parse_playstats(_rec(1234, 5, 999999, bytes_in=777))
    assert len(got) == 1
    assert (got[0].consumed, got[0].underruns,
            got[0].dev_us, got[0].bytes_in) == (1234, 5, 999999, 777)


def test_parse_playstats_finds_a_record_at_any_offset():
    """A read can start mid-record, so the parser scans rather than
    assuming the buffer begins on a boundary."""
    buf = b"\x00\x01rubbish\xff" + _rec(10, 0, 20) + b"trailing"
    got = measure.parse_playstats(buf)
    assert len(got) == 1 and got[0].consumed == 10


def test_parse_playstats_rejects_a_corrupt_record():
    """A bad CRC is skipped, not trusted. The magic is four bytes and
    will occur by chance in other data; without the check a run of
    sample values could be read as a status record."""
    bad = bytearray(_rec(10, 0, 20))
    bad[8] ^= 0xFF                      # flip a counter, leave the CRC
    assert measure.parse_playstats(bytes(bad)) == []


def test_parse_playstats_rejects_an_unknown_version():
    assert measure.parse_playstats(_rec(10, 0, 20, version=2)) == []


def test_playstat_rate_ignores_the_dead_head_and_a_frozen_tail():
    """The two shapes playstat_rate is responsible for.

    A run has a dead head: run_play issues P and then spends about half
    a second on console reads before the feeder starts, so the device
    sits play-active with consumed frozen at 0 for ~30 records. Span
    everything and the rate reads 55% slow.

    Selecting on `underruns` instead looks more principled and selects
    the whole array, because before the ring primes the DACC trigger has
    not started, so no ENDTX fires and underruns is frozen at 0
    alongside consumed. The discriminator has to be consumed.

    The ragged decay between "still fed" and "fully starved" is not this
    function's job - run_play slices the buffer at the moment the feeder
    stopped, so the records never contain it. That slice is what
    test_the_carrier_reports_what_the_console_trace_reports checks
    against hardware.
    """
    rate = 1_700_000.0                  # bytes/s the converter holds
    per = 20_000                        # 20 ms between records, in us
    step = rate * per / 1e6 / 1024      # buffers per interval
    stats, t, c = [], 0, 0.0
    for _ in range(30):                 # dead head: nothing consumed yet
        stats.append(measure.PlayStat(0, 0, 0, t)); t += per
    for _ in range(150):                # steady state
        c += step
        stats.append(measure.PlayStat(round(c), 0, 0, t)); t += per
    for _ in range(60):                 # starved: consumed frozen hard
        stats.append(measure.PlayStat(round(c), 0, 0, t)); t += per

    got = measure.playstat_rate(stats)
    assert got == pytest.approx(rate, rel=0.002), (
        f"recovered {got:.0f} B/s from a converter holding {rate:.0f}")


def test_playstat_rate_does_not_start_on_the_partial_interval():
    """The span must begin after consumption starts, not on the last
    frozen record.

    Starting one record early includes the interval in which playback
    began, which carries a fraction of a full interval's data over a
    full interval's time. It is one interval in ~150 and it read up to
    0.6 pp slow against hardware, wandering run to run with where in
    that interval the first buffer happened to land.
    """
    rate, per = 1_700_000.0, 20_000
    step = rate * per / 1e6 / 1024
    stats, t = [], 0
    stats.append(measure.PlayStat(0, 0, 0, t)); t += per   # last frozen
    c = step * 0.1                                         # partial start
    for _ in range(100):
        stats.append(measure.PlayStat(round(c), 0, 0, t)); t += per
        c += step
    got = measure.playstat_rate(stats)
    assert got == pytest.approx(rate, rel=0.002), (
        f"recovered {got:.0f} B/s - the partial first interval is in the span")


def test_playstat_rate_declines_to_guess_from_too_little():
    assert measure.playstat_rate([]) is None
    assert measure.playstat_rate([measure.PlayStat(0, 0, 0, 0)]) is None
    # All frozen: no interval over which the converter was consuming.
    frozen = [measure.PlayStat(5, 0, 0, i * 100) for i in range(10)]
    assert measure.playstat_rate(frozen) is None


# -- the closed loop, on hardware -------------------------------------

@pytest.mark.parametrize("rc", [44, 39])
def test_the_closed_loop_removes_most_of_the_oversupply(board, seconds,
                                                        calibration, rc):
    """Objective 0i's fix, measured against its own open-loop control.

    Interleaved in one test rather than compared against a recorded
    figure, because the converter picks its state per run: a closed-loop
    run in the slow state against an open-loop number from the fast one
    would flatter or damn the loop by up to 0.8 pp for nothing.

    What is left after the loop is startup, not rate error - see
    test_the_closed_loop_residual_is_a_startup_cost.
    """
    needs_a_buffering_host("the rate loop's whole subject")
    hz = measure.hz_for(rc)
    secs = window(seconds, 3.0)
    op = measure.run_play(board, dac_sps=hz, seconds=secs, drain_s=1.5)
    cl = measure.run_play(board, dac_sps=hz, seconds=secs, drain_s=1.5,
                          closed_loop=True)
    for r in (op, cl):
        assert not r.refused, r.console
        assert r.drained

    o = op.host_deficit / op.host_tx_bytes * 100
    c = cl.host_deficit / cl.host_tx_bytes * 100
    record(calibration, f"closed_loop_rc{rc}", {
        "hz": hz, "open_pct": round(o, 3), "closed_pct": round(c, 3),
        "retunes": cl.retunes})

    assert cl.retunes > 0, "the loop never retuned, so this proves nothing"
    assert o > 1.0, f"RC {rc}: open loop lost only {o:.2f}%, expected >1%"
    assert c < o / 2, (
        f"RC {rc}: closed loop lost {c:.2f}% against {o:.2f}% open - the "
        f"trim is not tracking the converter")


@pytest.mark.parametrize("rc", [44, 39])
def test_the_closed_loop_buys_nothing_with_underruns(board, seconds, rc):
    """The loop must not pay for accuracy in starvation.

    Trimming the feed down to the converter's rate moves toward
    under-feeding, and an underrun is a repeated buffer - a
    discontinuity invariant 5 exists to keep out of the data. The
    opposite trap is recorded in usb.md: over-feeding 1-2% takes the
    underrun counter to zero while the dropped samples stay missing.
    Neither counter is evidence on its own, so both are checked here.
    """
    needs_a_buffering_host("the rate loop's cost")
    res = measure.run_play(board, dac_sps=measure.hz_for(rc),
                           seconds=window(seconds, 3.0), drain_s=1.5,
                           closed_loop=True)
    assert not res.refused, res.console
    assert res.play.underruns == 0, (
        f"RC {rc}: the closed loop cost {res.play.underruns} underruns")


def test_the_closed_loop_leaves_an_exact_rate_alone(board, seconds):
    """At a rate the converter holds exactly there is nothing to correct.

    RC 65 measures byte-exact open loop, so the loop's job here is to do
    no harm: it should still run, and still lose nothing.
    """
    needs_a_buffering_host("the rate loop's no-op case")
    res = measure.run_play(board, dac_sps=measure.hz_for(65),
                           seconds=window(seconds, 3.0), drain_s=1.5,
                           closed_loop=True)
    assert not res.refused, res.console
    assert res.retunes > 0, "the loop did not run"
    assert res.play.underruns == 0
    pct = res.host_deficit / res.host_tx_bytes * 100
    assert pct < 0.1, f"RC 65 closed loop lost {pct:.3f}%, open loop loses 0"


@pytest.mark.slow
def test_the_closed_loop_residual_is_a_startup_cost(board, calibration):
    """What the loop leaves behind is bytes, not a rate.

    The feed runs open loop until the first trim, which cannot happen
    until the dead head has passed and a span exists to measure. Those
    bytes are lost once per run, so the loss per run is roughly constant
    and the percentage falls as the run lengthens. A rate model that was
    simply wrong would lose proportionally instead.

    Measured at RC 39: 27,648 B over 3 s and 28,544 B over 6 s, so
    0.466% became 0.242%.
    """
    needs_a_buffering_host("the rate loop's residual")
    hz = measure.hz_for(39)
    short = measure.run_play(board, dac_sps=hz, seconds=3.0, drain_s=1.5,
                             closed_loop=True)
    long = measure.run_play(board, dac_sps=hz, seconds=6.0, drain_s=1.5,
                            closed_loop=True)
    record(calibration, "closed_loop_startup_cost", {
        "short_bytes": short.host_deficit, "long_bytes": long.host_deficit,
        "short_pct": round(short.host_deficit / short.host_tx_bytes * 100, 3),
        "long_pct": round(long.host_deficit / long.host_tx_bytes * 100, 3)})

    assert short.host_deficit > 0, "nothing was lost, so nothing is proven"
    assert long.host_deficit < short.host_deficit * 1.5, (
        f"doubling the run took the loss from {short.host_deficit} B to "
        f"{long.host_deficit} B - that is a rate error, not a startup cost")


# -- loop mode's carrier ----------------------------------------------

def test_loop_mode_frames_carry_the_converter_rate(board, seconds,
                                                   calibration):
    """The frame header is loop mode's carrier, and it has an oracle.

    In play-only the signal rides the bulk-IN status record. In loop
    mode bulk IN carries frames and the endpoint is on DMA, so nothing
    else may write there - the header is the only channel left. It
    already carried the other half of a rate estimate, `timestamp_us`,
    so `play_consumed` completes the pair rather than adding one.

    The console trace checks it, exactly as it checks the play-only
    carrier: same converter, same device clock, sampled in the ENDTX
    handler instead of built into a frame.
    """
    # RC 65 rather than an oversupplied rate, because loop mode has no
    # device-side oracle: run_loop's shutdown is seconds of console
    # reads, over which play_run_us keeps growing while the starved
    # converter consumes nothing, so device_byte_rate() reads ~40% slow.
    # RC 65 needs no oracle - it is byte-exact by measurement, so the
    # converter is at nominal and the carrier must say so.
    dac = measure.hz_for(65)
    res = measure.run_loop(board, dac_sps=dac, adc_hz=measure.hz_for(130),
                           channels=2, seconds=window(seconds, 3.0))
    assert not res.refused, res.console
    assert res.frames > 100, f"only {res.frames} frames"

    stats = res.stream.play_stats
    assert len(stats) == res.frames, (
        f"{len(stats)} carriers against {res.frames} frames - the header "
        f"field is not being read for every frame")
    assert stats[-1].consumed > stats[0].consumed, (
        "play_consumed never moved, so the header is carrying nothing")

    carrier = measure.playstat_rate(stats)
    assert carrier, "the frame headers yielded no usable rate"

    nominal = dac * 2.0
    cp = (1 - carrier / nominal) * 100
    record(calibration, "loop_carrier_rc65", {
        "frames": res.frames, "carrier_pct": round(cp, 3)})
    assert abs(cp) < 0.20, (
        f"loop-mode carrier says the converter is {cp:+.2f}% off nominal at "
        f"a rate that is byte-exact, so it should be at nominal")


def test_the_closed_loop_runs_in_loop_mode_without_breaking_the_stream(
        board, seconds):
    """Trimming the feed must not disturb capture.

    Loop mode is the case where the correction and the measurement share
    a wire: the rate signal rides the frames, and retuning changes how
    fast the host writes into the same USB link those frames come back
    on. If that coupling misbehaves it shows up as CRC failures or
    sequence gaps, not as a bad rate.
    """
    needs_a_buffering_host("the rate loop in loop mode")
    res = measure.run_loop(board, dac_sps=measure.hz_for(44),
                           adc_hz=measure.hz_for(88), channels=2,
                           seconds=window(seconds, 3.0), closed_loop=True)
    assert not res.refused, res.console
    assert res.retunes > 0, "the loop never retuned, so this proves nothing"
    assert res.frames > 100, f"only {res.frames} frames"
    assert res.crc_bad == 0, f"{res.crc_bad} frames failed CRC"
    assert res.seq_gaps == 0, f"{res.seq_gaps} sequence gaps"
    assert res.play.underruns == 0, (
        f"the closed loop cost {res.play.underruns} underruns in loop mode")
