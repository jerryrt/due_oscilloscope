"""Capture the H7-TOOL's display over the control function (H7_OP_SCREEN, images that keep a shadow copy, docs/22).

    h7_screen.py capture.png          read the whole picture and write it as a PNG (also .ppm)

The panel cannot be read back on this board, so what comes back is the driver's copy of everything it has drawn:
valid once the whole screen has been drawn after the shadow was switched on. A capture is repeated up to 3 times if
the draw count moved while it was read, and refused after that rather than returned torn."""
import os, struct, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "host")); sys.path.insert(0, HERE)

OP_SCREEN = 0x48
CHUNK = 440


def fetch(call):
    """call(opcode, payload) -> reply payload. Returns (width, height, rgb888 bytes)."""
    for _ in range(3):
        w, h, fmt, _, total, draws = struct.unpack("<HHBBII", call(OP_SCREEN, b""))
        if fmt != 1: raise ValueError("unknown pixel format %d" % fmt)
        raw = bytearray(); torn = False
        while len(raw) < total:
            p = call(OP_SCREEN, struct.pack("<IH", len(raw), min(CHUNK, total - len(raw))))
            d, off = struct.unpack_from("<II", p)
            if off != len(raw): raise ValueError("chunk at %d, wanted %d" % (off, len(raw)))
            if d != draws: torn = True
            raw += p[8:]
        if not torn: return w, h, rgb565_be_to_rgb888(bytes(raw))
    raise RuntimeError("the picture kept changing while it was read")


def rgb565_be_to_rgb888(raw):
    out = bytearray(len(raw) // 2 * 3)
    for i in range(0, len(raw), 2):
        v = (raw[i] << 8) | raw[i + 1]
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        j = i // 2 * 3
        out[j] = (r << 3) | (r >> 2); out[j + 1] = (g << 2) | (g >> 4); out[j + 2] = (b << 3) | (b >> 2)
    return bytes(out)


def png(w, h, rgb):
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def main():
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    import control as ctl, h7_stream_check as chk
    with ctl.Control(chk.find_port(2)) as c:
        w, h, rgb = fetch(lambda op, body: c.call(op, body).payload)
    data = png(w, h, rgb) if sys.argv[1].endswith(".png") else b"P6 %d %d 255\n" % (w, h) + rgb
    with open(sys.argv[1], "wb") as f: f.write(data)
    print("wrote %s (%dx%d)" % (sys.argv[1], w, h))


if __name__ == "__main__":
    main()
