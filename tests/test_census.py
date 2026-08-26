"""
The splice census. No board required.

measure.level_census() is the instrument that settled issue #5, and it
replaced a pass/fail check that had a real defect under it for a whole
session. An instrument that reports a defect nobody can reproduce is
worth less than no instrument, so it is tested here against waveforms
whose answer is known by construction: the device is not needed to know
that a clean staircase has no splices in it.

The numbers in the assertions are the ones measured on hardware over 25
runs across the two firmwares - 778-780 on every defective run, 0 on
every healthy one - and the synthetic signals below are built to the
same shape.
"""

import math
import random

import measure

FS = 200_000
AMPLITUDE = 1371
MID = 2048
TABLE = 512                      # gen's sine table, and the DAC ring slot


def staircase(n=200_000, hold=2, noise=0):
    """`gen`'s output as the ADC sees it: a level per table entry, each
    held for `hold` samples, stepping by up to ~38 codes."""
    rng = random.Random(20260825)
    tone = FS / TABLE
    out = []
    for i in range(n):
        level = i // hold
        v = MID + AMPLITUDE * math.sin(2 * math.pi * tone * level * hold / FS)
        out.append(round(v) + (rng.randint(-noise, noise) if noise else 0))
    return out


def test_a_clean_staircase_has_no_splices():
    """The DAC step is not a splice, however much larger it is than the
    derivative of the sine that shape approximates."""
    c = measure.level_census(staircase())
    assert c["count"] == 0
    assert c["max_step"] < measure.STEP_SPLICE_CODES


def test_adc_noise_does_not_become_a_splice():
    c = measure.level_census(staircase(noise=2))
    assert c["count"] == 0


def test_a_splice_is_counted():
    """Data joined from two points in time, which is invariant 5."""
    v = staircase()
    joined = v[:100_000] + v[133_337:]
    assert measure.level_census(joined)["count"] == 1


def test_the_issue_5_signature_is_counted_once_per_occurrence():
    """Issue #5 is not a splice: it sets bit 6 of one sample every
    PLAY_BUF_SAMPLES, once per DAC ring slot. On the flat channel that
    is a single-sample spike of +64 codes, which crosses the threshold
    going up and again coming down.

    It is counted here on a flat channel exactly as the hardware shows
    it, because the census must not depend on there being a waveform
    underneath - A1 is unconnected and it is where the signature was
    first seen cleanly.
    """
    v = [MID] * 100_000
    hits = list(range(444, len(v), TABLE))
    for i in hits:
        v[i] |= 0x40
    c = measure.level_census(v)
    assert c["count"] == 2 * len(hits)
    assert c["max_step"] >= 64


def test_a_splice_is_not_periodic_and_the_issue_5_signature_is():
    """The discrimination the suite rests on. A splice is one event; the
    open device artifact is a metronome at the DAC table length, and only
    the second may be excused."""
    v = staircase()
    once = measure.level_census(v[:100_000] + v[133_337:])
    assert once["count"] == 1
    assert not once["periodic"]

    # The shape the board actually produces: a staircase with one sample
    # displaced once per DAC table wrap.
    w = staircase(noise=2)
    for i in range(444, len(w), TABLE):
        w[i] |= 0x40
    metronome = measure.level_census(w)
    assert metronome["periodic"], metronome
    assert metronome["period"] == TABLE, metronome


def test_the_threshold_sits_in_an_empty_gap():
    """The census reports the void it is judging in, so a later board
    that narrows it shows the number to move instead of hiding it."""
    lo, hi = measure.level_census(staircase(noise=2))["gap"]
    assert lo <= measure.STEP_SPLICE_CODES <= hi
    assert hi - lo >= 4


def test_a_flat_line_and_an_empty_series_are_not_errors():
    assert measure.level_census([])["count"] == 0
    assert measure.level_census([MID] * 1000)["count"] == 0
    assert measure.level_steps([MID]) == []


# ---------------------------------------------------------------------
# The flat-channel census
#
# measure.flat_census() exists because the tests above are not enough.
# They pin the signature at +64 codes, which is what Windows reported and
# which level_census() sees comfortably at STEP_SPLICE_CODES = 45. On
# macOS the same signature arrives at 26-32 codes, under that threshold,
# and tools/splices.py reported 0 splices for ten runs while six runs in
# ten were displacing samples on A1. The instrument said "does not
# reproduce" about a board that was reproducing it.
# ---------------------------------------------------------------------

MACOS_DEV = 29                   # 26-32 measured; the middle of it


def flat(n=100_000, level=2055, noise=1, dev=0, first=318, period=TABLE):
    """A1 under preset `M`: DC 2048 out of DAC1, so a flat line plus ADC
    noise, optionally with one sample displaced every `period`."""
    rng = random.Random(20260825)
    v = [level + rng.randint(-noise, noise) for _ in range(n)]
    if dev:
        for i in range(first, n, period):
            v[i] += dev
    return v


def test_a_flat_line_has_no_events():
    c = measure.flat_census(flat())
    assert c["count"] == 0
    assert c["max_dev"] < measure.FLAT_DEV_CODES


def test_the_macos_signature_is_counted_once_per_occurrence():
    """+29 codes, once per DAC table wrap. Counted once per event, not
    twice: unlike the staircase census this measures deviation from the
    median rather than steps between levels, so one displaced sample is
    one crossing."""
    n = 100_000
    c = measure.flat_census(flat(n=n, dev=MACOS_DEV))
    assert c["count"] == len(range(318, n, TABLE)), c
    assert c["periodic"] and c["period"] == TABLE, c


def test_the_staircase_census_cannot_see_the_macos_signature():
    """The regression this pair of instruments exists to prevent.

    Not an assertion about what level_census() *should* do - it is
    judging steps against a 38-code DAC staircase and 29 is honestly
    below that. It is a record of why censusing A0 alone is not an
    answer, so that "splices.py reported zero" is never again read as
    "the board is clean".
    """
    v = flat(dev=MACOS_DEV)
    assert measure.level_census(v)["count"] == 0
    assert measure.flat_census(v)["count"] > 0


def test_the_windows_signature_is_seen_by_both():
    v = flat(dev=64)
    assert measure.level_census(v)["count"] > 0
    assert measure.flat_census(v)["count"] > 0


def test_the_flat_threshold_sits_in_an_empty_gap():
    lo, hi = measure.flat_census(flat(dev=MACOS_DEV))["gap"]
    assert lo <= measure.FLAT_DEV_CODES <= hi
    assert hi - lo >= 4


def test_a_single_displacement_is_not_periodic():
    """One event is not the device artifact, and must not be excused as
    one however small it is."""
    v = flat()
    v[50_000] += MACOS_DEV
    c = measure.flat_census(v)
    assert c["count"] == 1
    assert not c["periodic"]


def test_an_empty_series_is_not_an_error():
    assert measure.flat_census([])["count"] == 0
    assert measure.flat_census([2055])["count"] == 0


# ------------------------------------------------------- periodic_census

def _flat(n=400_000, sd=0.85, seed=20260825):
    rng = random.Random(seed)
    return [MID + round(rng.gauss(0, sd)) for _ in range(n)]


def test_noise_alone_has_no_period():
    """The whole risk of a periodicity detector: finding structure in a
    long series of nothing. Both observed clean sd values."""
    for sd in (0.85, 1.05):
        c = measure.periodic_census(_flat(sd=sd))
        assert c["count"] == 0, (sd, c)


def test_large_aperiodic_outliers_are_rejected():
    """A splice is big and irregular; this defect is small and regular.
    An instrument that confused the two would be worse than useless."""
    v = _flat()
    rng = random.Random(7)
    for i in rng.sample(range(len(v)), 400):
        v[i] += 30
    assert measure.periodic_census(v)["count"] == 0


def test_a_small_periodic_displacement_is_found():
    """Seven codes, where FLAT_DEV_CODES is 20 and STEP_SPLICE_CODES 45.

    This is the case both fixed thresholds miss and it is the case the
    board spent a whole session in - every capture kept from 2026-08-25
    carries it at 6-7 codes, on runs that were reported clean at the
    time and used as control arms.
    """
    v = _flat()
    for i in range(444, len(v), TABLE):
        v[i] += 7
    c = measure.periodic_census(v)
    assert c["count"] > 700
    assert c["period"] == TABLE
    assert c["regularity"] >= 0.9
    assert 6 <= c["amplitude"] <= 8


def test_it_reports_nothing_rather_than_guessing_under_the_noise():
    """Four codes against sd 0.85 is not recoverable, and saying so is
    the honest answer. A detector that always finds something cannot be
    used to decide whether a board is reproducing."""
    v = _flat()
    for i in range(444, len(v), TABLE):
        v[i] += 4
    assert measure.periodic_census(v)["count"] == 0


def test_the_period_follows_the_table_not_the_threshold():
    """What has never varied across five measured amplitudes on two
    hosts is the period. That is why it is the thing to key on."""
    for table, amp in ((512, 7), (1024, 30), (512, 65)):
        v = _flat()
        for i in range(300, len(v), table):
            v[i] += amp
        c = measure.periodic_census(v)
        assert c["period"] == table, (table, amp, c)


# ---------------------------------------------------------------------
# Bursts. The artifact is not always one sample per wrap: at ADC RC 200
# on macOS each wrap displaces about four samples spaced 64 apart, and
# the gap test cannot see that shape at all - gaps of 64, 64, 64, 320
# put the commonest gap at 0.77 and nothing clears 0.9.
# ---------------------------------------------------------------------


def burst(n=100_000, level=2055, noise=1, dev=68, first=404,
          period=TABLE, spacing=64, per_burst=4):
    rng = random.Random(20260825)
    v = [level + rng.randint(-noise, noise) for _ in range(n)]
    for base in range(first, n, period):
        for j in range(per_burst):
            i = base + j * spacing
            if i < n:
                v[i] += dev
    return v


def test_a_burst_per_wrap_is_found_at_the_wrap_period():
    """Not at 64, which is the commonest gap and the wrong answer: the
    period that matters is the one that tracks GEN_TABLE_LEN."""
    c = measure.periodic_census(burst())
    assert c["count"] > 700, c
    assert c["period"] == TABLE, c
    assert c["regularity"] >= 0.9, c


def test_the_gap_test_alone_would_miss_the_burst():
    """Records why the fallback exists. The commonest gap in a four-event
    burst is 64 and it holds three quarters of them, so a rule that wants
    90% identical gaps rejects a run carrying 3276 events at 68 codes."""
    v = burst()
    at = [i for i, x in enumerate(v) if abs(x - 2055) > 30]
    gaps = [b - a for a, b in zip(at, at[1:])]
    best = max(set(gaps), key=gaps.count)
    assert best == 64
    assert gaps.count(best) / len(gaps) < 0.9


def test_the_burst_period_follows_the_table():
    c = measure.periodic_census(burst(period=2 * TABLE))
    assert c["period"] == 2 * TABLE, c


def test_shift_invariance_does_not_rescue_noise():
    """The fallback runs only when the gap test found nothing, which is
    exactly the state a clean run is in - so it must not turn one into a
    detection."""
    rng = random.Random(7)
    v = [2055 + rng.randint(-1, 1) for _ in range(100_000)]
    assert measure.periodic_census(v)["count"] == 0


def test_shift_invariance_does_not_rescue_aperiodic_outliers():
    rng = random.Random(11)
    v = [2055 + rng.randint(-1, 1) for _ in range(100_000)]
    for i in rng.sample(range(100_000), 400):
        v[i] += 30
    assert measure.periodic_census(v)["count"] == 0


# ---------------------------------------------------------------------
# Folding. Every detector above decides which samples are events, and
# each went blind when the amplitude crossed its line. fold_profile()
# decides nothing: it averages the run at a period it is told, so a
# displacement far under the per-sample noise still moves the mean of
# the wraps that share its phase.
#
# All seeded. Same numbers every run, on every host.
# ---------------------------------------------------------------------

FOLD_SEED = 20260826


def flat_run(n=200_000, level=2055, noise=1, seed=FOLD_SEED):
    rng = random.Random(seed)
    return [level + rng.randint(-noise, noise) for _ in range(n)], rng


def test_noise_folds_flat_at_both_periods():
    """512 bins give noise 512 chances to throw up a peak, so a clean run
    sits near 3.2 either way. FOLD_Z_DIRTY is set clear of that."""
    v, _ = flat_run()
    f = measure.fold_profile(v)
    assert f["z"] < measure.FOLD_Z_DIRTY
    assert f["control_z"] < measure.FOLD_Z_DIRTY


def test_a_displacement_far_under_every_threshold_is_found():
    """One code on 40% of wraps - 0.4 codes averaged, against detectors
    that draw their lines at 20 and 45. This is the whole point of the
    instrument, and the reason "presence may be constant" is answerable
    at all."""
    v, rng = flat_run()
    first = 300
    for i in range(first, len(v), TABLE):
        if rng.random() < 0.4:
            v[i] += 1
    f = measure.fold_profile(v)
    assert f["z"] > measure.FOLD_Z_DIRTY, f["z"]
    assert f["peak_phase"] == first % TABLE
    assert 0.3 < f["peak"] < 0.5
    # and neither threshold instrument sees anything at all
    assert measure.periodic_census(v)["count"] == 0
    assert measure.flat_census(v)["count"] == 0


def test_the_control_period_stays_quiet_when_the_real_one_fires():
    v, _ = flat_run()
    for i in range(300, len(v), TABLE):
        v[i] += 4
    f = measure.fold_profile(v)
    assert f["z"] > 10 * f["control_z"], f


def test_folding_at_the_wrong_period_finds_nothing():
    """Folding a locked signal at a period it is not locked to smears it
    across bins, which is what makes control_z a control."""
    v, _ = flat_run()
    for i in range(300, len(v), TABLE):
        v[i] += 4
    assert measure.fold_profile(v, period=TABLE + 1)["z"] \
        < measure.FOLD_Z_DIRTY


def test_aperiodic_outliers_do_not_fold():
    """Four hundred large displacements at random positions. Bigger than
    anything above and they must still read as nothing, because they are
    not locked to a phase."""
    v, rng = flat_run()
    for i in rng.sample(range(len(v)), 400):
        v[i] += 30
    assert measure.fold_profile(v)["z"] < measure.FOLD_Z_DIRTY


def test_a_burst_folds_at_the_wrap_period():
    """The shape that defeated the gap test folds like anything else -
    the instrument has no opinion about how many samples an event is."""
    f = measure.fold_profile(burst(n=200_000), period=TABLE)
    assert f["z"] > measure.FOLD_Z_DIRTY


def test_it_is_deterministic():
    """Same samples in, same numbers out - the property the harness
    depends on, since a verdict that moves between runs of the same data
    cannot gate an A/B."""
    v, _ = flat_run()
    for i in range(300, len(v), TABLE):
        v[i] += 3
    a = measure.fold_profile(v)
    b = measure.fold_profile(list(v))
    assert (a["z"], a["peak"], a["peak_phase"]) == \
           (b["z"], b["peak"], b["peak_phase"])


def test_a_short_run_is_not_an_error():
    assert measure.fold_profile([2055] * 100)["z"] == 0.0


# ---------------------------------------------------------------------
# Curvature. fold_profile()'s `z` assumes the folded profile is flat
# apart from the artifact, which holds only while A1 is a DC channel.
# `spike_z` subtracts each bin's own neighbours, so a one-bin event
# survives a smooth waveform underneath - and does not survive a
# staircase, which is the limitation that decided a hardware test.
# ---------------------------------------------------------------------


def sine_under(n=200_000, amp=700, period=TABLE, hold=1, spike=0,
               first=300, seed=FOLD_SEED):
    rng = random.Random(seed)
    v = []
    for i in range(n):
        phase = (i % period) // hold
        v.append(round(1668 + amp * math.sin(2 * math.pi * phase
                                             / (period // hold)))
                 + rng.randint(-1, 1))
    if spike:
        for i in range(first, n, period):
            v[i] += spike
    return v


def test_plain_z_is_blind_once_a_waveform_is_folded_in():
    """Why spike_z exists. Pull the DAC1 jumper and the floating input
    follows A0's sine through the multiplexer; the profile becomes the
    waveform and peak/MAD goes to 1 whether or not anything is there."""
    f = measure.fold_profile(sine_under(spike=4))
    assert f["z"] < 2.0
    assert f["spike_z"] > f["z"]


def test_a_spike_on_a_smooth_waveform_is_found_by_curvature():
    f = measure.fold_profile(sine_under(spike=4))
    assert f["spike_phase"] == 300 % TABLE
    assert f["spike"] > 3.0


def test_curvature_reports_nothing_on_a_waveform_alone():
    assert measure.fold_profile(sine_under())["spike_z"] < 2.0


def test_curvature_cannot_see_through_a_staircase():
    """The limitation, recorded because it decided an experiment.

    A0 carries gen's staircase - each DAC level held two ADC samples -
    so its folded profile has a large second difference at every step
    and a one-bin event does not stand out. A 40-code spike scores 1.4.
    So A0 cannot serve as the positive control for a jumper test, and
    the flat channel has to be made flat by other means rather than left
    floating.
    """
    quiet = measure.fold_profile(sine_under(amp=1371, hold=2))
    loud = measure.fold_profile(sine_under(amp=1371, hold=2, spike=40))
    assert quiet["spike_z"] < 2.0
    assert loud["spike_z"] < 2.0


def test_curvature_matches_plain_z_on_a_flat_channel():
    """The subtraction takes nothing away when there is nothing to take:
    on a DC channel both statistics find the same event."""
    v, _ = flat_run()
    for i in range(300, len(v), TABLE):
        v[i] += 4
    f = measure.fold_profile(v)
    assert f["spike_phase"] == f["peak_phase"]
    assert f["spike_z"] > measure.FOLD_Z_DIRTY


# ---------------------------------------------------------------------
# pair_fold: the staircase channel. A0 holds each DAC level for two ADC
# samples, so folding it directly measures the waveform; differencing
# within the pair cancels the waveform and keeps the event.
# ---------------------------------------------------------------------


def staircase_pairs(n=200_000, amp=1371, spike=0, first=300, period=TABLE,
                    seed=FOLD_SEED, hold=2):
    rng = random.Random(seed)
    v = []
    for i in range(n):
        lvl = (i % period) // hold
        v.append(round(2048 + amp * math.sin(2 * math.pi * lvl
                                             / (period // hold)))
                 + rng.randint(-1, 1))
    if spike:
        for i in range(first, n, period):
            v[i] += spike
    return v


def test_pair_fold_finds_what_folding_a_staircase_cannot():
    v = staircase_pairs(spike=40)
    assert measure.fold_profile(v)["spike_z"] < 2.0      # the reason it exists
    f = measure.pair_fold(v)
    assert f["hold_ok"], f["pair_spread"]
    assert f["z"] > measure.FOLD_Z_DIRTY
    assert abs(f["peak"]) > 30


def test_pair_fold_is_quiet_on_a_clean_staircase():
    f = measure.pair_fold(staircase_pairs())
    assert f["hold_ok"]
    assert f["z"] < measure.FOLD_Z_DIRTY


def test_pair_fold_refuses_when_the_pairing_is_broken():
    """The two samples of a level are only a level while the DAC and ADC
    rates are locked. Held for one sample instead of two, the difference
    is a DAC step and the result must not be read."""
    f = measure.pair_fold(staircase_pairs(hold=1, spike=40))
    assert not f["hold_ok"]
    assert f["pair_spread"] > 4.0
