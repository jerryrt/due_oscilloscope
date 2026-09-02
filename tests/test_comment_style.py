"""Comments that keep books on themselves, caught rather than remembered.

Issue #60: 167 lines across 76 files carry the repository's history
("used to / an earlier version / no longer") instead of an explanation
of the code, and six of them literally narrate their own correction -
`drivers/adc.c:31` opens by quoting its own earlier, wrong arithmetic
back at the reader. `docs/writing.md` already has the rule for this
("state what is true, never how it changed") and it was enforced in
`docs/` but never in code comments, which is where the prose went.

This is deliberately narrow. It does not ban "used to" - that phrase is
ordinary English and appears legitimately all over this tree ("the same
technique used to find the ADC ceiling", "may and may not be used to
claim"). It matches only the tight family of phrases where a comment or
docstring is talking about *its own* prior wording, the shape
`docs/writing.md` names as the tell: "a document that describes
itself". `tests/test_shared_source.py`'s `code_only()` makes the sibling
point about a guard that cries wolf on its own text - a pattern this
broad has to be this narrow, or the people who read it stop reading it.

Needs no board.
"""
import os
import re

import pytest

pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that carry the project's own comments and docstrings.
# Vendored toolchains, build output and venvs are excluded below by the
# same directory-name patterns .gitignore already uses to exclude them.
SCAN_DIRS = [
    "host",
    "gui",
    "tools",
    "tests",
    "drivers",
    "bsp",
    "apps",
    os.path.join("lib", "due_shared", "src"),
    os.path.join("sketches", "bringup"),
]

C_EXTS = {".c", ".h", ".cpp", ".ino"}
PY_EXTS = {".py"}

# Directory names to never descend into, wherever they occur.
_PRUNE = {
    "__pycache__", ".git", "build", "CMakeFiles",
    "toolchain", "venv", ".venv", ".venv-gui", ".venv-ft",
}


def _prune_dir(name):
    if name in _PRUNE:
        return True
    if name.startswith("build-"):
        return True
    if name.startswith("xpack-") or name.startswith("arm-gnu-toolchain-"):
        return True
    return False


# The self-referential family. Each phrase is a comment or docstring
# talking about what it (or the line/file/section it lives in) used to
# say - never a generic "used to" describing what the *code* once did.
_PHRASES = [
    r"this comment used to",
    r"this docstring (?:used to|said)",
    r"docstring used to",
    r"this used to say",
    r"used to read",
    r"this section used to",
    r"this file used to",
    r"this line used to",
]
PATTERN = re.compile("|".join(_PHRASES), re.IGNORECASE)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _c_comment_spans(text):
    """(offset, text) for every C block and line comment.

    Mirrors `test_shared_source.py`'s `code_only()` in reverse: that
    helper strips comments out to look at code; this one keeps only the
    comments to look at prose. Neither cares about the few characters at
    the seam (a `//` inside a string literal, say) because the phrases
    matched below do not occur in code.
    """
    spans = []
    for m in re.finditer(r"/\*.*?\*/", text, re.S):
        spans.append((m.start(), m.group(0)))
    for m in re.finditer(r"//[^\n]*", text):
        spans.append((m.start(), m.group(0)))
    return spans


def _py_comment_spans(text):
    """(offset, text) for every '#' comment and triple-quoted docstring."""
    spans = []
    for m in re.finditer(
        r"'''(?:\\.|[^\\])*?'''|\"\"\"(?:\\.|[^\\])*?\"\"\"", text, re.S
    ):
        spans.append((m.start(), m.group(0)))
    for m in re.finditer(r"#[^\n]*", text):
        spans.append((m.start(), m.group(0)))
    return spans


def _violations_in_file(path):
    ext = os.path.splitext(path)[1]
    text = _read(path)
    if ext in C_EXTS:
        spans = _c_comment_spans(text)
    elif ext in PY_EXTS:
        spans = _py_comment_spans(text)
    else:
        return set()

    hits = set()
    for start, span_text in spans:
        for m in PATTERN.finditer(span_text):
            offset = start + m.start()
            hits.add(_line_of(text, offset))
    return hits


def _scan():
    """{relative path: sorted [line numbers]} for every match in the tree."""
    found = {}
    for d in SCAN_DIRS:
        root_dir = os.path.join(REPO, d)
        if not os.path.isdir(root_dir):
            continue
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [sub for sub in dirs if not _prune_dir(sub)]
            for fn in files:
                ext = os.path.splitext(fn)[1]
                if ext not in C_EXTS and ext not in PY_EXTS:
                    continue
                path = os.path.join(root, fn)
                lines = _violations_in_file(path)
                if lines:
                    found[os.path.relpath(path, REPO)] = sorted(lines)
    return found


def test_pattern_catches_the_self_narrating_family():
    """Positive control: the pattern must fire on the family it is for.

    CLAUDE.md's shell-heredoc story is the reason this exists as its own
    test rather than trust in the regex above it: a pattern that has
    lost a backslash to an escaping accident still compiles and still
    looks right in a diff, and only stops matching. `repr()` on the
    compiled pattern is checked here too, for the same reason it caught
    that bug - a literal backspace byte does not show in a normal print.
    """
    assert "\x08" not in PATTERN.pattern, (
        f"the compiled pattern contains a literal backspace byte, "
        f"which is exactly how a shell heredoc ate a backslash and "
        f"produced a pattern that matches nothing: {PATTERN.pattern!r}")

    samples = [
        "This comment used to read 'always positive'.",
        "This docstring used to claim the buffer was zeroed.",
        "This docstring said the reset was optional.",
        "The docstring used to carry a third example here.",
        "This used to say the port never resets.",
        "uart_getc() used to read UART_RHR directly.",
        "This section used to describe the old ladder.",
        "This file used to be two, kept identical by hand.",
        "This line used to assume the shape was always sine.",
    ]
    for s in samples:
        assert PATTERN.search(s), f"pattern failed to match: {s!r}"


def test_pattern_does_not_flag_ordinary_prose():
    """Negative control: ordinary 'used to' is not the target.

    Real lines from this tree, none of them self-narrating - a comment
    describing what code once did, or "used to" meaning "employed to",
    is not the same defect as a comment describing what *it* once said.
    Banning "used to" outright is exactly the over-broad guard this
    project has already learned costs trust; see `code_only()`'s own
    docstring in `test_shared_source.py`.
    """
    benign = [
        "the same technique used to find the ADC ceiling",
        "ctl_temp_t carries what the reading may and may not be used "
        "to claim",
        "micros() used to be called on EVERY pass",
        "It used to be read out of tests/baseline.json",
        "`z` is used to change the boot rather than a reflash",
        "These two lines used to run after gen_go_tioa1()",
    ]
    for s in benign:
        assert not PATTERN.search(s), f"pattern over-matched benign text: {s!r}"


def test_no_self_narrating_comments():
    """The guard itself: no comment in the tree may narrate its own fix.

    A comment exists to help someone read the code; the history of how
    it used to be wrong belongs in `git log`, not in the file forever.
    See `docs/writing.md`'s "code comments" section for the keep/cut
    test and the load-bearing exception.
    """
    found = _scan()
    assert not found, (
        "self-narrating comments found (a comment or docstring "
        "describing what it used to say, rather than what is true "
        "now) - move the history to the commit that made the change "
        "and leave the comment stating the current fact:\n"
        + "\n".join(
            f"  {path}:{line}"
            for path, lines in sorted(found.items())
            for line in lines
        )
    )
