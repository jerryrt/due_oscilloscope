"""`docker/run-ci.sh` may not report an unanswered step as a pass.

Needs no board, and opens nothing. It reads and runs pieces of the
script rather than the whole thing: no compiler, no analyser and no
container are involved.

The script exists for one property and that property is the one nothing
was watching. It runs every check the build image can make and prints a
verdict, and its whole value is that a step which **did not run** is
reported as unanswered rather than folded into a pass - five states in
one column, an exit code no classifier recognises landing on DID NOT RUN
by construction, and DID NOT RUN outranking FAIL because "part of this
was not checked" is the weaker claim. Collapse a state, soften a
catch-all arm, or drop the build preflight, and every one of those goes
quiet while the suite stays green.

**The classifiers and the verdict are executed, not grepped.** A regex
over a shell script asserts what the text looks like; feeding
`class_pytest` an exit code and reading the state back asserts what the
script does. The functions are lifted out of the file by brace balance
and sourced, so what runs here is the same text `docker/run.sh` runs -
which is also why a bench with no `bash` skips rather than passes: this
would otherwise be a guard certifying a script it never executed.

`docker/run-cppcheck.sh`, `docker/run-clang-tidy.sh` and
`docker/run-fuzz.sh` each separate "found nothing" from "analysed
nothing" in their own exit codes, and they carry their own positive
controls. This is the guard on the file that consumes that distinction.
"""
import os
import re
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "docker", "run-ci.sh")

#: The one classifier whose unrecognised exit is FAIL rather than DID NOT
#: RUN, because the state it would otherwise need is established before
#: it is called: the firmware step is gated by a toolchain preflight, so
#: by the time a build has an exit code at all the tools were there and a
#: non-zero code is a build that failed. That arrangement is pinned by
#: test_the_firmware_step_is_preflighted below; without it this exemption
#: would be a hole.
_PREFLIGHTED = {"class_build"}

#: What a verdict may not say while a step is unanswered. `good` is not
#: here on purpose - the INCOMPLETE verdict says "does not say the tree
#: is good", and a word list that cannot tell a negation from a claim
#: fails on its own subject line.
_PASS_WORDS = re.compile(r"\b(pass|passed|passes|passing|ok|green|"
                         r"success|successful|clean)\b", re.I)

_OPENS = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{")

#: Where the hand-written record table is spliced into the verdict
#: fragment. A literal marker rather than a %s: the tail is full of
#: printf formats and a percent-format over it substitutes in the
#: wrong places.
_RECORDS = "@@RECORDS@@\n"


def _source():
    with open(SCRIPT, encoding="utf-8") as fh:
        return fh.read()


def _shell_functions(text):
    """name -> definition, for every top-level shell function.

    Brace balance over lines rather than a match ending at a `}` in the
    first column: `now()`, `took()` and `have_pytest()` are one-liners,
    and a pattern that wants a closing brace on its own line swallows
    each of them plus the function after it. That silently lost
    `last_match` and `run_step` when this was first written, and a
    fragment missing a helper fails loudly at `bash` rather than quietly
    here - but only because something ran it.
    """
    out, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        m = _OPENS.match(lines[i])
        if not m:
            i += 1
            continue
        start, depth = i, lines[i].count("{") - lines[i].count("}")
        while depth > 0 and i + 1 < len(lines):
            i += 1
            depth += lines[i].count("{") - lines[i].count("}")
        out[m.group(1)] = "\n".join(lines[start:i + 1])
        i += 1
    return out


def _states(text):
    """The five state words, as the script spells them once."""
    return dict(re.findall(r"^(S_[A-Z]+)='([^']*)'$", text, re.M))


def _bash():
    exe = shutil.which("bash")
    if not exe:
        pytest.skip("no bash on this bench, so run-ci.sh cannot be executed "
                    "here at all - a static reading of it is in "
                    "test_no_catch_all_arm_reports_a_pass")
    return exe


def _run(fragment):
    return subprocess.run([_bash(), "-c", fragment],
                          capture_output=True, text=True, timeout=60)


def _classifier_fragment(text, funcs):
    """The state words, the two log readers, and every classifier."""
    need = ["last_match", "first_match"]
    need += sorted(n for n in funcs if n.startswith("class_"))
    missing = [n for n in need if n not in funcs]
    assert not missing, (
        f"run-ci.sh no longer defines {missing}, so the classifiers cannot "
        "be lifted out and this guard would test nothing")
    consts = re.findall(r"^S_[A-Z]+='[^']*'$", text, re.M)
    return "\n".join(consts + [funcs[n] for n in need])


def _classify(fragment, name, rc, log):
    """Run one classifier and split its state from its detail."""
    out = _run(f'{fragment}\n{name} {rc} "{log}"\n')
    assert out.returncode == 0, f"{name} {rc} errored: {out.stderr}"
    state, _, detail = out.stdout.strip().partition("\t")
    return state, detail


def _verdict_fragment(text):
    """The summary and the verdict, with the records supplied by hand.

    Everything above the tally prints as it goes; the tally, the exit
    code and the verdict text are the part a reader is entitled to read
    on its own, and the part a step's state has to survive into.
    """
    i = text.index("\nn_pass=0")
    return "\n".join(re.findall(r"^S_[A-Z]+='[^']*'$", text, re.M)) \
        + "\nelapsed=0.0\n" + _RECORDS + text[i:]


def _verdict(fragment, rows):
    recs = "records=(\n" + "\n".join(
        "  $'%s\\t%s\\t0.0\\t%s'" % row for row in rows) + "\n)\n"
    out = _run(fragment.replace(_RECORDS, recs))
    assert not out.stderr, out.stderr
    return out.returncode, out.stdout


def _verdict_lines(stdout):
    """The VERDICT sentence, without the steps it goes on to name.

    A named step carries its own detail, and a DID NOT RUN detail may
    legitimately quote a pytest summary containing the word `passed`.
    The claim under test is the script's own, so it stops at the first
    indented line.
    """
    keep, seen = [], False
    for line in stdout.splitlines():
        if line.startswith("VERDICT"):
            seen = True
        elif seen and (not line.strip() or line.startswith("  ")):
            break
        if seen:
            keep.append(line)
    return "\n".join(keep)


# ---------------------------------------------------------------------
# The classifiers
# ---------------------------------------------------------------------

def test_an_unrecognised_exit_code_is_never_a_pass(tmp_path):
    """127 is what a renamed or deleted script produces.

    Every classifier is discovered rather than listed, so a sixth one
    added later is covered the day it appears - which is the failure
    mode a hand-written list has and this does not.

    The log is empty, so nothing a classifier reads out of it can push
    the answer towards a pass on its own.
    """
    text = _source()
    funcs = _shell_functions(text)
    frag = _classifier_fragment(text, funcs)
    states = _states(text)
    log = tmp_path / "empty.log"
    log.write_text("")

    names = sorted(n for n in funcs if n.startswith("class_"))
    assert len(names) >= 5, f"only {names} - the classifiers have moved"

    for name in names:
        for rc in (3, 4, 99, 127, 255):
            state, detail = _classify(frag, name, rc, log)
            assert state not in (states["S_PASS"], states["S_FIND"]), (
                f"{name} calls exit {rc} {state!r} ({detail}). An exit code "
                "no classifier recognises means the step did not answer, "
                "and reporting that as a pass is the one thing run-ci.sh "
                "exists to prevent")
            if name not in _PREFLIGHTED:
                assert state == states["S_NORUN"], (
                    f"{name} calls exit {rc} {state!r}, not "
                    f"{states['S_NORUN']!r}. Only {sorted(_PREFLIGHTED)} may "
                    "answer an unknown code with anything else, because only "
                    "they run behind a precondition check")


def test_the_documented_exit_codes_answer_as_documented(tmp_path):
    """The positive direction, without which the check above is vacuous.

    A classifier that answered DID NOT RUN to everything would satisfy
    every assertion in the previous test while making the whole script
    useless, so each documented code is pinned to the state its own
    comment promises.
    """
    text = _source()
    frag = _classifier_fragment(text, _shell_functions(text))
    s = _states(text)

    clean = tmp_path / "clean.log"
    clean.write_text("total 7\n506 passed, 5 skipped, 141 deselected\n")
    errored = tmp_path / "errored.log"
    errored.write_text("8 error in 1.20s\n")

    cases = [
        ("class_pytest", 0, clean, s["S_PASS"]),
        ("class_pytest", 1, clean, s["S_FAIL"]),
        ("class_pytest", 5, clean, s["S_NORUN"]),
        ("class_analyser", 0, clean, s["S_PASS"]),
        ("class_analyser", 2, clean, s["S_FIND"]),
        ("class_fuzz", 0, clean, s["S_PASS"]),
        ("class_fuzz", 2, clean, s["S_FAIL"]),
        ("class_repro", 0, clean, s["S_PASS"]),
        ("class_repro", 1, clean, s["S_FAIL"]),
        ("class_build", 0, clean, s["S_PASS"]),
        # The board-absent control's assertion is inverted: the board
        # tests must ERROR for want of hardware, so a zero exit means a
        # board answered on a machine chosen because it has none.
        ("class_board_absent", 0, errored, s["S_FAIL"]),
        ("class_board_absent", 1, errored, s["S_PASS"]),
        ("class_board_absent", 1, clean, s["S_FAIL"]),
    ]
    for name, rc, log, want in cases:
        state, detail = _classify(frag, name, rc, log)
        assert state == want, (
            f"{name} exit {rc} over {log.name} answered {state!r} "
            f"({detail}), documented as {want!r}")


def test_no_catch_all_arm_reports_a_pass():
    """Read rather than run, so a bench with no bash still checks this.

    Weaker than the executed check and not a substitute for it: it sees
    where the state words are written, not what the function returns.
    It is here because the executed tests skip without bash, and a
    tier-1 bench where they skip would otherwise watch nothing.
    """
    text = _source()
    good = {"$S_NORUN", "$S_FAIL"}
    for name, body in sorted(_shell_functions(text).items()):
        if not name.startswith("class_"):
            continue
        arms = re.findall(r"^\s*\*\)(.*?);;", body, re.M | re.S)
        arms += re.findall(r"^\telse\n(.*?)^\tfi", body, re.M | re.S)
        assert arms, (
            f"{name} has neither a catch-all case arm nor an else, so an "
            "exit code it does not name falls out with no state at all")
        for arm in arms:
            named = set(re.findall(r"\$S_[A-Z]+", arm))
            assert named and named <= good, (
                f"{name}'s catch-all arm reports {sorted(named)}. An "
                "unrecognised exit code must land on DID NOT RUN, or on "
                "FAIL where a precondition check has already run")


# ---------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------

def test_the_five_states_are_counted_separately():
    """One record of each state, and each lands in its own bucket.

    This is what a collapsed state looks like from the outside: fold
    DID NOT RUN into NOT SELECTED and the tally still prints five
    numbers, one of which is wrong, and the exit code stops gating.
    """
    text = _source()
    frag = _verdict_fragment(text)
    s = _states(text)
    rows = [(f"step{i}", state, "-")
            for i, state in enumerate(
                [s["S_PASS"], s["S_FIND"], s["S_FAIL"],
                 s["S_NORUN"], s["S_SKIP"]])]
    rc, out = _verdict(frag, rows)

    tally = [ln for ln in out.splitlines() if ln.startswith("steps:")]
    assert len(tally) == 1, out
    counts = [int(n) for n in re.findall(r"\b(\d+)\b", tally[0])]
    assert counts == [1, 1, 1, 1, 1], (
        f"{tally[0]!r} - five distinct states did not produce five counts "
        "of one, so at least one of them is no longer counted where it is "
        "reported")
    assert rc == 1, f"a DID NOT RUN in the table exited {rc}, not 1"


def test_did_not_run_outranks_failed():
    """1 wins over 2 when both happen.

    "Part of this was not checked" is the weaker claim and the honest
    one: a run that reports FAILED while a step is unanswered is
    claiming to know the shape of a tree it did not finish reading.
    """
    text = _source()
    frag = _verdict_fragment(text)
    s = _states(text)

    rc, _ = _verdict(frag, [("a", s["S_FAIL"], "boom")])
    assert rc == 2, "a gating failure alone must exit 2"

    rc, _ = _verdict(frag, [("a", s["S_NORUN"], "no clang")])
    assert rc == 1, "an unanswered step alone must exit 1"

    rc, out = _verdict(frag, [("a", s["S_FAIL"], "boom"),
                              ("b", s["S_NORUN"], "no clang")])
    assert rc == 1, (
        f"both together exited {rc}. DID NOT RUN must outrank FAIL, or a "
        "run that failed to check half the tree reports the half it read")
    assert "INCOMPLETE" in out, out

    rc, _ = _verdict(frag, [("a", s["S_PASS"], "-")])
    assert rc == 0, "a table of passes must exit 0"


def test_the_verdict_claims_no_pass_while_a_step_is_unanswered():
    """The words, not only the exit code.

    An exit code is read by a harness and the verdict line is read by a
    person, and the four guards this project documents all went wrong in
    the half a person reads.
    """
    text = _source()
    frag = _verdict_fragment(text)
    s = _states(text)

    _, out = _verdict(frag, [("host tier", s["S_PASS"], "506 passed"),
                             ("fuzz", s["S_NORUN"], "no clang")])
    said = _verdict_lines(out)
    assert said, out
    hit = _PASS_WORDS.search(said)
    assert not hit, (
        f"the verdict says {hit.group(0)!r} while a step DID NOT RUN:\n"
        f"{said}")

    # And it names what was not answered, rather than only counting it.
    assert "fuzz" in out and "no clang" in out, out

    # Not vacuous: the verdict for a clean run does claim a pass, so the
    # check above is reading a sentence that varies.
    _, clean = _verdict(frag, [("host tier", s["S_PASS"], "506 passed")])
    assert _PASS_WORDS.search(_verdict_lines(clean)), _verdict_lines(clean)


def test_the_firmware_step_is_preflighted():
    """A missing toolchain must not read as a build that failed.

    `class_build` maps every non-zero exit to FAIL, which is the one
    exemption in `_PREFLIGHTED` above, and it is only correct while
    something upstream has already established that the compiler, cmake
    and the SAM core are present. Drop the preflight and a container
    without a toolchain reports FAILED - a claim about the source -
    instead of DID NOT RUN, which is a claim about the run.
    """
    text = _source()
    first = text.index("build_blocked=")
    m = re.search(r'(?<![a-z_])run_step "firmware"', text)
    assert m, "run-ci.sh no longer runs a firmware step at all"
    built = m.start()
    assert first < built, (
        "the firmware step is reached before anything sets build_blocked")

    region = text[first:built]
    assert re.search(r"if\s+!\s+have_tool\s+\w+", region), (
        "nothing in the preflight asks the toolchain registry whether a "
        "tool resolves; on two of this project's three benches the build "
        "tools are not on PATH, so `command -v` is not that question")
    assert 'norun_step "firmware"' in region, (
        "the firmware step has no DID NOT RUN branch any more, so a bench "
        "with no toolchain reports a build failure it never attempted")
