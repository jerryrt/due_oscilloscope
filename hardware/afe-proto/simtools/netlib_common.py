"""The plumbing both boards' netlib.py files carried a copy of.

Each board's netlib keeps what is its own (parameter sets, netlist builders)
and delegates the file handling and ngspice invocation here. The functions
take the directories explicitly because netlib's `use_variant` rebinds its
own NETD/WORK/PFX at run time; the thin wrappers in each netlib read those
globals per call, so a variant switch still takes effect.

run_ng goes through the capped runner: a deck that runs away is killed at
the cap with RunError instead of taking the machine with it. Set
DUE_UNCAPPED=1 on a host with no systemd user scopes to run without it;
that is a stated choice, never a silent fallback.
"""
import hashlib
import os
import re
import subprocess

import numpy as np

from . import capped

DEFAULT_MEM = os.environ.get("DUE_NG_MEM", "4G")


class RunError(RuntimeError):
    pass


_VEC = re.compile(r"\b(?:[vi]\([^()\s,]+\)|[a-z][\w.]*#branch)", re.I)
_CONTROL = re.compile(r"^\s*\.control\b(.*?)^\s*\.endc\b", re.I | re.M | re.S)


def derive_save(text):
    """The vectors a deck's .control block reads (wrdata, let, meas, print...), lowercased, in first-seen order.
    Raises when the deck has a .control block that names none, or already carries a .save: the first cannot be
    restricted and the second has two sources of truth."""
    if re.search(r"^\s*\.save\b", text, re.I | re.M):
        raise ValueError("deck already has its own .save")
    seen = []
    for blk in _CONTROL.findall(text):
        for v in _VEC.findall(blk):
            v = v.lower()
            if v not in seen:
                seen.append(v)
    return seen


def with_save(text):
    """The deck with a .save of exactly the vectors its .control block reads, so ngspice keeps those and not every
    node and device current of every model in the deck (one vendor model took 5 GB that way). Returned unchanged:
    a deck without a .control block (batch analyses printing to the log), and a deck that runs the `noise`
    command, whose analysis aborts under a .save. The noise decks are small, so nothing is lost."""
    if not _CONTROL.search(text):
        return text
    if any(re.match(r"\s*noise\b", ln, re.I) for blk in _CONTROL.findall(text) for ln in blk.splitlines()):
        return text          # measured: with a .save, ngspice's noise analysis aborts ("no such plot named noise1"): it needs every node
    vecs = derive_save(text)
    if not vecs:
        raise ValueError("the deck's .control block reads no vector, so there is nothing to .save")
    end = re.search(r"^\s*\.end\s*$", text, re.I | re.M)
    if end is None:
        return text
    return text[:end.start()] + ".save " + " ".join(vecs) + "\n" + text[end.start():]


def write_net(netd, pfx, name, text):
    os.makedirs(netd, exist_ok=True)
    path = os.path.join(netd, pfx + name + ".cir")
    with open(path, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def run_ng(netd, work, pfx, name, text, timeout, mem=None, autosave=True):
    """Write <netd>/<pfx><name>.cir and run `ngspice -b` there (relative model paths resolve
    from netd). Returns stdout + stderr, as the per-board copies did. With autosave (the default) the deck is
    given a .save of the vectors its .control block reads; see with_save."""
    os.makedirs(work, exist_ok=True)
    path = write_net(netd, pfx, name, with_save(text) if autosave else text)
    argv = ["ngspice", "-b", os.path.basename(path)]
    if os.environ.get("DUE_UNCAPPED") == "1":
        r = subprocess.run(argv, cwd=netd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    res = capped.run(argv, mem=mem or DEFAULT_MEM, timeout=timeout, cwd=netd)
    if res.cap_killed or res.timed_out:
        raise RunError(f"{name}: ngspice {'hit the memory cap' if res.cap_killed else 'timed out'} "
                       f"(cap {mem or DEFAULT_MEM}, limit {timeout}s)")
    return res.stdout + res.stderr


def wr(work_rel, pfx, name, key):
    """Path of a wrdata file as the netlist (running in netd) must write it."""
    return f"{work_rel}/{pfx}{name}_{key}.dat"


def load(work, pfx, name, key, atleast_2d=False):
    a = np.loadtxt(os.path.join(work, f"{pfx}{name}_{key}.dat"))
    return np.atleast_2d(a) if atleast_2d else a


def ngspice_version(strip=None):
    out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    for l in out.splitlines():
        if "ngspice" in l.lower() and re.search(r"\d", l):
            return l.strip(strip) if strip else l.strip()
    lines = out.strip().splitlines()
    return out.strip() if strip else (lines[0] if lines else "")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()
