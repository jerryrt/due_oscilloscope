"""The statistics inside the scope metrics, on synthetic records.

`_rails` is here because its first version was `min(v), max(v)` and that
is what let a clipped record be reported as a 118 µs settling tail. The
whole of the artifact is in one line of arithmetic, so the arithmetic
gets a test that does not need a bench.

Raw extremes have now been the wrong statistic for a long record twice
in this project, in opposite directions: one railed sample in 65,526
read a 2.19 V pin as 3.640 V peak to peak, and one stray sample *above*
a rail hid 53,745 rail samples inside a filter written to exclude them.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))
import dso_metrics as dm  # noqa: E402


def test_a_clipped_record_gives_the_levels_it_rests_on():
    """The measured shape of the artifact: two rails, 48 mV apart, and
    six strays from interpolation between them."""
    v = [2.022] * 53745 + [1.977] * 11775 + [2.025, 1.9878, 2.009,
                                             1.9792, 2.0004, 2.0218]
    assert dm._rails(v) == (1.977, 2.022)


def test_one_stray_above_a_rail_does_not_become_the_rail():
    """The bug, in one case. `max()` returns 2.025, the filter keeps
    everything below 2.0248, and the rail at 2.022 passes as signal."""
    v = [2.022] * 1000 + [1.977] * 1000 + [2.025]
    assert max(v) == 2.025                       # what the old test used
    assert dm._rails(v)[1] == 2.022              # what rests there


def test_a_trace_that_is_entirely_on_screen_keeps_its_extremes():
    """No clipping means no level is common enough to be a rail, and the
    honest answer is the raw extremes - which makes the filter that uses
    these keep essentially everything, as it should."""
    v = [1.0 + i * 1e-6 for i in range(4000)]
    assert dm._rails(v) == (min(v), max(v))


def test_a_level_below_the_share_threshold_is_not_a_rail():
    v = [1.0] * 10000 + [2.0] * 10 + [0.5] * 10
    lo, hi = dm._rails(v, share=0.005)
    assert (lo, hi) == (1.0, 1.0)


def test_a_level_at_the_share_threshold_counts():
    v = [1.0] * 9800 + [2.0] * 100 + [0.5] * 100
    assert dm._rails(v, share=0.005) == (0.5, 2.0)


def test_the_distinct_floor_separates_a_tail_from_a_clipped_level():
    """The backstop, and the reason it does not depend on finding rails:
    a clipped level takes one value however many samples it holds, and a
    real tail at 0.29 codes per screen level takes hundreds."""
    railed = set([2.022, 1.977, 2.025, 1.9878, 2.009, 1.9792])
    tail = set(round(2.0 + 0.0001 * (i % 400), 6) for i in range(65000))
    assert len(railed) < dm.DISTINCT_FLOOR <= len(tail)


@pytest.mark.parametrize("share", [0.001, 0.005, 0.02])
def test_the_artifact_is_caught_at_any_plausible_share(share):
    """A threshold tuned against one capture is how a detector calibrated
    on 600 points found 17,580 edges in a clean sine at 65,526. This one
    must not be that: the separation is four orders of magnitude, so the
    exact value cannot matter."""
    v = [2.022] * 53745 + [1.977] * 11775 + [2.025]
    assert dm._rails(v, share=share) == (1.977, 2.022)
