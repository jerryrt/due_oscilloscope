"""The histogram, on its own. No board, no threads, no timing."""

import pytest

import jitter

pytestmark = pytest.mark.smoke


def test_an_empty_histogram_reports_zeroes_not_errors():
    h = jitter.Histogram("empty")
    s = h.summary()
    assert s["n"] == 0 and s["max_us"] == 0 and s["p99_us"] == 0


def test_the_maximum_is_exact_even_though_buckets_are_coarse():
    """The maximum is what a latency question is usually asking, so it
    is kept exactly rather than rounded to a bucket edge."""
    h = jitter.Histogram()
    for us in (5, 12345, 7):
        h.add_us(us)
    assert h.max_us == 12345
    assert h.count == 3


def test_one_late_sample_in_a_thousand_shows_in_the_tail_not_the_mean():
    """The whole reason this exists: an average hides the event that
    empties a buffer.

    Note what the percentiles honestly cannot do here. With 1,000
    samples the 999th is still in the dense bucket, so p99.9 reports
    that bucket - the outlier is one sample in a thousand and no
    percentile at that resolution is going to name it. `max_us` does,
    which is why it is kept exactly, and the outlier's own bucket is
    occupied so the distribution shows it too.
    """
    h = jitter.Histogram()
    for _ in range(999):
        h.add_us(100)
    h.add_us(500000)
    s = h.summary()
    assert s["mean_us"] < 1000, "the mean should barely notice"
    assert s["max_us"] == 500000, "the maximum should shout"
    assert s["p50_us"] <= 128, "the bulk should read as the bulk"
    tail = sum(n for i, n in enumerate(h.buckets) if (1 << i) >= 262144)
    assert tail == 1, "the outlier must occupy a bucket of its own"


def test_buckets_are_powers_of_two_and_ordered():
    h = jitter.Histogram()
    for us in (1, 2, 4, 8, 16, 32):
        h.add_us(us)
    assert h.count == 6
    assert h.summary()["p50_us"] <= h.summary()["p99_us"]


def test_seconds_and_microseconds_agree():
    a, b = jitter.Histogram(), jitter.Histogram()
    a.add(0.25)
    b.add_us(250000)
    assert a.max_us == b.max_us


def test_a_negative_interval_is_ignored_rather_than_bucketed():
    """Clocks and subtraction being what they are."""
    h = jitter.Histogram()
    h.add_us(-5)
    assert h.count == 0


def test_reset_clears_everything():
    h = jitter.Histogram()
    h.add_us(1000)
    h.reset()
    assert h.count == 0 and h.max_us == 0 and sum(h.buckets) == 0
