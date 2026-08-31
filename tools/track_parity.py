#!/usr/bin/env python3
"""Compare the tracks' console tables and main() init, as lists.

Every track's `main()` is the one file it does not share, and two
things live in it that must stay in step across tracks: the board
init sequence, and the console command table. Nothing fails when an
addition to one does not reach the other - not the build, not the
link, and not a board test, because a missing command is usually only
reachable by a test that already skips on that track.

Four real defects on 2026-08-31, all Track C, all invisible until
something else went looking:

  WDT->WDT_MR = WDT_MR_WDDIS   absent -> the board reset every 17 s
  clockref_init/poll           absent -> #52's reference never ran
  'T'                          bound to a DIFFERENT handler than B's
  'z', 'Z'                     absent -> Board.reset() a silent no-op

The third is the one a human reader will not catch: both tracks answer
`T`, neither errors, and only the behaviour differs. Only a comparison
of the two tables side by side shows it.

This is deliberately a TOOL and not a test. tests/ is in flight on
issues #50 and #54 and belongs to another bench this week; wiring this
into the suite is a one-line call to check() and is theirs to place.

Parsing is textual on purpose - no compiler, no board, no build. It
reads what a reviewer reads.
"""
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

MAINS = {
    "A": ROOT / "sketches" / "bringup" / "bringup.ino",
    "B": ROOT / "apps" / "baremetal_bringup" / "main.c",
    "C": ROOT / "apps" / "rtos_bringup" / "main.c",
}

# `{ 'h', h_help }` / `{ 'h', h_help },` with any spacing.
_ENTRY = re.compile(r"\{\s*'(\\?.)'\s*,\s*([A-Za-z_]\w*)\s*\}")

# A bare call statement at the top of main(): `led_init();`. Deliberately
# not a general expression parser - init is written as statements here,
# and anything cleverer would silently disagree with the reviewer's eye.
_CALL = re.compile(r"^\s*([a-z_]\w*)\s*\([^;]*\)\s*;\s*$")

# `WDT->WDT_MR = WDT_MR_WDDIS;` and friends: a register write is init too,
# and the watchdog defect was exactly one of these.
_REG = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*->\s*([A-Z][A-Za-z0-9_]*)\s*=")


def table(path):
    """The console command table as {letter: handler}."""
    if not path.exists():
        return None
    out = {}
    for letter, handler in _ENTRY.findall(path.read_text(errors="replace")):
        out[letter] = handler
    return out


def _body(text, start):
    """The braced body of the function whose signature starts at `start`.

    Brace matching rather than a stop-pattern. The first version looked
    for `for(;;)` or `void loop(`, which on Track A spanned from
    setup() at line 1109 to loop() at line 2113 and swallowed every
    function defined in between - 132 divergences, essentially all of
    them noise. A tool that cries wolf about a real class of defect is
    worse than no tool.
    """
    i = text.find("{", start)
    if i < 0:
        return ""
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j]
        j += 1
    return text[i:]


def init_sequence(path):
    """Init statements in the track's entry function.

    main() on the bare-metal and RTOS tracks; setup() on Track A, which
    is an Arduino sketch - the core supplies main() and calls setup()
    once, so they are the same position in the program under different
    names.

    **This compares call NAMES, so read a divergence before acting on
    it.** A track that does the same job better under another name reads
    as divergent here, and two of the three currently reported are that:

      "track C main() does not do: banner()"

    Track C ends with console_identity() and console_flush() instead.
    That is the *better* arrangement - CLAUDE.md says "ask a board what
    it is with `v`, not with the banner", and invariant 8 prices the
    banner at 89 ms of blocked main loop. Adding banner() to Track C to
    silence this line would make the image worse.

    A-vs-B init is the same story at larger scale: Track A is an Arduino
    sketch, so pinMode/analogReadResolution stand where Track B writes
    registers, and acq_init/gen_init are adc_init/dac_init renamed. Five
    of its six differences are decomposition.

    This is why tests/test_track_parity.py asserts nothing about init.
    The console table is a shared contract and is asserted; init is not
    one, is reported only, and needs a reader.
    """
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    m = (re.search(r"^int\s+main\s*\(", text, re.M)
         or re.search(r"^void\s+setup\s*\(", text, re.M))
    if not m:
        return None
    body = _body(text, m.start())
    # Init ends where the service loop begins.
    end = re.search(r"for\s*\(\s*;\s*;\s*\)|vTaskStartScheduler\s*\(",
                    body)
    if end:
        body = body[:end.start()]
    seq = []
    for line in body.splitlines():
        c = _CALL.match(line)
        if c:
            seq.append(c.group(1) + "()")
            continue
        r = _REG.match(line)
        if r:
            seq.append("%s->%s=" % (r.group(1), r.group(2)))
    return seq


def _norm(handler):
    """Handler names differ by track convention, not by behaviour.

    Track A writes `ha_xtalk`, Track B `h_xtalk` and Track C would
    write `c_xtalk` for the same command. Comparing raw names calls
    every shared binding a collision and buries the real ones - which
    is what the first run of this tool did: 16 false positives hiding
    one true one, and then a second round of them on Track A's two-
    letter prefix.
    """
    return re.sub(r"^[a-z]{1,2}_", "", handler)


def check(left="B", right="C"):
    """Return a list of human-readable divergences. Empty means parity."""
    lt, rt = table(MAINS[left]), table(MAINS[right])
    ls, rs = init_sequence(MAINS[left]), init_sequence(MAINS[right])
    bad = []
    if lt is None or rt is None or ls is None or rs is None:
        return ["could not parse one of the two main()s"]

    for letter in sorted(set(lt) & set(rt)):
        if _norm(lt[letter]) != _norm(rt[letter]):
            bad.append(
                "COLLISION: %r is %s on track %s and %s on track %s - "
                "both answer, neither errors, only the behaviour differs"
                % (letter, lt[letter], left, rt[letter], right))

    missing = sorted(set(lt) - set(rt))
    if missing:
        bad.append("track %s does not bind: %s"
                   % (right, " ".join(repr(c) for c in missing)))
    extra = sorted(set(rt) - set(lt))
    if extra:
        bad.append("track %s binds what %s does not: %s"
                   % (right, left, " ".join(repr(c) for c in extra)))

    for call in ls:
        if call not in rs:
            bad.append("track %s main() does not do: %s" % (right, call))
    return bad


# Console commands the suite and the host harness actually send. The
# two forms cover `cmd("X")`, `cmd("=<n>X")` and `cmd("=%dX" % n)`.
_USE = re.compile(r'(?:cmd|ask)\(\s*[fr]?"(?:=[^"]*?)?([A-Za-z0-9])"')
_USE_FMT = re.compile(r'(?:cmd|ask)\(\s*[fr]?"=%[^"]*?([A-Za-z])"')


def needed(left="B", right="C"):
    """Unbound commands the suite/host actually uses, most-used first.

    The point is to size a porting decision honestly. "Track C is
    missing 34 of Track B's commands" reads as a large piece of work;
    most of those 34 are Track B debug knobs that nothing outside
    Track B's own main.c has ever sent, and the suite cannot fail for
    want of them.

    Textual, so it is a LOWER bound: a command assembled at runtime
    from a variable would not be seen here. Every form currently in
    tests/ and host/ is a literal.
    """
    import collections
    lt, rt = table(MAINS[left]), table(MAINS[right])
    if lt is None or rt is None:
        return []
    unbound = set(lt) - set(rt)
    use, where = collections.Counter(), collections.defaultdict(set)
    for d in ("tests", "host"):
        for path in sorted((ROOT / d).glob("*.py")):
            text = path.read_text(errors="replace")
            for m in list(_USE.finditer(text)) + list(_USE_FMT.finditer(text)):
                ch = m.group(1)
                use[ch] += 1
                where[ch].add(path.name)
    out = [(use[c], c, lt[c], sorted(where[c])) for c in unbound if use[c]]
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def main(argv):
    left, right = (argv + ["B", "C"])[:2]
    print("console table and main() init: track %s against track %s\n"
          % (left, right))
    bad = check(left, right)
    for b in bad:
        print("  " + b)
    if not bad:
        print("  parity")
    print("\n%d divergence(s)" % len(bad))

    need = needed(left, right)
    if need:
        print("\nof the unbound commands, these are ones tests/ or host/ "
              "actually send:\n")
        for n, ch, handler, files in need:
            print("  %r  %-14s %2d call site(s)   %s"
                  % (ch, handler, n, " ".join(files)))
        print("\n  %d needed; the rest are never sent by anything outside "
              "track %s's own main()" % (len(need), left))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
