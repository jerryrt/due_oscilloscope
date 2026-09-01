"""#58: does DISTANCE FROM THE LAST BOARD RESET gate the contention lever?

linux-x1's bisect landed on 24488b4, "host: identify ports by VID/PID on
every platform", and that commit did not introduce defect B - it REMOVED
a board reset from port discovery:

    host/measure.py:1501  "Opening it asserts NRSTB and resets the board"
    host/ports.py:50      "probing opens the programming port and opening
                           it resets the board"

So every GOOD commit in that bisect ran against a freshly reset board
and every BAD one did not, and the likely reading is a pre-existing
defect that a per-discovery reset was masking.

WHY THIS BENCH CAN SAY SOMETHING ABOUT IT DESPITE A DEAD LEVER.

The pytest `board` fixture calls measure.Board(), which opens the
control port, which asserts NRSTB. Every one of this bench's 38 arms
therefore ran within seconds of a reset. That is ONE condition, run 38
times - not 38 chances at the phenomenon:

    condition A   reset, then arm          38 arms, 0 fired  (known)
    condition B   reset, then arm N times  NEVER RUN

If a reset masks defect B, condition B is where it should appear, and
this bench has never been in condition B. It is not on the eliminated
list - and that list is void anyway, being built from post-fade nulls.

WHAT COUNTS AS A RESULT, pre-registered:

  Only a POSITIVE result means anything. This bench's lever is 0/38, so
  a null here is a null from an instrument already established as unable
  to fire, and will be reported as exactly that and not as an
  elimination. That is the error made on this issue four hours ago and
  it is not being made again.

  A positive - any arm at distance > 1 showing seq_gaps at the READING
  client - would say the reset is the mask, on a second bench, and would
  explain this bench's unexplained fade.

The scenario is tests/test_daemon_hardware.py's
test_a_client_that_stops_reading_loses_frames_and_the_rest_do_not,
replicated so it can run N times against ONE open Board. The board is
opened once, at the start, and never reopened.
"""
import argparse
import json
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402
import provenance  # noqa: E402
from daemon import client as clientmod  # noqa: E402
from daemon import device as devmod  # noqa: E402
from daemon import protocol as proto  # noqa: E402
from daemon import server as servermod  # noqa: E402


def one_arm(board, seconds=25.0, preset="5"):
    """One run of the contention scenario. Returns the reading client's gaps."""
    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0,
                           client_queue_frames=8).start()
    silent = socket.create_connection(("127.0.0.1", srv.port))
    good = clientmod.Client("127.0.0.1", srv.port, timeout=20.0,
                            frame_capacity=20000)
    out = {"dropped": None, "seq_gaps": None, "frames": None, "error": None}
    try:
        silent.sendall(proto.encode_json(proto.T_CMD,
                                         {"op": "hello", "id": 1}))
        silent.sendall(proto.encode_json(proto.T_CMD,
                                         {"op": "subscribe", "frames": True,
                                          "id": 2}))
        good.connect()
        good.hello("control")
        good.subscribe()
        good.call("start", mode="capture", preset=preset)

        end = time.time() + seconds
        while time.time() < end:
            if max((s.dropped for s in srv.sessions), default=0) > 0:
                break
            time.sleep(0.1)
        out["dropped"] = max((s.dropped for s in srv.sessions), default=0)
        time.sleep(1.0)
        good.call("stop")
        ps = measure._finish(measure.parse_frames(b"".join(list(good.frames))))
        out["seq_gaps"] = ps.seq_gaps
        out["frames"] = good.frames_received
    except Exception as e:                       # noqa: BLE001
        out["error"] = "%r" % (e,)
    finally:
        try:
            good.close()
        except Exception:
            pass
        try:
            silent.close()
        except Exception:
            pass
        try:
            srv.stop()
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--arms", type=int, default=10,
                    help="arms from ONE board open. Arm 1 is condition A "
                         "(just reset); arms 2..N are condition B.")
    ap.add_argument("-s", "--seconds", type=float, default=25.0)
    ap.add_argument("--preset", default="5")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print("opening the control port ONCE - this asserts NRSTB and is the "
          "only reset in this run", flush=True)
    board = measure.Board(settle=3.0)
    rows = []
    try:
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join("%s=%s" % (k, v)
                                         for k, v in prov.items()), flush=True)
        t0 = time.time()
        for i in range(1, args.arms + 1):
            since = time.time() - t0
            r = one_arm(board, seconds=args.seconds, preset=args.preset)
            row = {"arm": i, "condition": "A" if i == 1 else "B",
                   "s_since_reset": round(since, 1),
                   "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "issue": 58, "team": "windows-platform-team",
                   "bench": "windows-desk",
                   "test": "reset-distance-rearm-attempt"}
            row.update(r)
            row.update(prov)
            rows.append(row)
            fired = (r["seq_gaps"] or 0) > 0
            print("arm %2d  cond %s  +%6.1fs  dropped=%-6s frames=%-7s "
                  "seq_gaps=%-4s %s%s"
                  % (i, row["condition"], since, r["dropped"], r["frames"],
                     r["seq_gaps"], "<<< FIRED" if fired else "",
                     (" ERROR " + r["error"]) if r["error"] else ""),
                  flush=True)
    finally:
        try:
            board.close()
        except Exception:
            pass

    fired = [r for r in rows if (r["seq_gaps"] or 0) > 0]
    b_arms = [r for r in rows if r["condition"] == "B"]
    b_fired = [r for r in b_arms if (r["seq_gaps"] or 0) > 0]
    summary = {"issue": 58, "test": "reset-distance-rearm-attempt",
               "team": "windows-platform-team", "bench": "windows-desk",
               "arms": len(rows), "fired": len(fired),
               "condition_B_arms": len(b_arms),
               "condition_B_fired": len(b_fired),
               "max_s_since_reset": max((r["s_since_reset"] for r in rows),
                                        default=None),
               "verdict": ("POSITIVE - the lever fired away from a reset"
                           if b_fired else
                           "NULL, AND A NULL FROM A DEAD INSTRUMENT. This "
                           "bench is 0/38 since the fade, so this eliminates "
                           "nothing and is NOT an elimination of the reset "
                           "hypothesis. Only linux-x1's live lever can test it.")}
    print()
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write(json.dumps(summary) + "\n")
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
