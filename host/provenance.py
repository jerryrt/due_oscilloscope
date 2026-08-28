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

**And it is a fact about a bench, not about the repository.** It was a
module constant until 2026-08-27, which meant every run on every bench
recorded the DSO bench's cabling. The Windows bench has DAC1 on A1 -
its own `x` and `s` both say so - and its first noise records claimed
"A1 free" anyway, which is worse than recording nothing: a reader
comparing two benches would have taken A1 for the free-pin control on
both. Declare a bench in `bench.json` at the repo root (gitignored, one
object, see `BENCH_FILE`); `wiring_source` says whether the string that
came out was declared or defaulted, so an undeclared bench is visible
rather than silently wearing someone else's cables.
"""
from __future__ import annotations

import json
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
            "build", "host_os", "repo_rev", "wiring", "bench",
            "fw_repo_rev")

#: `fw_repo_rev` is required because `fw_version` is not an answer.
#:
#: Both benches reported `fw 0.2.0` on 2026-08-27 while running builds
#: four hours and three DAC commits apart, and one of them published a
#: noise floor a whole bit wrong as a result. A version string is bumped
#: by hand and says what someone intended; the commit says what was
#: compiled.
#:
#: It is *not* baked into the firmware, deliberately - see
#: `lib/due_shared/src/fw_version.h`, which argues that two toolchains
#: would need build plumbing that can silently disagree. It is recorded
#: by `tools/flash.py` instead, which is the one place that knows the
#: binary and the tree at the same instant and so cannot disagree with
#: itself, and matched back here against the build stamp the device
#: reports.

#: `bench` is required, which means an undeclared bench cannot record.
#:
#: That is a deliberate answer to the question raised on issue #10 when
#: `WIRING` stopped being a module constant. A default is worse than a
#: blank here: the Windows bench's first records claimed `A1 free` on a
#: desk where DAC1 is jumpered to A1, so anyone comparing the two benches
#: would have taken A1 for the free-pin control on both. And that is not
#: a hypothetical detail - a bare neighbour was later measured to cost
#: its neighbour 0.347 bits, so the two desks were never the same
#: circuit.
#:
#: This module's own docstring says a run records its conditions or it
#: does not record. A wiring string that might be someone else's is not
#: a condition, it is a guess wearing one. Declaring costs one gitignored
#: file per desk, once.

#: Written by `tools/flash.py`, one JSON line per successful flash:
#: when, binary, sha256, repo_rev, dirty.
FLASH_LOG = "records/flash-log.jsonl"

#: Where a bench declares itself. Gitignored on purpose: it describes
#: one desk, and committing one desk's cables is how every other desk
#: ended up recording them. One JSON object, any of the keys below:
#:
#:     {"bench": "windows-desk",
#:      "wiring": "DAC0->A0, DAC1->A1, A2 bare",
#:      "wiring_since": "2026-08-27"}
BENCH_FILE = "bench.json"

#: The fallback when no bench has declared itself. It is the DSO bench's
#: cabling and it is right for exactly one desk, which is the whole
#: reason `wiring_source` exists: a run that used this says so, and a
#: reader can tell an assumption from a declaration.
DEFAULT_WIRING = "DAC0->A0, DAC1->scope EXT TRIG (x1), A1 free, A2 bare"
DEFAULT_WIRING_SINCE = "2026-08-27"


def bench():
    """The bench's own declaration, or an empty dict.

    Never raises and never guesses: an unreadable or malformed
    `bench.json` is reported as a field rather than allowed to stop a
    run, because a measurement that dies at the provenance step has
    still cost the bench time.
    """
    path = os.path.join(REPO, BENCH_FILE)
    try:
        with open(path) as f:
            got = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        return {"bench_error": f"{BENCH_FILE}: {e}"}
    if not isinstance(got, dict):
        return {"bench_error": f"{BENCH_FILE} is not a JSON object"}
    return got


def firmware(build_stamp=None):
    """Which commit produced the image the board is running.

    Reads the flash log newest-first and returns the entry that could
    have produced `build_stamp` - i.e. flashed at or after the moment
    the image was compiled. Anything else is a guess, and this returns
    a stated absence instead:

        {"fw_provenance": "unlogged"}    nothing in the log fits

    which `missing()` then refuses to record, because "the board is
    running something and nobody knows what" is exactly the condition
    that cost a bit of noise floor and two published figures.
    """
    path = os.path.join(REPO, FLASH_LOG)
    try:
        lines = [json.loads(x) for x in open(path) if x.strip()]
    except (OSError, ValueError):
        return {"fw_provenance": "unlogged"}
    if not lines:
        return {"fw_provenance": "unlogged"}
    stamp = _build_epoch(build_stamp)
    for rec in reversed(lines):
        when = _iso_epoch(rec.get("when"))
        if stamp is None or when is None or when >= stamp - 60:
            return {
                "fw_repo_rev": (rec.get("repo_rev") or "") +
                               ("-dirty" if rec.get("dirty") else ""),
                "fw_sha256": rec.get("sha256"),
                "fw_flashed_at": rec.get("when"),
                "fw_provenance": ("matched" if stamp is not None
                                  else "latest, unmatched build stamp"),
                "fw_source_current": fw_source_current(rec.get("repo_rev")),
            }
    return {"fw_provenance": "unlogged"}


#: What a firmware image is built from. If none of this moved between
#: the flashed commit and the tree, the board is running current
#: firmware however far the host tools have travelled.
FW_SOURCE = ("drivers", "apps", "lib", "linker", "cmake", "CMakeLists.txt",
             "sketches")


def fw_source_current(fw_rev):
    """Has any firmware source changed since the image was built?

    The honest answer to "the firmware commit and the host tree differ,
    does that matter?" - which they routinely do, because host tools and
    docs move many times a day and the board is flashed once. Comparing
    the two revisions alone would cry wolf every afternoon; comparing
    the paths an image is actually built from does not.

    Returns True, False, or None when it cannot tell - a detached rev, a
    missing git, a dirty flash. None is not False: "I could not check"
    and "it is stale" are different claims.
    """
    if not fw_rev:
        return None
    rev = fw_rev.split("-dirty")[0]
    # Not via `_git()`: that returns None for empty output, and an empty
    # diff is precisely the answer being asked for here. Collapsing "no
    # changes" into "could not check" made this report say it could not
    # tell, on a tree where it could.
    try:
        out = subprocess.run(
            ("git", "diff", "--name-only", f"{rev}..HEAD", "--") + FW_SOURCE,
            cwd=REPO, capture_output=True, text=True, timeout=5)
    except Exception:                                        # pragma: no cover
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() == ""


def _build_epoch(stamp):
    """`__DATE__ " " __TIME__` as an epoch, or None."""
    if not stamp:
        return None
    for fmt in ("%b %d %Y %H:%M:%S", "%b  %d %Y %H:%M:%S"):
        try:
            return time.mktime(time.strptime(stamp, fmt))
        except ValueError:
            continue
    return None


def _iso_epoch(s):
    if not s:
        return None
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def wiring():
    """(text, since, source). `source` is "declared" or "default"."""
    b = bench()
    text = b.get("wiring")
    if text:
        return text, b.get("wiring_since"), "declared"
    return DEFAULT_WIRING, DEFAULT_WIRING_SINCE, "default"


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
    b = bench()
    wire, since, source = wiring()
    p = {
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host_os": f"{platform.system()} {platform.release()}",
        "host_machine": platform.machine(),
        "python": sys.version.split()[0],
        "repo_rev": repo_rev(),
        "wiring": wire,
        "wiring_since": since,
        # Which of the two this is. A defaulted wiring is the DSO
        # bench's cabling worn by whoever ran the command, and a reader
        # comparing benches has to be able to see that.
        "wiring_source": source,
        "bench": b.get("bench"),
    }
    if b.get("bench_error"):
        p["bench_error"] = b["bench_error"]
    if board is not None:
        try:
            import measure
            ident = measure.identity(board)
            if ident:
                p.update(firmware(ident.get("build")))
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
