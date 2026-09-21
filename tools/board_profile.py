#!/usr/bin/env python3
"""One profile per known board, generated from the record.

    .venv/bin/python tools/board_profile.py --write    # regenerate records/boards/
    .venv/bin/python tools/board_profile.py --check    # fail if they drifted

A board is a die, named by the SAM3X's unique identifier (`board_uid`,
printed on the identity line as `uid=`), with the programming port's
16U2 serial as the cross-check. Its figures live scattered across rows
- records/rotation.jsonl, calibration.json - and a calibration path
needs one place per board where a figure, the state it was taken in,
and what has NOT been measured sit together. That place is
records/boards/<board_uid>.json.

EVERY FIGURE TRACES TO A ROW. The generator writes only what it read:
each converter entry names its source row by `taken_at`, and the
calibration block is copied from calibration.json when that file names
the board, else it is a block of nulls saying why. A literal typed into
a profile is a guess wearing a decimal point, and `--check` refuses a
profile that differs from what the record regenerates.

THE COMMITTED PROFILES COME FROM COMMITTED RECORDS ONLY. The flash log
is bench-local and gitignored, so folding it in would make `--check`
drift on every bench but the one that wrote the profile; it is read
only under `--flash-log PATH`, for a bench looking at its own history,
and never into the committed files.

A PHASE IS AN ARRANGEMENT, AND FIGURES ARE NEVER POOLED ACROSS ONE.
The rotation's `before` and `after` rows were taken with nothing on the
DUT; the same evening a Mega shield v3 went onto every DUT and later
rows carry `shield-v3`. Those are different arrangements of the same
board, so `converter_summary` is per phase, `arrangements` lists the
distinct phases seen with when each was first and last taken, and
`flags` is per phase too - a later arrangement gets its own entry
rather than overwriting the rotation's.

`large-tail` IS A LABEL, NOT A SPEC, and it is judged per phase, on
that phase's rested median alone: the rotation read the healthy boards
at a rested largest step of 43-48 codes and the outlier at 53-55, so a
rested median of 50 or more carries the flag on the phase that read
it. A board that lost its tail under the shield keeps the flag on its
rotation phases and none on the shield's; a board first seen under
the shield with the tail carries it there and nowhere else. It marks
rows that must be read with that in mind; nothing gates on it.

NOTES ARE HAND-KEPT AND MERGED, NEVER OVERWRITTEN. What a generator
cannot know - a board that is off every bench, one that cannot take a
shield - is written by a person into records/boards/_notes.json as
{board_uid: [note, ...]} and copied into each profile's `notes`. A uid
in that file that no row names is an error, so a typo cannot silently
drop a note.

EXIT CODES
    0   written, or --check found no drift
    1   --check found drift; the files are listed
    2   the record is inconsistent (one uid, two serials) or unreadable
"""

import argparse
import glob
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

SCHEMA = "board-profile/1"
ROTATION = os.path.join(ROOT, "records", "rotation.jsonl")
CALIBRATION = os.path.join(ROOT, "calibration.json")
BOARDS_DIR = os.path.join(ROOT, "records", "boards")
NOTES_NAME = "_notes.json"

#: Rested rows only: the rotation's declared rest. A warm board read as a
#: different board is what the rotation existed to stop.
RESTED_S = 1200
#: The label's threshold, from the rotation: healthy 43-48, outlier 53-55.
LARGE_TAIL_MEDIAN = 50.0
#: The phases the flag is judged on: the rotation's, no shield on the DUT.
ROTATION_PHASES = ("before", "after")
NOT_MEASURED = ("not measured; needs an external reference "
                "(docs/scope.md open question 5)")


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _calibration(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _median(values):
    return statistics.median(values) if values else None


def converter_entry(row):
    """The compact figure set of one rotation row, each traceable to it."""
    s = row["census_summary"]
    scales = row.get("tail_scale") or []
    base = [g for g in scales if g.get("arm") == "baseline"]
    temps = [t["code"] for t in row.get("temperatures") or []]
    return {
        "phase": row["phase"],
        "bench": row["bench"],
        "image": row["identity"].get("build"),
        "idle_before_s": row["idle_before_s"],
        "taken_at": row["taken_at"],
        "largest_median": s.get("largest_median"),
        "largest_range": [s.get("largest_min"), s.get("largest_max")],
        "count_range": [s.get("count_min"), s.get("count_max")],
        "tail_scale_a0": [g["a0_scale_codes"] for g in base],
        "tail_scale_a1": [g["a1_scale_codes"] for g in base],
        "tail_scale_status": row.get("tail_scale_status"),
        "die_code_mean": round(sum(temps) / len(temps), 4) if temps else None,
        "source": "records/rotation.jsonl",
        "row_taken_at": row["taken_at"],
    }


def history(events):
    """{bench: first, last, rows} from (bench, taken_at, source) events,
    grouped by bench, ordered by first appearance."""
    out = {}
    for bench, when, _source in sorted(events, key=lambda e: e[1]):
        h = out.setdefault(bench, {"bench": bench, "first": when,
                                   "last": when, "rows": 0})
        h["last"] = when
        h["rows"] += 1
    return list(out.values())


def _notes(boards_dir):
    path = os.path.join(boards_dir, NOTES_NAME)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_profiles(rotation_rows, calibration, flash_rows=(), generated=None,
                   notes=None):
    """{board_uid: profile} from the rows. Refuses one uid with two serials,
    and a note for a uid no row names."""
    notes = notes or {}
    by_uid = {}
    serials = {}
    for r in rotation_rows:
        uid = r.get("board_uid")
        if not uid:
            continue
        by_uid.setdefault(uid, []).append(r)
        serials.setdefault(uid, set()).add(r.get("board_serial"))
    for r in flash_rows:
        uid = r.get("board_uid")
        if not uid:
            continue
        by_uid.setdefault(uid, [])
        serials.setdefault(uid, set()).add(r.get("board_serial"))
    cal_board = (calibration.get("board") or {})
    cal_uid = cal_board.get("board_uid")
    if cal_uid:
        by_uid.setdefault(cal_uid, [])
        serials.setdefault(cal_uid, set()).add(cal_board.get("board_serial"))

    bad = {uid: s for uid, s in serials.items() if len({x for x in s if x}) > 1}
    if bad:
        raise ValueError("one uid, two serials - the record is inconsistent: "
                         + "; ".join(f"{uid}: {sorted(x for x in s if x)}"
                                     for uid, s in bad.items()))

    unknown = sorted(set(notes) - set(by_uid))
    if unknown:
        raise ValueError("a note names a board no row names - a typo would "
                         "silently drop it: " + ", ".join(unknown))

    profiles = {}
    for uid, rows in by_uid.items():
        rows = sorted(rows, key=lambda r: r["taken_at"])
        events = [(r["bench"], r["taken_at"], "records/rotation.jsonl")
                  for r in rows]
        events += [(r.get("bench"), r.get("taken_at"), "records/flash-log.jsonl")
                   for r in flash_rows
                   if r.get("board_uid") == uid and r.get("taken_at")]
        by_phase = {}
        for r in rows:
            by_phase.setdefault(r["phase"], []).append(r)
        summary = {}
        arrangements = []
        flags = {}
        for phase, prs in by_phase.items():
            rested = [r["census_summary"]["largest_median"] for r in prs
                      if r["idle_before_s"] >= RESTED_S
                      and r["census_summary"].get("largest_median") is not None]
            med = _median(rested)
            lo = [r["census_summary"].get("largest_min") for r in prs]
            hi = [r["census_summary"].get("largest_max") for r in prs]
            summary[phase] = {
                "rested_largest_median": med,
                "largest_range": [min(x for x in lo if x is not None) if any(x is not None for x in lo) else None,
                                  max(x for x in hi if x is not None) if any(x is not None for x in hi) else None],
                "n_rows": len(prs),
                "n_rested_rows": len(rested),
                "benches": sorted({r["bench"] for r in prs}),
            }
            arrangements.append({"phase": phase,
                                 "first": min(r["taken_at"] for r in prs),
                                 "last": max(r["taken_at"] for r in prs)})
            flags[phase] = (["large-tail"] if med is not None
                            and med >= LARGE_TAIL_MEDIAN else [])
        arrangements.sort(key=lambda a: a["first"])
        serial = next((x for x in serials[uid] if x), None)
        if cal_uid == uid:
            cal = {k: v for k, v in calibration.items() if not k.startswith("_")
                   and k != "board"}
            cal["measured_on_bench"] = cal_board.get("measured_on_bench")
            cal["source"] = "calibration.json"
        else:
            cal = {"dac_mv": None, "adc_transfer": None, "adc_gain": None,
                   "adc_offset": None, "reference": None,
                   "temperature_slope": None, "note": NOT_MEASURED}
        profiles[uid] = {
            "schema": SCHEMA,
            "board_uid": uid,
            "board_serial": serial,
            "first_seen": min((e[1] for e in events), default=None),
            "history": history(events),
            "converter": [converter_entry(r) for r in rows],
            "arrangements": arrangements,
            "converter_summary": summary,
            "calibration": cal,
            "flags": flags,
            "notes": list(notes.get(uid, [])),
            "generated": generated or {},
        }
    return profiles


def render(profile):
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def profile_path(boards_dir, uid):
    return os.path.join(boards_dir, f"{uid}.json")


def generated_block():
    """Who generated the files: the tool's own conditions, no board open.

    The block names the bench and the tree revision that wrote the file,
    which change with every commit and every bench - so `check()` strips
    it from both sides and compares the profile, not its author.
    """
    try:
        import provenance
        c = provenance.conditions()
        return {"tool": "tools/board_profile.py", "rev": c.get("repo_rev"),
                "bench": c.get("bench")}
    except Exception as exc:                                 # noqa: BLE001
        return {"tool": "tools/board_profile.py", "error": str(exc)}


def _comparable(profile):
    p = dict(profile)
    p.pop("generated", None)
    return render(p)


def _unchanged(path, profile):
    """True when the file on disk already carries this profile.

    A write leaves such a file alone, `generated` block included: that
    block names the bench and revision that last changed the data, and
    a bench that regenerates after adding its own row must not restamp
    the two files it did not measure. Three benches each writing every
    file would churn every profile on every row.
    """
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        try:
            on_disk = json.load(fh)
        except ValueError:
            return False
    return _comparable(on_disk) == _comparable(profile)


def check(profiles, boards_dir):
    """Files that differ from what the record regenerates, plus profiles
    on disk for no known uid. The `generated` block is not compared."""
    drift = []
    for uid, p in profiles.items():
        path = profile_path(boards_dir, uid)
        if not os.path.exists(path):
            drift.append(f"{path}: missing")
            continue
        with open(path, encoding="utf-8") as fh:
            try:
                on_disk = json.load(fh)
            except ValueError:
                drift.append(f"{path}: not JSON")
                continue
        if _comparable(on_disk) != _comparable(p):
            drift.append(f"{path}: differs from the record")
    known = set(profiles)
    for path in sorted(glob.glob(os.path.join(boards_dir, "*.json"))):
        uid = os.path.basename(path)[:-5]
        if os.path.basename(path) == NOTES_NAME:
            continue
        if uid not in known:
            drift.append(f"{path}: no row names this board")
    return drift


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true",
                      help="regenerate every profile from the record")
    mode.add_argument("--check", action="store_true",
                      help="exit 1 if any profile differs from the record")
    ap.add_argument("--rotation", default=ROTATION)
    ap.add_argument("--calibration", default=CALIBRATION)
    ap.add_argument("--boards-dir", default=BOARDS_DIR)
    ap.add_argument("--flash-log", default=None, metavar="PATH",
                    help="fold a bench-local flash log into the history; "
                         "never for the committed profiles, which must "
                         "regenerate identically on every bench")
    ap.add_argument("--no-generated", action="store_true",
                    help="omit the generated block (tests)")
    args = ap.parse_args(argv)

    try:
        profiles = build_profiles(
            _rows(args.rotation), _calibration(args.calibration),
            _rows(args.flash_log) if args.flash_log else (),
            generated=None if args.no_generated else generated_block(),
            notes=_notes(args.boards_dir))
    except ValueError as exc:
        print(f"board_profile: {exc}", file=sys.stderr)
        return 2
    if not profiles:
        print("board_profile: no board named in the record", file=sys.stderr)
        return 2

    if args.check:
        drift = check(profiles, args.boards_dir)
        if drift:
            print("board_profile: profiles drifted from the record:\n  "
                  + "\n  ".join(drift), file=sys.stderr)
            return 1
        print(f"board_profile: {len(profiles)} profile(s) match the record")
        return 0

    os.makedirs(args.boards_dir, exist_ok=True)
    for uid, p in profiles.items():
        path = profile_path(args.boards_dir, uid)
        state = "unchanged" if _unchanged(path, p) else "written"
        if state == "written":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render(p))
        per = ", ".join(f"{ph}: median {v['rested_largest_median']} n {v['n_rows']}"
                        for ph, v in p["converter_summary"].items())
        print(f"{uid} serial {p['board_serial']} [{per}] flags {p['flags']} "
              f"({state})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
