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

#: An OUT(...) call, capturing only its leading run of adjacent string
#: literals - which is the format, however many source lines it is
#: spread across. Everything after them is arguments.
_OUT_CALL = re.compile(
    r'OUT\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)[^;]*?\);', re.S)


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


#: One console_out emitter call, as it appears in a source line.
_EMIT = re.compile(r"con_(\w+)\(([^;]*)\);")

#: What each emitter contributes to the reconstructed format string. The
#: value emitters all become one placeholder because the comparison is
#: about *what is printed*, not about which width a column was given -
#: two tracks printing the same field with different padding are not two
#: diagnostics.
_EMIT_TEXT = {
    "u32": "%lu", "i32": "%lu", "u32w": "%lu", "u32l": "%lu",
    "hex32": "%lx", "strl": "%s", "pad": "",
}


def _emit_arg0(args):
    """The first argument of an emitter call, as written.

    The comma that ends it must not be one inside a string or character
    literal - `con_str(" Hz, ")` is a single argument, and splitting it
    at the comma yielded `" Hz` and then a stray `H` in the
    reconstructed format. Measured: it corrupted cmd_stream_uart's line
    to "trigger %lu H%s %lu Hz".
    """
    depth, cur, quote, esc = 0, "", None, False
    for ch in args:
        if quote:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
            continue
        if ch == "," and depth == 0:
            break
        depth += (ch in "([") - (ch in ")]")
        cur += ch
    return cur.strip()


def _fold_emitters(s):
    """Rewrite runs of con_* calls as the printf line they replaced.

    Issue #49 turned Track B's `printf("# a=%lu b=%lu\n", a, b)` into a
    run of emitter calls. That is one output statement written as six,
    so a line-based comparison sees a body six times longer than its
    pair and reports divergence in bodies that did not change at all -
    measured: `cmd_help`, six identical lines, fell from **1.00 to
    0.67** the day Track B migrated and Track A did not.

    So the run is folded back into a single `printf("...")` carrying the
    format string it reconstructs. Arguments are dropped on this side
    and on the other (see below): the question this tool asks is what a
    body *prints*, and `(unsigned long)x` against `x` was never a
    difference worth reporting.

    A `con_nl()` ends the line, which is where a `\n` used to be.
    """
    out, run = [], []

    def flush():
        if run:
            out.append('printf("' + "".join(run) + '");')
            run.clear()

    for line in s.splitlines():
        calls = _EMIT.findall(line)
        if not calls or _EMIT.sub("", line).strip():
            # Not a pure run of emitters - a control statement, a
            # declaration, an emitter buried in something else. Flush
            # what we have rather than guessing.
            flush()
            out.append(line)
            continue
        for name, args in calls:
            if name == "nl":
                run.append("\\n")
                flush()
            elif name == "str":
                a = _emit_arg0(args)
                run.append(a[1:-1] if a.startswith('"') else "%s")
            elif name == "ch":
                a = _emit_arg0(args)
                run.append(a[1:-1] if a.startswith("'") else "%c")
            elif name == "kv_u32":
                a = _emit_arg0(args)
                run.append((a[1:-1] if a.startswith('"') else "%s") + "=%lu")
            else:
                run.append(_EMIT_TEXT.get(name, "%lu"))
    flush()
    return "\n".join(out)


def normalise(s):
    """Code lines, with the output mechanism made common.

    Renaming the calls is not enough, and the residue is not random - it
    is structural, so it biases every printing body the same way:

      Track B      printf("text\n");
      Track A      snprintf(buf, sizeof(buf), "text");
                   Serial.println(buf);

    One line against two, and a trailing newline on one side that the
    other's println supplies implicitly. Renaming alone leaves those, so
    a body whose two copies say exactly the same thing scores as
    diverged - `cmd_help` is six lines that differ in nothing else and
    came out at 0.67.

    So the two-step is folded to one and the trailing newline dropped.
    What is left is what the function *does*.
    """
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)

    # Track B speaks a third dialect now - the console_out emitters of
    # issue #49 - and it has to be folded back to the same shape as the
    # other two or every migrated body reads as divergence. Do it first,
    # while the runs are still consecutive lines.
    s = _fold_emitters(s)

    # Track A's snprintf-into-buf followed by println(buf) is one output,
    # not two. Fold before renaming, while the shape is still visible.
    s = re.sub(r"snprintf\(\s*buf\s*,\s*sizeof\(buf\)\s*,\s*",
               "printf(", s)
    s = re.sub(r"\n\s*Serial\.println\(buf\);", "", s)

    for a, b in (("Serial.println", "OUT"), ("Serial.print", "OUT"),
                 ("snprintf", "OUT"), ("printf", "OUT"),
                 ("uart_flush", "FLUSH"), ("Serial.flush", "FLUSH")):
        s = s.replace(a, b)

    # println supplies the newline the printf side spells out.
    s = s.replace('\\n"', '"')

    # An output call's ARGUMENTS are not what this tool is asking about.
    # The question is what a body prints; `(unsigned long)trigger_hz`
    # against `trigger_hz` was never a difference worth reporting, and
    # after #49 one dialect carries its values inside the call and the
    # other does not, so leaving them in compares a line count rather
    # than a diagnostic. Keep the format string, drop the rest.
    s = _OUT_CALL.sub(lambda m: 'OUT(' + m.group(1) + ');', s)

    # The scratch buffer exists only to serve snprintf. It is output
    # mechanism, like the flush, so it goes the same way.
    s = re.sub(r"^\s*char (?:buf|line|label)\[[^\]]*\];\s*$", "", s,
               flags=re.M)

    # A conversion's width and flags are column layout, not diagnostic
    # content: `%8lu` and `%lu` print the same field. They have to be
    # collapsed on BOTH sides or the comparison is asymmetric - the
    # emitters carry width as an argument (con_u32w(v, 8, ' ')) which
    # this file has already reduced to a bare placeholder, so leaving
    # `%8lu` standing on the printf side would report divergence in a
    # body that prints identical fields. cmd_dac_sweep was doing exactly
    # that: `# %lu %lu %lu %lu` against `# %8lu %7lu %9lu %11lu`.
    s = re.sub(r"%[-+ 0#]*[0-9]*(?:l|ll|h|hh|z)?([diuxXocsp])", r"%\1", s)
    s = re.sub(r"%[diuxXo]", "%V", s)

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
