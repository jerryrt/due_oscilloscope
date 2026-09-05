#!/usr/bin/env python3
"""Power-cycle the board from software - IF the hub really cuts power.

Issue #5's last untried draw-event candidate is a power cycle, and on a
bench where the board hangs off a switchable hub it should not need
hands. **On this bench it does.** The hub carrying the Due (Bridgesil
35d6:2510, ports 2 and 3) advertises `ganged` rather than `ppps`,
accepts an off request, reports its ports off - and does not cut power.

That is why every path here verifies the cut instead of trusting the
acknowledgement. `uhubctl` returning "Port 3: 00a0 off" means the hub
said yes, not that the rail dropped.

**How the lie was caught, because I published the opposite first.** I
committed that a cycle had cleared a wedged 16U2 and therefore proved
the rail dropped. It had not: the flash tool of the day retried three
times on its own, and one of those retries landed at about the moment I
cycled.
The disproof is two-fold and neither part needs firmware - the device
nodes are still present *during* the off window, and the board's LED
keeps blinking through it, which the bench operator could see and I
could not.

The general form, worth more than this tool: **a device that reports
success is not evidence the physical thing happened.** Check the
consequence, not the acknowledgement.

So `--cycle` here reports failure and changes nothing. A bench with a
genuine `ppps` hub can use it; this one cannot, and #5's power-cycle
arm still needs hands on a cable.

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
    """Cut power, and CHECK the device actually went away.

    Returns True only if the nodes disappeared while the ports were
    off. A hub that ignores the request looks identical from the
    request's side, which is how this bench briefly believed it had a
    software power cycle.
    """
    before = set(glob.glob("/dev/cu.usbmodem*"))
    _run(["-f", "-l", hub, "-a", "off"])
    dropped = False
    end = time.time() + max(3.0, off_s)
    while time.time() < end:
        time.sleep(0.5)
        if not (set(glob.glob("/dev/cu.usbmodem*")) & before):
            dropped = True
    _run(["-f", "-l", hub, "-a", "on"])
    return dropped


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
    dropped = cycle(hub, args.off)
    if not dropped:
        print("FAILED: the nodes never went away while the ports were "
              "off, so the hub did not cut power. It acknowledged the "
              "request and ignored it - `ganged` hubs do. This bench "
              "cannot power-cycle in software; the arm needs hands.")
        return 1
    print("power was actually cut (nodes disappeared while off)")
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
