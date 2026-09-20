"""The fuzz campaign works in a local corpus and publishes at the end.

`docker/run-fuzz.sh` gives libFuzzer a corpus directory, and libFuzzer
writes every new interesting input into it as a file the moment it is
found - hundreds of creates inside a step that runs for a fixed time.
The gate hands the script `DUE_FUZZ_CORPUS` under `docker/out/ci`, and
in the container-local copy `docker/out` is a bridge back to the bench's
checkout: on `linux-x1` that is native ext4, on `windows-desk` it was
drvfs, on `mac-bench` it is sshfs. So the one step of the gate that still
did hot per-file I/O across the host mount was this one, and it showed
where a fixed-duration step can only show - not in the verdict, not in
the wall time, but in the work done: `windows-desk` measured 91,053
executions from a drvfs checkout against 322,998 from ext4 in the same
37.9 s, both PASS, and the ext4 tree had MORE corpus files. The gate
was reporting the same verdict on a third of the evidence.

The fix is the shape `docker/build-firmware.sh` already has for objects:
work locally, publish the result. libFuzzer's working corpus is in the
script's scratch directory, and `DUE_FUZZ_CORPUS` becomes where the
corpus is imported from at the start and published to at the end. A
crash reproducer still goes straight to the published `crashes/`, because
one file written once is not the cost and a reproducer must survive a
run that is killed.

WHAT THIS TEST OBSERVES, rather than asserts about the script's text.
It runs the real campaign with a published directory of its own and
looks at that directory twice: once while libFuzzer is provably writing
new units - its own `NEW` lines say so - and once after exit. Mid-run
the published directory must hold nothing, because the units are local;
after exit it must hold the corpus. A script that put the working corpus
back on the published path fails the first look; one that stopped
publishing fails the second. Both were tried on purpose before this was
trusted, and each failed the look it was meant to.

Needs clang with the libFuzzer runtime, which the image carries and a
bench may not; where it is absent this skips and says so, and the gate
runs it everywhere.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time

import pytest

pytestmark = pytest.mark.slow

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "docker", "run-fuzz.sh")

CAMPAIGN_S = 6
#: New units libFuzzer must have reported inside the campaign before the
#: published directory is inspected. Below this the mid-run look proves
#: nothing - with no unit written locally, an empty published directory
#: is what a broken script would show too.
NEW_UNITS = 3


def _libfuzzer_available():
    clang = shutil.which("clang")
    if not clang:
        return False
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("#include <stddef.h>\n#include <stdint.h>\n"
                     "int LLVMFuzzerTestOneInput(const uint8_t *d, size_t n)"
                     "{ (void)d; (void)n; return 0; }\n")
        r = subprocess.run([clang, "-fsanitize=fuzzer", "-o",
                            os.path.join(d, "t"), src],
                           capture_output=True)
        return r.returncode == 0


def _count_files(d):
    return sum(1 for e in os.listdir(d)
               if os.path.isfile(os.path.join(d, e)))


def _new_units_after_campaign(log_path):
    """How many `NEW` lines libFuzzer printed after the campaign began.

    The positive control prints `NEW` lines too, so they are only counted
    past the campaign banner. -1 while the banner has not appeared.
    """
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except FileNotFoundError:
        return -1
    at = text.find("== campaign:")
    if at < 0:
        return -1
    return len(re.findall(r"^#\d+\s+NEW\b", text[at:], re.M))


def test_the_campaign_writes_locally_and_publishes_at_the_end(tmp_path):
    if not _libfuzzer_available():
        pytest.skip("no clang with the libFuzzer runtime on this host; "
                    "the container has it and the gate runs this there")

    keep = tmp_path / "keep"
    log = tmp_path / "fuzz.log"
    env = dict(os.environ, DUE_FUZZ_CORPUS=str(keep))
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(["bash", SCRIPT, str(CAMPAIGN_S)],
                                cwd=REPO, env=env, stdout=out,
                                stderr=subprocess.STDOUT)
        try:
            # Wait until libFuzzer has itself reported enough new units
            # inside the campaign that its working corpus certainly
            # holds files, then look at where those files are NOT.
            deadline = time.monotonic() + 120
            seen = -1
            while proc.poll() is None and time.monotonic() < deadline:
                seen = _new_units_after_campaign(str(log))
                if seen >= NEW_UNITS:
                    break
                time.sleep(0.1)
            assert seen >= NEW_UNITS, (
                f"libFuzzer reported {seen} new units inside a {CAMPAIGN_S} s "
                f"campaign before it ended, below the {NEW_UNITS} this test "
                "needs to have observed anything - so this run says nothing "
                "about where the corpus was written. Log:\n"
                + open(log, encoding="utf-8", errors="replace").read()[-3000:])
            assert keep.is_dir(), "the published directory was never created"
            mid = _count_files(str(keep))
            assert mid == 0, (
                f"{mid} corpus files were in the published directory while "
                "the campaign was still running - libFuzzer is writing its "
                "working corpus across the published path, which on a bench "
                "whose docker/out is a network mount is the hot I/O this "
                "script exists to keep local")
        finally:
            rc = proc.wait(timeout=180)

    text = open(log, encoding="utf-8", errors="replace").read()
    assert rc == 0, f"run-fuzz.sh exited {rc}:\n{text[-3000:]}"
    final = _count_files(str(keep))
    assert final > 0, (
        "the campaign ended with nothing in the published directory: the "
        "corpus was not published, so a long campaign keeps nothing and "
        "the gate records nothing")
    assert (keep / "crashes").is_dir(), (
        "no crashes/ under the published directory, which is where a "
        "reproducer must land to survive the run")
    assert re.search(r"^published \d+ corpus files to ", text, re.M), (
        "the script did not report the publish it made")
