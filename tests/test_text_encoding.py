"""Every text-mode file open in the Python tree names its encoding.

Needs no board. A text open without `encoding=` uses the locale's codec:
UTF-8 on the macOS and Linux benches, cp936 on `windows-desk`. The files
this project reads - `bench.json`, the records, the sources, the report
template - are UTF-8, so on a cp936 host an unnamed open does one of two
things, and a caller sees neither as an error:

  * **A two-byte UTF-8 character decodes as a different character.** A
    middle dot (c2 b7) reads back as 路, µ as 碌, ± as 卤, Ω as 惟. The
    Latin-1 supplement and Greek - µs, 10 Ω, ±0.5 - are what an
    instrument project types by hand, and the wrong string is plausible.
  * **A three-byte character raises.** An em dash, a curly quote or ≈
    gives `UnicodeDecodeError`, which `provenance.bench()` catches as a
    `ValueError` and reports as a `bench_error` field on the row.

"Read and write as UTF-8" is one uniform policy, correct on every
platform, so it is enforced here rather than behind `host/transport.py`:
that seam is for code that has to differ by platform.

The scan is syntactic, over the parsed tree, so a call split across
lines is one call and an `open(` inside a comment or a string is not a
call. It covers `open`, `io.open`, `os.fdopen`, `Path.read_text` and
`Path.write_text`. A literal mode containing `b` is exempt, and so is a
call that forwards `**kwargs`. An attribute `.open()` on anything else -
a serial port, a GUI session - is not a file open and is not scanned.
"""
import ast
import builtins
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))

#: Every directory that holds this project's Python. `drivers`, `bsp`,
#: `apps` and `lib` hold C and are `tests/test_comment_style.py`'s.
SCAN_DIRS = ("host", "gui", "tools", "tests", "docker")

#: The directory names `tests/test_comment_style.py` never descends into,
#: so the two scans read the same tree.
_PRUNE = {
    "__pycache__", ".git", "build", "CMakeFiles",
    "toolchain", "venv", ".venv", ".venv-gui", ".venv-ft",
}


def _prune_dir(name):
    return (name in _PRUNE or name.startswith("build-")
            or name.startswith("xpack-")
            or name.startswith("arm-gnu-toolchain-"))


def python_files():
    for d in SCAN_DIRS:
        for root, dirs, files in os.walk(os.path.join(REPO, d)):
            dirs[:] = [s for s in dirs if not _prune_dir(s)]
            for fn in sorted(files):
                if fn.endswith(".py"):
                    yield os.path.join(root, fn)


def unnamed_opens(source, filename="<string>"):
    """(line, call text) for each text-mode open that names no encoding."""
    tree = ast.parse(source, filename)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open":
            mode_pos = 1
        elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
              and (f.value.id, f.attr) in (("io", "open"), ("os", "fdopen"))):
            mode_pos = 1
        elif isinstance(f, ast.Attribute) and f.attr in ("read_text",
                                                         "write_text"):
            mode_pos = None
        else:
            continue
        if any(kw.arg in ("encoding", None) for kw in node.keywords):
            continue
        mode = next((kw.value for kw in node.keywords if kw.arg == "mode"),
                    None)
        if mode is None and mode_pos is not None and len(node.args) > mode_pos:
            mode = node.args[mode_pos]
        if (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                and "b" in mode.value):
            continue
        out.append((node.lineno, ast.get_source_segment(source, node) or ""))
    return sorted(out)


def test_every_text_open_names_its_encoding():
    offenders = []
    for path in python_files():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        rel = os.path.relpath(path, REPO)
        offenders += [f"{rel}:{line}" for line, _call in
                      unnamed_opens(src, rel)]
    assert not offenders, (
        f"{len(offenders)} text-mode open(s) without encoding=. On a cp936 "
        f"host each one silently rewrites a two-byte character or raises on "
        f"a three-byte one. Add encoding=\"utf-8\":\n  "
        + "\n  ".join(offenders))


def test_the_scan_reaches_every_python_directory():
    seen = [os.path.relpath(p, REPO) for p in python_files()]
    tops = {p.split(os.sep)[0] for p in seen}
    assert tops == set(SCAN_DIRS), f"scanned {sorted(tops)}"
    for member in (os.path.join("host", "provenance.py"),
                   os.path.join("tools", "issue5_crossover.py"),
                   os.path.join("tests", "test_text_encoding.py")):
        assert member in seen, f"{member} is not scanned"


def test_the_scan_sees_each_form():
    forms = [
        "open(p)",
        "open(\n    p,\n    'w')",
        "json.load(open(p))",
        "io.open(p, 'a')",
        "os.fdopen(fd, 'w')",
        "p.read_text()",
        "p.read_text(errors='replace')",
        "p.write_text(s)",
    ]
    for src in forms:
        assert len(unnamed_opens(src)) == 1, f"missed: {src!r}"


def test_the_scan_exempts_what_has_no_encoding_to_name():
    clean = [
        "open(p, 'rb')",
        "open(p, mode='wb')",
        "os.fdopen(fd, 'r+b')",
        "open(p, encoding='utf-8')",
        "p.read_text(encoding='utf-8')",
        "open(p, **kw)",
        "# open(p)\nx = 1",
        "s = 'open(p)'",
        "port.open()",
        "session.open('control')",
    ]
    for src in clean:
        assert unnamed_opens(src) == [], f"flagged: {src!r}"


def _locale_as(codec):
    """`open` as a host whose locale codec is `codec` would run it."""
    def fake(*args, **kwargs):
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        if "b" not in mode:
            kwargs.setdefault("encoding", codec)
        return builtins.open(*args, **kwargs)
    return fake


def test_a_hand_typed_character_survives_the_bench_file(tmp_path, monkeypatch):
    """`bench.json` is typed by hand on every bench and read into every row.

    `provenance`'s `open` is made to default to cp936, as it does on
    `windows-desk`, so this fires on any host: an unnamed open corrupts
    the two-byte cases without raising and turns the three-byte one into
    a `bench_error`.
    """
    import provenance
    monkeypatch.setattr(provenance, "REPO", str(tmp_path))
    monkeypatch.setattr(provenance, "open", _locale_as("cp936"),
                        raising=False)
    for wiring in ("DAC0->A0 · DAC1->A1",
                   "10 µs settle, ±0.5 V, 10 Ω series",
                   "copper — about 10 cm"):
        (tmp_path / "bench.json").write_bytes(json.dumps(
            {"bench": "planted", "wiring": wiring},
            ensure_ascii=False).encode("utf-8"))
        got = provenance.bench()
        assert "bench_error" not in got, got
        assert got.get("wiring") == wiring, (
            f"read back {got.get('wiring')!r}, wrote {wiring!r}")
