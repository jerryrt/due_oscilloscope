#!/usr/bin/env python3
"""#79's control arm: does a held command link lock out a second owner?

    DUE_BENCH=<bench> python3 tools/issue79_held_link.py

`BoardDevice` and the `measure.Board` it wraps each open their own
`Control` on the command node. windows-desk measured that the second
one loses - Windows grants one handle per COM port, so the device's
link fails with `PermissionError(13)`, caches `None`, and every later
`counters()`, `load()` and `trace()` is refused for the device's life.
Held 0/3, released 3/3 there.

This is the arm that says whether that is the platform or the code.
Run it wherever you have a board: a platform that lets two handles hold
one tty should answer 3/3 in **both** arms, and a bench that does not is
a second platform with the defect rather than a confirmation of the
first. Since #79's fix the daemon takes the board's own link, so on
every platform both arms should answer.

Both arms open a fresh `BoardDevice` and read `counters()` through it.
The only difference is whether the Board's own link is open at that
moment. Interleaved, first pair dropped by index.

Reading a null here needs care in the usual way: the released arm is
this rig's positive control. If it does not answer, nothing in the run
means anything, because the path was not exercised at all.

THE BENCH IS REQUIRED, and nothing touches the board until it is known.
It comes from `DUE_BENCH` or from `bench.json`; with neither, this
refuses. The record is `records/issue79-held-link-<bench>.jsonl`, every
row carries `bench`, and an existing record is never overwritten - move
it aside first. Any command-line argument prints this and exits, so
asking for help cannot run the experiment.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import provenance                                           # noqa: E402

if len(sys.argv) > 1:
    print(__doc__)
    sys.exit(0 if sys.argv[1] in ("-h", "--help") else 2)

bench = os.environ.get("DUE_BENCH") or provenance.bench().get("bench")
if not bench:
    sys.exit("REFUSING: no bench. Set DUE_BENCH or declare one in "
             "bench.json - a row without its bench is comparable with "
             "nothing, and the record file is named after it.")
out = os.path.join(ROOT, "records", "issue79-held-link-%s.jsonl" % bench)
if os.path.exists(out):
    sys.exit(f"REFUSING: {out} already exists. Move it aside before "
             f"re-taking it; this tool does not overwrite a record.")

import measure                                              # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "host", "daemon"))
from device import BoardDevice                              # noqa: E402

board = measure.Board(settle=3.0)
prov = provenance.run_fields(board)
rows = []
try:
    for pair in range(4):
        for arm in ("held", "released"):
            if arm == "held":
                c = board.ctl()          # Board takes and keeps the node
                held_ok = c is not None
            else:
                board.ctl_invalidate()
                held_ok = None
            dev = BoardDevice(board)     # a second owner, fresh each time
            ctl = dev.control()
            note = getattr(dev, "_ctl_note", None)
            got = None
            err = None
            try:
                got = dev.counters() if ctl is not None else None
            except Exception as e:       # the refusal the client sees
                err = f"{type(e).__name__}: {e}"
            rows.append({"pair": pair, "arm": arm, "board_ctl_open": held_ok,
                         "device_ctl": ctl is not None,
                         "counters_ok": bool(got), "ctl_note": note,
                         "error": err, "bench": bench, **prov})
            print(f"pair {pair} {arm:9s}: device ctl "
                  f"{'yes' if ctl is not None else 'NO ':3s}  counters "
                  f"{'ok' if got else 'NO'}"
                  + (f"  note={note}" if note else "")
                  + (f"  err={err}" if err else ""), flush=True)
            board.ctl_invalidate()
            time.sleep(0.2)
finally:
    board.stop(); board.close()

with open(out, "x", encoding="utf-8", newline="\n") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
kept = [r for r in rows if r["pair"] != 0]
for arm in ("held", "released"):
    v = [r for r in kept if r["arm"] == arm]
    print(f"\n{arm:9s}: {sum(1 for r in v if r['counters_ok'])} / {len(v)} answered")
print(f"wrote {len(rows)} rows to {out}")
