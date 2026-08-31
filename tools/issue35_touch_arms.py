#!/usr/bin/env python3
"""Re-run the four arms that put a platform branch in `flash.py`.

Issue #35. `touch_1200(restore=True)` drops DTR at 1200, sets the speed
back to 115200, then closes. `restore=False` closes while still at 1200.
Linux needs the first - the stored termios is applied on the *next*
open, before pyserial can set the speed, so a port left at 1200 erases
the board it just flashed (3 of 3 on linux-x1).

macOS was measured to need the opposite: this bench reported across four
arms that dropping DTR and restoring 115200 before the close **does not
erase**, and that only closing at 1200 does. That measurement is why
`_flash_attempt` carries a fallback branch at all.

**It did not reproduce on 2026-08-31.** A plain `tools/flash.py` took
the default arm and the bus moved - SAM-BA came up, bossac wrote, verify
succeeded - twice, and the fallback never printed. Board state does not
explain it: a board already in the bootloader skips the touch entirely
("SAM-BA already up"), so there is no state in which the default arm is
reached and fails.

A branch in a file three benches share is worth exactly its premise, and
the premise is this bench's claim. So it gets re-measured rather than
argued about.

**The arm is read from the board, not from the return code.** The touch
either erased or it did not, and the honest witness is whether the
native nodes went away and a SAM-BA node appeared - the firmware's own
enumeration, which cannot be faked by a serial call that returned
cleanly.

Each rep that erases is repaired by reflashing before the next, so
every rep starts from the same state.

    python3 tools/issue35_touch_arms.py --reps 3
    python3 tools/issue35_touch_arms.py --reps 3 --arms restore,at1200
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "host"))
import flash  # noqa: E402


def nodes():
    return sorted(glob.glob("/dev/cu.usbmodem*"))


def state():
    """What the board is, read from enumeration alone."""
    ns = nodes()
    native = [n for n in ns if "B_" in n]
    samba = [n for n in ns if n.endswith("1301")]
    if samba and not native:
        return "samba"
    if native:
        return "running"
    return "unknown"


def arm_restore(port):
    """The default arm: DTR low at 1200, speed back to 115200, close."""
    s = flash.open_port(port, 1200)
    s.dtr = False
    time.sleep(0.1)
    s.baudrate = 115200
    s.close()


def arm_restore_wait(port):
    """As above but 1.5 s between the DTR drop and the speed restore."""
    s = flash.open_port(port, 1200)
    s.dtr = False
    time.sleep(1.5)
    s.baudrate = 115200
    s.close()


def arm_at1200(port):
    """Close while still at 1200 - the shape the macOS branch takes."""
    s = flash.open_port(port, 1200)
    s.dtr = False
    time.sleep(0.1)
    s.close()


ARMS = {"restore": arm_restore,
        "restore_wait": arm_restore_wait,
        "at1200": arm_at1200}


#: Where each repair flash's transcript goes.
#:
#: This captured to a variable and threw it away, and then a board came
#: back blank an hour later with the only transcript that could have
#: explained it already discarded. That is the standing rule in
#: CLAUDE.md - capture failure output to a file, always - broken inside
#: a tool written to investigate a flashing defect.
#:
#: A repair flash is exactly the run whose output is wanted later: it is
#: the one nobody is watching.
REFLASH_LOG = os.path.join(ROOT, "records", "issue35-reflash-transcripts.log")


def reflash(tag):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools",
                                                     "flash.py")],
                       capture_output=True, text=True)
    with open(REFLASH_LOG, "a") as fh:
        fh.write(f"\n===== repair flash after {tag} : rc={r.returncode} "
                 f"=====\n")
        fh.write(r.stdout or "")
        fh.write(r.stderr or "")
    # The lines that matter are few; print those and leave the rest on
    # disk, so a run stays readable and a post-mortem stays possible.
    for line in (r.stdout or "").splitlines():
        if line.startswith("==>") or "Verify" in line:
            print(f"      | {line}")
    return r.returncode


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--arms", default="restore,restore_wait,at1200")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    arms = [a for a in args.arms.split(",") if a.strip()]

    rows = []
    for rep in range(args.reps):
        for name in arms:
            if state() != "running":
                print(f"  (board not running - reflashing first)")
                if reflash(f"pre-rep{rep}-{name}") != 0:
                    print("reflash failed; stopping - transcript in "
                          f"{REFLASH_LOG}", file=sys.stderr)
                    return 2
                time.sleep(2.0)
            port = flash.find_console()
            before = state()
            ARMS[name](port)
            time.sleep(2.5)
            after = state()
            erased = after == "samba"
            rows.append({"rep": rep, "arm": name, "before": before,
                         "after": after, "erased": erased,
                         "nodes_after": nodes(), "bench": args.bench,
                         "issue": 35})
            print(f"rep {rep} {name:>13}: {before} -> {after}   "
                  f"{'ERASED' if erased else 'did not erase'}", flush=True)
            if erased:
                if reflash(f"rep{rep}-{name}") != 0:
                    print("reflash failed; stopping - transcript in "
                          f"{REFLASH_LOG}", file=sys.stderr)
                    return 2
                time.sleep(2.0)
            else:
                # Leave no port stored at 1200 for the next rep.
                flash.restore_115200(port)

    print()
    for name in arms:
        got = [r for r in rows if r["arm"] == name]
        n = sum(1 for r in got if r["erased"])
        print(f"{name:>13}: erased {n} of {len(got)}")

    out = args.out or os.path.join(
        ROOT, "records", f"issue35-touch-arms-{args.bench or 'unknown'}.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
