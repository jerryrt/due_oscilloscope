#!/usr/bin/env python3
"""Ask a running H7 image to restart into the stock boot loader over its control function (H7_OP_BOOTLOADER, image 13 and later).

    python3 targets/h7tool/tools/h7_to_bootloader.py

Needs no root and no raw USB access. Exit 0 once the unit has answered "armed"; 2 when no unit is found; 3 when the image has no such
opcode (image 12 and earlier answer CTL_ERR_OPCODE or BUSY) - use the vendor request then (h7_usb_probe.py bootloader, under sudo).
"""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "host"))
import control as ctl
import ports


def main():
    found = ports.find_h7()
    if not found:
        print("no H7 target found (1209:0001 with interfaces 0 and 2)", file=sys.stderr); return 2
    try:
        r = ctl.Control(found[1]).call(0x0044, b"BOOT")
    except ctl.ControlError as e:
        print(f"the image refused: {e}", file=sys.stderr); return 3
    print("armed" if r.payload == b"\x01" else f"unexpected reply {r.payload!r}")
    return 0 if r.payload == b"\x01" else 3


if __name__ == "__main__":
    sys.exit(main())
