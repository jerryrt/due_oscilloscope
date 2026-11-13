"""Python face of tools/capped.sh, the one copy of the memory-cap/timeout wrapper.

capped.sh runs a job in a systemd scope with MemoryMax and swap off, under
`timeout`, and prints one summary line on stderr. This module runs it and
parses that line, so every tool, test and bench gets the same cap and the
same figures.

The peak is the largest resident set /usr/bin/time reports for the job,
which is not the cgroup total: a job that forks several workers reads low.
The house rule is no pools, so it is a fair figure, and it is named
peak_rss_bytes to say what it is.
"""
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

CAPPED_SH = Path(__file__).resolve().parents[1] / "tools" / "capped.sh"
CAP_KILLED = 137
TIMED_OUT = 124

_SUMMARY = re.compile(r"^capped: peak_rss_kb=(\S+) wall_s=(\S+) exit=(\d+) cap=(\S+) limit_s=(\S+)$", re.M)


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str          # the job's own, without capped.sh's summary line
    wall_s: float | None
    peak_rss_bytes: int | None
    cap_killed: bool
    timed_out: bool


def in_container():
    """True inside docker/pcb's image, where docker run supplies the memory cap and
    the timeout is applied here; capped.sh's systemd scope does not exist."""
    return bool(os.environ.get("DUE_PCB_IMAGE_CONTENT"))


def per_job_cap_available():
    """A cap that applies to this one job. In the container the cap is the whole
    container's, set by run.sh, so a test of a per-job kill cannot run there."""
    return not in_container() and available()


def available():
    """True when a job can be run under the cap/timeout wrapper here."""
    if in_container():
        return shutil.which("timeout") is not None and Path("/usr/bin/time").exists()
    if shutil.which("systemd-run") is None or not Path("/usr/bin/time").exists():
        return False
    r = subprocess.run(["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=64M", "true"],
                       capture_output=True)
    return r.returncode == 0


def run(cmd, *, mem="2G", timeout=300, cwd=None, env=None, cpus=None):
    """Run `cmd` (an argv list) under the cap. Never raises on the job's own failure,
    but raises RuntimeError if capped.sh gave no summary line (it did not run)."""
    if isinstance(cmd, str):
        raise TypeError("cmd must be an argv list, not a shell string")
    if in_container():
        return _run_in_container(cmd, timeout, cwd, env)
    extra = ["-c", str(cpus)] if cpus is not None else []
    r = subprocess.run(["bash", str(CAPPED_SH), "-m", str(mem), "-t", str(timeout), *extra, *cmd],
                       cwd=cwd, env=env, capture_output=True, text=True)
    m = _SUMMARY.search(r.stderr)
    if m is None:
        raise RuntimeError(f"capped.sh printed no summary (exit {r.returncode}): {r.stderr[-300:]}")
    peak, wall = m.group(1), m.group(2)
    rc = int(m.group(3))
    return Result(rc, r.stdout, _SUMMARY.sub("", r.stderr).rstrip("\n"),
                  float(wall) if wall != "?" else None,
                  int(peak) * 1024 if peak != "?" else None,
                  cap_killed=rc == CAP_KILLED, timed_out=rc == TIMED_OUT)


def _run_in_container(cmd, timeout, cwd, env):
    """The container's memory cap is docker's (run.sh), so only the timeout and the
    peak figure are taken here, the way capped.sh takes them: /usr/bin/time."""
    with tempfile.NamedTemporaryFile("r", suffix=".time") as log:
        r = subprocess.run(["/usr/bin/time", "-f", "%M %e", "-o", log.name,
                            "timeout", "-k", "5", str(timeout), *cmd],
                           cwd=cwd, env=env, capture_output=True, text=True)
        last = (open(log.name).read().strip().splitlines() or [""])[-1]
    m = re.fullmatch(r"(\d+) ([\d.]+)", last)
    rc = 137 if (r.returncode in (137, -9) or (m is None and r.returncode == 143)) else r.returncode
    return Result(rc, r.stdout, r.stderr, float(m.group(2)) if m else None,
                  int(m.group(1)) * 1024 if m else None,
                  cap_killed=rc == CAP_KILLED, timed_out=rc == TIMED_OUT)
