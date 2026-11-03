"""The H7 control dispatcher (fw/ctl_h7.c) compiled for the host and driven by the project's own control parser
(host/control.py), so the frames it emits are checked by the code a real host will use. Needs a host C compiler;
without one every test here SKIPS, which is not a pass (docs/testing.md)."""
import ctypes, os, shutil, struct, subprocess, sys, zlib
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "targets", "h7tool", "tools")      # h7_ctl_stub.c lives with the tools
sys.path.insert(0, os.path.join(ROOT, "host"))
import control as ctl

CC = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(CC is None, reason="no host C compiler: this skip is NOT a pass")


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    out = tmp_path_factory.mktemp("h7ctl") / "ctl_h7.so"
    src = [os.path.join(ROOT, "targets/h7tool/fw/ctl_h7.c"), os.path.join(HERE, "h7_ctl_stub.c"), os.path.join(ROOT, "lib/due_shared/src/crc32.c")]
    inc = ["-I" + os.path.join(ROOT, p) for p in ("lib/due_shared/src", "lib/wire", "targets/h7tool/fw")]
    subprocess.run([CC, "-std=gnu11", "-shared", "-fPIC", "-O1", "-Wall", "-Werror=implicit"] + inc + ["-o", str(out)] + src, check=True)
    L = ctypes.CDLL(str(out)); L.ctl_h7_handle.restype = ctypes.c_size_t
    return L


def ask(lib, frame):
    tx = ctypes.create_string_buffer(512)
    n = lib.ctl_h7_handle(ctypes.c_char_p(frame), ctypes.c_size_t(len(frame)), tx)
    return tx.raw[:n]


def call(lib, opcode, payload=b"", req_id=7, **kw):
    reply = ask(lib, ctl.encode(opcode, req_id, payload, **kw))
    f, rest = ctl.decode(reply)
    assert f is not None and rest == b"" and f.crc_ok and f.req_id == req_id and f.opcode == opcode
    return f


def test_ping_identity_and_capability_parse_with_the_hosts_own_parser(lib):
    assert ctl._PING.unpack(call(lib, ctl.OP_PING).payload)[0] == 123456
    (track, cv, fv, ma, mi, pa, fb, fs, mck, adc, build) = ctl._IDENTITY.unpack(call(lib, ctl.OP_IDENTITY).payload)
    assert chr(track) == "H" and cv == ctl.VERSION == 4 and fv == 4 and fb == 4096 and fs == 2032
    assert (ma, mi, pa) == (0, 1, 0) and mck == 200_000_000 and adc == 25_000_000 and build.rstrip(b"\0") == b"h7-build-13"
    f = call(lib, ctl.OP_CAPABILITY); n, = struct.unpack_from("<H", f.payload)
    ops = set(struct.unpack_from("<%dH" % n, f.payload, 2))
    assert ops == {1, 2, 3, 0x20, 0x40, 0x41, 0x42, 0x43, 0x44}


def test_counters_have_the_dues_fifteen_word_layout(lib):
    assert len(call(lib, ctl.OP_COUNTERS).payload) == ctl._COUNTERS.size == 60


def test_config_round_trip_and_range_and_busy(lib):
    f = call(lib, 0x40); assert struct.unpack("<IIBBBBHH", f.payload)[:2] == (200, 800)
    new = struct.pack("<IIBBBBHH", 100, 40, 3, 2, 5, 3, 2036, 0)
    assert struct.unpack("<IIBBBBHH", call(lib, 0x40, new).payload) == (100, 40, 3, 2, 5, 3, 2036, 0)
    assert call_err(lib, 0x40, struct.pack("<IIBBBBHH", 79, 40, 3, 0, 0, 3, 2036, 0)) == 3    # period below the proven 80 ticks
    assert call(lib, 0x41, b"\x01").payload == b"\x01"
    assert call_err(lib, 0x40, new) == 5                      # CTL_ERR_BUSY while running
    assert call(lib, 0x41, b"\x00").payload == b"\x00"


def call_err(lib, opcode, payload=b"", req_id=9, **kw):
    f, _ = ctl.decode(ask(lib, ctl.encode(opcode, req_id, payload, **kw)))
    assert f.is_error and f.crc_ok
    return f.error[0]


def test_status_is_the_documented_72_bytes(lib):
    p = call(lib, 0x43).payload
    assert len(p) == 72
    run, play, timer, mask = p[:4]; frames, lost, sent = struct.unpack_from("<3I", p, 4 + 8)
    assert mask == 3 and (frames, sent, lost) == (1000, 998, 2)


def test_a_bad_crc_version_length_opcode_or_a_non_frame_is_refused_never_acted_on(lib):
    assert call_err(lib, ctl.OP_PING, crc=0xdeadbeef) == 4
    assert call_err(lib, ctl.OP_PING, version=3) == 1
    assert call_err(lib, 0x0999) == 2                          # CTL_ERR_OPCODE: the answer a Due gives to an H7 opcode
    assert call_err(lib, ctl.OP_PING, b"x") == 3
    assert call_err(lib, 0x41, b"\x07") == 3
    assert ask(lib, b"hello world, not a frame at all") == b""
    assert ask(lib, b"") == b""
    f = ctl.encode(ctl.OP_PING, 1)
    assert call_err(lib, ctl.OP_PING, b"\0" * 449) == 3         # over CTL_MAX_PAYLOAD (448)
    assert ask(lib, f[:10]) == b""                              # shorter than a header
    short = ctl.encode(0x40, 1, b"\0" * 16)[:-4]                # header says 16, only 12 bytes follow
    reply, _ = ctl.decode(ask(lib, short)); assert reply.is_error and reply.error[0] == 3


def test_bootloader_request_needs_the_exact_word_and_is_otherwise_refused_without_acting(lib):
    n0 = ctypes.c_int.in_dll(lib, "stub_boot_requests").value
    for body in (b"", b"BOO", b"BOOTS", b"boot", b"BOOK"):
        assert call_err(lib, 0x44, body) == 3                                  # CTL_ERR_LENGTH, and nothing armed
    assert ctypes.c_int.in_dll(lib, "stub_boot_requests").value == n0
    assert call(lib, 0x44, b"BOOT").payload == b"\x01"                        # armed, replied first
    assert ctypes.c_int.in_dll(lib, "stub_boot_requests").value == n0 + 1
