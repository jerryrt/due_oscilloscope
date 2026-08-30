#!/usr/bin/env python3
"""Power-cycle the board from software, where the hub allows it.

Issue #5 has one untried draw-event candidate left - a power cycle - and
it has sat untried on both benches because it was taken to need hands.
On a bench where the board hangs off a hub whose ports can be switched,
it does not.

    uhubctl -f -l <hub> -a cycle -d <seconds>

Two things have to be true and both are checkable rather than assumed.
BOTH of the Due's connectors must be on the switched hub, or the board
keeps its rail from the other one - locate() reports what it finds. And
the hub must actually cut power: this one advertises `ganged` rather
than `ppps`, so uhubctl needs -f, and plenty of hubs accept the request
and do nothing.

**How this bench knows the cycle is real**, since it is not obvious.
Firmware state cannot show it: opening the control port asserts NRSTB
and resets the SAM3X anyway, so anything volatile is cleared by the act
of measuring. The evidence is the programming port's 16U2 - a SEPARATE
chip that NRSTB cannot touch. Its 1200-baud erase/reset path had wedged
after about ten flashes, failing identically for both flashers over
half an hour, and one uhubctl cycle cleared it. Only losing the 5 V rail
does that.

    .venv/bin/python tools/powercycle.py --locate
    .venv/bin/python tools/powercycle.py --cycle --off 10
"""
import argparse
import glob
import re
import subprocess
import sys
import time

UHUBCTL = "uhubctl"


def _run(args):
    return subprocess.run([UHUBCTL] + args, capture_output=True,
                          text=True, timeout=120).stdout


def locate():
    """Which hub and ports carry the Due, and are both connectors there?

    Returns (hub, {port: description}) for the hub holding the most Due
    connectors, or (None, {}).
    """
    try:
        # No vendor filter: -n matches the HUB's vendor id, not the
        # attached device's, so "-n 2341" finds nothing at all - the hub
        # here is 35d6. List every hub and read the attachments.
        out = _run(["-f"])
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"uhubctl not usable: {exc}")
        return None, {}
    hub, found = None, {}
    best = (None, {})
    for line in out.splitlines():
        m = re.match(r"Current status for hub (\S+)", line)
        if m:
            if len(found) > len(best[1]):
                best = (hub, found)
            hub, found = m.group(1), {}
            continue
        m = re.match(r"\s+Port (\d+):.*\[2341:([0-9a-f]{4})(.*)\]", line)
        if m:
            found[int(m.group(1))] = f"2341:{m.group(2)}{m.group(3)}"
    if len(found) > len(best[1]):
        best = (hub, found)
    return best


def cycle(hub, off_s):
    _run(["-f", "-l", hub, "-a", "off"])
    time.sleep(off_s)
    _run(["-f", "-l", hub, "-a", "on"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--locate", action="store_true")
    ap.add_argument("--cycle", action="store_true")
    ap.add_argument("--off", type=float, default=10.0)
    ap.add_argument("--wait", type=float, default=8.0,
                    help="seconds to allow for re-enumeration")
    args = ap.parse_args()

    hub, ports = locate()
    if not hub:
        print("no hub found carrying an Arduino VID; this bench cannot "
              "power-cycle in software")
        return 1
    print(f"hub {hub}, Due connectors on ports "
          + ", ".join(f"{p} ({d})" for p, d in sorted(ports.items())))
    if len(ports) < 2:
        print("WARNING: fewer than two connectors found on this hub. The "
              "Due draws power from either, so cutting one may not drop "
              "the rail - check the other cable before trusting a null "
              "result.")
    if args.locate or not args.cycle:
        return 0

    before = sorted(glob.glob("/dev/cu.usbmodem*"))
    print(f"nodes before: {before}")
    cycle(hub, args.off)
    end = time.time() + args.wait
    while time.time() < end:
        time.sleep(0.5)
        after = sorted(glob.glob("/dev/cu.usbmodem*"))
        if after and after != []:
            break
    time.sleep(1.0)
    after = sorted(glob.glob("/dev/cu.usbmodem*"))
    print(f"nodes after : {after}")
    if not after:
        print("the board did not come back; check the cable")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
