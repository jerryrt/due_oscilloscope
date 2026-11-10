"""The per-frame channel statistics against the codes put into the stream. Board-free."""
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
    """A stream of random codes, and the codes put on each channel."""
    rng = random.Random(seed)
    out = []
    sent = {t: [] for t in tags}
    for seq in range(1, frames + 1):
        hdr = struct.pack(measure.HDR_FMT, measure.MAGIC, 3, 0, 0x03, seq, measure.hz_for(112), 1000 + seq * 5000, 0, 0, 0)
        hdr = hdr[:measure.HDR_LEN - 4]
        body = bytearray()
        for i in range(measure.FRAME_SAMPLES):
            code = rng.randrange(4096)
            tag = tags[i % len(tags)]
            sent[tag].append(code)
            body += bytes((code & 0xFF, (tag << 4) | (code >> 8)))
        out.append(hdr + struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF) + bytes(body))
    return b"".join(out), sent


def test_the_channel_statistics_are_those_of_the_codes_sent():
    data, sent = _stream(12)
    ps = measure._finish(measure.parse_frames(data))
    for tag, codes in sent.items():
        st = ps.per_channel[tag]
        assert (st.n, st.lo, st.hi) == (len(codes), min(codes), max(codes)), tag
        assert abs(st.mean - sum(codes) / len(codes)) < 1e-9, tag
        assert list(ps.series[tag]) == codes, tag


def test_the_comparison_can_fail():
    """A different stream must give different statistics, so equality above is not vacuous."""
    a = measure._finish(measure.parse_frames(_stream(4, seed=1)[0]))
    b = measure._finish(measure.parse_frames(_stream(4, seed=2)[0]))
    assert {t: (s.lo, s.hi, s.mean) for t, s in a.per_channel.items()} != \
           {t: (s.lo, s.hi, s.mean) for t, s in b.per_channel.items()}
