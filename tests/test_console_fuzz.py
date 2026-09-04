"""The debug console, fed arbitrary bytes, and the proof that it can fail.

`console.c` and `console_cmds.c` are the shared firmware behind the
programming port: an argument grammar typed a character at a time, a
command table, a dispatch, and the handler bodies that touch no
register. Nothing in front of them checks anything - no framing, no
CRC, no version gate - so the console is reachable by anyone holding a
serial cable, where `ctl.c` is reachable only by a peer that can build a
frame. They reach the outside world through `console_port.h` and
`ctl_port.h` alone, so they mock whole on a host compiler, the same
property `stream_port.h` gives the framer.

**What is under test is invariant 7**, not only memory safety: "every
main-loop pass has a bounded worst case that does not depend on what a
host chose to send". One keystroke is one pass. A console a malformed
line can walk off the end of, spin in, or make expensive by typing at
it for long enough is the defect this file exists to find.
`tests/console/fuzz_console.c` carries five oracles for that, and each
is mutation-tested below rather than trusted.

The mutations are mechanical edits to a copy of the shared source,
never to the tree, exactly as `test_ctl_fuzz.py` and
`test_framer_close.py` build theirs. Each anchor is asserted to appear
once, so a rewording fails here loudly instead of leaving a mutant
silently identical to the original. Two of them are the same defect at
two sites - the string walks corrected in `console_out.c` - because
correcting one left the other faulting, which is what makes them two
defects rather than one.

**The fast tier gets a couple of seconds of this and no more.** The
board-free selection is under a five-minute ceiling, and a fuzzing
campaign has no natural end - so what runs here is the built-in seed
corpus, which reaches every dispatch arm deterministically, plus a fixed
pseudo-random grind from two fixed seeds. `tests/console/fuzz_console.c`
is one target with two entry points, so a coverage-guided campaign runs
the same code.

**Both ABIs where the bench has both.** The target is a 32-bit
Cortex-M3 and every native harness on this project runs LP64, so a
defect that needs `size_t` and pointers to be 32 bits is invisible to
the whole host-run tier. `hostcc.abis()` reports what this machine can
build and run, and this file parametrises on it.
"""

import os
import re
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
TARGET = os.path.join(HERE, "console", "fuzz_console.c")

#: The shared sources the console is. `ctl.c` is here because the
#: generator arithmetic and `ctl_gen_describe()` live in it and
#: `console_cmds.c` calls them; its own parser is fuzzed by
#: `test_ctl_fuzz.py`.
SOURCES = ("console.c", "console_cmds.c", "console_out.c", "ctl.c",
           "crc32.c")

#: How many inputs the grind takes, and from which seeds. Fixed values,
#: because a run whose input set moves cannot be compared with the run
#: before it - and because a failure has to be re-enterable by anyone
#: who reads the failure message.
GRIND_RUNS = 25_000
GRIND_SEEDS = (1, 7)

#: Each mutation: which shared file, the text to remove or replace in a
#: copy of it, and what the harness must then say. The oracle each one
#: exercises is named, because a mutation that fires the wrong oracle is
#: a mutation that proved nothing about the one it was written for.
#:
#: `expect` is a list of alternatives rather than a conjunction, for the
#: reason `test_sanitizers.py` gives: which sanitizer speaks first is a
#: property of the compiler and not of the defect. A write past the end
#: of console.c's argument array is UBSan's array-bounds check on GCC
#: 15.2 and ASan's global redzone elsewhere, and both are the finding.
MUTATIONS = {
    "con-str-tests-its-bound-too-late": dict(
        file="console_out.c",
        oracle="ASan over the emitter walks",
        find="""		while (n < CON_STR_MAX && s[n])
			n++;
		if (n < CON_STR_MAX) {
""",
        replace="""		while (s[n] && n < CON_STR_MAX)
			n++;
		if (s[n] == '\\0') {
""",
        expect=["heap-buffer-overflow"],
    ),
    "con-strl-tests-its-bound-too-late": dict(
        file="console_out.c",
        oracle="ASan over the emitter walks, at the second site",
        find="""	while (s && n < CON_STR_MAX && s[n])
		n++;
""",
        replace="""	while (s && s[n] && n < CON_STR_MAX)
		n++;
""",
        expect=["heap-buffer-overflow"],
    ),
    "digits-past-the-last-argument": dict(
        file="console.c",
        oracle="ASan over console.c's argument array",
        find="""	if (arg_entry && c >= '0' && c <= '9') {
		if (arg_idx < CONSOLE_NARGS)
			arg[arg_idx] = arg[arg_idx] * 10u + (uint32_t)(c - '0');
		return;
	}
""",
        replace="""	if (arg_entry && c >= '0' && c <= '9') {
		arg[arg_idx] = arg[arg_idx] * 10u + (uint32_t)(c - '0');
		return;
	}
""",
        expect=["global-buffer-overflow", "out of bounds for type"],
    ),
    "an-idle-poll-closes-the-entry": dict(
        file="console.c",
        oracle="the argument model",
        find="""	if (c < 0)
		return;
""",
        replace="",
        expect=["arguments the grammar does not predict"],
    ),
    "a-refusal-without-the-prefix": dict(
        file="console.c",
        oracle="the output oracle",
        find="""		console_write("# ");
		console_write(k);
""",
        replace="""		console_write(k);
""",
        expect=["does not begin with '#'"],
    ),
    "a-wait-with-no-guard-on-it": dict(
        file="console_cmds.c",
        oracle="the bounded-work oracle",
        find="""		while (console_port_acq_buffers_done() == sync &&
		       (ctl_port_micros() - guard) < 2000000u)
			{ }
""",
        replace="""		while (console_port_acq_buffers_done() == sync)
			{ }
""",
        expect=["stopped making progress"],
    ),
}


def _comment_spans(src):
    """Where the comments and string literals are, as [start, end) pairs.

    One pass rather than a regex, because the three kinds nest the wrong
    way for one: a `/*` inside a string is not a comment, and a `//`
    inside one is not either. The strings are tracked only so the
    comment scan is not fooled by one.
    """
    spans = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
        elif src[i] in "\"'":
            q = src[i]
            i += 1
            while i < n and src[i] != q:
                i += 2 if src[i] == "\\" else 1
            i += 1
        else:
            i += 1
    return spans


def _is_code(src, start, end):
    """True if [start, end) lies outside every comment in `src`."""
    return not any(a < end and start < b for a, b in _comment_spans(src))


def _require(abi):
    if hostcc.cc() is None:
        pytest.skip("no host C compiler")
    if abi not in hostcc.abis():
        pytest.skip(f"this compiler cannot build and run {abi}-bit binaries")


def _gen_dir(tmp_path):
    """`fw_git_rev.h`, which the build system writes for a real image.

    `console.c` includes it for the identity line. A value is supplied
    here rather than reached for in a build tree, so this test needs no
    configured firmware build - the same choice `test_build_identity.py`
    makes, and for the stronger reason there.
    """
    inc = tmp_path / "gen"
    inc.mkdir(exist_ok=True)
    (inc / "fw_git_rev.h").write_text(
        "#ifndef FW_GIT_REV_H\n"
        "#define FW_GIT_REV_H\n"
        '#define FW_GIT_REV "fuzz"\n'
        "#endif\n")
    return str(inc)


def _build(tmp_path, name, abi, replaced=None):
    """Build the target, optionally against one substituted source."""
    sources = [replaced[1] if replaced and replaced[0] == f
               else os.path.join(SHARED, f) for f in SOURCES]
    exe = str(tmp_path / name)
    proc = subprocess.run(
        [hostcc.cc(), "-std=c11", "-Wall", "-Wextra",
         *hostcc.build_flags(abi),
         "-I", SHARED, "-I", _gen_dir(tmp_path), "-o", exe,
         TARGET, *sources],
        capture_output=True, text=True, env=hostcc.cc_env(), timeout=600)
    assert proc.returncode == 0, f"fuzz target build failed:\n{proc.stderr}"
    return exe


@pytest.fixture(scope="module")
def targets(tmp_path_factory):
    """One built target per ABI this bench can build and run."""
    if hostcc.cc() is None:
        return {}
    tmp = tmp_path_factory.mktemp("consolefuzz")
    return {abi: _build(tmp, f"fuzz_console{abi}", abi)
            for abi in hostcc.abis()}


def _run(exe, args, timeout=600):
    return subprocess.run([exe, *args], capture_output=True, text=True,
                          env=hostcc.cc_env(), timeout=timeout)


@pytest.mark.parametrize("abi", hostcc.ABIS)
def test_the_seed_corpus_finds_nothing(targets, abi):
    """Every command arm, every refusal, and the emitters at their bound.

    The seeds are keystroke strings built in the harness, so a new
    console letter is one line there rather than a binary nobody can
    read. They are the same bytes `--write-seeds` hands libFuzzer, so
    the fast tier and a campaign start from one corpus.
    """
    _require(abi)
    proc = _run(targets[abi], ["--builtin"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 violations" in proc.stdout, proc.stdout


@pytest.mark.parametrize("abi", hostcc.ABIS)
@pytest.mark.parametrize("seed", GRIND_SEEDS)
def test_a_deterministic_grind_finds_nothing(targets, abi, seed):
    """Fixed seeds, fixed count - re-enterable from the failure message.

    No coverage feedback, so this is a weaker instrument than a campaign
    and is not offered as a substitute for one. What it is, is the arm
    that runs on every change, on a bench with no clang.
    """
    _require(abi)
    proc = _run(targets[abi], ["--random", str(GRIND_RUNS), str(seed)])
    assert proc.returncode == 0, (
        f"reproduce with: fuzz_console --random {GRIND_RUNS} {seed}\n"
        + proc.stdout + proc.stderr)
    assert "0 violations" in proc.stdout, proc.stdout


@pytest.mark.parametrize("abi", hostcc.ABIS)
def test_the_caps_are_not_within_reach_of_ordinary_output(targets, abi):
    """The bounded-work caps must sit clear of what the console costs.

    A cap the corpus nearly reaches is a cap about to fire on something
    harmless, and a cap orders of magnitude away is one that would miss
    a real regression. The harness prints both, so the margin is read
    rather than assumed - `h` is the largest legitimate emitter and the
    rate sweep against an acquisition that never completes a buffer is
    the longest legitimate wait.
    """
    _require(abi)
    proc = _run(targets[abi], ["--builtin"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    marks = [ln for ln in proc.stdout.splitlines()
             if ln.startswith("high water:")]
    assert len(marks) == 1, proc.stdout
    got = [int(t) for t in re.findall(r"\d+", marks[0])]
    assert len(got) == 6, marks[0]
    for reached, cap in zip(got[:3], got[3:]):
        assert reached < cap, marks[0]
        assert cap < reached * 100, (
            f"a cap a hundred times what the console costs would not "
            f"catch a regression: {marks[0]}")


@pytest.mark.parametrize("abi", hostcc.ABIS)
@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_harness_catches_a_console_broken_on_purpose(tmp_path, abi, name):
    """One mutation per oracle, and the seed corpus alone must catch it.

    Not a test of the console - a test of the fuzz target. The six
    together say what this file's null result is worth: memory safety
    over the two string walks and over the argument array, a grammar
    that matches its own documentation, output a host can parse, and a
    keystroke that finishes.

    The corpus is what runs here rather than the grind, because a
    mutation only the random arm catches would be one the fast tier
    finds by luck.
    """
    _require(abi)
    m = MUTATIONS[name]
    original = os.path.join(SHARED, m["file"])
    with open(original) as fh:
        src = fh.read()
    assert src.count(m["find"]) == 1, (
        f"the {name} anchor is no longer in {m['file']} verbatim. If the "
        f"code was reworded, update MUTATIONS; if it was removed, that is "
        f"the regression this file exists to catch.")
    at = src.index(m["find"])
    assert _is_code(src, at, at + len(m["find"])), (
        f"the {name} anchor sits inside a comment in {m['file']}, so the "
        f"mutant would be identical to the original everywhere it runs and "
        f"the result below would mean nothing. That mistake has been made "
        f"on this project - a flag mutated inside a comment, and the green "
        f"read as evidence.")
    mutant = tmp_path / ("mutant_" + m["file"])
    mutant.write_text(src.replace(m["find"], m["replace"], 1))

    exe = _build(tmp_path, "fuzz_mutant", abi, (m["file"], str(mutant)))
    proc = _run(exe, ["--builtin"], timeout=300)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"the {name} mutant passed the seed corpus, so {m['oracle']} has "
        f"no power over it:\n{out}")
    assert any(e in out for e in m["expect"]), (
        f"the {name} mutant failed, but not through {m['oracle']}. "
        f"Expected one of {m['expect']}:\n{out}")
