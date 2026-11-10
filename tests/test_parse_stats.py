"""The per-frame channel statistics through numpy against the stdlib builtins. Board-free."""
import os
import random
import struct
import sys
import zlib

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host"))
import measure  # noqa: E402

pytestmark = pytest.mark.smoke


def _stream(frames, seed=7, tags=(0, 1)):
    rng = random.Random(seed)
    out = []
    for seq in range(1, frames + 1):
        hdr = struct.pack(measure.HDR_FMT, measure.MAGIC, 3, 0, 0x03, seq, 402061, 1000 + seq * 5000, 0, 0, 0)
        hdr = hdr[:measure.HDR_LEN - 4]
        body = bytearray()
        for i in range(measure.FRAME_SAMPLES):
            code = rng.randrange(4096)
            body += bytes((code & 0xFF, (tags[i % len(tags)] << 4) | (code >> 8)))
        out.append(hdr + struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF) + bytes(body))
    return b"".join(out)


def _stats(ps):
    return {tag: (st.n, st.lo, st.hi, st.mean) for tag, st in ps.per_channel.items()}


def test_the_numpy_statistics_equal_the_builtin_ones(monkeypatch):
    pytest.importorskip("numpy")
    data = _stream(12)
    monkeypatch.setattr(measure, "_STATS_NUMPY", True)
    fast = measure._finish(measure.parse_frames(data))
    monkeypatch.setattr(measure, "_STATS_NUMPY", False)
    slow = measure._finish(measure.parse_frames(data))
    assert _stats(fast) == _stats(slow)
    assert {t: bytes(v) for t, v in fast.series.items()} == {t: bytes(v) for t, v in slow.series.items()}
    assert len(_stats(fast)) == 2 and all(n > 0 for n, *_ in _stats(fast).values())


def test_the_comparison_can_fail(monkeypatch):
    """A different stream must give different statistics, so equality above is not vacuous."""
    a = measure._finish(measure.parse_frames(_stream(4, seed=1)))
    b = measure._finish(measure.parse_frames(_stream(4, seed=2)))
    assert _stats(a) != _stats(b)
