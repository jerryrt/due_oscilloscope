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


def firmware(build_stamp=None, track=None):
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
        if stamp is not None and when is not None and when < stamp - 60:
            continue
        # A record that flashed the *other* track cannot be the image
        # the board is reporting. Without this the newest record wins on
        # timing alone, and a bench that alternates tracks - this one
        # does, several times a session - can attribute a Track B board
        # to a Track A flash and never say so.
        rec_track = track_of_binary(rec.get("binary"))
        if track and rec_track and rec_track != str(track).strip().upper():
            continue
        return {
            "fw_repo_rev": (rec.get("repo_rev") or "") +
                           ("-dirty" if rec.get("dirty") else ""),
            "fw_sha256": rec.get("sha256"),
            # Which dirty, not merely that it was dirty. None on a clean
            # tree. tools/flash.py says why sha256 alone cannot answer
            # it: the identity line carries __DATE__/__TIME__, so the
            # binary hash changes on every rebuild of one source state.
            "fw_dirty_sha": rec.get("dirty_sha"),
            # Which code generator, and where it put things.
            #
            # `fw_repo_rev` was added because a version string is not a
            # commit. The same argument runs one step further: a commit
            # is not an image. Three benches build this repository with
            # three different compilers, and #5's displacement site is
            # "a lottery over code layout" - so a cross-bench comparison
            # that pins the commit has pinned the source and left the
            # variable free.
            #
            # None on any row written before tools/flash.py recorded
            # them, which is honest: those runs are attributable to a
            # commit and not to an image, and nothing can recover it now.
            "fw_cc": rec.get("cc"),
            "fw_layout": rec.get("layout"),
            "fw_flashed_at": rec.get("when"),
            "fw_provenance": ("matched" if stamp is not None
                              else "latest, unmatched build stamp"),
            "fw_source_current": fw_source_current(rec.get("repo_rev"),
                                                  rec_track),
            "fw_build_is_current": build_is_current(build_stamp, rec_track),
            "fw_source_track": rec_track,
        }
    return {"fw_provenance": "unlogged"}


#: What a firmware image is built from, **per track**.
#:
#: Split because one tuple covering both tracks cries wolf across them: a
#: Track A commit marked a Track B image as "predates a firmware commit"
#: while `firmware source since flashed` read unchanged on the same run,
#: and a flag that cries wolf costs the provenance discipline everything
#: it is for.
#:
#: `lib` and `linker` are in both by construction. `lib/due_shared/src`
#: is the wire contract both builds compile (invariant 3), and `linker/`
#: holds both scripts - `sam3x8e_flash.ld` for CMake and
#: `arduino_due_x_sram1.ld`, which `tools/sketch.py` pins Track A's
#: capture ring to SRAM bank 1 with.
FW_SOURCE_COMMON = ("lib", "linker")

#: Track B is CMake's source list; Track A is the sketch plus the shared
#: dirs. Verified against `CMakeLists.txt` and `tools/sketch.py` rather
#: than assumed: Track A compiles no `bsp/`, no `drivers/` and no
#: `apps/`, and CMake compiles no `sketches/`.
FW_SOURCE_TRACKS = {
    "B": FW_SOURCE_COMMON + ("bsp", "drivers", "apps", "cmake",
                             "CMakeLists.txt"),
    "A": FW_SOURCE_COMMON + ("sketches",),
    # Track C links Track B's bsp/, drivers/ and lib/ unchanged and adds
    # only its own application under apps/. So its source set is the
    # SAME as Track B's, and that is not an oversight - it is the first
    # time two tracks legitimately share a provenance answer.
    #
    # "Has the firmware changed since this image was flashed" therefore
    # answers identically for B and C on most commits, which is correct:
    # a change to drivers/adc.c really does invalidate both images. What
    # it means is that provenance can no longer distinguish which image
    # a stale flag is about, and a caller that needs to know must ask
    # the board with `v` rather than infer it from the paths.
    "C": FW_SOURCE_COMMON + ("bsp", "drivers", "apps", "cmake",
                             "CMakeLists.txt"),
}

#: Every path that builds *either* image, and the answer when the track
#: is not known. Over-reporting is the safe direction for a provenance
#: flag: a false "check your image" costs a rebuild, a false "your image
#: is current" costs a published figure.
#:
#: `bsp` was missing from this tuple until 2026-08-29, which was a false
#: *negative* and strictly worse than the cross-track false positive
#: above - `bsp/clock.c` sets MCK, and a flag reporting "current" across
#: a change to it is the one failure this whole module exists to stop.
FW_SOURCE = tuple(sorted(set(FW_SOURCE_TRACKS["A"] + FW_SOURCE_TRACKS["B"]
                            + FW_SOURCE_TRACKS["C"])))


def fw_source_paths(track):
    """The paths an image of `track` is built from.

    An unknown or unrecognised track gets the union, never a guess and
    never an empty set: see FW_SOURCE on which direction is safe.
    """
    if track is None:
        return FW_SOURCE
    return FW_SOURCE_TRACKS.get(str(track).strip().upper(), FW_SOURCE)


def track_of_binary(path):
    """Which track a flash-log `binary` field names, or None.

    The log has recorded the path since it existed, so this needs no new
    field and no re-flash to become useful on records already written.
    """
    if not path:
        return None
    p = str(path).replace("\\", "/")
    if "track_a" in p or "bringup.ino" in p:
        return "A"
    # Before baremetal_bringup, because Track C's binary lives in
    # build-c/ and its name shares no substring with Track B's - but a
    # future rename that made it "rtos_baremetal_bringup" would match
    # both, and the order is the cheap guard against that.
    if "rtos_bringup" in p:
        return "C"
    if "baremetal_bringup" in p:
        return "B"
    return None


def fw_source_current(fw_rev, track=None):
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
            ("git", "diff", "--name-only", f"{rev}..HEAD", "--")
            + fw_source_paths(track),
            cwd=REPO, capture_output=True, text=True, timeout=5)
    except Exception:                                        # pragma: no cover
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() == ""


def build_is_current(build_stamp, track=None):
    """Was the image compiled after the newest firmware source commit?

    `fw_source_current()` asks whether the *commit that was flashed* is
    still current, and that is not the same question: a build system can
    hand you a stale image while the flashing tool faithfully logs the
    current commit, and then "flashed after built" is trivially true and
    proves nothing.

    That is not hypothetical. `arduino-cli` served a cached Track A
    image stamped 11:34:37 on 2026-08-27 while `623d4dc` - which changes
    `sketches/bringup/ctl_port.cpp`, the very file carrying the stamp -
    had landed at 11:39. A clean rebuild stamped 20:35:25. The flash log
    recorded the current commit both times, because the flash *was*
    current; the image was not.

    So this compares the image's own stamp against the newest commit
    touching firmware source. Returns True, False, or None when it
    cannot tell.
    """
    stamp = _build_epoch(build_stamp)
    if stamp is None:
        return None
    try:
        out = subprocess.run(
            ("git", "log", "-1", "--format=%at", "--")
            + fw_source_paths(track),
            cwd=REPO, capture_output=True, text=True, timeout=5)
    except Exception:                                        # pragma: no cover
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    # A minute of slack: the stamp has second resolution and a commit
    # made during a build is not evidence of staleness.
    return stamp + 60 >= int(out.stdout.strip())


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
    # Which instrument took this session's counter reads.
    #
    # Emitted always, and not added to REQUIRED, because a run that read
    # no counter honestly has none to report and a required field that
    # is legitimately absent trains people to ignore `missing()`. What
    # makes a figure unattributable is a `console` count nobody noticed,
    # not a zero.
    #
    # `console` above zero means some measurement in this session was
    # taken with printf blocking the main loop it was measuring - see
    # measure.INSTRUMENT_READS and issue #51.
    try:
        import measure
        p["instrument"] = dict(measure.INSTRUMENT_READS)
    except Exception:                                     # pragma: no cover
        pass
    if board is not None:
        try:
            import measure
            ident = measure.identity(board)
            if ident:
                p.update(firmware(ident.get("build"), ident.get("track")))
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


def run_fields(board=None, ident=None):
    """The per-row provenance a record-writing tool should carry.

    Nine tools wrote `track="b"` as a literal, so every Track A run they
    recorded was labelled Track B (issue #53). A missing field is a gap;
    a wrong one is a trap, because a reader has no reason to distrust
    it - and `records/issue48-tracka-macos.jsonl` is 24 rows of Track A
    data saying `"b"`, supporting a commit whose claim is about which
    track it was.

    Ask the board instead. It is one identity query, it cannot disagree
    with itself, and it costs nothing next to the runs these tools make.

    The commit comes too, for #44's reason: the gaps files carried no
    image, so when an incidence stopped reproducing nobody could get
    back to the conditions that produced it. `fw_repo_rev` is what
    `tools/flash.py` logged for the image on the board; `repo_rev` is
    the tree the instrument ran from. They are different questions.

    `ident` is for a tool that holds the *command port* rather than a
    measure.Board. The control channel's IDENTITY carries the same
    track, and asking over the link a tool already has beats opening
    the programming port just to label a row - which for some tools
    would perturb the very thing being measured. Without either,
    `track` is "unknown": honest, but still a row nobody can attribute.
    """
    p = collect(board=board)
    if ident:
        # The control channel's IDENTITY carries the same track and
        # build string the console does, so it can fill every field
        # here - not just the track. firmware() is what turns a build
        # string into the commit tools/flash.py logged for that image.
        if ident.get("track"):
            p["track"] = ident["track"]
        if ident.get("build"):
            p["build"] = ident["build"]
            p.update(firmware(ident.get("build"), ident.get("track")))
    return {
        "track": p.get("track") or "unknown",
        "fw_repo_rev": p.get("fw_repo_rev"),
        "repo_rev": p.get("repo_rev"),
        "fw_build": p.get("build"),
        # A commit is not an image - see fw_cc/fw_layout in firmware().
        # Carried on every row a tool writes, so a figure that turns out
        # to depend on code layout can be re-read for it rather than
        # re-measured. Null on rows whose flash predates the field.
        "fw_cc": p.get("fw_cc"),
        "fw_layout": p.get("fw_layout"),
    }
