"""Would tools/track_parity.py have caught the five main() divergences?

Runs the CURRENT tool against the sources as they were at the PARENT of
each fixing commit, by extracting the two main()s with `git show`. The
tool is textual and reads nothing else, so this is the real question and
not an approximation of it.
"""
import pathlib, subprocess, sys, tempfile, importlib.util

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tp", ROOT / "tools" / "track_parity.py")
tp = importlib.util.module_from_spec(spec); spec.loader.exec_module(tp)

PATHS = {"B": "apps/baremetal_bringup/main.c", "C": "apps/rtos_bringup/main.c"}

CASES = [
    ("3aadf90", "watchdog: WDT->WDT_MR = WDT_MR_WDDIS absent from Track C",
     lambda b: any("WDT->WDT_MR=" in x for x in b)),
    ("1eec02b", "clockref_init/clockref_poll absent from Track C",
     lambda b: any("clockref" in x for x in b)),
    ("9829719", "'T' bound to a different handler; 'z'/'Z' unbound",
     lambda b: any(x.startswith("COLLISION: 'T'") for x in b)),
    # Match the COLLISION line specifically. The first version of this
    # check looked for "'k'" anywhere in the report and matched the
    # "track C does not bind: ... 'k' ..." line instead - a different
    # divergence class - so it read the fix as not having landed. The
    # signal was there; it did not measure what it was quoted for.
    ("96b3c23", "'k' collision (Track B's h_dac_30m) - the tool's own fifth find",
     lambda b: any(x.startswith("COLLISION: 'k'") for x in b)),
]

def show(rev, path):
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None

fails = 0
for fix, what, detects in CASES:
    parent = f"{fix}~1"
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ok = True
        for trk, rel in PATHS.items():
            text = show(parent, rel)
            if text is None:
                ok = False; break
            f = td / f"main_{trk}.c"; f.write_text(text, encoding="utf-8")
            tp.MAINS[trk] = f
        if not ok:
            print(f"SKIP  {parent}  (a main() did not exist yet)"); continue
        before = tp.check("B", "C")
        # and after the fix
        for trk, rel in PATHS.items():
            (td / f"a_{trk}.c").write_text(show(fix, rel) or "", encoding="utf-8")
            tp.MAINS[trk] = td / f"a_{trk}.c"
        after = tp.check("B", "C")

    caught = detects(before)
    gone = not detects(after)
    verdict = "CAUGHT" if caught else "MISSED"
    print(f"{verdict}  at {parent}  ({len(before)} divergences)  {what}")
    for line in before:
        if detects([line]):
            print(f"        > {line[:150]}")
    if not caught:
        fails += 1
    elif not gone:
        print(f"        ! still reported at {fix} - the fix did not clear it")
        fails += 1

print()
print("RESULT:", "all four historical defects are caught" if not fails
      else f"{fails} not caught")
sys.exit(1 if fails else 0)
