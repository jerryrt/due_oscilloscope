import struct, sys, zlib, os
sys.path.insert(0, os.path.dirname(__file__))
import h7_stream_check as c


def frame(seq, payload=None):
    h = struct.pack("<4sBBHIIIII", c.MAGIC, 4, 0, 1, seq, 1000000, 0, 0, 0)
    return h + struct.pack("<I", zlib.crc32(h) & 0xFFFFFFFF) + (payload or c.PAYLOAD)


def stream(seqs):
    return b"".join(frame(s) for s in seqs)


def test_clean_stream():
    r = c.analyse(stream(range(10)))
    assert r["clean"] and r["frames"] == 10 and r["lost"] == 0


def test_dropped_frame_is_a_gap():
    r = c.analyse(stream([0, 1, 2, 4, 5]))
    assert not r["clean"] and r["gaps"] == 1 and r["lost"] == 1


def test_flipped_payload_byte():
    b = bytearray(stream(range(4))); b[c.FRAME + 100] ^= 1
    r = c.analyse(bytes(b))
    assert not r["clean"] and r["bad_payload"] == 1


def test_flipped_header_byte_is_a_crc_failure():
    b = bytearray(stream(range(4))); b[c.FRAME + 8] ^= 1
    r = c.analyse(bytes(b))
    assert not r["clean"] and r["bad_crc"] == 1


def test_wrong_version_is_flagged():
    r = c.analyse(stream(range(3)), expect_version=3)
    assert not r["clean"] and r["bad_version"] == 3


def test_restart_is_a_run_start_not_a_gap():
    r = c.analyse(stream([0, 1, 2, 0, 1]))
    assert r["clean"] and r["run_starts"] == 1


def test_empty_is_not_clean():
    assert not c.analyse(b"")["clean"]


def test_adc_mode_reports_the_codes_and_does_not_compare_a_pattern():
    p = struct.pack("<%dH" % c.SAMPLES, *([100] * (c.SAMPLES - 1) + [40000]))
    s = b"".join(frame(i, p) for i in range(3))
    assert not c.analyse(s)["clean"]                 # pattern mode: payload differs
    r = c.analyse(s, pattern=False)
    assert r["clean"] and r["lo"] == 100 and r["hi"] == 40000 and r["samples"] == 3 * c.SAMPLES


def test_rate_check_catches_a_converter_that_skips_triggers():
    assert c.rate_ok(5_000_000, 1_000_000, 5.0)
    assert not c.rate_ok(2_500_000, 1_000_000, 5.0)      # half the triggers lost
    assert not c.rate_ok(5_200_000, 1_000_000, 5.0)
