"""lib/due_shared/src/crashrec.c: the fault record that survives a reset.

The module is driven on the host: a harness includes the source, so it
can play the part of "RAM a reset does not clear". Board-free.

**The test's own power is checked.** The harness is built against the
real source and against three mutants - the CRC check removed, the
"reported once" clear removed, and the reset-loop guard off by one - and
each mutant must fail. Each mutant is one exact substitution, asserted to
match once, so a reworded source fails here loudly instead of leaving a
mutant that silently equals the original.
"""
import os
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
HARNESS = os.path.join(HERE, "crashrec", "harness.c")
SRC = os.path.join(SHARED, "crashrec.c")

MUTANTS = {
    "no_crc_check": (
        "rec.crc == rec_crc(&rec);", "1;",
        "corrupted block reported as a fault"),
    "pending_never_cleared": (
        "\t\trec.pending = 0;      /* reported once; count and streak stay */\n",
        "",
        "fault reported twice"),
    "loop_guard_off_by_one": (
        "rec.streak < CRASHREC_MAX_STREAK", "rec.streak <= CRASHREC_MAX_STREAK",
        "fault 3 in a row must not reset"),
}


def _build(tmp_path, src, name):
    exe = str(tmp_path / name)
    proc = subprocess.run(
        [hostcc.cc(), "-std=c11", "-Wall", *hostcc.sanitize_flags(),
         f'-DCRASHREC_SRC="{src}"', "-I", SHARED, "-o", exe, HARNESS,
         os.path.join(SHARED, "crc32.c")],
        capture_output=True, text=True, env=hostcc.cc_env())
    assert proc.returncode == 0, f"harness build failed:\n{proc.stderr}"
    return exe


def _run(exe):
    return subprocess.run([exe], capture_output=True, text=True,
                          env=hostcc.cc_env())


@pytest.mark.skipif(hostcc.cc() is None, reason="no host C compiler")
def test_the_record_survives_a_restart_and_is_reported_once(tmp_path):
    proc = _run(_build(tmp_path, SRC, "real"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


@pytest.mark.skipif(hostcc.cc() is None, reason="no host C compiler")
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_the_harness_fails_on_each_mutant(tmp_path, name):
    old, new, expect = MUTANTS[name]
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    assert text.count(old) == 1, (
        f"mutant {name}: the text it removes is no longer in crashrec.c "
        f"exactly once. Update the mutant; do not delete it.")
    mutant = tmp_path / f"crashrec_{name}.c"
    mutant.write_text(text.replace(old, new, 1), encoding="utf-8")
    proc = _run(_build(tmp_path, str(mutant), name))
    assert proc.returncode != 0, (
        f"the {name} mutant passed the harness, so the harness has no "
        f"power over that fault:\n" + proc.stdout)
    assert expect in proc.stdout


def test_reset_names_cover_every_rsttyp_value():
    # The names live in C; this holds the table's contract on the host.
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    for word in ("power-on", "backup", "watchdog", "software", "user-pin"):
        assert f'"{word}"' in text
