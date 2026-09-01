"""#50 item 3: does the Track A suite tell us anything the Track B one does not?

The issue asks to "remove duplicated and over-verbose cases" and marks it
"suspected rather than established". The largest single duplication in
this project is not inside a file - it is that the whole suite runs
twice, once per track, for about 15 minutes each on mac-bench and about
8.5 minutes here.

Whether that second run is duplication or oracle is an empirical
question that nobody has asked directly: run both, diff the per-test
outcomes, and see how many tests actually disagree.

WHY THIS IS NOT ALREADY ANSWERED BY #54. That measurement compared the
two tracks' compiled code and found A-vs-B differs in 0 of 64 functions
on SHARED source, against 18 of 63 across benches. That is a statement
about lib/due_shared only. Invariant 3 keeps hardware source per-track,
and main() is per-track entirely, so a test can still separate the
tracks by reaching driver or main() code around an identical shared
function. #54 says the shared half cannot differ; it does not say a
test outcome cannot.

WHAT A DISAGREEMENT MEANS, and it is not automatically oracle value:

  * a test that FAILS on one track and PASSES on the other is the
    oracle working - that is the divergence the two-track design exists
    to surface.
  * a test SKIPPED on one and run on the other is a capability gap, not
    an oracle result. Track A does not implement everything.
  * a FLAKY test that differs run to run on ONE track is neither, and
    is the thing most likely to be mistaken for the first. This tool
    cannot tell it from a real divergence on one pair of runs, and says
    so rather than pretending otherwise.

So the output is a floor on duplication and not a verdict: tests that
AGREE are duplicated for certain; tests that disagree need a repeat run
on one track before anyone calls them oracle.

    .venv/Scripts/python.exe -m pytest --track=b -q --junit-xml=b.xml
    .venv/Scripts/python.exe -m pytest --track=a -q --junit-xml=a.xml
    .venv/Scripts/python.exe tools/issue50_track_diff.py b.xml a.xml
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET


def outcomes(path):
    """{test id: outcome} from a pytest junit-xml file."""
    root = ET.parse(path).getroot()
    out = {}
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        cls = case.get("classname") or ""
        # Strip the track parametrisation so the two runs' ids line up:
        # the same test is "foo[b]" on one run and "foo[a]" on the other.
        base = name
        for suffix in ("[b]", "[a]", "[c]"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        key = "%s::%s" % (cls, base)
        verdict = "passed"
        for child in case:
            tag = child.tag.lower()
            if tag in ("failure", "error"):
                verdict = tag
                break
            if tag == "skipped":
                verdict = "skipped"
                break
        # A test id can appear twice if it is parametrised on something
        # else as well; keep the worst outcome rather than the last.
        rank = {"passed": 0, "skipped": 1, "failure": 2, "error": 3}
        if key not in out or rank[verdict] > rank[out[key]]:
            out[key] = verdict
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track_b_xml")
    ap.add_argument("track_a_xml")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    b = outcomes(args.track_b_xml)
    a = outcomes(args.track_a_xml)
    both = sorted(set(b) & set(a))
    only_b = sorted(set(b) - set(a))
    only_a = sorted(set(a) - set(b))

    agree = [k for k in both if b[k] == a[k]]
    differ = [k for k in both if b[k] != a[k]]

    # The three classes of disagreement, which are not the same finding.
    oracle, capability, other = [], [], []
    for k in differ:
        pair = {b[k], a[k]}
        if pair <= {"passed", "failure", "error"}:
            oracle.append(k)
        elif "skipped" in pair:
            capability.append(k)
        else:
            other.append(k)

    print("tests present in both runs : %d" % len(both))
    print("  identical outcome        : %d  (%.1f%%)"
          % (len(agree), 100.0 * len(agree) / len(both) if both else 0))
    print("  DIFFERENT outcome        : %d" % len(differ))
    print("      pass/fail split (candidate ORACLE value) : %d" % len(oracle))
    print("      one side skipped (capability gap)        : %d" % len(capability))
    print("      other                                    : %d" % len(other))
    print("only in the Track B run    : %d" % len(only_b))
    print("only in the Track A run    : %d" % len(only_a))
    if oracle:
        print()
        print("candidate oracle divergences - each needs a REPEAT on one")
        print("track before it counts, since a flaky test looks identical:")
        for k in oracle:
            print("  %-72s B=%-8s A=%s" % (k[-72:], b[k], a[k]))
    if capability:
        print()
        print("capability gaps (one side skipped):")
        for k in capability[:20]:
            print("  %-72s B=%-8s A=%s" % (k[-72:], b[k], a[k]))
        if len(capability) > 20:
            print("  ... and %d more" % (len(capability) - 20))

    summary = {
        "issue": 50, "test": "track-a-vs-track-b-outcome-diff",
        "team": "windows-platform-team", "bench": "windows-desk",
        "in_both": len(both), "identical": len(agree),
        "different": len(differ),
        "oracle_candidates": oracle,
        "capability_gaps": len(capability),
        "other": other,
        "only_track_b": only_b, "only_track_a": only_a,
        "caveat": ("Tests that AGREE are duplicated for certain. Tests that "
                   "DISAGREE are not automatically oracle value - a flaky "
                   "test looks identical on one pair of runs, and a skip is "
                   "a capability gap rather than a divergence. This is a "
                   "floor on duplication, not a verdict."),
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(summary) + "\n")
        print()
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
