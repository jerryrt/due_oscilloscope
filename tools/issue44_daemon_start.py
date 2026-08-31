#!/usr/bin/env python3
"""#44 through the daemon, which is where the start-race fix actually is.

`7c0bba2` gated `host/daemon/device.py`'s `read()` on `running` as well
as `fd`, because two readers were on the stream during `start()` and
`drain_until_quiet` was throwing away frames from the run that had just
begun. Every existing windows-desk arm on #44 drives `measure.run_loop`,
and `host/measure.py` does not import the daemon at all - so none of them
can see that defect, and a null from them is not evidence about the fix.
This is the arm that can.

**Firmware is not the variable and must not be reflashed between arms.**
The change is host-side, so the matched comparison is two *host trees*
against one image: run this from `main`, then from a worktree checked out
at `7c0bba2~1`, with the same board untouched in between. That is one
knob, and it is the only way this bench can say whether the window
produced real frame loss rather than only a possible one.

What it counts, and why both:

  seq_gaps      frames the device emitted that never reached the client.
                This is the quantity the fix is about - a frame consumed
                by the drain and dropped leaves a hole in the sequence.
  first_seq     the sequence number of the first frame the client saw.
                A start-window loss shows here even when the gap count
                does not, because frames discarded BEFORE the client's
                first frame leave no gap - there is nothing on the near
                side of them to be discontinuous with. Missing this is
                how a start-race hides from a gap counter.

That second column is the reason this tool exists rather than a
`--reps` flag on `issue44_gaps.py`: the existing instrument counts holes
between frames it received, and the defect throws frames away before the
first one it receives.

    python3 tools/issue44_daemon_start.py --reps 16 --preset 1
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))

import measure                                              # noqa: E402
import provenance                                           # noqa: E402
from daemon import device as devmod                         # noqa: E402
from daemon import server as servermod                      # noqa: E402
from daemon import client as clientmod                      # noqa: E402


def one_run(board, preset, want, timeout):
    """One start/collect/stop cycle on a held Board. Never raises."""
    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=timeout)
    try:
        c.connect()
        c.hello("control")
        c.subscribe()
        t0 = time.time()
        c.call("start", mode="capture", preset=str(preset))
        frames = c.wait_frames(want, timeout=timeout)
        c.call("stop")
        ps = measure._finish(measure.parse_frames(b"".join(frames)))
        return {
            "frames": ps.frames,
            "seq_gaps": ps.seq_gaps,
            "dropped": ps.dropped_frames,
            "crc_bad": ps.crc_bad,
            # The device's own sequence number on the first frame the
            # client saw. Frames discarded before it leave no gap, so
            # this is the column a start-race shows up in.
            "first_seq": ps.first_seq,
            "start_to_first_s": round(time.time() - t0, 3),
        }
    finally:
        for shut in (c.close, srv.stop):
            try:
                shut()
            except Exception:                                # noqa: BLE001
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reps", type=int, default=16)
    ap.add_argument("--preset", default="1")
    ap.add_argument("--want", type=int, default=40,
                    help="frames to collect per rep")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if not a.bench:
        ap.error("--bench is required; a row whose bench nobody can name "
                 "is not comparable with anything (#53)")

    # One held Board for the whole arm. BoardDevice takes the Board
    # itself, and re-opening it per rep would reset the device and make
    # every rep a first run - which CLAUDE.md says to discard.
    board = measure.Board(settle=3.0)
    prov = provenance.collect(board=board)

    out = a.out or os.path.join(
        REPO, "records", f"issue44-daemon-start-{a.bench}.jsonl")
    rows = []
    print(f"daemon start-race arm: preset {a.preset}, {a.reps} reps, "
          f"want {a.want} frames\n")
    for i in range(1, a.reps + 1):
        try:
            r = one_run(board, a.preset, a.want, a.timeout)
        except Exception as e:                               # noqa: BLE001
            r = {"error": repr(e)}
        r.update({"run": i, "issue": 44, "bench": a.bench,
                  "test": "daemon-start-race",
                  "preset": a.preset, "want": a.want})
        for k in ("track", "fw_repo_rev", "repo_rev", "fw_cc", "fw_layout",
                  "fw_build", "host_os"):
            if k in prov:
                r[k] = prov[k]
        rows.append(r)
        print(f"  run {i:2d}: frames={r.get('frames')} "
              f"seq_gaps={r.get('seq_gaps')} first_seq={r.get('first_seq')} "
              f"{r.get('error','')}")
        time.sleep(0.5)

    try:
        board.close()
    except Exception:                                        # noqa: BLE001
        pass

    bad = [r for r in rows if (r.get("seq_gaps") or 0) or r.get("error")]
    print(f"\n  {len(bad)} of {len(rows)} runs had gaps or errored")
    with open(out, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"  wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
