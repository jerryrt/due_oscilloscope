"""Does Track A's command port fail to come up after a flash on Windows?

Issue #19: ~1 in 10 on the macOS bench, both occurrences Track A. If it
reproduces here it is the device; if 15 flashes are clean it points the
other way, and either answer is worth more than another occurrence there.

On failure, capture `u` and `E` from the programming port BEFORE
re-flashing - that is the evidence the first two occurrences did not
produce.

    python3 tools/enum_probe.py              # discover the port, 12 rounds
    python3 tools/enum_probe.py --runs 15
    python3 tools/enum_probe.py --port COM7  # when discovery is the thing
                                             # under test

**This reflashes the board every round.** Argument parsing happens
before anything opens a port, so `--help` answers rather than starting
an experiment.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure                                            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=12,
                    help="flash and check this many times (default 12)")
    ap.add_argument("--port", default=None,
                    help="programming port. Discovered by USB VID/PID when "
                         "omitted, which is what a bench should use: the "
                         "native numbers move on every reflash, and a "
                         "hardcoded one aims the 1200-baud erase at "
                         "whatever now answers to that name")
    args = ap.parse_args()

    fails = 0
    for i in range(args.runs):
        # measure.flash() is the one place that knows where each track's
        # image is. A hardcoded image path here would be how a moved
        # artifact becomes a broken bench tool nobody finds until they
        # next need it.
        try:
            measure.flash(track="a", control=args.port)
        except Exception as e:                               # noqa: BLE001
            print("%2d  FLASH FAILED: %s" % (i, e))
            continue
        time.sleep(1.0)
        b = None
        try:
            b = measure.Board(settle=3.0)
            b.stop()
            b.drain_console(0.4)
            c = b.ctl()
            ok = c is not None
            ident = c.identity()["track"] if ok else "-"
            print("%2d  ctl=%-5s track=%s" % (i, "OK" if ok else "NONE", ident),
                  flush=True)
            if not ok:
                fails += 1
                print("    ---- capturing u and E before any re-flash ----")
                for cmd in ("u", "E"):
                    b.poll_console()
                    b.cmd(cmd)
                    out = b.drain_console(3.0) or ""
                    for line in out.splitlines():
                        print("    %s| %s" % (cmd, line.strip()))
        except Exception as e:                               # noqa: BLE001
            fails += 1
            print("%2d  EXCEPTION %s" % (i, e), flush=True)
        finally:
            if b is not None:
                try:
                    b.close()
                except Exception:                            # noqa: BLE001
                    pass

    print("\n%d of %d flashes failed to present a command port"
          % (fails, args.runs))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
