"""Drive the exploring opcodes of the H7 control function (image 27 and later test images) from the host.

    h7_explore.py peek ADDR [COUNT]          read 32-bit words
    h7_explore.py poke ADDR VALUE [WIDTH]    write 1, 2 or 4 bytes, print the word read back
    h7_explore.py test ID [ARG ...]          run an image-defined test, print its result words (hex)
    h7_explore.py shell                      the same commands, one per line, on one connection

Numbers are decimal or 0x hex. The image refuses what it does not allow (error 0x40). Needs no sudo."""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "host")); sys.path.insert(0, HERE)
import control as ctl
import h7_stream_check as chk


def run(c, words):
    cmd, a = words[0], [int(w, 0) for w in words[1:]]
    if cmd == "peek":
        n = a[1] if len(a) > 1 else 1
        d = c.call(0x45, struct.pack("<IB", a[0], n)).payload
        for i in range(n): print("%08x: %08x" % (a[0] + 4 * i, struct.unpack_from("<I", d, 4 * i)[0]))
    elif cmd == "poke":
        d = c.call(0x46, struct.pack("<IIB", a[0], a[1], a[2] if len(a) > 2 else 4)).payload
        print("%08x" % struct.unpack("<I", d)[0])
    elif cmd == "test":
        d = c.call(0x47, bytes([a[0]]) + b"".join(struct.pack("<I", x & 0xFFFFFFFF) for x in a[1:])).payload
        print(" ".join("%08x" % struct.unpack_from("<I", d, 1 + 4 * i)[0] for i in range((len(d) - 1) // 4)))
    else:
        raise SystemExit(__doc__)


def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    with ctl.Control(chk.find_port(2)) as c:
        if sys.argv[1] == "shell":
            for line in sys.stdin:
                if line.strip():
                    try: run(c, line.split())
                    except ctl.ControlError as e: print("refused:", e)
        else:
            run(c, sys.argv[1:])


if __name__ == "__main__":
    main()
