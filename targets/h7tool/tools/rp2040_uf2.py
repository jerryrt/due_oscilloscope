"""Convert between a flat RP2040 flash image and UF2, the drag-and-drop format of its USB boot drive (docs/24).

    python3 targets/h7tool/tools/rp2040_uf2.py to-uf2 image.bin out.uf2 [--length N]    # image starts at 0x10000000; --length keeps only the first N bytes
    python3 targets/h7tool/tools/rp2040_uf2.py to-bin in.uf2 out.bin                      # blocks placed by their target address; gaps filled with 0xFF

UF2 blocks are 512 bytes: three magic words, flags, target address, payload size, block number, block count, family id, 476 bytes of data, a closing magic. The RP2040
family id is 0xE48BFF56. Nothing here touches a device."""
import struct, sys

MAGIC0, MAGIC1, MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30
FLAG_FAMILY = 0x00002000
RP2040_FAMILY, FLASH_BASE, PAYLOAD = 0xE48BFF56, 0x10000000, 256


def bin_to_uf2(data, base=FLASH_BASE, family=RP2040_FAMILY):
    n = (len(data) + PAYLOAD - 1) // PAYLOAD
    out = bytearray()
    for i in range(n):
        chunk = bytes(data[i * PAYLOAD:(i + 1) * PAYLOAD]).ljust(PAYLOAD, b"\xff")
        out += struct.pack("<IIIIIIII", MAGIC0, MAGIC1, FLAG_FAMILY, base + i * PAYLOAD, PAYLOAD, i, n, family) + chunk.ljust(476, b"\0") + struct.pack("<I", MAGIC_END)
    return bytes(out)


def uf2_to_bin(uf2, family=RP2040_FAMILY):
    """Returns (base address, flat bytes) of the blocks of this family; raises ValueError on a block that is not UF2 or has a wrong family or a gap-free overlap."""
    if len(uf2) % 512: raise ValueError("a UF2 file is a whole number of 512-byte blocks")
    blocks = {}
    for off in range(0, len(uf2), 512):
        m0, m1, flags, addr, size, no, total, fam = struct.unpack_from("<IIIIIIII", uf2, off)
        if m0 != MAGIC0 or m1 != MAGIC1 or struct.unpack_from("<I", uf2, off + 508)[0] != MAGIC_END: raise ValueError("block %d is not a UF2 block" % (off // 512))
        if flags & FLAG_FAMILY and fam != family: raise ValueError("block %d is for family 0x%08x" % (off // 512, fam))
        if size > 476: raise ValueError("block %d payload too large" % (off // 512))
        blocks[addr] = uf2[off + 32:off + 32 + size]
    base = min(blocks); end = max(a + len(d) for a, d in blocks.items())
    out = bytearray(b"\xff" * (end - base))
    for a, d in blocks.items(): out[a - base:a - base + len(d)] = d
    return base, bytes(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    length = None
    if "--length" in a: i = a.index("--length"); length = int(a[i + 1], 0); del a[i:i + 2]
    if len(a) != 3 or a[0] not in ("to-uf2", "to-bin"): raise SystemExit(__doc__)
    if a[0] == "to-uf2":
        data = open(a[1], "rb").read()
        open(a[2], "wb").write(bin_to_uf2(data[:length] if length else data))
    else:
        base, data = uf2_to_bin(open(a[1], "rb").read())
        open(a[2], "wb").write(data); print("base 0x%08x, %d bytes" % (base, len(data)))
