"""The documents name paths; the paths must still exist.

Needs no board and opens nothing. It reads `CLAUDE.md`, `README.md`,
`CONTRIBUTING.md` and every `docs/*.md`, and the output of
`git ls-files`.

`CLAUDE.md` is read by every agent on every task whether they went
looking or not, which makes a stale line in it more expensive than a
stale line anywhere else - it is repeated into work rather than found
during it. The rest of the documents are read when someone goes looking,
and what they find has to point at something: `docs/HANDOFF.md` was
deleted while eleven `docs/` files and `CLAUDE.md` cited it, and
`tools/sketch.sh` outlived its deletion in four documents for five days,
while the suite stayed green. `tests/test_census.py` reads a function,
and `tests/test_comment_style.py` scans source directories; nothing was
reading the prose.

Two properties are cheap enough to hold mechanically:

  * every path a document names still exists, and
  * every constant `CLAUDE.md` states still has that value in the code.

Everything else in these files is prose, measurement and judgement, and
no test can hold those. Do not try: a guard that pretends to check a
claim it cannot check is worse than the claim going unchecked.

**What the reference scan reads, and what it does not.** Inline code
spans only, split on whitespace so a path inside a command line is seen.
Fenced blocks are deliberately out of scope: their tokens are
shell-quoted and flag-prefixed - `-DCMAKE_TOOLCHAIN_FILE=cmake/...` does
not tokenise as a path without a second splitting rule - and the paths
they do yield are build outputs and venv paths that no fresh checkout
has. Scanning them would buy two real references for six standing
exemptions and a tokeniser that misses things without saying so.

A token with a slash is a path candidate when its last segment carries
a source extension or its first segment is a tracked top-level
directory. Prose elides with slashes too - `rate/tone`, `ADC_SEQR1/2`,
`origin/main`, `ttyACM0/1/2` - and none of those starts with a
directory this tree has, so the rule drops them without an allowlist
entry each. What it cannot see is a reference whose whole top-level
directory has gone; that shape has not happened here, and a scan that
read every slash would cost a dozen exemptions to catch it.

**A path is resolved against `git ls-files`, not the filesystem**, so
the answer is the same on every bench: a build directory, a venv and a
per-bench record file are not the tree. The basename fallback is
deliberate - the prose writes `frame.h` for
`lib/due_shared/src/frame.h`, and a rule refusing that would mean twelve
false positives here or an unreadable file. It also means a document
naming a deleted path whose basename survives elsewhere is not caught;
that is the price of the fallback, and it is paid knowingly.
"""
import collections
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------
# Check 1 - every path a document names resolves
# ---------------------------------------------------------------------

#: What is scanned. Every Markdown document a reader is routed to; the
#: standing pages live on the issue tracker and are not in the tree.
DOCUMENTS = tuple(["CLAUDE.md", "README.md", "CONTRIBUTING.md"]
                  + sorted("docs/" + f for f in os.listdir(
                      os.path.join(REPO, "docs")) if f.endswith(".md")))

#: A token that could be a repository path. Relative only: a leading `/`
#: or `~` is a device node, a MacPorts prefix or a home directory, and
#: none of those is this tree's to guarantee.
_PATHISH = re.compile(r"^(?![/~])[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*/?$")

#: Extensions that make a token a file reference. Without this,
#: `CMakeLists.txt` and `toolchains.json` - both named in CLAUDE.md, both
#: at the repository root - would not be candidates at all. A slash-free
#: token also needs a stem: a bare `.json` or `.c` in prose is a kind of
#: file, not a file.
_EXT = re.compile(r"\.(?:c|h|cpp|py|md|sh|json|jsonl|txt|ld|cmake|ini|yml)$")

#: Inline code spans. The lookarounds keep the fence markers of a
#: ```-delimited block from being read as an empty span whose neighbours
#: then pair up wrongly.
_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")

#: Paths the documents name on purpose that this tree does not contain,
#: and why each one is not a defect. Every entry is asserted still absent
#: and still cited: an exemption that has quietly become resolvable, or
#: whose sentence has gone, is a standing permission nobody re-reads.
ALLOWED = {
    # The Arduino core, which is fetched by the SAM package and lives
    # under ~/.arduino15. The documents name these to say what the core
    # does, or gets wrong, about the hardware.
    "boards.txt": "Arduino SAM package, outside this repository",
    "platform.txt": "Arduino SAM package, outside this repository",
    "flash.ld": "Arduino SAM core linker script, outside this repository",
    "variant.cpp": "Arduino SAM variant table, outside this repository",
    "Arduino.h": "Arduino SAM core header, outside this repository",
    "wiring_analog.c": "Arduino SAM core source, outside this repository",
    "syscalls_sam3.c": "Arduino SAM core source, outside this repository",
    "USBCore.cpp": "Arduino SAM core source, outside this repository",
    "uotghs_device.h": "Arduino SAM libsam header, outside this repository",
    "cores/arduino/USB/CDC.cpp":
        "Arduino SAM core source, outside this repository",
    "system/libsam/source/uotghs_device.c":
        "Arduino SAM libsam source, outside this repository",

    # Deleted on purpose, and the two CLAUDE.md sentences naming it
    # record that: CLAUDE.md is the one document that carries recorded
    # mistakes, and a Track A build path that was retired is one.
    "tools/sketch.py":
        "deleted with the arduino-cli build path; CLAUDE.md records that",

    # The FreeRTOS kernel, fetched at configure time by Track C's build.
    "heap_4.c": "FreeRTOS kernel source, fetched at configure time",
    "port.c": "FreeRTOS kernel port, fetched at configure time",

    # Written per bench and gitignored, so each is absent from a fresh
    # checkout by design rather than by accident. `.gitignore` says why
    # for every one of them.
    "records/flash-log.jsonl":
        "written by tools/flash.py per bench; gitignored",
    "bench.json": "one desk's cabling, per host/provenance.py; gitignored",
    "toolchains.local.json":
        "per-machine tool locations beside toolchains.json; gitignored",
    "compile_commands.json": "CMake build output; gitignored",
    "baseline.measured.json":
        "written by --calibrate for a human to promote; gitignored",
    "tests/baseline.measured.json":
        "written by --calibrate for a human to promote; gitignored",
}

#: References that must survive any reformatting, so a pattern that has
#: stopped matching fails by name instead of going quiet. One of each
#: shape the scan has to see: a path with a slash, a slash-free file
#: recognised by its extension, a path written inside a command line,
#: and one from a document other than CLAUDE.md.
_ANCHORS = {
    "CLAUDE.md": ("docs/scope.md", "CMakeLists.txt", "host/ports.py"),
    "docs/testing.md": ("host/measure.py",),
}

#: What the scan currently reads. A pattern that stops matching, or a
#: document set that loses half its references, has to be loud rather
#: than green - the bounds are wide enough not to fail on ordinary
#: editing and narrow enough that reading nothing cannot pass. The
#: CLAUDE.md row is separate because that file is the one every session
#: loads, and a scan of it going quiet should say so by name.
_MIN_REFS = {"CLAUDE.md": 55, "*": 400}
_MAX_REFS = {"CLAUDE.md": 140, "*": 1000}
_MIN_RESOLVED = {"CLAUDE.md": 45, "*": 350}


def _git_files():
    """Every tracked path, or a failure - never a skip.

    A bench with no git is not a bench that can build this firmware:
    `cmake/fw_git_rev.cmake` stamps the commit into every image on
    every track. So the absent-git case is a broken checkout to report,
    and reporting it as a skip is the substitution
    `--require-board` exists to refuse elsewhere.
    """
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                         capture_output=True, text=True)
    assert out.returncode == 0, (
        f"`git ls-files` failed in {REPO}: {out.stderr.strip()!r}. This "
        "guard resolves the documents' paths against the index rather "
        "than the filesystem, so it cannot run without one")
    files = [p for p in out.stdout.split("\0") if p]
    assert len(files) > 100, (
        f"`git ls-files` returned {len(files)} paths, which is not this "
        "repository; every reference below would read as broken")
    return files


def _index():
    """Tracked paths, the directories they imply, and their basenames."""
    files = _git_files()
    dirs = set()
    for path in files:
        parts = path.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return set(files), dirs, {os.path.basename(p) for p in files}


def _top_dirs():
    return {d for d in _index()[1] if "/" not in d}


def _candidate(tok, tops):
    """Whether one whitespace-split token from a code span is a path."""
    if not _PATHISH.match(tok):
        return False
    if "/" in tok:
        return bool(_EXT.search(tok)) or tok.split("/", 1)[0] in tops
    return bool(_EXT.search(tok)) and not tok.startswith(".")


def _references(doc, tops=None):
    """token -> line numbers, for every path-like inline code span."""
    if tops is None:
        tops = _top_dirs()
    found = collections.defaultdict(list)
    for lineno, line in enumerate(_read(*doc.split("/")).splitlines(), 1):
        for span in _SPAN.findall(line):
            for tok in span.split():
                if _candidate(tok, tops):
                    found[tok].append(lineno)
    return dict(found)


def _all_references(tops):
    """(doc, token) -> line numbers, across every document."""
    out = {}
    for doc in DOCUMENTS:
        for tok, lines in _references(doc, tops).items():
            out[(doc, tok)] = lines
    return out


def _resolve(tok, files, dirs, bases):
    """"exact", "basename" or "nowhere" for one reference."""
    stem = tok.rstrip("/")
    if stem in files or stem in dirs:
        return "exact"
    if os.path.basename(stem) in bases:
        return "basename"
    return "nowhere"


def test_the_document_set_is_what_it_claims_to_be():
    """The list is built from the filesystem, so hold its shape.

    A `docs/` that has been moved, or a listing that returns nothing,
    would leave every test below parametrised over CLAUDE.md alone and
    green.
    """
    assert len(DOCUMENTS) >= 20, (
        f"only {len(DOCUMENTS)} documents found: {DOCUMENTS}. The scan is "
        "meant to cover every docs/*.md plus the three at the root")
    assert "docs/testing.md" in DOCUMENTS and "docs/scope.md" in DOCUMENTS
    tracked = set(_git_files())
    untracked = [d for d in DOCUMENTS if d not in tracked]
    assert not untracked, (
        f"{untracked} are scanned but not tracked; either add them or "
        "they are one bench's scratch and do not belong in docs/")


def test_the_reference_scan_reads_what_it_claims_to():
    """The counts, and a few references by name.

    Without this the checks below are satisfied by a pattern that
    matches nothing: reformat a document, or break the regex, and an
    empty candidate set passes every assertion about it. This project
    has four recorded guards that went green while checking zero of
    what they named, and `docker/run-cppcheck.sh` draws the same
    distinction in its exit codes - found nothing is not analysed
    nothing.

    The anchors are the half a count cannot give. A pattern narrowed
    until it reads only slash-free filenames would still produce a
    plausible number.
    """
    tops = _top_dirs()
    every = _all_references(tops)
    claude = {tok for (doc, tok) in every if doc == "CLAUDE.md"}
    counts = {"CLAUDE.md": len(claude), "*": len(every)}
    for key, n in counts.items():
        assert _MIN_REFS[key] <= n <= _MAX_REFS[key], (
            f"{key} yields {n} path references, outside the expected "
            f"{_MIN_REFS[key]}-{_MAX_REFS[key]}. Either the documents "
            "changed shape or this scan has stopped reading them; a "
            "reference check over nothing passes for the wrong reason")

    missing = [f"{doc}: {a}" for doc, anchors in _ANCHORS.items()
               for a in anchors if (doc, a) not in every]
    assert not missing, (
        f"{missing} are no longer parsed out of the documents. Each is "
        "one shape this scan has to see - a path with a slash, a "
        "slash-free file known by its extension, a path inside a command "
        "line, and one outside CLAUDE.md - so losing one means the "
        "pattern reads less than it claims. If the document genuinely "
        "stopped naming it, pick another anchor of the same shape rather "
        "than deleting the assertion")


@pytest.mark.parametrize("doc", DOCUMENTS)
def test_every_path_a_document_names_resolves(doc):
    """A path in a document points at something, or it is allowlisted.

    `docs/HANDOFF.md` was deleted while twelve files cited it, and
    nothing in the suite noticed. That is the failure this catches, and
    it is cheap to catch because a path is the one claim in a document
    that has a mechanical answer.
    """
    files, dirs, bases = _index()
    refs = _references(doc, {d for d in dirs if "/" not in d})

    broken = []
    for tok, lines in sorted(refs.items()):
        where = _resolve(tok, files, dirs, bases)
        if where == "nowhere" and tok not in ALLOWED:
            at = ", ".join(f"line {n}" for n in lines)
            broken.append(f"{tok} ({at})")

    assert not broken, (
        f"{doc} names paths that are not in the tree: "
        + "; ".join(broken)
        + ". Correct the reference, or - if the path is deliberately "
        "outside this repository - add it to ALLOWED with the reason")


def test_enough_references_resolve_for_the_check_to_mean_anything():
    """The check above is vacuous if almost everything is allowlisted."""
    files, dirs, bases = _index()
    every = _all_references({d for d in dirs if "/" not in d})
    resolved = {
        "CLAUDE.md": sum(1 for (doc, tok) in every if doc == "CLAUDE.md"
                         and _resolve(tok, files, dirs, bases) != "nowhere"),
        "*": sum(1 for (doc, tok) in every
                 if _resolve(tok, files, dirs, bases) != "nowhere"),
    }
    for key, n in resolved.items():
        assert n >= _MIN_RESOLVED[key], (
            f"only {n} references in {key} resolved, against "
            f"{_MIN_RESOLVED[key]} expected; the allowlist is carrying "
            "the check")


def test_every_allowlist_entry_is_still_absent_and_still_cited():
    """An exemption goes when its reason does, in either direction.

    `tests/test_clean_build.py` carried two dead ALLOWED entries until
    2026-09-04, and the lesson there is the one that applies here: an
    exemption costs nothing on the day it is written and everything on
    the day the thing it exempts changes. Two ways for that to happen
    and both are checked - a path that has appeared in the tree, so the
    entry now hides a real reference from the scan, and a path no
    document names any more, so the entry is a permission for nothing.
    """
    files, dirs, bases = _index()
    cited = {tok for (_doc, tok)
             in _all_references({d for d in dirs if "/" not in d})}

    now_resolvable = sorted(
        f"{tok} (resolves as {_resolve(tok, files, dirs, bases)}; "
        f"exempted as {reason!r})"
        for tok, reason in ALLOWED.items()
        if _resolve(tok, files, dirs, bases) != "nowhere")
    assert not now_resolvable, (
        "these are on the allowlist and now resolve, so the exemption is "
        "hiding a reference the scan would otherwise check: "
        + "; ".join(now_resolvable))

    uncited = sorted(tok for tok in ALLOWED if tok not in cited)
    assert not uncited, (
        f"{uncited} are allowlisted and no document names them any more. "
        "An entry nobody re-reads is how an exemption outlives its "
        "reason; delete it")


# ---------------------------------------------------------------------
# Check 2 - the constants CLAUDE.md states match the code
# ---------------------------------------------------------------------

#: symbol, the file that defines it, how to read the value out of that
#: file, how to read the value out of CLAUDE.md, and values in CLAUDE.md
#: that are not a claim about the symbol.
#:
#: Both patterns capture, and both must match. A symbol whose source
#: pattern finds nothing is a constant that has moved or been renamed -
#: which is exactly the drift this catches - so it fails rather than
#: skips. A CLAUDE.md pattern that finds nothing means the sentence was
#: reworded and this row has to be re-read, which is also a failure and
#: not a silent pass.
#:
#: Only symbols whose value CLAUDE.md actually states are here.
#: `PLAY_PRIME_BUFS` is the near miss worth naming: the file states
#: `PLAY_PRIME_BUFS = 4`, which is the value the defect had, and the
#: current 24 appears only as "raising it to 24" in the prose around it.
#: Pairing the symbol with the first number would fail on a correct
#: tree, and pairing it with the second would be reading a sentence this
#: cannot parse reliably.
_Const = collections.namedtuple(
    "_Const", "symbol file source claude ignore")


def _c(symbol, file, source, claude, ignore=()):
    return _Const(symbol, file, source, claude, frozenset(ignore))


CONSTANTS = [
    # "TIOA0 is capped by `ACQ_MIN_RC` = 86 at 453,488 Hz".
    _c("ACQ_MIN_RC", "drivers/acq.h",
       r"^#define\s+ACQ_MIN_RC\s+(\d+)u?\s*$",
       r"`ACQ_MIN_RC`\s*=\s*(\d+)"),

    # The identity line, and "All three tracks report `ctlver=4`".
    # `ctlver=0` is the documented sentinel for a track with no control
    # channel - a statement about the protocol, not about this version.
    _c("CTL_VERSION", "lib/due_shared/src/ctl_wire.h",
       r"^#define\s+CTL_VERSION\s+(\d+)\s*$",
       r"\bctlver=(\d+)", ignore={"0"}),

    _c("FRAME_VERSION", "lib/due_shared/src/frame.h",
       r"^#define\s+FRAME_VERSION\s+(\d+)\s*$",
       r"\bframever=(\d+)"),

    # `fw=0.2.0` in the identity line. Read as the three fields
    # together, because FW_VERSION_STR is derived from them and the
    # string is what the line carries.
    _c("FW_VERSION_STR", "lib/due_shared/src/fw_version.h",
       r"#define\s+FW_VERSION_MAJOR\s+(\d+)\s*\n"
       r"#define\s+FW_VERSION_MINOR\s+(\d+)\s*\n"
       r"#define\s+FW_VERSION_PATCH\s+(\d+)\s*$",
       r"\bfw=(\d+\.\d+\.\d+)\b"),

    # "a constant 512-byte write, `Feeder.WRITE_SIZE`", and "A constant
    # 512 bytes is lossless". Both are read; both have to agree.
    _c("Feeder.WRITE_SIZE", "host/measure.py",
       r"^\s+WRITE_SIZE\s*=\s*(\d+)\s*$",
       r"constant\s+(\d+)[\s-]+bytes?"),

    # "`OVERSUPPLIED = {44, 39}` in `tests/test_integrity.py` is this".
    _c("OVERSUPPLIED", "tests/test_integrity.py",
       r"^OVERSUPPLIED\s*=\s*(\{[^}]*\})\s*$",
       r"`OVERSUPPLIED\s*=\s*(\{[^}]*\})`"),

    # "Track A must be built with `--build-property
    # build.f_cpu=78000000L` or `micros()` is silently wrong", and the
    # host divides by the same number to compute an RC.
    _c("F_CPU", "cmake/track_a.cmake",
       r"^\s*F_CPU=(\d+)L\s*$",
       r"build\.f_cpu=(\d+)L"),
    _c("MCK_HZ", "host/measure.py",
       r"^MCK_HZ\s*=\s*([0-9_]+)\s*$",
       r"build\.f_cpu=(\d+)L"),
]


def _norm(value):
    """Digit groupings are a spelling, not a value: 78_000_000 is 78000000."""
    return value.replace("_", "") if re.fullmatch(r"[0-9_]+", value) else value


def _one(matches, what, where):
    """The single value a set of matches agrees on."""
    values = {_norm(m if isinstance(m, str) else ".".join(m))
              for m in matches}
    assert values, f"{what} matched nothing in {where}"
    assert len(values) == 1, (
        f"{what} reads {sorted(values)} from {where}, so {where} states "
        "the value more than one way and they disagree")
    return values.pop()


def test_the_constant_table_covers_more_than_one_claim():
    """A table emptied to one row would satisfy every test below."""
    assert len(CONSTANTS) >= 6, (
        f"only {len(CONSTANTS)} constants are checked. The table is meant "
        "to cover the values CLAUDE.md states outright; shrinking it is "
        "how this check stops being one")
    assert len({c.file for c in CONSTANTS}) >= 5, (
        "the table reads too few files to catch a constant moving")


@pytest.mark.parametrize("const", CONSTANTS, ids=lambda c: c.symbol)
def test_the_constants_claude_md_states_match_the_code(const):
    """One row: what the file defines against what CLAUDE.md says.

    Both sides fail loudly when they find nothing. A symbol missing from
    its named file is a constant that moved, and a skip there would hide
    precisely the rot this exists to catch - `bsp/load.c` is named in
    CLAUDE.md and the file is `lib/due_shared/src/load.c`, which is how
    quietly that happens.
    """
    source = _read(*const.file.split("/"))
    found = re.findall(const.source, source, re.M)
    assert found, (
        f"{const.symbol} is not defined in {const.file} any more - "
        f"nothing there matches {const.source!r}. It has been renamed, "
        f"moved or reformatted, and CLAUDE.md still states its value")
    in_code = _one(found, const.symbol, const.file)

    said = [m for m in re.findall(const.claude, _read("CLAUDE.md"))
            if _norm(m if isinstance(m, str) else ".".join(m))
            not in const.ignore]
    assert said, (
        f"CLAUDE.md no longer states a value for {const.symbol} in the "
        f"form {const.claude!r}. The sentence was reworded; re-read it "
        f"and update this row, because a pattern that matches nothing "
        f"is a check that passes for the wrong reason")
    in_doc = _one(said, const.symbol, "CLAUDE.md")

    assert in_code == in_doc, (
        f"{const.symbol} is {in_code} in {const.file} and CLAUDE.md says "
        f"{in_doc}. CLAUDE.md is loaded into every session, so a stale "
        f"value there is repeated into work rather than found during it")
