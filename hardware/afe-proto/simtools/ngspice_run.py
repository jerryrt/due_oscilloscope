"""The one way to run an ngspice deck: batch, capped, one corner, a declared .save list.

An unrestricted ngspice run saves every node and every device current of
every model in the deck; one vendor model took 5 GB that way. So a deck
here cannot be run without naming the vectors it needs, a deck that tries
to save everything is refused, and the raw file is checked afterwards to
hold nothing beyond what was asked for.

One corner per process: `corner` values are scalars. Looping corners is the
caller's job, one run() each, so a cap kill names the corner that did it.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import capped
from .raw import Plot, read_raw

_SAVE_ALL = re.compile(r"^\s*\.?save\s+all\b|^\s*\.options?\b.*\bsavecurrents\b", re.I | re.M)
_STEP = re.compile(r"^\s*\.(step|alter|alterparam|mc)\b", re.I | re.M)
_END = re.compile(r"^\s*\.end\s*$", re.I | re.M)
_VEC = re.compile(r"^(v|i)\([^()\s]+\)$|^[A-Za-z_][\w#.]*$", re.I)


class DeckError(ValueError):
    """The deck or its arguments break a rule; nothing was run."""


class RunError(RuntimeError):
    """ngspice ran and failed: cap kill, timeout, or a non-zero exit."""


@dataclass
class Run:
    result: capped.Result
    raw_path: Path
    corner: dict
    saved: list

    def plots(self):
        return read_raw(self.raw_path)

    @property
    def peak_rss_bytes(self):
        return self.result.peak_rss_bytes

    @property
    def wall_s(self):
        return self.result.wall_s


def prepare(deck, save, corner=None):
    """Return the deck text actually run. Raises DeckError on any rule broken."""
    save = list(save or [])
    if not save:
        raise DeckError("a .save list is required: name the vectors this run needs")
    for v in save:
        if not _VEC.match(v) or v.lower() == "all":
            raise DeckError(f"bad .save entry {v!r}")
    if _SAVE_ALL.search(deck):
        raise DeckError("the deck saves everything (save all / savecurrents); list the vectors instead")
    if _STEP.search(deck):
        raise DeckError("one corner per process: remove .step/.alter/.mc and call run() per corner")
    if re.search(r"^\s*\.save\b", deck, re.I | re.M):
        raise DeckError("the deck has its own .save; pass the list to run() so there is one source")
    m = _END.search(deck)
    if m is None:
        raise DeckError("the deck has no .end line")
    lines = []
    for k, val in (corner or {}).items():
        if isinstance(val, (list, tuple, set, dict)):
            raise DeckError(f"corner {k!r}: one corner per process, got a {type(val).__name__}")
        lines.append(f".temp {val}" if k == "temp" else f".param {k}={val}")
    body = deck[:m.start()].rstrip("\n").split("\n", 1)     # title line stays first
    inject = "\n".join(lines + [".save " + " ".join(save)])
    rest = body[1] if len(body) > 1 else ""
    return f"{body[0]}\n{inject}\n{rest}\n.end\n"


def run(deck, *, save, workdir, name, corner=None, mem="2G", timeout=300, extra_vars_ok=("time", "frequency")):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    text = prepare(deck, save, corner)
    cir, raw = workdir / f"{name}.cir", workdir / f"{name}.raw"
    cir.write_text(text)
    if raw.exists():
        raw.unlink()
    res = capped.run(["ngspice", "-b", "-r", raw.name, cir.name], mem=mem, timeout=timeout, cwd=workdir)
    if res.cap_killed or res.timed_out or res.returncode != 0:
        why = "memory cap" if res.cap_killed else "timeout" if res.timed_out else f"exit {res.returncode}"
        raise RunError(f"{name}: ngspice stopped by {why} (corner {corner}, cap {mem}, limit {timeout}s)")
    if not raw.exists():
        raise RunError(f"{name}: ngspice exited 0 but wrote no raw file; log tail: {res.stdout[-300:]}")
    out = Run(res, raw, dict(corner or {}), list(save))
    allowed = {s.lower() for s in save} | set(extra_vars_ok)
    for p in out.plots().values():
        extra = [n for n in p.names if n not in allowed]
        if extra:
            raise RunError(f"{name}: raw file holds vectors beyond the .save list: {extra[:5]}")
    return out
