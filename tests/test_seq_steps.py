"""`seq_steps` must actually see a gap - the control for a null.

Board-free. It exists because a 0-of-40 result on issue #44 is only
worth reading if the instrument that produced it can detect the thing
it reported absent, and nothing else in the suite exercises the gap
path. An instrument that always returns zero returns zero on a healthy
run too, and the two are indistinguishable from the outside.

Builds a synthetic stream with a known hole in the sequence and checks
that the parser reports its position, its size, and the device clock
either side - which is what tells a transport loss from an ordering
fault, and is the whole reason the field was added.
"""
import struct
import sys
import zlib
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import measure

pytestmark = pytest.mark.smoke

PERIOD_US = 5000


def _frame(seq, ts):
    hdr = struct.pack(measure.HDR_FMT[:1] + measure.HDR_FMT[1:],
                      measure.MAGIC, 3, 0, 0x03, seq, 402061, ts, 0, 0, 0)
    hdr = hdr[:measure.HDR_LEN - 4]
    crc = zlib.crc32(hdr) & 0xFFFFFFFF
    return hdr + struct.pack("<I", crc) + b"\x00\x08" * measure.FRAME_SAMPLES


def _stream(seqs):
    return b"".join(_frame(s, 1000 + s * PERIOD_US) for s in seqs)


def test_no_gap_reports_none():
    ps = measure.parse_frames(bytearray(_stream(range(1, 11))))
    assert ps.frames == 10
    assert ps.seq_gaps == 0
    assert not ps.seq_steps


def test_gap_is_located_and_sized():
    # 1..5, then 5 frames missing, then 11..15.
    ps = measure.parse_frames(bytearray(_stream(list(range(1, 6))
                                                + list(range(11, 16)))))
    assert ps.frames == 10
    assert ps.seq_gaps == 1
    assert ps.dropped_frames == 5

    (idx, t0, t1, n_lost), = ps.seq_steps
    assert n_lost == 5
    # 1-based index of the frame that FOLLOWS the gap: five frames
    # arrived, the sixth is the one whose seq jumped. Pinned because
    # "where the gap is" is off by one either way and a reader
    # correlating gap position against run position needs to know
    # which.
    assert idx == 6
    # The device clock across the hole: 6 periods for 5 missing frames.
    assert t1 - t0 == 6 * PERIOD_US


def test_two_gaps_are_kept_separately():
    ps = measure.parse_frames(bytearray(_stream([1, 2, 5, 6, 20])))
    assert ps.seq_gaps == 2
    assert [n for (_i, _a, _b, n) in ps.seq_steps] == [2, 13]
