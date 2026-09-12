#!/usr/bin/env python3
"""One machine-readable row describing a `docker/run-ci.sh` run.

    docker/run.sh docker/run-ci.sh; rc=$?
    python3 tools/container_report.py --exit "$rc" \
            --append records/container-universality.jsonl

APPEND THROUGH THE TOOL, NOT THROUGH THE SHELL. `>> records/...` looks
equivalent and is not: the shell creates the file before this runs, so an
untracked record makes the working tree dirty and every row comes out
labelled `<rev>-dirty` for a reason that has nothing to do with the tree
being edited. That is how the first row taken here was labelled, and three
benches would each have recorded it. `--append` reads the provenance first
and opens the file afterwards.

WHAT THIS IS FOR. Three benches are answering one question - is the
container's check set the same thing on Linux, macOS and Windows - and
three benches typing three prose summaries cannot answer it. A figure
without its bench is not comparable with anything, and a figure
hand-transcribed out of a fixed-width table into an issue comment is
worse: nobody can tell a typo from a finding. So every bench runs the
same instrument and appends one row.

IT READS ARTEFACTS, NOT THE SUMMARY PROSE. `docker/run-ci.sh` prints a
five-state table and this deliberately does not parse it. Re-deriving
those states here would be a second implementation of its classifiers,
and two classifiers that disagree is worse than one - the whole point of
that script is that a state means one thing. What this collects instead
is the set of facts that are unambiguous wherever they are read: the
build environment JSON the build itself wrote, the counts the analysers
print about themselves, and the pytest summary lines. The run's VERDICT
arrives as `--exit`, from the script's own exit code.

`--exit` IS REQUIRED AND IS NOT GUESSED. A row with no verdict would be
a row that says every step passed by omission, and the exit code is the
one fact no artefact in the log directory carries. Read it without a
pipe - `cmd; rc=$?` - because `cmd | tee; echo $?` reports tee's.

Stdlib only, and it runs on the HOST rather than in the image: half of
what makes a row comparable is which container runtime produced it, and
from inside the container every bench looks like Linux.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCHEMA = "container-universality/1"

#: The ten steps `docker/run-ci.sh` runs, in its own order, and the log
#: each writes. A step absent from the log directory is reported absent
#: rather than skipped over: a missing log and a step that passed are the
#: same silence otherwise.
STEPS = ("firmware", "host-tier", "board-absent", "reproducible-b",
         "reproducible-a", "stack-report", "cppcheck", "clang-tidy", "fuzz",
         "working-tree")

#: pytest's own tail. Matched on the summary line and not on the body,
#: for the reason class_board_absent gives: a clean run's log contains
#: the words "1 passed" inside quoted source, so grepping the whole file
#: reads every run as a pass.
_PYTEST = re.compile(r"^=*\s*(\d+ (?:passed|failed|error|skipped|deselected)"
                     r"[^=]*?)\s*(?:in [\d.]+s.*)?=*$", re.M)
_TOTAL = re.compile(r"^total\s+(\d+)", re.M)
_EXECS = re.compile(r"number_of_executed_units:\s*(\d+)")
_LAYOUT = re.compile(r'"layout":\s*"([0-9a-f]+)"')
#: `tools/reproducible.py`'s per-artifact column. The COUNT rather than
#: its own verdict line, because a count of 0 is the claim and the
#: sentence is a rendering of it - and a bench whose bytes differ needs
#: the number, not the word.
_DIFFER = re.compile(r"(\d+) differing bytes")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _pytest_tail(text):
    """The LAST pytest summary line, or None.

    Last rather than first: a failing run prints a short-summary block
    before the tail, and the tail is the one that counts everything.
    """
    hits = _PYTEST.findall(text or "")
    return hits[-1].strip() if hits else None


def _run(argv):
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or out.stderr or "").strip().splitlines()[0] \
        if (out.stdout or out.stderr).strip() else None


def runtime():
    """How this host runs Linux containers, which is half the question.

    Docker's own version string does not say: `docker version` looks the
    same under Docker Desktop, colima and a native daemon. So the
    context name comes with it - `colima` on mac-bench, `desktop-linux`
    under Docker Desktop's WSL2 backend, `default` on a native daemon -
    and it is reported rather than interpreted, because mapping a
    context name onto a mechanism is a guess this does not need to make.
    """
    return {
        "docker_version": _run(["docker", "version", "--format",
                                "{{.Server.Version}}"]),
        "docker_context": _run(["docker", "context", "show"]),
        "host_kernel": platform.release(),
        "host_machine": platform.machine(),
        "host_system": platform.system(),
        # WSL puts a marker in the kernel string and nothing else does.
        "wsl": "microsoft" in platform.release().lower(),
    }


def baked_revision(build):
    """The revision compiled INTO the container's Track B image, or None.

    `FW_GIT_REV` is a string in the binary, so an artifact says which
    commit it was built from no matter what the working tree has done
    since. That is what makes the check below possible, and it is the
    check that matters most to a cross-bench comparison: three benches
    can only compare artifact hashes at one commit, and the way that
    silently stops being true is a tree that moved after the build.
    """
    for name in ("baremetal_bringup.bin", "baremetal_bringup.elf"):
        path = os.path.join(build, name)
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            continue
    return None


def collect(logs, build, exit_code):
    sys.path.insert(0, os.path.join(REPO, "host"))
    prov = {}
    try:
        import provenance
        prov = provenance.collect()
    except Exception:                                        # noqa: BLE001
        prov = {}

    env = {}
    env_path = os.path.join(build, "build-env.json")
    raw = _read(env_path)
    if raw:
        try:
            env = json.loads(raw)
        except ValueError:
            env = {"parse_error": env_path}

    steps = {}
    for name in STEPS:
        text = _read(os.path.join(logs, name + ".log"))
        if text is None:
            # ABSENT, not zero. A step whose log is missing did not run,
            # and a row that omitted it would read as a step that had
            # nothing to report.
            steps[name] = None
            continue
        row = {"log_bytes": len(text)}
        tail = _pytest_tail(text)
        if tail:
            row["pytest"] = tail
        total = _TOTAL.findall(text)
        if total:
            row["findings"] = int(total[-1])
        execs = _EXECS.findall(text)
        if execs:
            row["executions"] = int(execs[-1])
        layouts = _LAYOUT.findall(text)
        if layouts:
            row["layouts"] = layouts
        differ = _DIFFER.findall(text)
        if differ:
            row["differing_bytes"] = [int(d) for d in differ]
        steps[name] = row

    return {
        "schema": SCHEMA,
        "tool": "tools/container_report.py",
        "verdict_exit": exit_code,
        "bench": prov.get("bench"),
        "repo_rev": prov.get("repo_rev"),
        "taken_at": prov.get("taken_at"),
        "host_os": prov.get("host_os"),
        "python": prov.get("python"),
        "runtime": runtime(),
        "build_env": env.get("build_env"),
        "build_image": env.get("build_image"),
        # The CONTENT hash, not the id. An image id is local to the
        # machine that built it and cannot match across benches; the
        # content hash is the one that is supposed to.
        "build_image_content": env.get("build_image_content"),
        "artifacts": env.get("artifacts"),
        "steps": steps,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exit", dest="exit_code", type=int, required=True,
                    metavar="N",
                    help="docker/run-ci.sh's own exit code: 0 everything "
                         "ran and nothing gating failed, 1 a step DID NOT "
                         "RUN, 2 a gating step failed. Read it WITHOUT a "
                         "pipe")
    ap.add_argument("--logs", default=os.path.join(REPO, "docker/out/ci"),
                    help="the per-step logs (default docker/out/ci)")
    ap.add_argument("--build", default=os.path.join(REPO, "docker/out/build"),
                    help="where the container's Track B build wrote "
                         "build-env.json (default docker/out/build)")
    ap.add_argument("--append", metavar="PATH",
                    help="append the row to PATH rather than printing it. "
                         "Use this rather than a shell `>>`: the shell "
                         "creates the file first, which makes the tree "
                         "dirty and labels the row for it")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.logs):
        print(f"no log directory at {args.logs}\nRun `docker/run.sh "
              f"docker/run-ci.sh` first; this describes a run rather than "
              f"performing one.", file=sys.stderr)
        return 2

    row = collect(args.logs, args.build, args.exit_code)
    if not row.get("bench"):
        # The same rule every record in this tree follows: an undeclared
        # bench cannot record, because a figure without its bench is not
        # comparable with anything.
        print("no bench declared, so this row would not be attributable.\n"
              "Write bench.json - host/provenance.py says what it wants.",
              file=sys.stderr)
        return 2
    # --- a dirty tree cannot produce a comparable row ---
    #
    # NOBODY CAN REPRODUCE A DIRTY BUILD, because the delta hash baked
    # into the image is a function of the dirt. So an artifact hash from
    # one is not a figure another bench can match, and a row carrying it
    # answers nothing while looking exactly like a row that does.
    #
    # It is also the recording half of catching a run which dirties the
    # tree UNDERNEATH itself. `docker/run-ci.sh`'s own positive control
    # crashes a harness on purpose, and where the kernel writes
    # `core.<pid>` into the working directory - WSL2's default - the
    # repository is dirty from that moment on. The row then came out
    # labelled `<rev>-dirty` with CLEAN artifact hashes in it, because
    # build-env.json is written by the firmware step before the host
    # tier runs: a row nobody can interpret. The run half is
    # `run-ci.sh`'s `working tree` step, which fails such a run and names
    # the step that changed the tree; this is what stops its row being
    # recorded anyway.
    rev = row.get("repo_rev") or ""
    if "-dirty" in rev or "+" in rev:
        print(f"repo_rev is {rev!r}: this tree is dirty, so the image "
              f"carries a working-tree delta hash and no other bench can "
              f"reproduce its artifacts.\nCommit or stash, rebuild, re-run, "
              f"then record. If the run itself dirtied the tree - a core "
              f"dump in the working directory will do it - that is the "
              f"defect to fix, not this check.", file=sys.stderr)
        return 2

    # --- the artifact and the tree must name one commit ---
    #
    # MECHANICAL RATHER THAN REMEMBERED. "Rebuild before you record" is
    # the instruction, and it has been got wrong twice on this bench
    # alone; a row whose repo_rev names a commit the binary was not
    # built from is not merely mislabelled, it silently voids the
    # cross-bench artifact comparison it exists to feed. FW_GIT_REV is
    # a string in the image, so the artifact can be asked directly.
    #
    # THE SUBSTRING CHECK ALONE IS NOT ENOUGH and the dirty guard above
    # is what covers it: `f5db1e8+ee5c634a` contains `f5db1e8`, so a
    # dirty image passed this check while the row asserted it matched
    # HEAD. Found on windows-desk, where the run dirtied its own tree.
    short = rev.split("-")[0].split("+")[0]
    blob = baked_revision(args.build)
    if blob is None:
        row["artifact_revision_checked"] = False
    elif short and short.encode() not in blob:
        print(f"the image in {args.build} does not carry {short!r}, so it "
              f"was not built from this tree's HEAD.\nRebuild and re-run "
              f"before recording: FW_GIT_REV is compiled in, and a row "
              f"labelled with\na commit the binary was not built from voids "
              f"the comparison it feeds.", file=sys.stderr)
        return 2
    else:
        row["artifact_revision_checked"] = True

    if row.get("build_env") != "container":
        # The one thing this row must not do is describe a HOST run as a
        # container one. build-firmware.sh writes "container" only when
        # docker/run.sh set DUE_BUILD_IMAGE_ID, so this is the build's
        # own answer rather than an assumption about how it was invoked.
        print(f"build_env is {row.get('build_env')!r}, not 'container' - "
              f"{args.build}/build-env.json says this build did not run in "
              f"the image.\nThis row would answer a question nobody asked; "
              f"run `docker/run.sh docker/run-ci.sh`.", file=sys.stderr)
        return 2

    line = json.dumps(row, sort_keys=True)
    if not args.append:
        print(line)
        return 0
    # Opened only now, with the provenance already read.
    with open(args.append, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"appended one row for {row['bench']} at {row['repo_rev']} to "
          f"{args.append}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
