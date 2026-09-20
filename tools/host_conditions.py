#!/usr/bin/env python3
"""What was true of the HOST when an arm ran, recorded beside the arm.

    .venv/bin/python tools/host_conditions.py
    .venv/bin/python tools/host_conditions.py --json records/hostcond-<arm>.jsonl

Needs no board and opens no port: it reads `/sys`, `/proc` and the device
nodes, so it can run immediately before or after a capture without
perturbing it.

## Why this exists

The #5 jumper crossover found that this board's exchange sites moved
29-63% after the wires were swapped, while the untouched control board
did not move at all. `mac-bench`'s control bounds **their** board's
session-to-session drift at 0.19 codes on 238. It does not bound this
bench's, and `windows-desk` made the point that settles it: the control
is a different board on a different host, and in this arm the host's
reading of the stream sets the timing of the device's USB IN DMA
transfers - the one remaining route from host to device. So a change
specific to this session - a different hub port, a re-enumeration, host
load - is not excluded by a control measured elsewhere.

Nothing in this project recorded any of that. `provenance.run_fields()`
answers "which firmware, which image, which tree", which is the right
question for a *binary* and says nothing about the machine the arm ran
on.

**Registered before the return leg rather than reconstructed after it**,
which is the only version worth having: conditions recalled once a
result is known are not evidence.

## What it records, and what each is for

`ports`      which node is control/native/command. This bench's order is
             `ttyACM2`/`ttyACM0`/`ttyACM1`, not the ACM0/1/2 an example
             table elsewhere shows, and they re-enumerated mid-session
             once already.
`usb_path`   the sysfs path per node, e.g. `usb1/1-4/1-4.3/1-4.3:1.0` -
             which physical hub and port. A cable moved to another port
             changes this.
`node_ctime` when each device node was created. A USB disconnect, even
             into the same socket, removes and re-adds the node, so an
             unchanged ctime across two arms is evidence the link was
             never broken. It is a proxy and is labelled one.
`load`       1/5/15-minute load and CPU count.
`host_uptime`, `kernel`, `python`.

It does NOT ask the board anything. Board uptime, firmware and image are
`provenance`'s job and are already on every captured row; duplicating
them here would give a second home for a fact that has one.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

NODES = ("control", "native", "command")


def usb_path(node):
    """The sysfs path, trimmed to the bus/hub/port part.

    Linux only - it returns None elsewhere rather than inventing
    something, because a field that is sometimes a guess is worse than a
    field that is sometimes absent.
    """
    name = os.path.basename(node)
    link = f"/sys/class/tty/{name}/device"
    try:
        full = os.path.realpath(link)
    except OSError:
        return None
    if "/usb" not in full:
        return None
    return "usb" + full.split("/usb", 1)[1]


def node_ctime(node):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S",
                             time.localtime(os.stat(node).st_ctime))
    except OSError:
        return None


def collect():
    out = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "kernel": platform.release(),
           "platform": sys.platform,
           "python": platform.python_version()}
    try:
        out["load1"], out["load5"], out["load15"] = [
            round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        pass
    out["cpus"] = os.cpu_count()
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            out["host_uptime_s"] = round(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass

    try:
        import ports as ports_mod
        # wait=0: this is a snapshot of what is attached now, taken
        # immediately before and after an arm. The default 8 s waits for
        # a board to finish enumerating, which is what a caller that
        # just reset one wants and is exactly wrong here - a conditions
        # reader that blocks for eight seconds is measuring a different
        # moment than the one it was asked about, and in a container,
        # where no board can ever appear, it is the whole cost.
        #
        # Positional, NOT native_order(): find_all_ports() already
        # returns (programming, samples, commands) and NODES zips
        # against those positions. native_order() sorts native nodes by
        # (serial, interface) - it has no idea the programming port is
        # in the list, and sorting it in by serial relabels all three.
        found = ports_mod.find_all_ports(wait=0.0)
    except Exception as exc:                       # noqa: BLE001
        out["ports_error"] = f"{type(exc).__name__}: {exc}"
        found = None
    if found:
        named = dict(zip(NODES, found)) if not isinstance(found, dict) else found
        out["ports"] = {k: str(v) for k, v in named.items()}
        out["usb_path"] = {k: usb_path(str(v)) for k, v in named.items()}
        out["node_ctime"] = {k: node_ctime(str(v)) for k, v in named.items()}

    try:
        out["repo_rev"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.strip()
    except Exception:                              # noqa: BLE001
        out["repo_rev"] = None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default=None, help="append one row here")
    ap.add_argument("--label", default=None,
                    help="what this reading is of, e.g. 'before-return-leg'")
    args = ap.parse_args()
    row = collect()
    if args.label:
        row["label"] = args.label
    for k, v in row.items():
        print(f"  {k}: {v}")
    if args.json:
        with open(args.json, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"\nappended to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
