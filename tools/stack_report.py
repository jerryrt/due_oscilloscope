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

EVERY TRACK IS IN EVERY TABLE. A track whose row carries no bound -
`state` of `recursion` or `refused`, with `blocked` saying what stopped
the walk - renders in the same table as the bounded ones, its bound cell
reading `(no bound)` and its reason beside it. Dropping it would leave
the comparison silently two-track, and absence reads as "not measured"
or as "fine" depending on the reader: the same failure the record format
refuses one level up by writing a row rather than staying silent. The
diagram is the one region that cannot draw such a track, because there
is no chain; it draws a node saying so instead of leaving a gap.

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

#: What a track that carries no bound renders as. Distinct from ABSENT
#: on purpose: the field is not missing, the walk refused to produce it,
#: and the reason is in the cell next to this one.
NO_BOUND = "(no bound)"
NO_CHAIN = "(no chain)"

#: The states that come with a number. Anything else - `refused`,
#: `recursion` - is a row without one.
BOUNDED = ("exact", "upper bound")


def _unreadable(message):
    """Exit 2: the record could not be read at all.

    TWO AND NOT ONE, because a gate has to tell "the document drifted"
    from "there was nothing to compare it against". Both are non-zero
    and only the first is an answer; the second is the DID NOT RUN state
    docker/run-ci.sh exists to keep separate, and it cannot separate
    them from one exit code. The analysers here already use 0/1/2 for
    exactly this, so nothing new is being invented.
    """
    sys.stderr.write(message + "\n")
    raise SystemExit(2)


class Records(dict):
    """{track: latest row}, with `.by_bench` for the cross-bench view.

    A dict subclass rather than a second loader, because every region
    but one wants the collapsed view and the odd one out should not make
    the others take an argument they ignore. `.by_bench` is
    {(bench, track): latest row for that pair}.

    THE COLLAPSED VIEW HIDES THE COMPARISON, which is why this exists.
    `load()` keeps the latest row per track, so the moment a second
    bench recorded, the whole document described that bench and nothing
    said so - three benches' rows in the record and one bench's figures
    on the page. That is the failure r_bounds' own docstring warns
    about, one dimension over: a row quietly missing from a comparison
    reads as agreement.
    """

    by_bench = {}


def load(path=RECORDS):
    """{track: row}, latest row per track.

    A missing or empty file is an error. An empty table generated from
    nothing looks exactly like a firmware with no stack, and `--check`
    would then pass on a document that says so.
    """
    if not os.path.exists(path):
        _unreadable(
            "no record at %s - take one with `tools/stack_depth.py "
            "--record` from a -DFIRMWARE_CALLGRAPH=ON build" % path)
    rows, pairs = {}, {}
    with io.open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                _unreadable("%s:%d: not JSON: %s" % (path, n, exc))
            if row.get("schema") != SCHEMA:
                _unreadable(
                    "%s:%d: schema %r, want %r - the fields may have moved, "
                    "so this stops rather than reading it as if they had not"
                    % (path, n, row.get("schema"), SCHEMA))
            track = row.get("track")
            if not track:
                _unreadable("%s:%d: row carries no track" % (path, n))
            if "roots" not in row:
                _unreadable("%s:%d: row carries no roots" % (path, n))
            rows[track] = row
            bench = row.get("bench")
            if bench:
                pairs[(bench, track)] = row
    if not rows:
        _unreadable("%s holds no rows - nothing to report" % path)
    out = Records(rows)
    out.by_bench = pairs
    return out


def _cell(value):
    """One table cell. A pipe inside a reason would end the column, so it
    is escaped: a blocked row's text is a compiler's, not this tool's."""
    if value is None or value == "":
        return ABSENT
    return str(value).replace("|", "\\|")


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


def _bounded(row):
    """Does this row carry a bound at all?

    Two ways not to. The producer can answer `refused` or `recursion`,
    which is the three-state contract doing its job; or it can answer
    with a state that carries a number and no roots to hang it on, which
    is a partial scan. Both render as a row saying so.
    """
    return row.get("state") in BOUNDED and bool(row.get("roots"))


def _why(row):
    """Why a row carries no bound, as one cell - or `none` when it does.

    `none` rather than an empty cell, because `blocked: []` is a
    measurement: the walk ran and nothing stopped it.
    """
    items = row.get("blocked") or []
    if items:
        # Unescaped: this goes through a cell renderer that escapes, and
        # escaping twice writes the backslash into the document.
        return "; ".join("%s: %s" % (b.get("what") or ABSENT,
                                     b.get("why") or ABSENT) for b in items)
    if not _bounded(row):
        return ("state %s, and the row lists no blocker"
                % (row.get("state") or ABSENT))
    return "none"


def _root_why(entry, row):
    """One root's blocker, falling back to the track's.

    A root recorded before per-root refusal existed carries neither a
    state nor a blocker of its own, so it inherits the track's - which
    is what those rows meant when they were written and is not a guess.
    """
    items = entry.get("blocked") or []
    if items:
        return "; ".join("%s: %s" % (b.get("what") or ABSENT,
                                     b.get("why") or ABSENT) for b in items)
    return _why(row)


def _state_why(row):
    """The state and the blocker, as one phrase and without saying the
    same word twice: a recursion row's blocker is already labelled
    `recursion`."""
    state = row.get("state") or ABSENT
    why = _why(row)
    return why if why.startswith("%s:" % state) else "%s - %s" % (state, why)


def _deepest(row):
    if not _bounded(row):
        return None
    got = _roots(row)
    return got[0] if got else None


# --- the regions ------------------------------------------------------

def r_bounds(recs):
    """One row per root that carries a bound, with the graph it came from.

    Every track appears. A track the walk could not bound gets one row
    with `(no bound)` where the number would be and the blocker beside
    it, in this table rather than under a heading of its own: a reader
    comparing three tracks has to see all three without scrolling, and a
    track quietly missing from a comparison reads as agreement.

    The zero-byte roots are omitted and the count of them is printed, on
    `tools/stack_depth.py --mermaid`'s rule: a reader cannot tell a short
    table from a filtered one unless the filter is part of the output.
    """
    rows, elided, unbounded, partial = [], [], [], []
    for track in sorted(recs):
        row = recs[track]
        sites, targets = row.get("indirect_sites"), row.get("indirect_targets")
        graph = ("%s / %s" % (_cell(sites), _cell(targets)),
                 _cell(row.get("functions")))
        if not _bounded(row):
            unbounded.append("track %s" % track)
            rows.append({
                "track": track,
                "root": NO_CHAIN,
                "bytes": NO_BOUND,
                "state": _cell(row.get("state")),
                "blocked by": _why(row),
                "functions": graph[1],
                "indirect sites/targets": graph[0],
            })
            continue
        # A REFUSED ROOT IS KEPT WHATEVER ITS BYTES ARE. Its bytes are
        # null, so the zero-byte filter would drop it - and the document
        # would then show a track's clean roots with nothing anywhere to
        # say that some were not walked. That is the body-of-zeroes
        # failure in a table: the reader cannot tell a short list from a
        # filtered one.
        kept = [r for r in _roots(row)
                if (r.get("bytes") or 0) > 0 or r.get("state") == "refused"]
        elided.append("%d on track %s" % (len(row["roots"]) - len(kept), track))
        for r in kept:
            per_root = r.get("state") == "refused"
            rows.append({
                "track": track,
                "root": _cell(r.get("root")),
                "bytes": NO_BOUND if per_root else _cell(r.get("bytes")),
                "state": _cell(r.get("state") or row.get("state")),
                "blocked by": _root_why(r, row),
                "functions": graph[1],
                "indirect sites/targets": graph[0],
            })
            if per_root:
                partial.append("track %s" % track)
    tail = "\n\nRoots whose bound is 0 B are not listed: %s." % (
        ", ".join(elided) or "no track reported one")
    if unbounded:
        tail += (" No root was walked on %s at all, so that row carries the "
                 "state and the blocker where the others carry a number."
                 % ", ".join(unbounded))
    if partial:
        tail += (" Refusal is per root: %s carries both bounded rows and "
                 "`%s` rows, and a refused root's own blocker is in the cell "
                 "beside it. A bounded row's figure came off a subgraph with "
                 "nothing unfollowed in it, so the refusals beside it do not "
                 "weaken it."
                 % (", ".join(sorted(set(partial))), NO_BOUND))
    tail += (" `functions` and `indirect sites/targets` describe the whole "
             "graph the walk ran over, so they repeat down a track's rows and "
             "are counted for a track that reached no bound too.")
    return _table(rows) + tail


def r_chains(recs):
    """The deepest root's chain per track, frame by frame.

    A track with no chain is one row saying which state stopped it, for
    the reason `r_bounds` gives: three tracks, one table.
    """
    rows, heads = [], []
    for track in sorted(recs):
        row = recs[track]
        deep = _deepest(row)
        if deep is None:
            heads.append("track %s: no chain, %s" % (track, _why(row)))
            rows.append({
                "track": track,
                "#": NO_CHAIN,
                "function": _state_why(row),
                "frame B": NO_BOUND,
                "total below B": NO_BOUND,
            })
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


def _label(text):
    """Mermaid label text.

    A quote ends the label and an angle bracket starts markup, so both
    become the entities Mermaid renders back. `&` goes first or it
    rewrites the entities the others just wrote.
    """
    out = str(text).replace("&", "#amp;").replace('"', "#quot;")
    return out.replace("<", "#lt;").replace(">", "#gt;")


def r_diagram(recs):
    """The deepest chain per track, as a Mermaid block GitHub renders.

    The whole diagram is the critical path - the record carries that
    chain and nothing beside it - so every edge is drawn heavy. The graph
    the bound was computed from, pruned and with the siblings on it, is
    `tools/stack_depth.py --mermaid`.

    THIS IS THE ONE REGION THAT CAN SKIP A TRACK, because a track with no
    chain has nothing to draw. It says so in the picture - a box carrying
    the state and the blocker, where the other tracks have a column of
    frames - and again in prose under it. A missing subgraph would read
    as a track with no stack.
    """
    ids = _ids(recs)
    out = ["```mermaid", "graph TD"]
    notes, skipped = [], []
    for track in sorted(recs):
        row = recs[track]
        deep = _deepest(row)
        if deep is None:
            why = _state_why(row)
            node = "%s_none" % track
            notes.append(node)
            skipped.append("track %s (%s)" % (track, why))
            out.append('  subgraph sg_%s["track %s - no chain to draw"]'
                       % (track, track))
            out.append("  direction TB")
            out.append('    %s["%s<br/>%s"]' % (node, _label(NO_CHAIN),
                                                _label(why)))
            out.append("  end")
            continue
        chain = deep.get("chain") or []
        out.append('  subgraph sg_%s["track %s - %s - %s B"]'
                   % (track, track, _label(deep.get("root")),
                      _cell(deep.get("bytes"))))
        out.append("  direction TB")
        for i, step in enumerate(chain):
            out.append('    %s["%s<br/>%s B · %s total"]'
                       % (ids[(track, i)], _label(step.get("function")),
                          _cell(step.get("frame")), _cell(step.get("below"))))
        for i in range(len(chain) - 1):
            out.append("    %s ==> %s" % (ids[(track, i)], ids[(track, i + 1)]))
        out.append("  end")
    for key in sorted(ids.values()):
        out.append("  style %s stroke-width:3px" % key)
    for key in sorted(notes):
        out.append("  style %s stroke-dasharray:4 3" % key)
    out.append("```")
    if skipped:
        out.append("")
        out.append("No chain is drawn for %s: the walk reported no root, so "
                   "there is no worst case to draw. The box says which state "
                   "stopped it; the bounds table above carries the same "
                   "reason." % ", ".join(skipped))
    return "\n".join(out)


def r_nesting(recs):
    """The worst case on a stack, which is not any row of the bounds table.

    Two tables, because the total and the reason for it answer different
    questions: the first says whether the firmware fits, the second says
    which level to look at if it does not. A row whose record carries no
    nesting at all renders `(absent)` rather than a zero - a track with
    no interrupt accounting is the one thing that must not read as a
    track with no interrupts.
    """
    totals, levels = [], []
    for track in sorted(recs):
        nest = recs[track].get("nesting")
        if not nest:
            blank = _cell(None)
            totals.append({"track": track, "thread mode": blank,
                           "levels": blank, "never enabled": blank,
                           "worst case": blank, "state": blank})
            continue
        rows = nest.get("levels") or []
        totals.append({
            "track": track,
            "thread mode": "%s through `%s`" % (_cell(nest.get(
                "thread_bytes")), _cell(nest.get("thread_root"))),
            "levels": _cell(len(rows)),
            "never enabled": _cell(len(nest.get("off") or [])),
            "worst case": "**%s**" % _cell(nest.get("total")),
            "state": _cell(nest.get("state")),
        })
        for row in rows:
            levels.append({
                "track": track,
                "level": (_cell(row.get("level"))
                          if row.get("level") is not None else "undeclared"),
                "bytes": _cell(row.get("bytes")),
                "handlers": ", ".join("`%s`" % h
                                      for h in row.get("handlers") or []),
            })
    frames = sorted({r["nesting"]["exc_frame"] for r in recs.values()
                     if r.get("nesting")})
    note = ("Every level's figure includes %s B of hardware exception frame - "
            "eight words plus a word of STKALIGN padding - so a level costs "
            "that much even where its handler is a counter increment. "
            "Handlers at one level do not nest, so a level is charged one "
            "frame and its deepest member; an `undeclared` row is a handler "
            "with no declared level, assumed to nest on its own, which is "
            "the ceiling the state column reports against."
            % ", ".join(str(f) for f in frames) if frames else
            "No record carries an interrupt accounting.")
    return (_table(totals) + "\n\n" + _table(levels) + "\n\n" + note)


def r_benches(recs):
    """The same question asked of every bench that has answered it.

    One row per (bench, track), because the independent variable here is
    the code generator and the collapsed view cannot show it. A bench
    that has not recorded is simply not a row - this table cannot invent
    one - so the note says how many benches are in it, which is what
    stops a one-bench table reading as agreement between three.

    AND IT SAYS WHETHER THE ROWS ARE COMPARABLE AT ALL. Frames compare
    across benches only at one commit; rows taken at different ones may
    differ because the firmware moved rather than because the compiler
    did. So the revisions are a column and a mismatch is stated in the
    note rather than left for a reader to notice.
    """
    pairs = getattr(recs, "by_bench", None)
    if not pairs:
        return ("*(no per-bench rows: the record carries no `bench` field, "
                "which is older than this table)*")
    rows, revs, benches = [], set(), set()
    for (bench, track) in sorted(pairs, key=lambda k: (k[1], k[0])):
        row = pairs[(bench, track)]
        nest = row.get("nesting") or {}
        deep = _deepest(row)
        revs.add(row.get("repo_rev"))
        benches.add(bench)
        rows.append({
            "track": track,
            "bench": bench,
            "cc": _cell(row.get("cc")),
            "repo_rev": _cell(row.get("repo_rev")),
            "deepest chain": (_cell(deep.get("bytes")) if deep else NO_BOUND),
            "chain state": _cell(row.get("state")),
            "one-stack worst case": _cell(nest.get("total")) if nest
                                    else _cell(None),
            "nesting state": _cell(nest.get("state")) if nest
                             else _cell(None),
        })
    note = ("%d bench(es) and %d track-rows. "
            % (len(benches), len(rows)))
    if len(revs) == 1:
        note += ("Every row is at `%s`, so the figures are comparable: one "
                 "source, one set of frames, and the compiler is the only "
                 "thing left varying." % sorted(revs)[0])
    else:
        note += ("**The rows are at %d different revisions** - %s - so a "
                 "difference between benches may be the firmware moving "
                 "rather than the compiler. Re-take them at one commit "
                 "before reading a delta as a code-generator effect."
                 % (len(revs), ", ".join("`%s`" % r for r in sorted(revs))))
    return _table(rows) + "\n\n" + note


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
    "benches": r_benches,
    "bounds": r_bounds,
    "nesting": r_nesting,
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
                    help="exit 1 if the document is not what this would "
                         "generate, 2 if the record could not be read at "
                         "all. Proves the document matches the record, NOT "
                         "that the record is current")
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
