#!/usr/bin/env python3
"""Generate the stack-depth tables and diagram from the recorded rows.

    python3 tools/stack_report.py            # print the regions
    python3 tools/stack_report.py --write    # update docs/stack-depth.md
    python3 tools/stack_report.py --check    # fail if the document drifted

The arrangement is `tools/report.py`'s, for the same reason: a number
copied into prose stops being connected to the measurement that produced
it, and then outlives it. So this generates the *tables* whose every cell
comes from `records/stack-depth.jsonl`, and writes them into marked
regions of a document that is otherwise prose. Argument, caveat and
retraction stay hand-written, because they are the part a generator
cannot check and the part that carries the meaning.

A region is machine-owned or it is not. Between the markers nothing
survives regeneration, so nothing hand-written may be put there.

    <!-- generated: bounds -->
    ...table...
    <!-- end generated -->

WHAT `--check` PROVES, AND WHAT IT CANNOT. It proves the document
matches the record. It CANNOT prove the record is current: the record is
written by `tools/stack_depth.py --record` from a `-DFIRMWARE_CALLGRAPH=ON`
build, and this reads JSON and writes Markdown with no ELF, no build and
no toolchain in the path. A stale record and a document generated from
it agree perfectly and `--check` passes for ever. Re-taking the
measurement is a firmware build and is nobody's automatic step; treating
a green check as evidence that the bound still holds is exactly the
conflation this project keeps writing guards against.

WHAT IT REFUSES. `tools/stack_depth.py` answers in three states -
exact, upper bound, or no number at all - and a report that filled a
blank cell would undo that at the last step. So an absent field is
rendered as `(absent)`, never as a zero or a dash that reads as a
measurement; a record file that is missing or empty is an error rather
than an empty table; and a row whose schema is not the one below stops
the run instead of being read on the assumption that the fields did not
move.

The latest row per track wins, so re-recording a track appends rather
than rewriting.

Stdlib only, like the rest of the build-side tooling here.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(HERE, "records", "stack-depth.jsonl")
DOC = os.path.join(HERE, "docs", "stack-depth.md")

SCHEMA = "stack-depth/1"

BEGIN = "<!-- generated: %s -->"
END = "<!-- end generated -->"

#: What an absent field renders as. Not "-" and not 0: both read as a
#: measurement, and this tool sits downstream of one that refuses to
#: print a number it could not derive.
ABSENT = "(absent)"


def load(path=RECORDS):
    """{track: row}, latest row per track.

    A missing or empty file is an error. An empty table generated from
    nothing looks exactly like a firmware with no stack, and `--check`
    would then pass on a document that says so.
    """
    if not os.path.exists(path):
        raise SystemExit(
            "no record at %s - take one with `tools/stack_depth.py "
            "--record` from a -DFIRMWARE_CALLGRAPH=ON build" % path)
    rows = {}
    with io.open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise SystemExit("%s:%d: not JSON: %s" % (path, n, exc))
            if row.get("schema") != SCHEMA:
                raise SystemExit(
                    "%s:%d: schema %r, want %r - the fields may have moved, "
                    "so this stops rather than reading it as if they had not"
                    % (path, n, row.get("schema"), SCHEMA))
            track = row.get("track")
            if not track:
                raise SystemExit("%s:%d: row carries no track" % (path, n))
            if "roots" not in row:
                raise SystemExit("%s:%d: row carries no roots" % (path, n))
            rows[track] = row
    if not rows:
        raise SystemExit("%s holds no rows - nothing to report" % path)
    return rows


def _cell(value):
    if value is None or value == "":
        return ABSENT
    return str(value)


def _table(rows):
    """Markdown, with the header taken from the first row's keys."""
    if not rows:
        return "*(no rows)*"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |")
    return "\n".join(out)


def _roots(row):
    """Recorded roots, deepest first. Ties broken by name so the order is
    the same on every bench rather than the order a dict iterated in."""
    return sorted(row["roots"],
                  key=lambda r: (-(r.get("bytes") or 0), r.get("root") or ""))


def _deepest(row):
    got = _roots(row)
    return got[0] if got else None


# --- the regions ------------------------------------------------------

def r_bounds(recs):
    """One row per root that carries a bound, with the graph it came from.

    The zero-byte roots are omitted and the count of them is printed, on
    `tools/stack_depth.py --mermaid`'s rule: a reader cannot tell a short
    table from a filtered one unless the filter is part of the output.
    """
    rows, elided = [], []
    for track in sorted(recs):
        row = recs[track]
        kept = [r for r in _roots(row) if (r.get("bytes") or 0) > 0]
        elided.append("%d on track %s" % (len(row["roots"]) - len(kept), track))
        sites, targets = row.get("indirect_sites"), row.get("indirect_targets")
        for r in kept:
            rows.append({
                "track": track,
                "root": _cell(r.get("root")),
                "bytes": _cell(r.get("bytes")),
                "state": _cell(row.get("state")),
                "functions": _cell(row.get("functions")),
                "indirect sites/targets": "%s / %s" % (_cell(sites),
                                                       _cell(targets)),
            })
    tail = ("\n\nRoots whose bound is 0 B are not listed: %s. `functions` and "
            "`indirect sites/targets` describe the whole graph the walk ran "
            "over, so they repeat down a track's rows." % ", ".join(elided))
    return _table(rows) + tail


def r_chains(recs):
    """The deepest root's chain per track, frame by frame."""
    rows, heads = [], []
    for track in sorted(recs):
        deep = _deepest(recs[track])
        if deep is None:
            heads.append("track %s: no root recorded" % track)
            continue
        heads.append("track %s: %s, %s B"
                     % (track, _cell(deep.get("root")), _cell(deep.get("bytes"))))
        for i, step in enumerate(deep.get("chain") or []):
            rows.append({
                "track": track,
                "#": i,
                "function": _cell(step.get("function")),
                "frame B": _cell(step.get("frame")),
                "total below B": _cell(step.get("below")),
            })
    return _table(rows) + "\n\n" + "; ".join(heads) + "."


def _ids(recs):
    """(track, index) -> mermaid node id, stable across runs."""
    out = {}
    for track in sorted(recs):
        deep = _deepest(recs[track])
        for i in range(len((deep or {}).get("chain") or [])):
            out[(track, i)] = "%s%d" % (track, i)
    return out


def r_diagram(recs):
    """The deepest chain per track, as a Mermaid block GitHub renders.

    The whole diagram is the critical path - the record carries that
    chain and nothing beside it - so every edge is drawn heavy. The graph
    the bound was computed from, pruned and with the siblings on it, is
    `tools/stack_depth.py --mermaid`.
    """
    ids = _ids(recs)
    out = ["```mermaid", "graph TD"]
    for track in sorted(recs):
        deep = _deepest(recs[track])
        if deep is None:
            out.append("  %%%% track %s: no root recorded" % track)
            continue
        chain = deep.get("chain") or []
        out.append('  subgraph sg_%s["track %s - %s - %s B"]'
                   % (track, track, _cell(deep.get("root")),
                      _cell(deep.get("bytes"))))
        out.append("  direction TB")
        for i, step in enumerate(chain):
            out.append('    %s["%s<br/>%s B · %s total"]'
                       % (ids[(track, i)], _cell(step.get("function")),
                          _cell(step.get("frame")), _cell(step.get("below"))))
        for i in range(len(chain) - 1):
            out.append("    %s ==> %s" % (ids[(track, i)], ids[(track, i + 1)]))
        out.append("  end")
    for key in sorted(ids.values()):
        out.append("  style %s stroke-width:3px" % key)
    out.append("```")
    return "\n".join(out)


def r_provenance(recs):
    """Which image each figure came off, so a cell can be chased."""
    rows = []
    for track in sorted(recs):
        row = recs[track]
        rows.append({
            "track": track,
            "bench": _cell(row.get("bench")),
            "repo_rev": _cell(row.get("repo_rev")),
            "cc": _cell(row.get("cc")),
            "elf": _cell(row.get("elf")),
            "elf_sha256": _cell(row.get("elf_sha256")),
            "taken_at": _cell(row.get("taken_at")),
        })
    tools = sorted({_cell(r.get("tool")) for r in recs.values()})
    lists = sorted({_cell(r.get("declarations")) for r in recs.values()})
    return (_table(rows)
            + "\n\nSchema `%s`, written by %s, resolving its indirect call "
              "sites from %s." % (SCHEMA, ", ".join("`%s`" % t for t in tools),
                                  ", ".join("`%s`" % d for d in lists)))


REGIONS = {
    "bounds": r_bounds,
    "chains": r_chains,
    "diagram": r_diagram,
    "provenance": r_provenance,
}


def render(name, recs):
    return REGIONS[name](recs)


def apply_to(text, recs):
    """Replace every marked region. Returns (text, names with no region).

    A name the document does not mark is reported rather than appended:
    where a region belongs is an editorial decision and this does not
    make it.
    """
    missing = []
    for name in sorted(REGIONS):
        begin = BEGIN % name
        if begin not in text:
            missing.append(name)
            continue
        pat = re.compile(re.escape(begin) + ".*?" + re.escape(END), re.DOTALL)
        text = pat.sub(lambda _m, n=name: (BEGIN % n) + "\n"
                       + render(n, recs) + "\n" + END, text)
    return text, missing


def drifted(text, recs):
    """The names of the regions whose content is not what this generates."""
    out = []
    for name in sorted(REGIONS):
        begin = BEGIN % name
        if begin not in text:
            continue
        i = text.index(begin) + len(begin)
        body = text[i:text.index(END, i)]
        if body.strip("\n") != render(name, recs):
            out.append(name)
    return out


def _shown(path):
    """The path as a reader can retype it: relative inside the tree, and
    left alone outside it, where a relative path is a row of `..`."""
    rel = os.path.relpath(path, HERE)
    return path if rel.startswith("..") else rel


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="update the document in place")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the document is not what this "
                         "would generate. Proves the document matches the "
                         "record, NOT that the record is current")
    ap.add_argument("--records", default=RECORDS)
    ap.add_argument("--doc", default=DOC)
    args = ap.parse_args(argv)

    recs = load(args.records)

    if not (args.write or args.check):
        for name in sorted(REGIONS):
            print("## %s\n\n%s\n" % (name, render(name, recs)))
        return 0

    with io.open(args.doc, encoding="utf-8") as fh:
        text = fh.read()
    new, missing = apply_to(text, recs)

    if args.check:
        if new != text:
            print("%s drifted from %s in: %s - run "
                  "`python3 tools/stack_report.py --write`"
                  % (_shown(args.doc), _shown(args.records),
                     ", ".join(drifted(text, recs)) or "an unmarked region"),
                  file=sys.stderr)
            return 1
        if missing:
            print("no region for: %s (nothing to check)" % ", ".join(missing),
                  file=sys.stderr)
            return 1
        print("generated regions match %s; this says nothing about whether "
              "that record is current" % _shown(args.records))
        return 0

    with io.open(args.doc, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    print("wrote %s" % args.doc)
    if missing:
        print("no region for: %s" % ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
