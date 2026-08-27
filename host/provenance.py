"""What has to be true about a run before its numbers mean anything.

A measurement without its conditions is not a baseline point, and this
project has paid for that twice: `FW_VERSION_STR` said 0.1.0 while the
numbers said 0.2.0, identically on both tracks and reaching different
consumers; and a branch's recorded "160 passed / 88 failed" outlived the
`measure.py` that produced it, so by the time anyone read it the number
described instruments that no longer existed.

So the rule here is that a run **records its conditions or it does not
record**. `collect()` gathers them and `missing()` says which are
absent; a harness that cannot fill the required ones should refuse
rather than write something unattributable.

Two of these deserve their own warning.

**The probe ratio is asserted, not measured.** A scope reports what it
has been *told* a probe divides by, and there is no way to ask what is
fitted. Getting it wrong is a silent factor of ten - it cost three runs
on the EXT trigger, where a x10 probe put the usable trigger window at
0.1-0.2 V and a sweep looking at 0.0/0.3/0.6/1.0/1.2 stepped over it and
concluded the input was dead. Both the told value and a sanity check
against a known amplitude are recorded, and a mismatch is flagged rather
than resolved.

**The wiring is an assumption with a date on it.** DAC0 to A0 is the
baseline; DAC1 went to the scope's EXT TRIG on 2026-08-27 and is no
longer on an analog channel. A2 is bare unless someone has just fitted
something and said so.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

#: Fields a run must carry. Anything here that `collect()` could not
#: establish makes the run unattributable, not merely under-documented.
REQUIRED = ("track", "fw_version", "ctl_version", "frame_version",
            "build", "host_os", "repo_rev", "wiring")

#: The bench as it stands. Not discoverable - a cable is not a register -
#: so it is declared here and dated, and a run that was taken on a
#: different bench records a different string rather than silently
#: meaning something else.
WIRING = "DAC0->A0, DAC1->scope EXT TRIG (x1), A1 free, A2 bare"
WIRING_SINCE = "2026-08-27"


def _git(*args):
    try:
        out = subprocess.run(("git",) + args, cwd=REPO, capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:                                     # pragma: no cover
        return None


def repo_rev():
    """What the host tools were when this ran, dirty flag included.

    Dirty matters more than the hash: a figure taken with uncommitted
    changes cannot be reproduced from the history, and saying so is the
    difference between a number to trust and one to re-take.
    """
    rev = _git("rev-parse", "--short", "HEAD")
    if rev is None:
        return None
    dirty = _git("status", "--porcelain")
    return rev + ("-dirty" if dirty else "")


def collect(board=None, inst=None, channels=(1, 2), extra=None):
    """Everything that makes a run attributable. Never raises.

    `board` and `inst` are optional so a board-free or scope-free run
    still records what it can and `missing()` names the rest.
    """
    p = {
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host_os": f"{platform.system()} {platform.release()}",
        "host_machine": platform.machine(),
        "python": sys.version.split()[0],
        "repo_rev": repo_rev(),
        "wiring": WIRING,
        "wiring_since": WIRING_SINCE,
    }
    if board is not None:
        try:
            import measure
            ident = measure.identity(board)
            if ident:
                p.update({
                    "track": ident["track"],
                    "fw_version": ident["fw_version"],
                    "ctl_version": ident["ctl_version"],
                    "frame_version": ident["frame_version"],
                    "mck_hz": ident["mck_hz"],
                    "adc_clock_hz": ident["adc_clock_hz"],
                    "build": ident["build"],
                })
        except Exception as e:                            # pragma: no cover
            p["board_error"] = f"{type(e).__name__}: {e}"
    if inst is not None:
        try:
            p["instrument"] = " ".join(inst.identify())
            # As TOLD, and the name says so: there is no query for what
            # is actually fitted.
            p["probe_ratio_told"] = {
                f"ch{c}": inst.probe(c) for c in channels}
            p["trigger"] = inst.trigger_edge()
            p["trigger_coupling"] = inst.trigger_coupling()
        except Exception as e:                            # pragma: no cover
            p["instrument_error"] = f"{type(e).__name__}: {e}"
    if extra:
        p.update(extra)
    return p


def missing(p):
    """Required fields this provenance could not establish."""
    return [k for k in REQUIRED if not p.get(k)]


def check_probe(p, ch, seen_vpp, expected_vpp, tolerance=0.15):
    """Flag a probe ratio that the signal contradicts.

    The only handle there is on a ratio nobody can query: drive a known
    amplitude and see whether the instrument agrees about it. A factor
    of ten out is unmistakable; anything subtler this cannot see, and it
    does not pretend to.
    """
    if not expected_vpp or seen_vpp is None:
        return None
    ratio = seen_vpp / expected_vpp
    if abs(ratio - 1.0) <= tolerance:
        return None
    note = (f"ch{ch} read {seen_vpp:.3f} V against an expected "
            f"{expected_vpp:.3f} V, a factor of {ratio:.2f}. The probe "
            f"is told x{p.get('probe_ratio_told', {}).get(f'ch{ch}', '?')}; "
            f"check what is fitted")
    p.setdefault("warnings", []).append(note)
    return note
