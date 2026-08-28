#!/usr/bin/env python3
"""The seam list for issue #14, extracted rather than curated.

`stream.c` and `stream.cpp` are one file written twice (issue #14), and
the plan for sharing them starts by *pinning* what each copy reaches
outside itself - before anything moves, so the move can be checked
against a recorded before. The eventual `stream_port.h` must declare
exactly the seam this tool extracts; a curated list would drift the way
the five one-underscore names already did.

The contract, in the shape of `tools/report.py`:

**The list is not the deliverable. The check is.** `--check` re-extracts
and compares against `tools/stream_seam.list`, name by name, and fails
on drift in either direction. The extraction is mechanical and the test
suite proves the check can fail (a wrong list must be noticed), because
a generated-artifact check that silently extracts nothing passes
forever - see issue #14's discussion of exactly that failure.

**Classification is by declaring header, not by judgement.** Every
external call is attributed to the included header that declares it,
resolved the way the build resolves it (own directory first, then the
fixed project include dirs). A name no project header declares is
`other` - libc, the Arduino core, CMSIS, compiler syntax - and is
pinned too, so a new dependency on the platform shows up in the same
diff as a new dependency on a seam module.

The one curated fact is which headers *are* the seam - acq, gen and the
transport - and that is the decision issue #14 records, not this tool's.

Known hole, noted in review (windows-desk, on the issue): a
function-like #define is not a prototype, so a macro-shaped interface
in a seam header would classify as "other". Today that is theoretical
- nothing either stream file calls is a macro - and the core check
turns it into a feature: a macro reaching stream_core.c fails the
"no shared header declares" arm until it becomes a function.

    python3 tools/stream_seam.py            # print the classified list
    python3 tools/stream_seam.py --write    # update tools/stream_seam.list
    python3 tools/stream_seam.py --check    # fail if the list drifted
"""
import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The two copies of the one file, and where each one's includes resolve.
# Include order mirrors the builds: the file's own directory wins, then
# the project-wide dirs both builds add (-I bsp, -I lib/due_shared/src).
SOURCES = {
    "a": os.path.join("sketches", "bringup", "stream.cpp"),
    "b": os.path.join("drivers", "stream.c"),
}
INCLUDE_DIRS = [os.path.join("bsp"), os.path.join("lib", "due_shared", "src")]

# Issue #14's decision: the seam stream_port.h will declare is the acq
# and gen interfaces plus the transport. Headers, not names - the names
# come from extraction.
SEAM_HEADERS = {"acq.h", "gen.h", "usbdma.h", "usb_cdc.h",
                "stream_port.h"}

LIST_PATH = os.path.join(REPO, "tools", "stream_seam.list")

# The shared framer and its dependency record (issue #14 step 3). The
# core may reach only what the record and the shared headers declare -
# plus the C library's memcpy - and the record may declare nothing the
# core does not use. Both directions are drift.
CORE = os.path.join("lib", "due_shared", "src", "stream_core.c")
PORT = os.path.join("lib", "due_shared", "src", "stream_port.h")
CORE_ALLOWED_OTHER = {"memcpy"}

KEYWORDS = {"if", "while", "for", "switch", "return", "sizeof", "do",
            "else", "defined",
            # compiler syntax that parses like a call and is not one
            "__attribute__", "aligned", "_Static_assert", "static_assert"}


def _strip(text):
    """Drop comments and string/char literals so they cannot fake calls."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r'"(\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(\\.|[^'\\])*'", "''", text)
    return text


def _read(relpath):
    with open(os.path.join(REPO, relpath)) as f:
        return f.read()


def called_names(text):
    """Every identifier used as a call: name followed by an open paren,
    not reached through . or -> (a member is the pointer's business)."""
    return {m.group(1)
            for m in re.finditer(r"(?<![\w.>])([A-Za-z_]\w*)\s*\(", text)
            } - KEYWORDS


def defined_names(text):
    """Names this file defines itself: functions (name(...){ ) and
    macros (#define name...), neither of which is an external call."""
    d = {m.group(1) for m in re.finditer(
        r"\b([A-Za-z_]\w*)\s*\([^;{()]*(?:\([^()]*\)[^;{()]*)*\)\s*\{",
        text)}
    d |= {m.group(1) for m in re.finditer(
        r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", text, flags=re.M)}
    return d - KEYWORDS


def declared_in_header(text):
    """What a header offers a caller: prototypes (name(...);) and
    static inline definitions (name(...) {), which are interface too -
    acq.h hands out its frame accessors that way."""
    d = {m.group(1)
         for m in re.finditer(
             r"\b([A-Za-z_]\w*)\s*\([^;{()]*(?:\([^()]*\)[^;{()]*)*\)\s*;",
             text)}
    d |= {m.group(1) for m in re.finditer(
        r"\b([A-Za-z_]\w*)\s*\([^;{()]*(?:\([^()]*\)[^;{()]*)*\)\s*\{",
        text)}
    return d - KEYWORDS


def extern_data_decls(text):
    """Variables a header shares: extern <type> name; or name[...];.

    The parenthesis guard keeps function prototypes out - a prototype
    has an argument list and a data declaration does not.
    """
    return {m.group(1) for m in re.finditer(
        r"\bextern\s+[^;()=]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;",
        text)}


def includes(text):
    """Quoted includes only - <...> is the platform's and stays other.

    Runs on raw text: _strip blanks string literals, and the include's
    file name is one.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return [m.group(1)
            for m in re.finditer(r'^[ \t]*#[ \t]*include[ \t]+"([^"]+)"',
                                 text, flags=re.M)]


def _resolve(header, srcdir):
    """Resolve an include the way the build does: the source's own
    directory first, then the project include dirs. None if the header
    is not this repository's (Arduino.h, sam.h)."""
    for d in [srcdir] + INCLUDE_DIRS:
        p = os.path.join(REPO, d, header)
        if os.path.isfile(p):
            # One separator on every platform. The pinned list is a
            # committed artifact, and os.path.join would spell these
            # paths with backslashes on Windows - which made every
            # name drift in both directions the first time the check
            # ran on the other bench.
            return os.path.join(d, header).replace(os.sep, "/")
    return None


def extract(relpath):
    """The classified external-call list for one stream file.

    Returns {name: origin} where origin is the repo-relative header
    that declares the name, or "other" when no included project header
    does.
    """
    raw = _read(relpath)
    text = _strip(raw)
    srcdir = os.path.dirname(relpath)

    decls = {}  # name -> header relpath, first include wins, like a build
    data = {}
    for inc in includes(raw):
        rp = _resolve(inc, srcdir)
        if rp is None:
            continue
        htext = _strip(_read(rp))
        for name in declared_in_header(htext):
            decls.setdefault(name, rp)
        for name in extern_data_decls(htext):
            data.setdefault(name, rp)

    out = {}
    for name in called_names(text) - defined_names(text):
        out[(name, "fn")] = decls.get(name, "other")

    # Extern data the file reaches is seam surface exactly as a call is
    # - the framer reads acq_produced and play_consumed straight out of
    # another module. Any identifier a header declares extern that
    # appears in the source at all is a reference; C has no other way
    # to spell one.
    idents = set(re.findall(r"\b[A-Za-z_]\w*\b", text))
    for name, rp in data.items():
        if name in idents and not _defines_data(text, name):
            out[(name, "data")] = rp
    return out


def _defines_data(text, name):
    """True if the file itself defines this variable at file scope - a
    module's own export (declared extern in its own header, defined
    here) is not a dependency. File scope is column 0 in this
    codebase's style, which both stream files follow."""
    return re.search(
        r"(?m)^(?!extern\b)[A-Za-z_][\w \t*]*\b" + re.escape(name) +
        r"\s*(?:\[[^\]]*\])*\s*(?:=[^;]*)?;", text) is not None


def seam(relpath):
    """Just the names the future stream_port.h must declare."""
    return {n for (n, _kind), org in extract(relpath).items()
            if os.path.basename(org) in SEAM_HEADERS}


def render():
    """The pinned-list text: one line per name, sorted, diffable."""
    lines = ["# generated by tools/stream_seam.py --write; do not edit.",
             "# <track> <declaring header|other> <fn|data> <name>"]
    for track in sorted(SOURCES):
        ext = extract(SOURCES[track])
        for name, kind in sorted(ext):
            lines.append(f"{track} {ext[(name, kind)]} {kind} {name}")
    return "\n".join(lines) + "\n"


def check(list_path=LIST_PATH):
    """Compare the pinned list against a fresh extraction.

    Returns a list of drift lines, empty when the two agree. A missing
    or empty pinned list is drift, never a pass - the failure mode this
    guards is a check that compares nothing and reports agreement.
    """
    want = render().splitlines()
    want = [l for l in want if not l.startswith("#")]
    try:
        with open(list_path) as f:
            have = [l.rstrip("\n") for l in f
                    if l.strip() and not l.startswith("#")]
    except OSError as e:
        return [f"unreadable pinned list: {e}"]
    if not want:
        return ["extraction produced nothing; the extractor is broken"]
    drift = []
    for line in sorted(set(want) - set(have)):
        drift.append(f"extracted but not pinned: {line}")
    for line in sorted(set(have) - set(want)):
        drift.append(f"pinned but not extracted: {line}")
    return drift


def port_decls(port_text=None):
    """Everything stream_port.h offers: functions and extern data."""
    if port_text is None:
        port_text = _strip(_read(PORT))
    return declared_in_header(port_text) | extern_data_decls(port_text)


def core_check(port_text=None):
    """Drift between stream_core.c and stream_port.h, both directions.

    Returns a list of complaint lines, empty when they agree. The
    port_text parameter exists for the test that proves this check can
    fail; the default is the real header.
    """
    ext = extract(CORE)
    if not ext:
        return ["extraction of stream_core.c produced nothing; "
                "the extractor is broken"]
    declared = port_decls(port_text)
    used = {name for (name, _kind) in ext}
    drift = []
    for (name, kind), origin in sorted(ext.items()):
        undeclared = (origin == "other" and name not in CORE_ALLOWED_OTHER) \
            or (os.path.basename(origin) == "stream_port.h"
                and name not in declared)
        if undeclared:
            drift.append(f"stream_core.c reaches {name} ({kind}), which "
                         "no shared header declares")
    for name in sorted(declared - used):
        drift.append(f"stream_port.h declares {name}, which "
                     "stream_core.c does not use")
    return drift


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="update tools/stream_seam.list")
    ap.add_argument("--check", action="store_true",
                    help="fail if the pinned list has drifted")
    args = ap.parse_args(argv)

    if args.check:
        drift = check() + core_check()
        for line in drift:
            print(line)
        return 1 if drift else 0
    if args.write:
        with open(LIST_PATH, "w") as f:
            f.write(render())
        print(f"wrote {os.path.relpath(LIST_PATH, REPO)}")
        return 0

    sys.stdout.write(render())
    for track in sorted(SOURCES):
        names = sorted(seam(SOURCES[track]))
        print(f"# seam[{track}]: {len(names)} names: {' '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
