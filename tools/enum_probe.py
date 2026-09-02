"""Does Track A's command port fail to come up after a flash on Windows?

Issue #19: ~1 in 10 on the macOS bench, both occurrences Track A. If it
reproduces here it is the device; if 15 flashes are clean it points the
other way, and either answer is worth more than another occurrence there.

On failure, capture `u` and `E` from the programming port BEFORE
re-flashing - that is the evidence the first two occurrences did not
produce.
"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
fails = 0

for i in range(N):
    # measure.flash() rather than sketch.py, which is gone (#55).
    #
    # windows-desk's tool and windows-desk's hardcoded COM7, left as
    # they are - only the flash call is changed, because sketch.py was
    # deleted underneath it and a hardcoded caller is how a deletion
    # becomes a broken tool nobody finds until they next need it.
    # measure.flash() is the one place that knows how each track builds.
    try:
        measure.flash(track="a", build=True, control="COM7")
    except Exception as e:                               # noqa: BLE001
        print("%2d  FLASH FAILED: %s" % (i, e))
        continue
    time.sleep(1.0)
    b = None
    try:
        b = measure.Board(settle=3.0)
        b.stop(); b.drain_console(0.4)
        c = b.ctl()
        ok = c is not None
        ident = c.identity()["track"] if ok else "-"
        print("%2d  ctl=%-5s track=%s" % (i, "OK" if ok else "NONE", ident),
              flush=True)
        if not ok:
            fails += 1
            print("    ---- capturing u and E before any re-flash ----")
            for cmd in ("u", "E"):
                b.poll_console(); b.cmd(cmd)
                out = b.drain_console(3.0) or ""
                for l in out.splitlines():
                    print("    %s| %s" % (cmd, l.strip()))
    except Exception as e:                                   # noqa: BLE001
        fails += 1
        print("%2d  EXCEPTION %s" % (i, e), flush=True)
    finally:
        if b is not None:
            try:
                b.close()
            except Exception:                                # noqa: BLE001
                pass

print("\n%d of %d flashes failed to present a command port" % (fails, N))
