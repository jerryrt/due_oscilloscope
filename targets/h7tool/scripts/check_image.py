#!/usr/bin/env python3
"""Apply the H7-TOOL boot loader's acceptance rules to an app .bin.

Rules are from ../h7tool_usb_control/14-firmware-update-procedures.md
(boot loader v2.06, read from disassembly; the SP test and the vector
test are what the loader checks, the size cap is ours).
Exit 0 only if every rule holds.
"""
import struct
import sys

MAX_BYTES = 1_310_720          # 10 x 128 KB; stock V2.33 is 1,292,096
FLASH_APP = 0x08020000


def check(data):
    errs = []
    if len(data) < 24:
        return ["image shorter than 24 bytes (no vectors 0..5)"]
    if len(data) > MAX_BYTES:
        errs.append(f"{len(data)} bytes exceeds {MAX_BYTES}")
    w = struct.unpack_from("<6I", data, 0)
    # boot loader: ((SP + 0x20000) & 0x2FF00000) in {0x20000000, 0x24000000}
    # note: this test also admits 0x30xxxxxx and 0x34xxxxxx aliases of those banks
    if ((w[0] + 0x20000) & 0x2FF00000) not in (0x20000000, 0x24000000):
        errs.append(f"initial SP {w[0]:#010x} fails the loader's DTCM/AXI test")
    for i, v in enumerate(w[1:], 1):
        # loader: byte[2]<0x20 and byte[3]==0x08 of each word, i.e. 0x08xxxxxx below 0x08200000
        if (v >> 24) != 0x08 or ((v >> 16) & 0xFF) >= 0x20:
            errs.append(f"vector {i} = {v:#010x} is not in 0x08000000..0x081FFFFF")
        elif v < FLASH_APP | 1 or not v & 1:
            if i == 1 and not v & 1:
                errs.append(f"reset vector {v:#010x} has no Thumb bit")
            elif v < FLASH_APP:
                errs.append(f"vector {i} = {v:#010x} points into the boot loader")
    return errs


if __name__ == "__main__":
    errs = check(open(sys.argv[1], "rb").read())
    for e in errs:
        print("FAIL:", e)
    print("OK" if not errs else f"{len(errs)} problem(s)")
    sys.exit(1 if errs else 0)
