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
import os
import re

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
    `add_dependencies(baremetal_bringup enforce_clean_build)`, which
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
    assert re.search(r"--target\s+baremetal_bringup", cml), (
        "the driver cleans but never builds the firmware; `all` would "
        "now produce no image at all")
    assert re.search(r"add_executable\(\s*baremetal_bringup\s+"
                     r"EXCLUDE_FROM_ALL", cml), (
        "baremetal_bringup is back in `all`, so `cmake --build build` "
        "builds it directly and incrementally, stepping past the clean")

    assert not re.search(r"add_dependencies\(\s*baremetal_bringup\s+"
                         r"\w*clean\w*\s*\)", cml), (
        "the clean is a dependency of the executable again. That is the "
        "shape that broke under Ninja: the generator plans the whole "
        "graph, then the clean deletes the objects the same plan is "
        "about to link. See issue #35")


def test_flashing_track_b_also_gets_a_clean_build():
    """The flash target must not route around the driver.

    `flash` used to say `DEPENDS baremetal_bringup`, which now names a
    target outside `all` and would build it incrementally - a clean
    build for anyone typing `cmake --build build` and a stale one for
    anyone typing `--target flash`, which is the more dangerous of the
    two because its output goes on a board and into the flash log.
    """
    cml = _read("CMakeLists.txt")
    assert re.search(r"add_dependencies\(\s*flash\s+firmware\s*\)", cml), (
        "the flash target does not depend on the `firmware` driver, so "
        "`cmake --build build --target flash` can put an incrementally "
        "built image on the board")
    flash_block = cml[cml.index("add_custom_target(flash\n"):] \
        if "add_custom_target(flash\n" in cml else cml[cml.index("add_custom_target(flash"):]
    flash_block = flash_block[:flash_block.index("add_dependencies(flash")]
    assert "DEPENDS baremetal_bringup" not in flash_block, (
        "the flash target depends on baremetal_bringup directly again, "
        "which bypasses the clean")


def test_track_a_build_is_clean_by_construction():
    """Track A's target cleans first, as `firmware` and `firmware_rtos` do.

    Ported from the guard that asserted `tools/sketch.py` (deleted,
    #55) passed `--clean` to arduino-cli. The reason is unchanged and is not
    hypothetical: arduino-cli's cache did not notice every change under
    `--libraries`, which is how a Track A image once shipped with a stale
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


def test_track_a_flash_builds_before_it_flashes():
    """`measure.flash(track='a')` compiles rather than reusing an artifact.

    Ported from the guard on `sketch.py upload`, deleted in #55, and
    this one is not hypothetical either. `upload` used to flash whatever .bin was in
    the build path, which is the image for whatever tree last compiled
    and not the image for this one. It put an experimental firmware -
    with issue #33's guard deliberately removed - onto a bench whose
    working tree was clean, and the only tell was that the recorded sha
    did not change.

    A flash is the single moment the tree and the board are supposed to
    agree, so it is the last place to reuse an artifact. The CMake path
    moved the risk rather than removing it: `build-a/` persists between
    runs exactly as arduino-cli's cache did.
    """
    mp = _read("host", "measure.py")

    i = mp.index('elif track == "a":')
    body = mp[i:i + 4000]

    # Match the argv, not the word. The first version of this asserted
    # `"firmware_track_a" in body`, and a mutation that pointed the build
    # at the raw `track_a_bringup` target - bypassing the clean wrapper,
    # exactly the defect - still passed, because the name also appears in
    # the comment four lines above. A guard that cannot fail is the thing
    # this file exists to prevent, so it is checked by mutation now.
    built = re.search(r'"--build",\s*build_a,\s*"--target",\s*"([a-z_]+)"',
                      body)
    assert built, (
        "measure.flash()'s Track A branch no longer runs a cmake --build "
        "on build_a, so it can put an image on the board that does not "
        "match the tree")
    assert built.group(1) == "firmware_track_a", (
        f"measure.flash() builds the {built.group(1)!r} target directly "
        "instead of firmware_track_a, which bypasses the clean wrapper")
    assert built.start() < body.index("flash.py"), (
        "measure.flash() flashes Track A before building it")


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
#: says it is, so a stale cache is the last thing it can tolerate.
#:
#: **Every entry spawns a build tool, and that is asserted rather than
#: intended.** An exemption for a file that needs none costs nothing on
#: the day it is written and everything on the day that file gains a
#: build spawn: it is then permitted silently, by a line nobody re-read.
#: Two entries here were in exactly that state - a tool that reports
#: where the compiler resolved, and one that puts a .bin on a board -
#: and dropping either from this set changed no result.
ALLOWED = {"host/measure.py", "tools/reproducible.py"}

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

    **Transitive, and it was not until 2026-08-31.** This matched
    `arduino-cli|cmake` in the spawn window and nothing else, so a file
    that spawned a file that spawned a build tool was invisible - and the
    allowlist entry permitting the legitimate middle file also hid every
    caller behind it. `tools/enum_probe.py` spawned `tools/sketch.py`,
    which drove arduino-cli, and this test passed for as long as both
    existed. It surfaced during #55 only because `sketch.py` was being
    deleted and somebody re-grepped; both are gone now (bf041e3), and
    the deletion would otherwise have left a bench tool broken for
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
        "can produce an image from a stale cache. Call measure.flash() "
        "rather than spawning a builder: "
        + ", ".join(sorted(set(offenders))))


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
    if "rtos_bringup" not in cml:
        pytest.skip("Track C is not in this tree yet")

    assert "add_custom_target(firmware_rtos" in cml, (
        "Track C has a build target but no clean-build wrapper. Every "
        "image in this project is built from scratch; see the comment "
        "above `firmware`.")

    body = cml[cml.index("add_custom_target(firmware_rtos"):]
    body = body[:body.index("VERBATIM")]
    clean_at = body.find("--target clean")
    build_at = body.find("--target rtos_bringup")
    assert clean_at >= 0, "firmware_rtos does not clean"
    assert build_at >= 0, "firmware_rtos does not build rtos_bringup"
    assert clean_at < build_at, (
        "firmware_rtos builds before it cleans, which cleans away the "
        "image it just produced")

    assert "add_dependencies(rtos_bringup" not in cml, (
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
