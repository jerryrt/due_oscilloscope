#!/usr/bin/env python3
"""Which paired console bodies are one logic, and which only share a name?

Issue #45 is "share the application layer maximally", and both benches
sized it by counting lines in functions that appear on both tracks:
2,531 lines by one count, 1,204 by mine, 694 after stripping comments.
Every one of those numbers assumes a paired *name* means paired
*behaviour*.

Measured, it usually does not. Run this before moving anything.

Two bodies can differ three ways and only the first is de-duplication:

  same logic          identical once the output mechanism is neutralised.
                      Moving it removes a copy and changes nothing.
  diverged copies     the same diagnostic, drifted. Moving it is a merge
                      and someone has to choose which drift survives.
  different           two different diagnostics wearing one name. Moving
  diagnostics         it DELETES one of them. That is not sharing.

The output mechanism is neutralised deliberately - printf against
Serial.print, uart_flush against Serial.flush - because console_write()
and console_flush() already solve that difference and it would otherwise
make every pair look unlike itself.

    python3 tools/console_pairs.py
    python3 tools/console_pairs.py --show cmd_read
"""
import argparse
import difflib
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKS = {"b": os.path.join("apps", "baremetal_bringup", "main.c"),
          "a": os.path.join("sketches", "bringup", "bringup.ino")}

#: Named bodies the console handlers call. Handlers themselves are thin
#: adapters and were measured not worth moving: only one of 48 moves
#: without naming something new in a port, and the other 24 would cost
#: 23 port names of which 17 buy a single handler each.
BODY = re.compile(
    r"^static (?:void|bool|uint32_t|int) "
    r"(cmd_[a-z0-9_]+|identity_line|gen_report|diag_start|trigger_fault"
    r"|measure_gpio|measure_printf|play_dump|bleed_settle)\s*\(", re.M)

SAME, DIFFERENT = 0.85, 0.55


def bodies(relpath):
    with open(os.path.join(REPO, relpath), encoding="utf-8") as f:
        t = f.read()
    out = {}
    for m in BODY.finditer(t):
        i = t.index("{", m.end())
        d, j = 0, i
        while j < len(t):
            if t[j] == "{":
                d += 1
            elif t[j] == "}":
                d -= 1
                if d == 0:
                    break
            j += 1
        out[m.group(1)] = t[i:j + 1]
    return out


def normalise(s):
    """Code lines, with the output mechanism made common."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    for a, b in (("Serial.println", "OUT"), ("Serial.print", "OUT"),
                 ("snprintf", "OUT"), ("printf", "OUT"),
                 ("uart_flush", "FLUSH"), ("Serial.flush", "FLUSH")):
        s = s.replace(a, b)
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def classify(ratio):
    if ratio > SAME:
        return "same logic"
    if ratio < DIFFERENT:
        return "DIFFERENT diagnostics"
    return "diverged copies"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", help="print both bodies of one name")
    args = ap.parse_args()

    A, B = bodies(TRACKS["a"]), bodies(TRACKS["b"])
    if args.show:
        for tag, src in (("track B", B), ("track A", A)):
            print(f"--- {tag} ---")
            print("\n".join(normalise(src[args.show])))
        return

    print(f"{'body':<22}{'B/A':>9}{'similarity':>12}   reading")
    tally = {}
    for n in sorted(set(A) & set(B)):
        a, b = normalise(A[n]), normalise(B[n])
        r = difflib.SequenceMatcher(None, a, b).ratio()
        v = classify(r)
        tally[v] = tally.get(v, 0) + 1
        print(f"{n:<22}{f'{len(b)}/{len(a)}':>9}{r:>11.2f}   {v}")
    print()
    for k in ("same logic", "diverged copies", "DIFFERENT diagnostics"):
        print(f"  {tally.get(k, 0):>2}  {k}")
    print("\nOnly the first line is de-duplication. The third deletes a "
          "diagnostic;\nthe second is a merge somebody has to decide.")


if __name__ == "__main__":
    main()
