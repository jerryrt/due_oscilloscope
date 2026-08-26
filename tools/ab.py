"""Compare firmware conditions against a control arm that must reproduce.

The instrument for the mistake this project made four times in one day.

Issue #5 is bimodal and its incidence drifts on a scale of hours: the
same image measured 5/10 dirty in the morning and 0/10 that evening. So
a run of clean results proves nothing on its own, and an experiment
whose arms are separated in time is comparing eras, not conditions.

Four findings died of this. "wip/stream-stop-race fixes it" (25/25
clean), "four bytes of bss flip it", "the TIOA0/TIOA1 phase decides it"
(16/16 clean), "printf placement decides it" (0/10 both ways) - and on
the other host a 32-of-32 sweep that read as three working treatments
until someone noticed the fourth condition was the untreated baseline.
Every one of them was a negative result, which is why they were hard to
see as comparisons at all: nothing looks less like a claim than a column
of zeroes.

So this harness enforces two things a hand-run sweep does not:

  * the conditions are interleaved, one rep of each per round, so drift
    lands on every arm equally instead of on whichever ran last;
  * one condition is named the control, and if the control never goes
    dirty the result is REFUSED rather than reported. A treatment that
    beats a control which never reproduced has beaten nothing.

Conditions are shell commands that leave the board flashed and ready -
typically a build and an upload. The control is whichever condition is
named by --control, and it should be the untreated one.

    python3 tools/ab.py --rounds 10 \
        --control 'git stash && make flash' \
        --arm     'git stash pop && make flash'

Nothing here knows what a condition does. It runs it, measures the
board, and refuses to draw a conclusion the data cannot support.
"""
import argparse
import os
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host"))
import measure  # noqa: E402


def measure_once(board, seconds, preset):
    """One capture. Dirty if either channel is above its own threshold."""
    res = measure.run_capture(board, preset=preset, seconds=seconds)
    ps = res.stream
    flat = ps.series.get(measure.CH_A1, [])
    flat = flat[ps._index_at(measure.CH_A1, measure.SETTLE_US):]
    step = ps.series.get(measure.CH_A0, [])
    step = step[ps._index_at(measure.CH_A0, measure.SETTLE_US):]
    if len(flat) < 1000:
        return None                      # no data is not a clean run
    fc = measure.flat_census(flat)
    sc = measure.level_census(step)
    return {"dirty": bool(fc["count"] or sc["count"]),
            "flat": fc["count"], "step": sc["count"],
            "max_dev": fc["max_dev"], "period": fc["period"] or sc["period"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True,
                    help="shell command that flashes the untreated arm")
    ap.add_argument("--arm", action="append", default=[], required=True,
                    help="shell command that flashes a treated arm; repeatable")
    ap.add_argument("--rounds", type=int, default=10,
                    help="reps per condition, interleaved")
    ap.add_argument("-s", "--seconds", type=float, default=2.0)
    ap.add_argument("--preset", default="M")
    args = ap.parse_args()

    conditions = [("control", args.control)]
    conditions += [(f"arm{i+1}", c) for i, c in enumerate(args.arm)]
    tally = {name: [0, 0] for name, _ in conditions}

    for rnd in range(1, args.rounds + 1):
        for name, cmd in conditions:
            print(f"[round {rnd}] {name}: {cmd}", flush=True)
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"{name}: flash command failed ({r.returncode})\n"
                         f"{r.stdout[-2000:]}{r.stderr[-2000:]}")
            board = measure.Board(settle=3.0)
            try:
                board.stop(); board.drain_console(0.4)
                got = measure_once(board, args.seconds, args.preset)
            finally:
                try:
                    board.stop()
                finally:
                    board.close()
            if got is None:
                sys.exit(f"{name} round {rnd}: no data - the stream did not "
                         f"run, so this round says nothing. Check the flash.")
            tally[name][1] += 1
            tally[name][0] += got["dirty"]
            mark = (f"DIRTY flat={got['flat']} step={got['step']} "
                    f"dev={got['max_dev']:.0f} period={got['period']}"
                    if got["dirty"] else "clean")
            print(f"           -> {mark}", flush=True)

    print("\n" + "=" * 56)
    for name, cmd in conditions:
        d, n = tally[name]
        print(f"  {name:8s} dirty {d}/{n}   {cmd}")
    print("=" * 56)

    cd, cn = tally["control"]
    if cd == 0:
        print(
            "\nREFUSED. The control arm never reproduced the defect in "
            f"{cn} rounds, so this run measures the era and not the "
            "conditions. Every arm reading zero is what a board that is "
            "not currently reproducing looks like, whatever the arms do.\n"
            "Re-run when the control is dirty, or report the control's "
            "rate and claim nothing about the arms.")
        return 2
    print(f"\nControl reproduced ({cd}/{cn}), so the arms are comparable.")
    for name, _ in conditions[1:]:
        d, n = tally[name]
        print(f"  {name}: {d}/{n} against control {cd}/{cn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
