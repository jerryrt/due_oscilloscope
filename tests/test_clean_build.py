"""Every build in this project is a full build, and this fails if not.

Needs no board. It is a guard against drift rather than a behaviour
test: the enforcement itself is two lines in two files, and both are the
kind of line a future reader deletes to make a build faster.

The reason it is worth a test at all is that the failure it prevents is
silent. On 2026-08-29 arduino-cli's object cache produced a Track A
image built from a new `ctl_port.cpp` and a stale `ctl.c`: the
capability word carried the new bit, so the opcode worked, while the
capability *report* omitted it because that table lived in the file the
cache reused. The board answered correctly and described itself wrongly,
nothing in the build output mentioned a cached object, and the only tell
was eight bytes of flash.

A full build is 0.6 s for Track B and 2.2 s for Track A on the slowest
bench here, against measurement runs of nine minutes to eight hours that
quote the resulting image by commit. `tools/metrics.py` already warns
"a build cache probably served a stale object"; this stops it happening.
"""
import ast
import fnmatch
import glob
import os
import re
import shlex

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _ignored_dirs():
    """Directory patterns .gitignore already excludes.

    The scan below walks the tree looking for project Python, and a
    vendored toolchain unpacked in place is not project Python. This
    bench has `tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/` - 1.0 GB and
    **102 .py files**, one of which is CPython's own
    `badsyntax_pep3120.py`, deliberately not UTF-8. Reading it raised
    UnicodeDecodeError and failed this test outright.

    `.gitignore` already says those directories are not ours -
    `tools/xpack-*/`, `tools/arm-gnu-toolchain-*/`, `tools/toolchain/` -
    so the patterns are read from there rather than copied here. A
    second list would drift from the first, and this test exists to
    stop exactly that kind of drift elsewhere.

    CLAUDE.md tells everyone to use the xPack toolchain, so any bench
    that unpacks it under tools/ hits this.
    """
    pats = []
    try:
        for line in _read(".gitignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.endswith("/"):
                pats.append(line.rstrip("/"))
    except OSError:
        pass
    return pats


def test_track_b_cmake_forces_a_full_build():
    """CMake cleans before every build of the firmware, in that order.

    Checked at the source rather than by building, so it fails on the
    change that removes it rather than on the measurement that trusts
    it.

    The shape matters as much as the presence, and that is what this
    file got wrong the first time. The original spelling was
    `add_dependencies(track_b_bringup enforce_clean_build)`, which
    asks the build system to run a clean inside the same graph it is
    about to link. Make re-evaluates between steps and honoured it - 25
    of 25 objects recompiled per invocation, measured - while Ninja
    plans the whole graph first and deleted the objects the same plan
    was about to link, so windows-desk could not build at all and
    `flash.py` then flashed the previous image (issue #35). It had been
    silently Make-works / Ninja-broken since it landed, and neither half
    was visible from either bench alone.

    So the clean and the build are two *child* invocations of CMake,
    sequenced by the shell rather than by the generator, and this pins
    every part of that arrangement - including the absence of the shape
    that failed.
    """
    cml = _read("CMakeLists.txt")

    assert re.search(r"add_custom_target\(\s*firmware\s+ALL", cml), (
        "CMakeLists.txt no longer defines the `firmware ALL` driver, so "
        "`cmake --build build` is incremental again and can link a "
        "mixed-revision image")
    assert re.search(r"--target\s+clean", cml), (
        "the driver no longer invokes CMake's clean target; an rm -rf of "
        "the object directory is not equivalent, it removes build.make "
        "and the build fails outright")
    assert re.search(r"--target\s+track_b_bringup", cml), (
        "the driver cleans but never builds the firmware; `all` would "
        "now produce no image at all")
    assert re.search(r"add_executable\(\s*track_b_bringup\s+"
                     r"EXCLUDE_FROM_ALL", cml), (
        "track_b_bringup is back in `all`, so `cmake --build build` "
        "builds it directly and incrementally, stepping past the clean")

    assert not re.search(r"add_dependencies\(\s*track_b_bringup\s+"
                         r"\w*clean\w*\s*\)", cml), (
        "the clean is a dependency of the executable again. That is the "
        "shape that broke under Ninja: the generator plans the whole "
        "graph, then the clean deletes the objects the same plan is "
        "about to link. See issue #35")


def test_cmake_refuses_to_configure_outside_the_container():
    """Firmware is built in the pinned container, and CMake says so first.

    A host build carries whichever compiler that bench installed, a SAM
    core found by folder name and a FreeRTOS fetched at configure time.
    So `CMakeLists.txt` refuses any configure that `docker/run.sh` did not
    launch, and it does that ahead of `project()`, where a host with no
    compiler at all still gets the container line instead of a toolchain
    search error. `docker/run.sh` is the one file that sets the variable
    the guard reads.

    Flashing is not a CMake target either: CMake runs only inside the
    image, which holds no bossac and reaches no board.
    """
    cml = _read("CMakeLists.txt")
    guard = re.search(r'if\("\$ENV\{DUE_BUILD_IMAGE_ID\}"\s+STREQUAL\s+""\)'
                      r'\s*message\(FATAL_ERROR', cml)
    assert guard, (
        "CMakeLists.txt no longer refuses a configure outside the build "
        "container, so a host can build an image again")
    assert guard.start() < cml.index("\nproject("), (
        "the container guard comes after project(), so a host configure "
        "searches for a toolchain before it is refused")
    assert re.search(r'--env\s+"DUE_BUILD_IMAGE_ID=\$image_id"',
                     _read("docker", "run.sh")), (
        "docker/run.sh no longer passes DUE_BUILD_IMAGE_ID, so the guard "
        "refuses the container too")
    assert "add_custom_target(flash" not in cml, (
        "CMake has a flash target again. Flashing is a host step through "
        "tools/flash.py, and CMake runs only where no board is reachable")


def test_a_configure_outside_the_container_is_refused(tmp_path):
    """The guard above, run rather than read.

    The static test proves the lines are there; this proves CMake obeys
    them. It configures the real tree into a scratch directory with
    DUE_BUILD_IMAGE_ID removed from the environment, and the refusal has
    to name the container command, so a configure that failed for any
    other reason does not count as the guard firing. Inside the image the
    variable is set, so this is the container's host tier deliberately
    stepping outside it; a bench has no cmake and skips.
    """
    import shutil
    import subprocess

    cmake = shutil.which("cmake")
    if not cmake:
        pytest.skip("no cmake on PATH, which is what a bench is meant to "
                    "look like; the container's host tier runs this")
    env = {k: v for k, v in os.environ.items() if k != "DUE_BUILD_IMAGE_ID"}
    proc = subprocess.run([cmake, "-S", REPO, "-B", str(tmp_path / "b")],
                          env=env, capture_output=True, text=True,
                          timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "CMake configured the firmware with no build container around it")
    assert "docker/run.sh docker/build-firmware.sh" in out, (
        f"the configure failed, but not on the container guard:\n{out[-800:]}")


def test_track_a_build_is_clean_by_construction():
    """Track A's target cleans first, as `firmware` and `firmware_track_c` do.

    The reason is not hypothetical: under the arduino-cli build path
    Track A once had, the cache did not notice every change under
    `--libraries`, which is how a Track A image shipped with a stale
    `lib/due_shared` object. Under CMake the same failure is available -
    an incremental build of a tree whose shared sources moved - and the
    same answer applies, so the assertion moves rather than retires.

    `cmake/track_a.cmake` says it itself: the first cut of the file had
    no wrapper, and the image was correct only because the tree happened
    to be configured fresh each time.
    """
    ta = _read("cmake", "track_a.cmake")

    m = re.search(r"add_custom_target\(firmware_track_a(.*?)VERBATIM\)",
                  ta, re.S)
    assert m, ("cmake/track_a.cmake no longer defines firmware_track_a, "
               "so there is no clean-build wrapper for Track A")
    body = m.group(1)
    assert "--target clean" in body, (
        "firmware_track_a no longer cleans before it builds. An "
        "incremental Track A build can carry a stale lib/due_shared "
        "object, which has shipped an image here before")
    assert body.index("--target clean") < body.index("track_a_bringup"), (
        "firmware_track_a builds before it cleans")


def test_the_suite_reflash_flashes_the_tree_s_container_image():
    """`measure.flash()` flashes the container's image and builds nothing.

    It is the reflash the board suite and every bench tool go through, so
    it is where a host build would come back. That it spawns no builder is
    held by the scan below, now that it is off the allowlist. This holds
    the other half: it flashes the path `provenance.CONTAINER_IMAGES`
    names, and it asks `flash.py` for `--require-tree`, which refuses an
    image the container did not build or that carries another commit.

    Matched on the call and the argv rather than on the names, because a
    name also appears in the docstring above them.
    """
    mp = _read("host", "measure.py")
    i = mp.index("\ndef flash(")
    end = mp.find("\ndef ", i + 1)
    body = mp[i:end if end >= 0 else len(mp)]
    assert re.search(r"provenance\.CONTAINER_IMAGES\.get\(track\)", body), (
        "measure.flash() no longer takes its image from "
        "provenance.CONTAINER_IMAGES")
    assert re.search(r'"--bin",\s*binary,\s*"--require-tree"', body), (
        "measure.flash() no longer passes --require-tree, so the suite can "
        "flash an image that is not this tree's")
    assert "host/measure.py" not in ALLOWED, (
        "measure.py is allowed to spawn a build tool again")


_TOOL = re.compile(r"arduino-cli|\bcmake\b")

#: Spawn surfaces, by the module that owns them. `shutil` is not one:
#: `which()` resolves a path without running it, so what it hands back
#: is caught at the spawn that follows.
_SPAWN_FUNCS = {
    "subprocess": {"run", "call", "check_call", "check_output", "Popen"},
    "os": {"system", "popen",
           "execv", "execve", "execvp", "execvpe",
           "execl", "execle", "execlp", "execlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe",
           "spawnl", "spawnle", "spawnlp", "spawnlpe"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}

#: Keywords that can carry a program or an argv, and no others. `cwd=`
#: and `env=` name directories, and one of this project's directories is
#: called `cmake`.
_ARGV_KWARGS = {"args", "cmd", "command", "argv", "executable"}

#: Levels of local binding a command is followed back through. One is
#: what the known shape needs - `argv = [...]` on the line above the
#: spawn - and three covers a name bound to a name bound to a resolved
#: path without turning this into an interprocedural analysis. A binding
#: that crosses a function boundary is not followed; the transitive pass
#: is what catches the caller instead.
_RESOLVE_DEPTH = 3

#: Fallback only, for source that will not parse.
_SPAWN = re.compile(r"subprocess\.(run|call|check_call|check_output|Popen)"
                    r"\(", re.S)


def _regex_spawns(text):
    """(line, the 300 characters after each spawn) in unparsable source."""
    for m in _SPAWN.finditer(text):
        yield text[:m.start()].count(chr(10)) + 1, text[m.end():m.end() + 300]


def _iter_scope(node):
    """Every node inside one scope, without descending into a nested one.

    The nested scope's own node is still yielded, so a caller can
    recurse into it with that scope's bindings in front of the chain.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(n))


def _bindings(scope):
    """name -> every expression bound to it in this scope.

    Every assignment rather than the last one: a name assigned in two
    branches has two values, and a static scan has no idea which of them
    runs.
    """
    out = {}
    for n in _iter_scope(scope):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(n.target, ast.Name) and n.value is not None:
                out.setdefault(n.target.id, []).append(n.value)
        elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
            out.setdefault(n.target.id, []).append(n.value)
    return out


def _spawn_names(tree):
    """Local names that reach a spawn, after import aliasing.

    `import subprocess as sp` still has to match `sp.run`, and
    `from subprocess import Popen as P` has to match `P(...)`. The bare
    module names are seeded whether or not an import was found, because
    an import inside a function body is one this does not look for.
    """
    attr_bases = {m: m for m in _SPAWN_FUNCS}
    plain = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _SPAWN_FUNCS:
                    attr_bases[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            if node.module in _SPAWN_FUNCS:
                for a in node.names:
                    if a.name in _SPAWN_FUNCS[node.module]:
                        plain[a.asname or a.name] = node.module
    return attr_bases, plain


def _is_spawn(call, attr_bases, plain):
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        mod = attr_bases.get(f.value.id)
        return bool(mod) and f.attr in _SPAWN_FUNCS.get(mod, ())
    return isinstance(f, ast.Name) and f.id in plain


def _spawns(tree):
    """(call node, scope chain) for every spawn, innermost scope first."""
    attr_bases, plain = _spawn_names(tree)
    found = []

    def walk(scope, chain):
        chain = [_bindings(scope)] + chain
        for n in _iter_scope(scope):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                walk(n, chain)
            elif isinstance(n, ast.Call) and _is_spawn(n, attr_bases, plain):
                found.append((n, chain))

    walk(tree, [])
    return found


def _lookup(name, chain):
    for scope in chain:
        if name in scope:
            return scope[name]
    return []


def _resolved(call, chain):
    """The spawn's command, with the local names in it substituted in.

    The command expression rather than a window of source, because
    `host/provenance.py` lists "cmake" as a *directory* in FW_SOURCE and
    a test that cannot tell a directory from a spawned tool is one
    people learn to ignore. `cwd=` and `env=` are excluded for the same
    reason; the keywords that can carry a program are not.

    The whole command matches, not argv[0]: `["sh", "-c", "cmake ..."]`
    puts the tool in an argument, and reading only the program would
    miss it. The cost is that a spawn passed a path *through* the cmake
    directory reads as a build tool and has to be allowed or spelled
    differently.
    """
    exprs = list(call.args)
    exprs += [kw.value for kw in call.keywords
              if kw.arg in _ARGV_KWARGS or kw.arg is None]
    texts, seen, frontier = [], set(), exprs
    for _ in range(_RESOLVE_DEPTH + 1):
        nxt = []
        for e in frontier:
            texts.append(ast.unparse(e))
            for n in ast.walk(e):
                if isinstance(n, ast.Name) and n.id not in seen:
                    seen.add(n.id)
                    nxt.extend(_lookup(n.id, chain))
        if not nxt:
            break
        frontier = nxt
    return "\n".join(texts)


def _spawn_commands(text):
    """(line, resolved command text) for every spawn in one file."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file this cannot parse must not become an invisible one, so
        # it falls back to reading the source after each spawn.
        yield from _regex_spawns(text)
        return
    for call, chain in _spawns(tree):
        yield call.lineno, _resolved(call, chain)


def _project_py():
    """Every .py in the project, excluding vendored and gitignored trees."""
    ignored = _ignored_dirs()
    out = {}
    for root, dirs, files in os.walk(REPO):
        keep = []
        for d in dirs:
            if d in {".git", "build", ".venv", ".venv-gui",
                     "vendor", "__pycache__", "records"}:
                continue
            rel_d = os.path.relpath(os.path.join(root, d),
                                    REPO).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel_d, pat) for pat in ignored):
                continue
            keep.append(d)
        dirs[:] = keep
        for name in files:
            if not name.endswith(".py"):
                continue
            # Forward slashes on every platform. ALLOWED is written
            # with them, and `os.path.relpath` hands back `host\measure.py`
            # on win32 - so the allowlist matched nothing there and the
            # test reported an *allowed* file as an offender. It failed
            # on windows-desk for the whole of 2026-08-30 and was read as
            # a pre-existing failure to work around rather than a defect
            # in the test, which is what a tier-1 platform failure gets
            # if nobody looks at it.
            rel = os.path.relpath(os.path.join(root, name),
                                  REPO).replace(os.sep, "/")
            out[rel] = _read(rel)
    return out


#: Files permitted to spawn a build tool directly. Everything else that
#: reaches one, at any depth, is a build path that skipped the clean.
#: `tools/reproducible.py` builds twice on purpose and compares the
#: bytes, and it goes through the same enforced target every other
#: caller does - its whole subject is that a build is what its source
#: says it is, so a stale cache is the last thing it can tolerate. It
#: runs in the build image, and CMake refuses it anywhere else.
#:
#: **Every entry spawns a build tool, and that is asserted rather than
#: intended.** An exemption for a file that needs none costs nothing on
#: the day it is written and everything on the day that file gains a
#: build spawn: it is then permitted silently, by a line nobody re-read.
#:
#: `host/measure.py` is deliberately not here. It flashes the container's
#: images and builds none, so a build spawn appearing in it is exactly
#: what the scan exists to report.
ALLOWED = {"tools/reproducible.py"}

#: Programs that can produce an image. `cmake` covers the wrappers;
#: `make` and `ninja` are the generators underneath them, and naming an
#: executable target to one of those is the way around a wrapper that no
#: `cmake --build` audit would see.
_BUILD_TOOLS = {"cmake", "make", "gmake", "ninja"}

#: Shell operators that end a simple command. A token equal to one of
#: these starts a new argv, so a builder invoked after a `&&` or inside
#: `$( )` is read as a builder and not as an argument to whatever came
#: before it.
_SHELL_OPS = {";", "&", "&&", "||", "|", "|&", "(", ")", "{", "}",
              "<", ">", ">>", "<<", "<<<", "<&", ">&", "\n"}

#: How far a line with an open quote may reach for its closing one. The
#: longest in this tree is the clang-tidy canary body at 31 lines; the
#: bound is here so a genuinely unterminated quote is reported rather
#: than swallowing the rest of the file.
_JOIN_LIMIT = 60


#: Memo for the tree walk below. Two tests want the same answer and the
#: walk reads every .py in the project to produce it.
_DIRECT = {}


def _project_direct_builders():
    """Every project .py, this file's path, and the set that builds.

    The third is the files that spawn a build tool with no other file
    in between - pass one of the scan below, and the set an allowlist
    entry has to belong to.
    """
    if not _DIRECT:
        files = _project_py()
        here = os.path.relpath(__file__, REPO).replace(os.sep, "/")
        _DIRECT["files"] = files
        _DIRECT["here"] = here
        _DIRECT["direct"] = {
            rel for rel, text in files.items()
            if rel != here
            and any(_TOOL.search(c) for _ln, c in _spawn_commands(text))}
    return _DIRECT["files"], _DIRECT["here"], _DIRECT["direct"]


def test_every_allowlist_entry_actually_builds():
    """A file exempted from the scan must be a file the scan would catch.

    Break it the other way to see what it is for: add any file at all to
    ALLOWED and the suite stays green, because an exemption costs
    nothing until it is needed. This makes the set self-describing - an
    entry is here because that file spawns a compiler today, and it goes
    when that stops being true rather than a release later.
    """
    _files, _here, direct = _project_direct_builders()
    dead = sorted(ALLOWED - direct)
    assert not dead, (
        f"{dead} are on the build-tool allowlist and spawn no build tool. "
        "An exemption for a file that does not need one is a blanket "
        "permission nobody will re-read on the day it starts to matter")


def test_nothing_else_builds_behind_the_enforcement():
    """No other caller spawns a compiler, at any depth.

    The enforcement is one line per build system, which only holds while
    those are the only ways to produce an image. A third path added later
    would bypass both silently, so this fails on its appearance.

    **Transitive.** Matching `arduino-cli|cmake` in the spawn window and
    nothing else leaves a file that spawns a file that spawns a build
    tool invisible - and an allowlist entry permitting the legitimate
    middle file hides every caller behind it. `tools/enum_probe.py`
    spawned the Track A wrapper that drove arduino-cli, and a scan that
    stopped one hop short passed for as long as both existed; the
    wrapper's deletion would then have left a bench tool broken for
    whoever next needed it.

    A one-off bench tool with a hardcoded path is invisible to every
    other check here - not imported, not collected, not exercised on any
    other bench - so this scan is the only thing that reads it at all.

    The builder set is computed rather than listed, so it cannot go
    stale: pass one finds every file that reaches a build tool directly,
    pass two finds every file that spawns one of those.

    **The scan walks the AST because a regex could not see argv in a
    variable.** Two probe files driving the identical build were
    measured on 2026-09-02, one binding the command first and one
    spelling it inside the call:

        argv = [cmake, "--build", "build", "-j"]
        subprocess.run(argv, check=True)

    Reading the source after the spawn passed the first and failed the
    second, so which of two equivalent spellings a caller happened to
    choose decided whether the guard existed at all. Names are resolved
    through `_RESOLVE_DEPTH` levels of local binding, and a build tool
    named only inside a shell script is out of reach of any .py scan -
    `docker/*.sh` spawns cmake and nothing here reads it.
    """
    files, here, direct = _project_direct_builders()

    offenders = [f"{rel} (spawns a build tool directly)"
                 for rel in sorted(direct - ALLOWED)]

    # Pass two: anything spawning a file that builds. Match on basename,
    # because callers spell the path every way - os.path.join(REPO, ...),
    # a bare "tools/x.py", a module constant. The set is exactly the
    # files that build, which is why ALLOWED may hold no entry that does
    # not: a name in here flags every caller of it, so a file listed
    # above for tidiness would make its callers offenders.
    builder_names = {os.path.basename(r) for r in (direct | ALLOWED)}
    for rel, text in sorted(files.items()):
        if rel in ALLOWED or rel == here or rel in direct:
            continue
        for ln, cmd in _spawn_commands(text):
            hit = next((b for b in builder_names if b in cmd), None)
            if hit:
                offenders.append(
                    f"{rel}:{ln} (spawns {hit}, which builds)")

    assert not offenders, (
        "these reach a build tool outside the enforced paths, so they "
        "can produce an image from a stale cache. Firmware is built in "
        "the container, docker/run.sh docker/build-firmware.sh, and "
        "measure.flash() flashes what it wrote: "
        + ", ".join(sorted(set(offenders))))


# ---------------------------------------------------------------------
# The container scripts
#
# Everything above walks Python, and a shell script is not Python.
# `docker/*.sh` is a build path too: `docker/build-firmware.sh` drives
# the enforced targets today, and one word of it is the difference
# between that and an image built incrementally.
# ---------------------------------------------------------------------

def _cmake_custom_targets(text):
    """(name, body) for every add_custom_target, by parenthesis balance.

    Balance rather than a match ending at `VERBATIM)`: every wrapper in
    this tree happens to end that way and nothing requires the next one
    to. A pattern that assumed it would run past the end of any target
    that did not, and read the target after it as part of the body.
    """
    for m in re.finditer(r"add_custom_target\(\s*([A-Za-z0-9_]+)", text):
        i = text.index("(", m.start())
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group(1), text[m.end():j]


def _clean_build_wrappers():
    """wrapper name -> {"builds": executable, "all": in the default target}.

    Read out of the CMake sources rather than listed here. There are
    three wrappers and Track C's arrived after the first two; a fourth
    track adds one to CMake, and a list written down in this file would
    not know about it while the scripts calling it would.
    """
    sources = ["CMakeLists.txt"]
    sources += sorted("cmake/" + n
                      for n in os.listdir(os.path.join(REPO, "cmake"))
                      if n.endswith(".cmake"))
    out = {}
    for rel in sources:
        text = _read(rel)
        for name, body in _cmake_custom_targets(text):
            if "--target clean" not in body:
                continue
            built = [t for t in re.findall(r"--target\s+(\S+)", body)
                     if t != "clean"]
            if not built:
                continue
            out[name] = {
                "builds": built[-1],
                "all": bool(re.search(r"add_custom_target\(\s*" + name
                                      + r"\s+ALL", text)),
            }
    return out


def _logical_lines(text):
    """(first line number, line) with backslash continuations joined."""
    out, buf, start = [], "", 1
    for i, raw in enumerate(text.splitlines(), 1):
        if not buf:
            start = i
        if raw.endswith("\\"):
            buf += raw[:-1] + " "
            continue
        out.append((start, buf + raw))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def _shell_commands(text):
    """(line, argv) per simple command, plus the lines that would not read.

    Tokenised rather than grepped, and the difference is not academic.
    `docker/run-clang-tidy.sh` passes `--target-dir` to a Python script
    three lines below a `cmake` invocation, and a pattern hunting for
    `--target` in a window of source reads that as a cmake target. What
    the guard has to see is an argument vector, so it builds one.

    Line by line, because `shlex` treats a newline as ordinary
    whitespace: lexed whole, a script collapses into one enormous
    command whose argv[0] is the shebang and no builder is ever at the
    head of anything. A line that will not tokenise on its own has an
    open quote, so the following lines are folded in until it closes -
    `die` messages and the clang-tidy canary body are written that way.

    What still will not read is returned rather than dropped. A guard
    that silently skips what it cannot see passes for the wrong reason,
    so the caller fails on an unread line that names a build tool.
    """
    lines = _logical_lines(text)
    commands, blind, i = [], [], 0
    while i < len(lines):
        ln, first = lines[i]
        joined, tokens, end = first, None, i
        for j in range(i, min(i + _JOIN_LIMIT, len(lines))):
            if j > i:
                joined += " " + lines[j][1]
            try:
                lex = shlex.shlex(joined, posix=True, punctuation_chars=True)
                lex.whitespace_split = True
                tokens = list(lex)
            except ValueError:
                continue
            end = j
            break
        i = end + 1
        if tokens is None:
            blind.append((ln, first))
            continue
        argv = []
        for tok in tokens:
            if tok in _SHELL_OPS:
                if argv:
                    commands.append((ln, argv))
                argv = []
            else:
                argv.append(tok)
        if argv:
            commands.append((ln, argv))
    return commands, blind


def _cmake_targets(argv):
    """The targets a `cmake --build` names, in every spelling of it."""
    out = []
    for i, tok in enumerate(argv):
        if tok in ("--target", "-t") and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif tok.startswith("--target="):
            out.append(tok.split("=", 1)[1])
    return out


def test_the_runner_stops_its_container_when_it_is_killed():
    """`docker run` is a client, and the daemon outlives it.

    A killed client leaves the container running with nothing attached.
    On mac-bench that happened three times in one session, and a
    reproducer from an earlier session ran under `qemu-i386` for seven
    days, burning 7h02 of CPU inside a 4-vCPU VM while every timing
    taken there was taken against it.

    Three parts, and none of them works alone: the cidfile says which
    container to stop, the trap is what runs on the way out, and the
    client must be waited on rather than run in the foreground - bash
    holds a trap until the foreground command returns, so the version
    written that way still leaked. Measured, 2 of 2 either way.

    A static read, because the behavioural check needs a docker daemon
    and this tier has none.
    """
    body = _read("docker", "run.sh")
    for needed, why in (
            ("--cidfile", "nothing records which container to stop"),
            ("trap cleanup", "nothing runs on the way out"),
            ("docker stop", "the trap no longer stops the container"),
            ('wait "$client"', "the client is in the foreground again, so "
                               "the trap cannot run until it returns")):
        assert needed in body, (
            f"docker/run.sh no longer carries {needed!r}: {why}, and a "
            f"killed run leaves its container up")


def test_every_populate_knob_survives_the_container_boundary():
    """A knob the bench sets must be named in `run.sh` or it is not one.

    A container inherits nothing from the invoking shell. `populate.sh`
    reads `DUE_COPY_GIT`, and setting it on the host did nothing at all
    until `run.sh` passed it: measured as `UNSET` inside the container,
    so every bench silently got the default and mac-bench could not
    select the copy its own measurement calls for - 28 ms per git
    operation copied against 420 ms bridged, on sshfs.

    Written as "every knob `populate.sh` reads", not as a list, so the
    next one cannot be added on one side of the boundary only.
    """
    # EVERY script that runs INSIDE the container, not just populate.sh.
    # The first version of this guard scanned that one file, and the knob
    # that was still broken - DUE_COPY_DIR, read by in-copy.sh - was in
    # the file it did not scan. A guard general in its wording and narrow
    # in its input set reports the property as protected while the defect
    # sits one file away.
    inside = ("populate.sh", "in-copy.sh", "run-ci.sh", "run-fuzz.sh",
              "run-cppcheck.sh", "run-tests.sh", "build-firmware.sh")
    knobs = set()
    for name in inside:
        try:
            knobs |= set(re.findall(r'\$\{(DUE_[A-Z0-9_]+)',
                                    _read("docker", name)))
        except FileNotFoundError:
            pass
    # Supplied by the image or computed by run.sh itself, so they are not
    # bench knobs and nothing is expected to forward them from a shell.
    knobs -= {"DUE_FREERTOS_DIR", "DUE_BUILD_IMAGE_ID",
              "DUE_BUILD_IMAGE_CONTENT", "DUE_BUILD_IMAGE"}
    assert knobs, (
        "no DUE_* knob found in docker/populate.sh, so this guard is "
        "reading nothing")
    runner = _read("docker", "run.sh")
    for knob in sorted(knobs):
        assert f'--env "{knob}=' in runner, (
            f"docker/populate.sh reads {knob} and docker/run.sh does not "
            f"pass it, so setting it on the bench does nothing")


def test_no_container_script_carries_a_mangled_line_continuation():
    """`\\n` between two arguments is a literal `n`, not a newline.

    Found in `docker/run.sh`'s `mkdir -p`, where a continuation had been
    written as `\\n` and bash therefore passed `n` as a path: every run
    of the container since created an empty directory called `n` in the
    repository root. It survived unnoticed because git does not track an
    empty directory, so no bench's `git status` ever mentioned it.

    The shape is worth a guard rather than a fix alone: it is invisible
    in a diff, it produces no error, and in a command that writes rather
    than creates it would put a file somewhere nobody is looking.
    """
    offenders = []
    for path in sorted(glob.glob(os.path.join(REPO, "docker", "*.sh"))):
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        for n, line in enumerate(_read(rel).splitlines(), 1):
            if re.search(r'(^|\s)\\n(\s|$)', line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, (
        "a backslash-n sits between arguments, which bash passes as the "
        "literal argument 'n' rather than breaking the line:\n"
        + "\n".join(offenders))


def test_the_container_scripts_build_only_through_the_wrappers():
    """No shell script produces an image outside a clean-build wrapper.

    The scan above walks the AST of every project `.py` and catches a
    spawn however its argv is built, which is everything a Python caller
    can do and nothing a shell script can. `docker/*.sh` is the
    project's other build path - one entry point runs every check the
    build image can make, and its firmware step is a shell script - and
    the enforcement it can step around is the same one, for the same
    reason: an incremental build has shipped a mixed-revision image
    here, and the only tell was eight bytes of flash.

    Two rules, and the second is not implied by the first. A
    `cmake --build` that names a target must name a wrapper. And no
    build tool at all may name a wrapped executable, because
    `ninja track_a_bringup` reaches the same object directory with no
    `--target` in it to audit.

    A `cmake --build` naming nothing builds the default target, which is
    where `firmware ALL` lives - so that spelling is enforced only while
    some wrapper is in `all`, and this asserts that rather than assuming
    it.
    """
    wrappers = _clean_build_wrappers()
    assert len(wrappers) >= 2, (
        f"only {sorted(wrappers)} read as clean-build wrappers. Either the "
        "wrappers have changed shape or this test can no longer find them, "
        "and it must not go quiet either way")
    wrapped = {w["builds"] for w in wrappers.values()}

    scripts = sorted(glob.glob(os.path.join(REPO, "docker", "*.sh")))
    assert scripts, (
        "docker/ holds no shell script, so this guard reads nothing at all")

    offenders = []
    for path in scripts:
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        commands, blind = _shell_commands(_read(rel))

        for ln, line in blind:
            if any(t in line for t in _BUILD_TOOLS):
                offenders.append(
                    f"{rel}:{ln} names a build tool on a line this cannot "
                    f"tokenise, so it goes unread: {line.strip()[:60]}")

        for ln, argv in commands:
            tool = os.path.basename(argv[0])
            if tool not in _BUILD_TOOLS:
                continue
            named = [a for a in argv[1:] if a in wrapped]
            if named:
                offenders.append(
                    f"{rel}:{ln} builds {named[0]} directly, which is the "
                    "executable a wrapper cleans before it builds")
            if tool != "cmake" or "--build" not in argv:
                continue
            targets = _cmake_targets(argv)
            if not targets:
                assert any(w["all"] for w in wrappers.values()), (
                    f"{rel}:{ln} builds the default target and no wrapper is "
                    "in `all` any more, so it builds nothing, or builds "
                    "around the clean")
                continue
            for t in targets:
                if t not in wrappers:
                    offenders.append(
                        f"{rel}:{ln} builds --target {t}, which is not one "
                        f"of the clean-build wrappers {sorted(wrappers)}")

    assert not offenders, (
        "these produce an image outside the enforced targets, so a "
        "container build can carry a stale object: " + "; ".join(offenders))


def test_track_c_cmake_forces_a_full_build_too():
    """The third build path gets the same enforcement as the other two.

    Track C (issue #45) is a third way to produce an image, and the
    docstring at the top of this file says the enforcement "is two lines
    in two files". It is three now, and a build path that skipped it
    would be exactly the silent drift this file exists to catch - worse
    for Track C than for the others, because Track C links Track B's
    drivers unchanged, so a stale object there produces two images that
    disagree about hardware neither of them programmes differently.

    Guarded only when the target exists: Track C is behind
    `option(BUILD_TRACK_C ...)` while it is at stage C1, and a test that
    demanded the target unconditionally would fail on every bench that
    has not opted in.
    """
    cml = _read("CMakeLists.txt")
    if "track_c_bringup" not in cml:
        pytest.skip("Track C is not in this tree yet")

    assert "add_custom_target(firmware_track_c" in cml, (
        "Track C has a build target but no clean-build wrapper. Every "
        "image in this project is built from scratch; see the comment "
        "above `firmware`.")

    body = cml[cml.index("add_custom_target(firmware_track_c"):]
    body = body[:body.index("VERBATIM")]
    clean_at = body.find("--target clean")
    build_at = body.find("--target track_c_bringup")
    assert clean_at >= 0, "firmware_track_c does not clean"
    assert build_at >= 0, "firmware_track_c does not build track_c_bringup"
    assert clean_at < build_at, (
        "firmware_track_c builds before it cleans, which cleans away the "
        "image it just produced")

    assert "add_dependencies(track_c_bringup" not in cml, (
        "the clean is expressed as a dependency again. That is the shape "
        "that was Make-works / Ninja-broken for Track B - see the test "
        "above and issue #35.")


def test_track_c_freertos_is_pinned_to_a_commit_not_a_tag():
    """A tag can be moved upstream; a hash cannot.

    The owner's ruling on issue #45 decision (3) was "fetch at configure
    time, locked version, for build stability". A tag satisfies the
    letter of that and not the intent: `GIT_TAG V11.1.0` resolves to
    whatever V11.1.0 points at the day the fetch happens, and nothing in
    this tree would record that it moved.
    """
    path = os.path.join(REPO, "cmake", "freertos.cmake")
    if not os.path.isfile(path):
        pytest.skip("Track C is not in this tree yet")
    text = _read("cmake", "freertos.cmake")

    m = re.search(r'GIT_TAG\s+\$\{FREERTOS_COMMIT\}', text)
    assert m, "FreeRTOS is not fetched at a pinned commit"
    m = re.search(r'set\(FREERTOS_COMMIT\s+"([0-9a-f]{40})"\)', text)
    assert m, (
        "FREERTOS_COMMIT is not a full 40-character SHA. A tag or a "
        "short hash is not a lock.")


def test_the_build_image_carries_the_freertos_cmake_pins():
    """The image's FreeRTOS copy is fetched at freertos.cmake's hash.

    `docker/Dockerfile` cannot read `cmake/`: its build context is
    `docker/`. So the pin is written twice, and a bump that reaches one
    file and not the other leaves the image carrying a FreeRTOS the host
    build does not use. freertos.cmake's own check then refuses it at
    configure, inside the container, where the first sign is a red
    firmware step rather than this line.
    """
    path = os.path.join(REPO, "cmake", "freertos.cmake")
    if not os.path.isfile(path):
        pytest.skip("Track C is not in this tree yet")
    pin = re.search(r'set\(FREERTOS_COMMIT\s+"([0-9a-f]{40})"\)',
                    _read("cmake", "freertos.cmake"))
    arg = re.search(r"^ARG FREERTOS_COMMIT=([0-9a-f]{40})$",
                    _read("docker", "Dockerfile"), re.M)
    assert pin, "freertos.cmake no longer pins FREERTOS_COMMIT"
    assert arg, ("docker/Dockerfile no longer fetches FreeRTOS at a pinned "
                 "ARG FREERTOS_COMMIT, so a container build of Track C has "
                 "no copy and no network")
    assert arg.group(1) == pin.group(1), (
        f"docker/Dockerfile fetches FreeRTOS {arg.group(1)} and "
        f"cmake/freertos.cmake pins {pin.group(1)}")


def test_track_c_keeps_the_build_path_out_of_its_image():
    """Two builds of one commit must not differ by where they were built.

    `configASSERT` in FreeRTOSConfig.h passes `__FILE__`, which puts the
    absolute path of the checkout and of FreeRTOS into the image. Moving
    one FreeRTOS copy between two directories changed 18,203 bytes of the
    Track C image. The FreeRTOS map has to come after the checkout's,
    because FreeRTOS sits inside the checkout under build-c/_deps and
    GCC applies the last matching map.
    """
    path = os.path.join(REPO, "cmake", "freertos.cmake")
    if not os.path.isfile(path):
        pytest.skip("Track C is not in this tree yet")
    maps = re.findall(r"-ffile-prefix-map=\$\{(\w+)\}=",
                      _read("cmake", "freertos.cmake"))
    assert "CMAKE_SOURCE_DIR" in maps and "freertos_SOURCE_DIR" in maps, (
        f"freertos.cmake maps {maps}; both the checkout and FreeRTOS have "
        "to be mapped or their paths reach the image")
    assert maps.index("freertos_SOURCE_DIR") > maps.index("CMAKE_SOURCE_DIR"), (
        "the FreeRTOS map comes before the checkout's, so a FreeRTOS copy "
        "inside the tree is mapped as part of the checkout")
    assert re.search(r"target_compile_options\(track_c_bringup\s+PRIVATE\s+"
                     r"\$\{FREERTOS_PREFIX_MAP\}\)", _read("CMakeLists.txt")), (
        "track_c_bringup does not compile with FREERTOS_PREFIX_MAP, so the "
        "maps are defined and never reach the compiler")
