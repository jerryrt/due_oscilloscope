"""tools/rp2040_picoboot.py: the command it builds, and the property that matters, that it cannot send anything but reads. No USB: a fake
device records what would have gone on the bus."""
import os, struct, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "targets", "h7tool", "tools"))
import rp2040_picoboot as pb


class FakeDev:
    def __init__(self): self.written = []
    def write(self, ep, data, timeout=None): self.written.append((ep, bytes(data)))
    def read(self, ep, n, timeout=None): return bytes(n if n != 64 else 0)


def test_the_read_command_is_the_32_bytes_the_boot_rom_expects():
    c = pb.pack_command(pb.PC_READ, 7, struct.pack("<II", 0x10000000, 4096), 4096, 8)
    assert len(c) == 32
    assert struct.unpack_from("<IIBBHI", c) == (0x431FD10B, 7, 0x84, 8, 0, 4096)
    assert c[16:24] == struct.pack("<II", 0x10000000, 4096) and c[24:] == bytes(8)


@pytest.mark.parametrize("cid", [0x01, 0x02, 0x03, 0x05, 0x08, 0x09, 0x0A, 0x8A, 0x8B, 0x00, 0xFF])
def test_nothing_that_erases_writes_executes_or_reboots_reaches_the_bus(cid):
    dev = FakeDev(); p = pb.Pico(dev, 3, 0x84, 1)
    with pytest.raises(ValueError):
        p.cmd(cid)
    assert dev.written == []


def test_the_three_allowed_commands_do_go_out_and_each_read_is_one_chunk_at_most():
    dev = FakeDev(); p = pb.Pico(dev, 3, 0x84, 1)
    p.xip_for_reading()
    assert [struct.unpack_from("<I", d, 0)[0] for _, d in dev.written] == [0x431FD10B] * 2
    assert [d[8] for _, d in dev.written] == [0x06, 0x07]
    assert len(p.read(0x10000000, 256)) == 256
    with pytest.raises(ValueError):
        p.read(0x10000000, 8192)


def test_the_allowed_set_is_exactly_exit_xip_enter_xip_and_read():
    assert pb.READ_ONLY == {0x06, 0x07, 0x84}
