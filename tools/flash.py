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

# How long to wait for the native bootloader node after the touch. It is
# an optimisation - the programming port is tried regardless - so this is
# patience, not a deadline anything depends on.
SAMBA_WAIT_S = 15.0


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


def samba_nodes():
    """Every ROM-bootloader node on the system.

    With blank flash the SAM3X boots ROM SAM-BA, which enumerates on the
    NATIVE port as 03EB:6124 - not through the 16U2. So after an erase
    the programming port is the wrong place to look, and bossac reports
    "No device found" on a board that is sitting in the bootloader
    waiting.

    Returns a list, never one node, because attributing a bootloader to
    a board is the whole problem: SAM-BA has a different VID/PID and no
    serial number in common with the running firmware, so with two
    boards attached there is nothing in the enumeration that says which
    is which. The caller has to earn the attribution - see main().
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()
            if (p.vid, p.pid) == SAMBA]


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
    except Exception as e:                               # noqa: BLE001
        # Do NOT swallow this silently. The docstring above says why: a
        # port left at 1200 re-triggers the 16U2's erase-and-reset on the
        # next open, so a silent failure here re-arms exactly the hazard
        # this function exists to disarm, and the next person sees a
        # board that wipes itself whenever a tool attaches.
        print(f"WARNING: could not restore {port} to 115200: {e}",
              file=sys.stderr)
        print("         The next open of this port may erase the board. "
              "Re-open it at", file=sys.stderr)
        print("         115200 before using it.", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.path.join(REPO, "build",
                                                  "baremetal_bringup.bin"))
    ap.add_argument("--port", help="programming port; discovered if omitted")
    ap.add_argument("--bossac", help="bossac executable; from the registry "
                                     "if omitted (CMake passes it)")
    ap.add_argument("--samba", help="bootloader port to flash directly, for "
                                    "when more than one board is blank")
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

    # A bootloader node is only used if it can be attributed to the board
    # we were asked to flash. Attribution comes from one of two things: it
    # appeared as a result of *our* touch, or it is the only one on the
    # system and no port was named. Anything else and we would be aiming
    # an erase at somebody else's board - the same accident find_console
    # refuses, and the one the comment above it records.
    before = set(samba_nodes())
    console = None
    target = native_usb = None

    if args.samba:
        target, native_usb = args.samba, "true"
        print(f"==> SAM-BA        : {target} (named)")
    elif before and not args.port:
        if len(before) > 1:
            sys.exit(f"more than one board is in SAM-BA: {sorted(before)}. "
                     f"Pass --samba to say which, or --port to touch a "
                     f"specific programming port.")
        target, native_usb = next(iter(before)), "true"
        print(f"==> SAM-BA already up on {target} (native USB)")

    if target is None:
        console = find_console(args.port)
        print(f"==> port   : {console}")
        touch_1200(console)
        target, native_usb = console, "false"
        # The touch erases; the chip then boots ROM SAM-BA on the native
        # port. Take only a node that was NOT there beforehand - that is
        # what makes it ours rather than whichever blank board happened
        # to be plugged in.
        # Poll gently and for longer. 5 s of 0.25 s polling was not
        # enough on macOS - measured failing about one run in three - and
        # re-enumerating every serial device four times a second while
        # the board is itself re-enumerating is not free. Missing the
        # node is no longer fatal, because the programming port is tried
        # too, so this can afford to be patient rather than eager.
        deadline = time.time() + SAMBA_WAIT_S
        while time.time() < deadline:
            fresh = set(samba_nodes()) - before
            if len(fresh) == 1:
                target, native_usb = fresh.pop(), "true"
                print(f"==> SAM-BA came up on {target} (native USB)")
                break
            if len(fresh) > 1:
                sys.exit(f"the touch brought up {len(fresh)} bootloader "
                         f"nodes: {sorted(fresh)}. Refusing to guess.")
            time.sleep(0.5)
        else:
            print(f"==> no native SAM-BA node in {SAMBA_WAIT_S:.0f} s; "
                  f"the programming port serves the ROM monitor too")

    # Try every route before giving up, because by this point the touch
    # has already erased the board: a failure here is not "nothing
    # happened", it is a board with no program in it.
    #
    # The native SAM-BA node is an OPTIMISATION, never a requirement. The
    # SAM3X ROM monitor listens on the UART behind the 16U2 as well, so
    # the programming port always works - that is why the old shell
    # script had no race at all. Treating the native node as the only
    # path is what made this fail one run in three on macOS and leave the
    # board unbootable.
    routes = []
    if native_usb == "true":
        routes.append((target, "true", "native SAM-BA"))
        if console:
            routes.append((console, "false", "programming port"))
    else:
        routes.append((target, "false", "programming port"))

    rc = 1
    for node, usb, label in routes:
        print(f"==> bossac: writing {os.path.basename(binary)} via {node} "
              f"({label})")
        rc = subprocess.call([bossac, "-i", "-d",
                              f"--port={os.path.basename(node)}",
                              "-U", usb, "-e", "-w", "-v", "-b", binary, "-R"])
        if rc == 0:
            break
        print(f"    {label} failed ({rc})")
        if (node, usb, label) is not routes[-1]:
            time.sleep(1.5)

    if console:
        restore_115200(console)
    if rc != 0:
        print("", file=sys.stderr)
        print(f"FLASH FAILED ({rc}) - and the board is now ERASED.",
              file=sys.stderr)
        print("The 1200-baud touch erases before anything is written, so "
              "there is no", file=sys.stderr)
        print("program on the board and it will not enumerate its native "
              "port. This is", file=sys.stderr)
        print("recoverable: just run the flash again. The board is sitting "
              "in ROM SAM-BA", file=sys.stderr)
        print("and the next run takes the 'already up' path.",
              file=sys.stderr)
        print("If it still fails, press ERASE then RESET on the board and "
              "retry.", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
