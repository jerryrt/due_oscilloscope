"""The alias sweep under SOLO: the hold, the fold, and the rate that pairs.

Needs no board. SOLO (issue #83 V1b) writes DAC0 on every DAC trigger, so
the two things the default layout gives the sweep for free - two A0
samples per DAC0 level, and a wrap of GEN_TABLE_LEN samples - both change.
The most likely wrong answer is a sweep that still folds at GEN_TABLE_LEN:
it pairs cleanly, reports hold_ok, and halves every one-entry site by
laying the two halves of the table over each other. The synthetic table
below is built to show exactly that.
"""
import math
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import issue5_alias_sweep as sw  # noqa: E402
import measure  # noqa: E402

SOLO = measure.GEN_SYNCS["solo"]
CYCLE = measure.GEN_SYNCS["cycle"]
ENTRIES = 2 * (measure.GEN_TABLE_LEN // 2)   # SOLO: every entry is DAC0
POINTS = 256                                  # sine period, in entries
SITE_ENTRY = 100
SITE_CODES = -20
WRAPS = 40


def _solo_capture(samples_per_level, seed=1):
    """A0 through a SOLO table, one displaced sample at one entry per wrap."""
    rng = random.Random(seed)
    vals = []
    for _ in range(WRAPS):
        for e in range(ENTRIES):
            level = 2048 + 1500 * math.sin(2 * math.pi * e / POINTS)
            for s in range(samples_per_level):
                v = level + rng.gauss(0, 0.6)
                if e == SITE_ENTRY and s == 0:
                    v += SITE_CODES
                vals.append(round(v))
    return vals


def test_solo_folds_a_whole_table_and_reads_the_site_at_full_height():
    fold = measure.pair_fold(_solo_capture(2), period=sw.fold_len(SOLO))
    assert fold["hold_ok"]
    dev, sites, _, _ = sw.read_profile(fold["profile"])
    assert len(dev) == ENTRIES
    assert sites == [SITE_ENTRY]
    assert dev[SITE_ENTRY] < 0.75 * SITE_CODES


def test_a_default_fold_under_solo_pairs_cleanly_and_halves_the_site():
    """Why fold_len matters: the wrong fold is not refused, it is wrong."""
    fold = measure.pair_fold(_solo_capture(2), period=measure.GEN_TABLE_LEN)
    assert fold["hold_ok"]
    dev, _, _, _ = sw.read_profile(fold["profile"])
    assert 0.35 * SITE_CODES > dev[SITE_ENTRY] > 0.65 * SITE_CODES


def test_solo_at_equal_rates_is_refused_by_the_hold():
    fold = measure.pair_fold(_solo_capture(1), period=sw.fold_len(SOLO))
    assert not fold["hold_ok"]


def test_the_default_layout_is_unchanged():
    assert sw.fold_len(CYCLE) == measure.GEN_TABLE_LEN
    assert sw.fold_len(None) == measure.GEN_TABLE_LEN
    assert sw.bin_clocks(195, None) == 390
    assert sw.predict(195)[1] == 21
    assert sw.predict(195, step=sw.bin_clocks(195, CYCLE)) == sw.predict(195)


def test_solo_at_half_the_rate_writes_dac0_as_cycle_sync_does():
    assert sw.bin_clocks(sw.rc_of(100000), SOLO) == \
        sw.bin_clocks(sw.rc_of(200000), CYCLE) == 390
    cycle_sites, _ = sw.predict(195, step=sw.bin_clocks(195, CYCLE))
    solo_sites, _ = sw.predict(390, step=sw.bin_clocks(390, SOLO),
                               nbins=sw.fold_len(SOLO) // 2)
    assert [b for b in solo_sites if b < 256] == cycle_sites


@pytest.mark.parametrize("spec, expect", [
    ("200000", ("=200000,200000M", 200000, 200000)),
    ("100000:200000", ("=100000,200000M", 100000, 200000)),
])
def test_presets_parse(spec, expect):
    assert sw.parse_preset(spec) == expect


def test_solo_refuses_a_rate_pair_that_cannot_hold():
    sw.check_rates(100000, 200000, SOLO)
    sw.check_rates(200000, 200000, CYCLE)
    with pytest.raises(SystemExit):
        sw.check_rates(200000, 200000, SOLO)


def test_sync_readback_matches_the_firmware_report_and_nothing_near_it():
    report = ("gen shape 0 = sine, 256 pts/cycle, amp 256/256, sync 3 = solo "
              "- DAC0 only, no sync, 2x rate at 256/256")
    assert sw.sync_readback_ok(report, SOLO)
    assert not sw.sync_readback_ok(report, CYCLE)
    assert not sw.sync_readback_ok(report.replace("sync 3", "sync 13"), 1)
    assert sw.sync_code("solo") == SOLO and sw.sync_code("3") == SOLO
    assert sw.sync_code(None) is None
