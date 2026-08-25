#!/usr/bin/env python3
"""Flash a bare-metal .bin to the Due, on any host.

This is the single implementation; tools/flash.sh is a shim onto it and
the CMake `flash` target invokes it. Where the tools live is CMake's
business (cmake/hosttools.cmake, toolchains.json) - it passes --bossac.
Run standalone and this resolves the same registry itself.

The Due enters SAM-BA when the programming port is opened at 1200 baud:
the 16U2 sees the baud change followed by DTR dropping, and asserts ERASE
then RESET. That baud rate is a control signal here, not a data rate.
pyserial performs that identically on every platform, which is why there
is no OS branch in this file.

    python3 tools/flash.py                        # discover everything
    python3 tools/flash.py --port COM7
    python3 tools/flash.py --bin build/x.bin --port /dev/cu.usbmodem14201
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain                                        # noqa: E402

REPO = toolchain.REPO
VID, PID_CONSOLE = 0x2341, 0x003D          # programming port (the 16U2)
SAMBA = (0x03EB, 0x6124)                   # SAM3X ROM bootloader


def find_console(explicit=None):
    """The programming port, by USB VID/PID - identical on every OS."""
    if explicit:
        return explicit
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("needs pyserial to discover the port (pip install pyserial), "
                 "or pass --port")
    hits = [p.device for p in list_ports.comports()
            if p.vid == VID and p.pid == PID_CONSOLE]
    if not hits:
        # Refuse rather than guessing: the 1200-baud touch ERASES whatever
        # port it lands on, and aiming it at the wrong one wipes the flash
        # without writing anything. That has happened once already.
        sys.exit("no programming port found (VID 2341 PID 003D); pass --port")
    if len(hits) > 1:
        sys.exit(f"more than one programming port: {hits}; pass --port")
    return hits[0]


def find_samba():
    """The ROM bootloader, if it is already running.

    Found the hard way: with blank flash the SAM3X boots ROM SAM-BA, which
    enumerates on the NATIVE port as 03EB:6124 - not through the 16U2. So
    after an erase the programming port is the wrong place to look, and
    bossac reports "No device found" on a board that is sitting in the
    bootloader waiting. Check for it before touching anything.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if (p.vid, p.pid) == SAMBA:
            return p.device
    return None


def touch_1200(port):
    import serial
    print(f"==> 1200-baud touch on {port} (erase + reset)")
    s = serial.Serial()
    s.port, s.baudrate = port, 1200
    s.open()
    s.dtr = False                     # the erase+reset trigger
    time.sleep(0.1)
    s.close()
    # The programming port's CDC belongs to the 16U2, which is not itself
    # reset, so the node normally persists. Give it a moment regardless.
    time.sleep(1.5)


def restore_115200(port):
    """Leave sane line coding behind.

    A port left at 1200 re-triggers the 16U2 erase-and-reset on the NEXT
    open, which presents as the board mysteriously restarting whenever a
    tool attaches.
    """
    import serial
    try:
        s = serial.Serial()
        s.port, s.baudrate = port, 115200
        s.open()
        s.close()
    except Exception:                                    # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.path.join(REPO, "build",
                                                  "baremetal_bringup.bin"))
    ap.add_argument("--port", help="programming port; discovered if omitted")
    ap.add_argument("--bossac", help="bossac executable; from the registry "
                                     "if omitted (CMake passes it)")
    args = ap.parse_args()

    binary = os.path.abspath(args.bin)
    if not os.path.isfile(binary):
        sys.exit(f"no such binary: {binary}\nbuild it first: cmake --build build")

    bossac = args.bossac
    if not bossac:
        _, bossac = toolchain.resolve("bossac")
    if not bossac or not os.path.isfile(bossac):
        sys.exit("bossac not found. Add a pattern to toolchains.json, or "
                 "pass --bossac. Run: python3 tools/toolchain.py")

    print(f"==> bossac : {bossac}")
    print(f"==> binary : {binary}")

    console = None
    target = find_samba()
    if target:
        # Already in the bootloader: do not touch, that would only reset it.
        print(f"==> SAM-BA already up on {target} (native USB)")
        native_usb = "true"
    else:
        console = find_console(args.port)
        print(f"==> port   : {console}")
        touch_1200(console)
        target, native_usb = console, "false"
        # The touch erases; the chip then boots ROM SAM-BA on the native
        # port. Prefer it when it shows up - it is the path that works.
        for _ in range(20):
            found = find_samba()
            if found:
                print(f"==> SAM-BA came up on {found} (native USB)")
                target, native_usb = found, "true"
                break
            time.sleep(0.25)

    # bossac wants the node name, not the path.
    print(f"==> bossac: writing {os.path.basename(binary)} via {target}")
    rc = subprocess.call([bossac, "-i", "-d", f"--port={os.path.basename(target)}",
                          "-U", native_usb, "-e", "-w", "-v", "-b", binary, "-R"])
    if console:
        restore_115200(console)
    if rc != 0:
        print(f"bossac failed ({rc})", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
