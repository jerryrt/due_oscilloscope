"""The daemon's framing, tested without a socket, a thread or a board.

Everything here is pure: bytes in, messages out. That is the point of
keeping `daemon/protocol.py` free of I/O - the layer a whole front end
depends on can be exercised exhaustively in milliseconds, including the
cases a socket produces rarely and at the worst moment.
"""

import json
import random

import pytest

from daemon import device as devmod
from daemon import protocol as proto

pytestmark = pytest.mark.smoke


def test_header_is_eight_bytes_and_starts_with_the_magic():
    msg = proto.encode(proto.T_CMD, b"x")
    assert proto.HDR_LEN == 8
    assert msg[:2] == proto.MAGIC
    assert len(msg) == 8 + 1


@pytest.mark.parametrize("mtype", sorted(proto.TYPE_NAMES))
def test_every_type_round_trips(mtype):
    body = b"\x00\xff" * 17
    dec = proto.Decoder()
    assert dec.feed(proto.encode(mtype, body)) == [(mtype, body)]


def test_empty_body_is_a_message_not_a_nothing():
    dec = proto.Decoder()
    assert dec.feed(proto.encode(proto.T_EVT, b"")) == [(proto.T_EVT, b"")]


def test_json_round_trips_with_nesting_and_unicode():
    obj = {"op": "start", "rates": {"adc_hz": 200000}, "note": "µs ± 1"}
    dec = proto.Decoder()
    (mtype, body), = dec.feed(proto.encode_json(proto.T_CMD, obj))
    assert mtype == proto.T_CMD
    assert proto.decode_json(body) == obj


def test_json_is_compact_on_the_wire():
    """Not cosmetic: at a few hundred events a second the separators
    are the difference between a small message and a padded one."""
    body = proto.encode_json(proto.T_EVT, {"a": 1, "b": 2})[proto.HDR_LEN:]
    assert b", " not in body and b": " not in body


@pytest.mark.parametrize("body", [b"[]", b'"a string"', b"3", b"null"])
def test_a_json_body_that_is_not_an_object_is_refused(body):
    with pytest.raises(proto.ProtocolError):
        proto.decode_json(body)


def test_invalid_json_and_invalid_utf8_are_refused():
    with pytest.raises(proto.ProtocolError):
        proto.decode_json(b"{not json")
    with pytest.raises(proto.ProtocolError):
        proto.decode_json(b'{"k": "\xff\xfe"}')


def test_encoding_an_unknown_type_is_refused():
    with pytest.raises(proto.ProtocolError):
        proto.encode(99, b"")


def test_encoding_an_oversize_body_is_refused():
    with pytest.raises(proto.ProtocolError):
        proto.encode(proto.T_AWG, b"\x00" * (proto.MAX_BODY + 1))


def test_a_message_arriving_one_byte_at_a_time_still_arrives():
    msg = proto.encode_json(proto.T_CMD, {"op": "ping", "id": 7})
    dec = proto.Decoder()
    out = []
    for i in range(len(msg)):
        out += dec.feed(msg[i:i + 1])
        if i < len(msg) - 1:
            assert dec.pending > 0
    assert len(out) == 1
    assert proto.decode_json(out[0][1])["id"] == 7


@pytest.mark.parametrize("split", range(1, 20))
def test_any_split_point_reassembles(split):
    stream = b"".join(proto.encode_json(proto.T_CMD, {"op": "ping", "id": i})
                      for i in range(4))
    dec = proto.Decoder()
    out = []
    for i in range(0, len(stream), split):
        out += dec.feed(stream[i:i + split])
    assert [proto.decode_json(b)["id"] for _, b in out] == [0, 1, 2, 3]


def test_several_messages_in_one_chunk_all_come_out():
    stream = (proto.encode(proto.T_FRAME, b"a" * 10) +
              proto.encode(proto.T_EVT, b"{}") +
              proto.encode(proto.T_AWG, b"b" * 3))
    dec = proto.Decoder()
    got = dec.feed(stream)
    assert [t for t, _ in got] == [proto.T_FRAME, proto.T_EVT, proto.T_AWG]
    assert dec.pending == 0


def test_a_bad_magic_fails_loudly_rather_than_hunting_for_the_next_one():
    """A stream that has lost framing has already produced an unknown
    amount of garbage. Resynchronising invents structure."""
    dec = proto.Decoder()
    with pytest.raises(proto.ProtocolError) as e:
        dec.feed(b"XX" + proto.encode(proto.T_EVT, b"{}")[2:])
    assert "magic" in str(e.value)


def test_an_unknown_type_in_the_header_is_refused():
    good = bytearray(proto.encode(proto.T_EVT, b"{}"))
    good[2] = 77
    with pytest.raises(proto.ProtocolError):
        proto.Decoder().feed(bytes(good))


def test_an_oversize_declared_length_is_refused_before_it_is_believed():
    """The check is on the declared length, not on what arrived: the
    point is to refuse to wait for - or allocate - four gigabytes
    because a header said so."""
    hdr = proto.HDR.pack(proto.MAGIC, proto.T_AWG, 0, 0xFFFFFFFF)
    dec = proto.Decoder()
    with pytest.raises(proto.ProtocolError) as e:
        dec.feed(hdr)
    assert "limit" in str(e.value)


def test_a_device_frame_crosses_the_wire_byte_identical():
    """The property the whole design rests on: what the device sent is
    what the client parses, so continuity stays provable."""
    dev = devmod.FakeDevice()
    dev.start("capture", adc_hz=200000, channels=2)
    frame = dev.read()
    dec = proto.Decoder()
    (mtype, body), = dec.feed(proto.encode(proto.T_FRAME, frame))
    assert mtype == proto.T_FRAME
    assert body == frame
    assert body[:4] == devmod.FRAME_MAGIC
    assert len(body) == devmod.FRAME_BYTES


def test_random_chunking_of_a_long_stream_is_stable():
    rnd = random.Random(20260822)
    msgs = []
    for i in range(50):
        if i % 3 == 0:
            msgs.append(proto.encode(proto.T_FRAME, bytes([i]) * 4096))
        else:
            msgs.append(proto.encode_json(proto.T_EVT, {"event": "n", "i": i}))
    stream = b"".join(msgs)
    dec = proto.Decoder()
    out = []
    i = 0
    while i < len(stream):
        n = rnd.randint(1, 5000)
        out += dec.feed(stream[i:i + n])
        i += n
    assert len(out) == 50
    assert dec.pending == 0
    assert b"".join(proto.encode(t, b) for t, b in out) == stream


def test_the_protocol_version_is_declared_once():
    """Two copies of a version number is one copy too many."""
    from daemon import PROTOCOL_VERSION
    assert PROTOCOL_VERSION == proto.PROTOCOL_VERSION
    assert isinstance(proto.PROTOCOL_VERSION, int)
