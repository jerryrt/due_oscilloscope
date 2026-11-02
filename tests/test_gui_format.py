"""The GUI's sample format (docs/20): a Due frame decodes exactly as before, a version-4 frame (16-bit, planar, no tag) decodes
by its header version, and volts come from the device description's per-channel calibration. The module-level format is global
state, so every test that changes it restores the Due's in a finally: a leaked format would make unrelated tests read the wrong scale."""
import struct

import pytest

np = pytest.importorskip("numpy", reason="needs the GUI venv (numpy); a skip here is NOT a pass")
from gui import stream  # noqa: E402

H7_DESC = {"kind": "h7", "track": "h", "frame_bytes": 4096, "samples_per_frame": 2032, "frame_version": 4,
           "sample": {"bits": 16, "layout": "planar", "full_scale_codes": 65535},
           "channels": [{"id": 1, "label": "CH1", "calibration": {"zero_code": 32875.0, "codes_per_volt": 2284.9}},
                        {"id": 2, "label": "CH2", "calibration": {"zero_code": 32854.0, "codes_per_volt": 2280.2}}]}


def frame(version, mask, payload, seq=5, rate=1_000_000):
    return struct.pack(stream.HDR_FMT, b"DUE0", version, 0, mask, seq, rate, 0, 0, 0, 0) + payload


@pytest.fixture
def restore():
    yield
    stream.set_format(stream.DUE_FORMAT)


def test_a_due_frame_decodes_as_it_always_did_and_a_description_without_sample_is_a_due():
    samples = [(7 << 12) | 100, (6 << 12) | 200, (7 << 12) | 101, (6 << 12) | 201]
    f = stream.decode(frame(3, 0xC0, struct.pack("<4H", *samples)))
    assert sorted(f.channels) == [6, 7] and list(f.channels[7]) == [100, 101] and list(f.channels[6]) == [200, 201]
    assert stream.format_from_description({"kind": "board", "track": "b"}) is stream.DUE_FORMAT
    assert stream.LABELS == {7: "A0", 6: "A1"} and stream.FULL_SCALE_CODES == 4095 and (stream.CH_A0, stream.CH_A1) == (7, 6)


def test_a_version_4_frame_is_planar_16_bit_and_keyed_by_channel_id():
    two = struct.pack("<6H", 1000, 1001, 1002, 60000, 60001, 60002)           # CH1 block then CH2 block
    f = stream.decode(frame(4, 0b11, two))
    assert sorted(f.channels) == [1, 2] and list(f.channels[1]) == [1000, 1001, 1002] and list(f.channels[2]) == [60000, 60001, 60002]
    only2 = stream.decode(frame(4, 0b10, struct.pack("<3H", 7, 8, 9)))
    assert list(only2.channels) == [2] and list(only2.channels[2]) == [7, 8, 9]             # the id is the bit's number, not the position
    assert stream.decode(frame(4, 0b11, struct.pack("<5H", 1, 2, 3, 4, 5))) is None        # does not divide into two planes
    assert stream.decode(frame(4, 0, struct.pack("<2H", 1, 2))) is None


def test_the_description_builds_a_format_with_labels_calibration_and_a_bipolar_span(restore):
    fmt = stream.format_from_description(H7_DESC)
    assert fmt.labels == {1: "CH1", 2: "CH2"} and fmt.full_scale == 65535 and fmt.y_lo < -14 and fmt.y_hi > 14
    stream.set_format(fmt)
    assert stream.LABELS == {1: "CH1", 2: "CH2"} and (stream.CH_A0, stream.CH_A1) == (1, 2) and stream.FULL_SCALE_CODES == 65535


def test_volts_use_each_channels_own_zero_and_scale_and_invert(restore):
    stream.set_format(stream.format_from_description(H7_DESC))
    assert abs(float(stream.codes_to_volts(32875, tag=1))) < 1e-6 and abs(float(stream.codes_to_volts(32854, tag=2))) < 1e-6
    assert abs(float(stream.codes_to_volts(32875 + 2284.9, tag=1)) - 1.0) < 1e-3
    assert abs(float(stream.codes_to_volts(32854, tag=1)) - (32854 - 32875) / 2284.9) < 1e-4      # CH1's zero, not CH2's
    for tag in (1, 2):
        assert abs(stream.volts_to_codes(float(stream.codes_to_volts(45000, tag=tag)), tag=tag) - 45000) <= 1


def test_restoring_the_due_format_restores_its_scale_exactly(restore):
    before = float(stream.codes_to_volts(3000))
    stream.set_format(stream.format_from_description(H7_DESC))
    assert float(stream.codes_to_volts(3000)) != before
    stream.set_format(stream.DUE_FORMAT)
    assert float(stream.codes_to_volts(3000)) == before and stream.LABELS == {7: "A0", 6: "A1"} and (stream.CH_A0, stream.CH_A1) == (7, 6)
