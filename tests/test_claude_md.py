"""`CLAUDE.md` is loaded into every session, and nothing else reads it.

Needs no board and opens nothing. It reads one file and the output of
`git ls-files`.

Every other document in this tree is read when someone goes looking for
it; `CLAUDE.md` is read by every agent on every task whether they went
looking or not, which makes a stale line in it more expensive than a
stale line anywhere else - it is repeated into work rather than found
during it. Nothing was watching it. `docs/HANDOFF.md` was deleted while
eleven `docs/` files and `CLAUDE.md` cited it and the suite stayed
green; `tests/test_census.py` reads a function, and
`tests/test_comment_style.py` scans source directories.

Two properties are cheap enough to hold mechanically:

  * every path it names still exists, and
  * every constant it states still has that value in the code.

Everything else in the file is prose, measurement and judgement, and no
test can hold those. Do not try: a guard that pretends to check a claim
it cannot check is worse than the claim going unchecked.

**What the reference scan reads, and what it does not.** Inline code
spans only, split on whitespace so a path inside a command line is seen.
Fenced blocks are deliberately out of scope: their tokens are
shell-quoted and flag-prefixed - `-DCMAKE_TOOLCHAIN_FILE=cmake/...` does
not tokenise as a path without a second splitting rule - and the paths
they do yield are build outputs and venv paths that no fresh checkout
has. Scanning them would buy two real references for six standing
exemptions and a tokeniser that misses things without saying so.

**A path is resolved against `git ls-files`, not the filesystem**, so
the answer is the same on every bench: a build directory, a venv and a
per-bench record file are not the tree. The basename fallback is
deliberate - the prose writes `frame.h` for
`lib/due_shared/src/frame.h`, and a rule refusing that would mean twelve
false positives here or an unreadable file.
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
# Check 1 - every path CLAUDE.md names resolves
# ---------------------------------------------------------------------

#: A token that could be a repository path. Relative only: a leading `/`
#: or `~` is a device node, a MacPorts prefix or a home directory, and
#: none of those is this tree's to guarantee.
_PATHISH = re.compile(r"^(?![/~])[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*/?$")

#: Extensions that make a slash-free token a file reference. Without
#: this, `CMakeLists.txt` and `toolchains.json` - both named in
#: CLAUDE.md, both at the repository root - would not be candidates at
#: all.
_EXT = re.compile(r"\.(?:c|h|cpp|py|md|sh|json|jsonl|txt|ld|cmake|ini|yml)$")

#: Inline code spans. The lookarounds keep the fence markers of a
#: ```-delimited block from being read as an empty span whose neighbours
#: then pair up wrongly.
_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")

#: Paths CLAUDE.md names on purpose that this tree does not contain, and
#: why each one is not a defect. Every entry is asserted still absent and
#: still cited: an exemption that has quietly become resolvable, or whose
#: sentence has gone, is a standing permission nobody re-reads.
ALLOWED = {
    # The Arduino core, which is fetched by the SAM package and lives
    # under ~/.arduino15. CLAUDE.md names these to say what the core
    # does, or gets wrong, about the hardware.
    "boards.txt": "Arduino SAM package, outside this repository",
    "platform.txt": "Arduino SAM package, outside this repository",
    "flash.ld": "Arduino SAM core linker script, outside this repository",
    "variant.cpp": "Arduino SAM variant table, outside this repository",
    "cores/arduino/USB/CDC.cpp":
        "Arduino SAM core source, outside this repository",

    # Deleted on purpose, and the sentence naming it says so.
    "tools/sketch.py":
        "deleted with issue #55; the sentence naming it records that",

    # Written per bench and gitignored, so it is absent from a fresh
    # checkout by design rather than by accident.
    "records/flash-log.jsonl":
        "written by tools/flash.py per bench; gitignored",

    # Not paths. The scan cannot tell a slash in prose from a separator,
    # and narrowing it enough to exclude these would also drop
    # `lib/due_shared` and every other extension-free directory the file
    # names.
    "origin/main": "a git ref, not a path",
    "wip/track-a-control-channel": "a deleted git branch, not a path",
    "rate/tone": "a ratio in prose, not a path",
    "FW_VERSION_MAJOR/MINOR/PATCH":
        "three macro names elided with slashes, not a path",
}

#: References that must survive any reformatting of CLAUDE.md, so a
#: pattern that has stopped matching fails by name instead of going
#: quiet. One of each shape the scan has to see: a path with a slash, a
#: slash-free file recognised by its extension, and a path written
#: inside a command line.
_ANCHORS = ("docs/scope.md", "CMakeLists.txt", "host/ports.py")

#: What the scan currently reads. A pattern that stops matching, or a
#: CLAUDE.md that loses half its references, has to be loud rather than
#: green - the bounds are wide enough not to fail on ordinary editing
#: and narrow enough that reading nothing cannot pass.
_MIN_REFS, _MAX_REFS = 55, 140
_MIN_RESOLVED = 45


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
        "guard resolves CLAUDE.md's paths against the index rather than "
        "the filesystem, so it cannot run without one")
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


def _references():
    """token -> line numbers, for every path-like inline code span."""
    found = collections.defaultdict(list)
    for lineno, line in enumerate(_read("CLAUDE.md").splitlines(), 1):
        for span in _SPAN.findall(line):
            for tok in span.split():
                if _PATHISH.match(tok) and ("/" in tok or _EXT.search(tok)):
                    found[tok].append(lineno)
    return dict(found)


def _resolve(tok, files, dirs, bases):
    """"exact", "basename" or "nowhere" for one reference."""
    stem = tok.rstrip("/")
    if stem in files or stem in dirs:
        return "exact"
    if os.path.basename(stem) in bases:
        return "basename"
    return "nowhere"


def test_the_reference_scan_reads_what_it_claims_to():
    """The count, and three references by name.

    Without this the check below is satisfied by a pattern that matches
    nothing: reformat CLAUDE.md, or break the regex, and an empty
    candidate set passes every assertion about it. This project has four
    recorded guards that went green while checking zero of what they
    named, and `docker/run-cppcheck.sh` draws the same distinction in
    its exit codes - found nothing is not analysed nothing.

    The anchors are the half a count cannot give. A pattern narrowed
    until it reads only slash-free filenames would still produce a
    plausible number.
    """
    refs = _references()
    assert _MIN_REFS <= len(refs) <= _MAX_REFS, (
        f"CLAUDE.md yields {len(refs)} distinct path references, outside "
        f"the expected {_MIN_REFS}-{_MAX_REFS}. Either the file changed "
        "shape or this scan has stopped reading it; a reference check "
        "over nothing passes for the wrong reason")

    missing = [a for a in _ANCHORS if a not in refs]
    assert not missing, (
        f"{missing} are no longer parsed out of CLAUDE.md. Each is one "
        "shape this scan has to see - a path with a slash, a slash-free "
        "file known by its extension, and a path inside a command line - "
        "so losing one means the pattern reads less than it claims. If "
        "CLAUDE.md genuinely stopped naming it, pick another anchor of "
        "the same shape rather than deleting the assertion")


def test_every_path_claude_md_names_resolves():
    """A path in CLAUDE.md points at something, or it is on the allowlist.

    `docs/HANDOFF.md` was deleted while twelve files cited
    it, and nothing in the suite noticed. That is the failure this
    catches, and it is cheap to catch because a path is the one claim in
    the file that has a mechanical answer.
    """
    files, dirs, bases = _index()
    refs = _references()

    resolved = 0
    broken = []
    for tok, lines in sorted(refs.items()):
        where = _resolve(tok, files, dirs, bases)
        if where != "nowhere":
            resolved += 1
        elif tok not in ALLOWED:
            at = ", ".join(f"line {n}" for n in lines)
            broken.append(f"{tok} ({at})")

    assert not broken, (
        "CLAUDE.md names paths that are not in the tree: "
        + "; ".join(broken)
        + ". Correct the reference, or - if the path is deliberately "
        "outside this repository - add it to ALLOWED with the reason")

    assert resolved >= _MIN_RESOLVED, (
        f"only {resolved} references resolved, against {len(refs)} read. "
        "The check above is vacuous if almost everything is allowlisted")


def test_every_allowlist_entry_is_still_absent_and_still_cited():
    """An exemption goes when its reason does, in either direction.

    `tests/test_clean_build.py` carried two dead ALLOWED entries until
    2026-09-04, and the lesson there is the one that applies here: an
    exemption costs nothing on the day it is written and everything on
    the day the thing it exempts changes. Two ways for that to happen
    and both are checked - a path that has appeared in the tree, so the
    entry now hides a real reference from the scan, and a path CLAUDE.md
    has stopped naming, so the entry is a permission for nothing.
    """
    files, dirs, bases = _index()
    refs = _references()

    now_resolvable = sorted(
        f"{tok} (resolves as {_resolve(tok, files, dirs, bases)}; "
        f"exempted as {reason!r})"
        for tok, reason in ALLOWED.items()
        if _resolve(tok, files, dirs, bases) != "nowhere")
    assert not now_resolvable, (
        "these are on the allowlist and now resolve, so the exemption is "
        "hiding a reference the scan would otherwise check: "
        + "; ".join(now_resolvable))

    uncited = sorted(tok for tok in ALLOWED if tok not in refs)
    assert not uncited, (
        f"{uncited} are allowlisted and CLAUDE.md no longer names them. "
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
