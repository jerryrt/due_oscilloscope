"""tools/rp2040_uf2.py: the UF2 layout, the round trip, and the parser against the vendor's own UF2 file for the 250M module when it is on this machine (the skip says so)."""
import os, struct, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "targets", "h7tool", "tools", "rp2040_uf2.py")
sys.path.insert(0, os.path.dirname(TOOL))
import rp2040_uf2 as uf

VENDOR = os.path.expanduser("~/MCU.Projects/h7tool_backup/stock_release_files/")


def test_a_block_has_the_uf2_layout():
    u = uf.bin_to_uf2(bytes(range(256)) * 2 + b"abc")
    assert len(u) == 3 * 512
    m0, m1, flags, addr, size, no, total, fam = struct.unpack_from("<IIIIIIII", u, 512)
    assert (m0, m1, flags, addr, size, no, total, fam) == (0x0A324655, 0x9E5D5157, 0x2000, 0x10000100, 256, 1, 3, 0xE48BFF56)
    assert u[512 + 32:512 + 32 + 256] == bytes(range(256))
    assert struct.unpack_from("<I", u, 512 + 508)[0] == 0x0AB16F30
    assert u[2 * 512 + 32:2 * 512 + 35] == b"abc" and u[2 * 512 + 35:2 * 512 + 32 + 256] == b"\xff" * 253       # a short tail is padded with 0xFF


def test_the_round_trip_returns_the_image_padded_to_a_whole_payload():
    data = bytes((i * 7) & 255 for i in range(1000))
    base, back = uf.uf2_to_bin(uf.bin_to_uf2(data))
    assert base == 0x10000000 and back[:1000] == data and back[1000:] == b"\xff" * (1024 - 1000)


def test_blocks_are_placed_by_address_and_gaps_read_as_erased():
    a = uf.bin_to_uf2(b"A" * 256, base=0x10000000); b = uf.bin_to_uf2(b"B" * 256, base=0x10000400)
    base, back = uf.uf2_to_bin(a + b)
    assert base == 0x10000000 and back[:256] == b"A" * 256 and back[256:0x400] == b"\xff" * (0x400 - 256) and back[0x400:0x500] == b"B" * 256


@pytest.mark.parametrize("damage, why", [
    (lambda u: u[:100], "a truncated file"),
    (lambda u: struct.pack("<I", 0) + u[4:], "the first magic"),
    (lambda u: u[:508] + struct.pack("<I", 0) + u[512:], "the closing magic"),
    (lambda u: u[:28] + struct.pack("<I", 0x12345678) + u[32:], "another family's block"),
])
def test_damaged_files_are_refused(damage, why):
    with pytest.raises(ValueError):
        uf.uf2_to_bin(damage(uf.bin_to_uf2(b"x" * 300)))


@pytest.mark.skipif(not os.path.exists(VENDOR + "DSO_250M（V1.04）.uf2"), reason="the vendor's 250M module files are not on this machine; this skip is NOT a pass")
def test_the_vendors_own_uf2_parses_to_the_vendors_own_bin():
    base, data = uf.uf2_to_bin(open(VENDOR + "DSO_250M（V1.04）.uf2", "rb").read())
    vendor_bin = open(VENDOR + "DSO_250M（V1.04）.bin", "rb").read()
    assert base == 0x10000000 and data[:len(vendor_bin)] == vendor_bin


@pytest.mark.parametrize("old, new, what", [
    ('FLAG_FAMILY = 0x00002000', 'FLAG_FAMILY = 0x00000000', "family flag"),
    ("base + i * PAYLOAD, PAYLOAD, i, n, family", "base + i * PAYLOAD, PAYLOAD, i + 1, n, family", "block numbering"),
    ("out[a - base:a - base + len(d)] = d", "out[a - base + 1:a - base + 1 + len(d)] = d", "placement"),
    ("RP2040_FAMILY, FLASH_BASE, PAYLOAD = 0xE48BFF56", "RP2040_FAMILY, FLASH_BASE, PAYLOAD = 0xE48BFF57", "family id"),
])
def test_a_fault_in_the_converter_is_caught(tmp_path, old, new, what):
    import importlib.util
    src = open(TOOL, encoding="utf-8").read()
    assert src.count(old) == 1, what
    p = tmp_path / "uf2_mut.py"; p.write_text(src.replace(old, new), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("uf2_mut", str(p)); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    ok = True
    try:
        u = m.bin_to_uf2(bytes(range(256)) * 2)
        m0, m1, flags, addr, size, no, total, fam = struct.unpack_from("<IIIIIIII", u, 512)
        ok = (flags, no, fam) == (0x2000, 1, 0xE48BFF56) and m.uf2_to_bin(u)[1] == bytes(range(256)) * 2
        a = m.bin_to_uf2(b"A" * 256); b = m.bin_to_uf2(b"B" * 256, base=0x10000400)
        ok = ok and m.uf2_to_bin(a + b)[1][0x400:0x500] == b"B" * 256
    except Exception:
        ok = False
    assert not ok, what
