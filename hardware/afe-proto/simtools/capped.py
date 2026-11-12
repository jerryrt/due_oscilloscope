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
import re
import shutil
import subprocess
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


def available():
    """True when capped.sh can create a capped user scope here."""
    if shutil.which("systemd-run") is None or not Path("/usr/bin/time").exists():
        return False
    r = subprocess.run(["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=64M", "true"],
                       capture_output=True)
    return r.returncode == 0


def run(cmd, *, mem="2G", timeout=300, cwd=None, env=None):
    """Run `cmd` (an argv list) under the cap. Never raises on the job's own failure,
    but raises RuntimeError if capped.sh gave no summary line (it did not run)."""
    if isinstance(cmd, str):
        raise TypeError("cmd must be an argv list, not a shell string")
    r = subprocess.run(["bash", str(CAPPED_SH), "-m", str(mem), "-t", str(timeout), *cmd],
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
