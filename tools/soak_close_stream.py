#!/usr/bin/env python3
"""Close the native port mid-capture, without stopping the stream.

`tools/soak0c.py` soaks close() against playback - the OUT direction,
with write URBs in flight. Nothing soaked the other one, and the capture
path is where `5d6e7ab` changed behaviour: when DTR drops mid-transfer
the framer now waits for the DMA that owns the head buffer instead of
releasing it. That is the path CLAUDE.md calls dangerous (objective 0c),
so it wanted exercising rather than reasoning about.

**What this measures: that nothing regressed. It does not catch the bug
the fix fixes, and that was checked rather than assumed.** Twelve cycles
on the fixed image and twelve on the image before it, same board, same
session: 0 wedged and 0 dirty recoveries on both, close in 0.003-0.005 s
either way, frame counts identical to the frame.

So the discrimination is nil, and the reason is worth writing down
because it is why a regression test for `5d6e7ab` is hard. The bytes the
defect corrupts go to a host that has already closed the port, so nobody
reads them; and the stop that follows aborts the DMA channel and resets
every bit of framer state, so the device recovers cleanly whether or not
it just handed the PDC a buffer the USB controller was reading. The
defect is real by inspection - a CPU write into an active DMA source,
invariant 1, and a frame spliced across two points in time carrying a
valid CRC, invariant 5 - but its blast radius is a frame nobody is
listening for.

What the soak is therefore good for: proving a change to the not-ready
path has not made close() hang or left the device unable to stream
afterwards. Both are real risks on this path and neither is covered
elsewhere.

    .venv/bin/python tools/soak_close_stream.py -n 12

The stream is stopped over the *console* port afterwards, never the
native one: the native fd is gone by then, which is the whole point.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--cycles", type=int, default=12)
    ap.add_argument("--preset", default="5")
    ap.add_argument("--stream-s", type=float, default=0.4,
                    help="how long to let frames flow before closing, so "
                         "a transfer is in flight when DTR drops")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    worst = 0.0
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.cycles + 1):
            fd = board.open_native(blocking_writes=True)
            measure.drain_until_quiet(fd, quiet=0.2, cap=3.0)
            board.cmd(args.preset)

            # Read a little, so the device is mid-frame with a DMA
            # armed rather than idle when the port goes away.
            got, end = 0, time.time() + args.stream_s
            while time.time() < end:
                try:
                    got += len(fd.read(65536) or b"")
                except OSError:
                    break

            t0 = time.time()
            wedged = False
            try:
                board.close_native(fd)      # no stop command first
            except Exception as e:                          # noqa: BLE001
                wedged = True
                print(f"  cycle {i}: close raised {e!r}", flush=True)
            close_s = time.time() - t0
            worst = max(worst, close_s)

            # Stop over the console, which is the only port still open.
            board.cmd("0")
            board.drain_console(0.4)

            # The question that matters: is the next capture clean?
            res = measure.run_capture(board, preset=args.preset,
                                      seconds=1.0)
            ps = res.stream
            row = {"cycle": i, "bench": args.bench,
                   "streamed_bytes": got,
                   "close_s": round(close_s, 3), "wedged": wedged,
                   "frames": ps.frames, "seq_gaps": ps.seq_gaps,
                   "crc_bad": ps.crc_bad,
                   "dropped_frames": ps.dropped_frames,
                   "overrun_frames": ps.overrun_frames,
                   "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
            rows.append(row)
            print(f"cycle {i:3d}: streamed {got:8d} B, close "
                  f"{close_s:6.3f} s{'  WEDGED' if wedged else ''}  "
                  f"-> recovery: frames {ps.frames:4d} "
                  f"seq_gaps {ps.seq_gaps} crc_bad {ps.crc_bad} "
                  f"dropped {ps.dropped_frames}", flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    if rows:
        bad = [r for r in rows
               if r["seq_gaps"] or r["crc_bad"] or r["frames"] == 0]
        times = sorted(r["close_s"] for r in rows)
        print(f"\n{len(rows)} cycles: close {times[0]:.3f}-{times[-1]:.3f} s, "
              f"median {times[len(times) // 2]:.3f}; "
              f"{sum(1 for r in rows if r['wedged'])} wedged; "
              f"{len(bad)} dirty recoveries")
        if bad:
            for r in bad:
                print(f"  cycle {r['cycle']}: frames {r['frames']} "
                      f"seq_gaps {r['seq_gaps']} crc_bad {r['crc_bad']}")
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
