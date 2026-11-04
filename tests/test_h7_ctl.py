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


@pytest.fixture(scope="module")
def xlib(tmp_path_factory):
    """The same dispatcher linked with the stub that switches the exploring opcodes on."""
    out = tmp_path_factory.mktemp("h7ctlx") / "ctl_h7x.so"
    src = [os.path.join(ROOT, "targets/h7tool/fw/ctl_h7.c"), os.path.join(HERE, "h7_ctl_stub.c"), os.path.join(HERE, "h7_ctl_explore_stub.c"),
           os.path.join(ROOT, "lib/due_shared/src/crc32.c")]
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


def test_exploring_opcodes_are_absent_unless_the_image_provides_them(lib):
    for op in (0x45, 0x46, 0x47):
        assert call_err(lib, op, b"\0" * 5) == 2             # CTL_ERR_OPCODE, not a body of zeroes


def test_exploring_opcodes_peek_poke_and_explore(xlib):
    f = call(xlib, ctl.OP_CAPABILITY); n, = struct.unpack_from("<H", f.payload)
    assert {0x45, 0x46, 0x47} <= set(struct.unpack_from("<%dH" % n, f.payload, 2))
    assert call(xlib, 0x46, struct.pack("<IIB", 0x1004, 0xA1B2C3D4, 4)).payload == struct.pack("<I", 0xA1B2C3D4)
    assert call(xlib, 0x46, struct.pack("<IIB", 0x1006, 0x55, 1)).payload == struct.pack("<I", 0xA155C3D4)   # one byte, read back whole
    assert call(xlib, 0x45, struct.pack("<IB", 0x1000, 3)).payload == struct.pack("<III", 0, 0xA155C3D4, 0)
    r = call(xlib, 0x47, bytes([1]) + struct.pack("<II", 5, 0x80000000)).payload
    assert r == bytes([1]) + struct.pack("<II", 10, 0)
    assert call(xlib, 0x47, bytes([1])).payload == bytes([1])


def test_exploring_opcodes_refuse_what_the_image_refuses_and_malformed_bodies(xlib):
    assert call_err(xlib, 0x45, struct.pack("<IB", 0x0, 1)) == 0x40            # address outside the stub's memory
    assert call_err(xlib, 0x47, bytes([2])) == 0x40                            # unknown test id
    assert call_err(xlib, 0x45, struct.pack("<IB", 0x1002, 1)) == 3            # unaligned
    assert call_err(xlib, 0x45, struct.pack("<IB", 0x1000, 17)) == 3           # more than 16 words
    assert call_err(xlib, 0x46, struct.pack("<IIB", 0x1001, 0, 2)) == 3        # half word on an odd address
    assert call_err(xlib, 0x46, struct.pack("<IIB", 0x1000, 0, 3)) == 3        # width 3
    assert call_err(xlib, 0x47, bytes([1]) + b"\0" * 5) == 3                   # arguments not whole words
    assert call_err(xlib, 0x47, bytes([1]) + b"\0" * 28) == 3                  # seven arguments


def test_screen_capture_is_absent_unless_the_image_keeps_a_shadow(lib):
    assert call_err(lib, 0x48) == 2                                              # CTL_ERR_OPCODE, not zeroes
    f = call(lib, ctl.OP_CAPABILITY); n, = struct.unpack_from("<H", f.payload)
    assert 0x48 not in set(struct.unpack_from("<%dH" % n, f.payload, 2))


def test_screen_capture_info_and_chunks_reassemble_the_picture(xlib):
    f = call(xlib, ctl.OP_CAPABILITY); n, = struct.unpack_from("<H", f.payload)
    assert 0x48 in set(struct.unpack_from("<%dH" % n, f.payload, 2))
    w, h, fmt, _, total, draws = struct.unpack("<HHBBII", call(xlib, 0x48).payload)
    assert (w, h, fmt, total, draws) == (240, 320, 1, 153600, 41)
    got = bytearray()
    while len(got) < total:
        want = min(440, total - len(got))
        p = call(xlib, 0x48, struct.pack("<IH", len(got), want)).payload
        d, off = struct.unpack_from("<II", p)
        assert (d, off, len(p) - 8) == (41, len(got), want)
        got += p[8:]
    assert bytes(got) == bytes((i * 7 + 3) & 255 for i in range(total))


def test_screen_capture_refuses_what_is_outside_the_picture_or_malformed(xlib):
    assert call_err(xlib, 0x48, struct.pack("<IH", 153600, 2)) == 0x40            # offset at the end
    assert call_err(xlib, 0x48, struct.pack("<IH", 153598, 4)) == 0x40            # runs off the end
    assert call_err(xlib, 0x48, struct.pack("<IH", 0, 441)) == 0x40               # more than a chunk
    assert call_err(xlib, 0x48, struct.pack("<IH", 0, 0)) == 0x40
    assert call_err(xlib, 0x48, b"\0" * 5) == 3                                    # wrong length
    last = call(xlib, 0x48, struct.pack("<IH", 153598, 2)).payload                  # the last two bytes are fine
    assert len(last) == 10


def test_the_screen_tool_turns_the_chunks_into_a_picture(xlib):
    """tools/h7_screen.fetch against the dispatcher: RGB565 big-endian to RGB888, the PNG decodes to the same pixels, and a
    picture that changed while it was read is retried and then refused."""
    sys.path.insert(0, HERE)
    import h7_screen
    import zlib as z

    def via(lib_):
        return lambda op, body: call(lib_, op, body).payload
    w, h, rgb = h7_screen.fetch(via(xlib))
    raw = bytes((i * 7 + 3) & 255 for i in range(240 * 320 * 2))
    v = (raw[0] << 8) | raw[1]
    assert (w, h, len(rgb)) == (240, 320, 240 * 320 * 3)
    assert rgb[0] == ((v >> 11) & 31) << 3 | ((v >> 11) & 31) >> 2 and rgb[2] == (v & 31) << 3 | (v & 31) >> 2
    data = h7_screen.png(w, h, rgb)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
    flat = z.decompress(idat)
    assert len(flat) == h * (1 + w * 3) and flat[1:1 + w * 3] == rgb[:w * 3]
    n = [0]

    def moving(op, body):
        if body and n[0] % 5 == 1: xlib.stub_set_draws(100 + n[0])
        n[0] += 1
        return call(xlib, op, body).payload
    xlib.stub_set_draws(41)
    with pytest.raises(RuntimeError):
        h7_screen.fetch(lambda op, body: (xlib.stub_set_draws(1000 + n[0]) or moving(op, body)) if body else moving(op, body))
    xlib.stub_set_draws(41)
