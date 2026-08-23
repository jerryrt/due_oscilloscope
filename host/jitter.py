"""Latency histograms for the streaming paths.

Every failure in this project so far has been a latency failure at a
moment when a buffer was empty, not a throughput failure - and an
average hides exactly that. A handful of late wakeups per second
vanishes into a mean and shows instantly in a maximum, which is why
this records the maximum and a spread rather than a rate.

Log-2 buckets in microseconds, so one counter covers a microsecond and
a second without choosing a scale in advance. The percentiles it
reports are bucket boundaries, not exact values: the point is to see
that the tail moved, not to quote three significant figures at it.

Stdlib only, and cheap enough for a real-time loop: one monotonic read
and one integer increment per sample.
"""

from __future__ import annotations

import math
import threading

# 0..25 covers 1 us to about 33 s.
N_BUCKETS = 26


class Histogram:
    """Latency samples in log-2 microsecond buckets."""

    def __init__(self, name=""):
        self.name = name
        self.buckets = [0] * N_BUCKETS
        self.count = 0
        self.total_us = 0
        self.max_us = 0
        self._lock = threading.Lock()

    def add_us(self, us):
        if us < 0:
            return
        i = 0 if us < 1 else min(int(math.log2(us)) + 1, N_BUCKETS - 1)
        # Single-writer paths do not need the lock, but a histogram
        # shared by two threads would lose counts without the GIL, and
        # this is cheap next to what it measures.
        with self._lock:
            self.buckets[i] += 1
            self.count += 1
            self.total_us += us
            if us > self.max_us:
                self.max_us = us

    def add(self, seconds):
        self.add_us(int(seconds * 1e6))

    def _quantile(self, q):
        """An upper bound for the quantile, in microseconds.

        Nearest-rank over the buckets, reporting the bucket's upper
        edge, so `p99_us` reads as "99% of samples were at most this".
        It is a bound rather than a value - with 1,000 samples, p99.9 is
        the 999th of them, and a single outlier above it shows in
        `max_us`, which is kept exactly for that reason.
        """
        if not self.count:
            return 0
        want = q * self.count
        seen = 0
        for i, n in enumerate(self.buckets):
            seen += n
            if seen >= want:
                return 1 << i
        return self.max_us

    def summary(self):
        return {
            "n": self.count,
            "max_us": self.max_us,
            "mean_us": round(self.total_us / self.count, 1) if self.count
            else 0,
            "p50_us": self._quantile(0.50),
            "p99_us": self._quantile(0.99),
            "p999_us": self._quantile(0.999),
        }

    def reset(self):
        with self._lock:
            self.buckets = [0] * N_BUCKETS
            self.count = 0
            self.total_us = 0
            self.max_us = 0

    def __repr__(self):
        s = self.summary()
        return (f"<{self.name or 'jitter'} n={s['n']} max={s['max_us']}us "
                f"p99={s['p99_us']}us>")
