"""`tools/stack_depth.py`, and whether it can be believed.

A stack-depth tool is exactly the shape of instrument this project keeps
learning not to trust: it reports one number, the number is almost always
plausible, and the failure mode is that it silently leaves out an edge and
reports a smaller one. Nobody notices a bound that is too generous until the
stack is already through the heap.

So the tests here are mostly about REFUSAL. The arithmetic gets one positive
control - a graph small enough to add up by hand - and everything else asks
whether the tool declines to answer when it should. That split is deliberate:
`CLAUDE.md`'s rule is that a guard is not trusted until it has failed once on
purpose, and for this tool "failing" means printing no number at all.

No board, no build, no toolchain: every fixture is a `.ci` file written here.
The format is GCC's, quoted from real output in `docs/` and reproduced exactly
enough that a change in the parser fails these rather than passing them.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import stack_depth as sd                                      # noqa: E402


def _node(title, name, where, frame=None, shape=None):
    """One `.ci` node line. `frame=None` is an external - no byte count."""
    label = f"{name}\\n{where}"
    if frame is not None:
        label += f"\\n{frame} bytes (static)\\n0 dynamic objects"
    tail = f' shape : {shape}' if shape else ""
    return f'node: {{ title: "{title}" label: "{label}"{tail} }}'


def _edge(src, dst, at):
    return f'edge: {{ sourcename: "{src}" targetname: "{dst}" label: "{at}" }}'


def _ci(tmp_path, name, lines):
    d = tmp_path / "build"
    d.mkdir(exist_ok=True)
    (d / f"{name}.ci").write_text(
        f'graph: {{ title: "{name}"\n' + "\n".join(lines) + "\n}\n")
    return str(d)


# --- the arithmetic, once ---------------------------------------------------

def test_the_walk_takes_the_deepest_chain_not_the_sum(tmp_path):
    """The one positive control, small enough to add up by hand.

    main calls both a cheap function and an expensive one. The answer is the
    deeper branch, not both branches added together - which is the arithmetic
    error that would make every figure this tool prints too large, and so the
    one that would never be noticed by anyone checking whether the bound is
    safe.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("t.c:deep", "deep", "t.c:2:1", 80),
        _node("t.c:leaf", "leaf", "t.c:3:1", 48),
        _node("t.c:cheap", "cheap", "t.c:4:1", 8),
        _edge("main", "t.c:cheap", "t.c:10:1"),
        _edge("main", "t.c:deep", "t.c:11:1"),
        _edge("t.c:deep", "t.c:leaf", "t.c:12:1"),
    ])
    g, files = sd.parse([build])
    assert files == 1
    total, chain = sd.deepest(g, "main", dict(g.frame), {}, {})
    assert total == 24 + 80 + 48, "deepest chain, not the sum of all branches"
    assert [g.name[t] for t in chain] == ["main", "deep", "leaf"]


# --- the refusals -----------------------------------------------------------

def test_a_cycle_is_named_rather_than_summed(tmp_path):
    """Recursion has no worst-case depth, so there is no number to print.

    Invariant 7 forbids it on the working path, which makes this a defect
    report rather than a limitation of the tool.
    """
    build = _ci(tmp_path, "t", [
        _node("a", "a", "t.c:1:1", 16),
        _node("b", "b", "t.c:2:1", 16),
        _edge("a", "b", "t.c:3:1"),
        _edge("b", "a", "t.c:4:1"),
    ])
    g, _ = sd.parse([build])
    with pytest.raises(RecursionError) as exc:
        sd.deepest(g, "a", dict(g.frame), {}, {})
    assert "a" in str(exc.value) and "b" in str(exc.value), (
        "the cycle has to be named; 'there is a cycle somewhere' is not "
        "actionable on a 345-function graph")
    assert sd.main([build]) == 4


def test_an_undeclared_indirect_call_is_refused(tmp_path):
    """The whole point of the tool.

    A call through a function pointer that nobody has declared a target set
    for is unfollowable. Printing a depth that skips it would be an
    under-report - the direction that matters - so nothing is printed.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("main", sd.INDIRECT, "t.c:9:3"),
    ])
    assert sd.main([build]) == 3


def test_an_external_with_no_frame_is_refused(tmp_path):
    """A library leaf we cannot size is the same failure one layer down."""
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("vendor_blob", "vendor_blob", "blob.h:1:1", shape="ellipse"),
        _edge("main", "vendor_blob", "t.c:9:3"),
    ])
    assert sd.main([build]) == 3
    # ...and declaring it, with a measurement behind it, is what unblocks it.
    assert sd.main([build, "--leaf", "vendor_blob=16"]) == 0


def test_a_declared_leaf_is_actually_added(tmp_path):
    """Otherwise --leaf would be a way to silence the refusal for free."""
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("vendor_blob", "vendor_blob", "blob.h:1:1", shape="ellipse"),
        _edge("main", "vendor_blob", "t.c:9:3"),
    ])
    g, _ = sd.parse([build])
    frames = dict(g.frame)
    frames["vendor_blob"] = 16
    total, _chain = sd.deepest(g, "main", frames, {}, {})
    assert total == 40


# --- the two things the compilers disagree about ----------------------------

def test_a_weak_alias_is_not_mistaken_for_an_external(tmp_path):
    """xPack 15.2.1 emits these and Debian 14.2.1 does not.

    One `shape : triangle` node per unused interrupt vector, aliasing
    Default_Handler, carrying no byte count. A tool that keys only on "no
    frame" calls all 49 of them unresolved and refuses on the container while
    working on the bench - a tool that is correct on one compiler and silent on
    the other, which is the worst of the three states to be in.

    The alias costs no frame of its own, so it is zero and the edge carries the
    walk on to the handler it aliases.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("s.c:CAN1_Handler", "CAN1_Handler", "sam3x8e.h:207:6",
              shape="triangle"),
        _node("s.c:Default_Handler", "Default_Handler", "s.c:9:1", 32),
        _edge("main", "s.c:CAN1_Handler", "t.c:3:1"),
        _edge("s.c:CAN1_Handler", "s.c:Default_Handler", "sam3x8e.h:207:6"),
    ])
    g, _ = sd.parse([build])
    assert g.frame["s.c:CAN1_Handler"] == 0
    assert "s.c:CAN1_Handler" not in g.externals, (
        "a weak alias is local code, not a library leaf")
    total, _chain = sd.deepest(g, "main", dict(g.frame), {}, {})
    assert total == 24 + 0 + 32


def test_statics_in_two_units_are_two_functions(tmp_path):
    """`static void helper()` in two files is not one node.

    GCC titles a static with its defining path for exactly this reason. Keying
    the graph on the bare name would merge them, and the merged node would
    carry the larger frame and both sets of edges - inventing a chain that no
    call can take.
    """
    _ci(tmp_path, "one", [
        _node("one.c:helper", "helper", "one.c:1:1", 8),
        _node("f", "f", "one.c:2:1", 16),
        _edge("f", "one.c:helper", "one.c:3:1"),
    ])
    build = _ci(tmp_path, "two", [
        _node("two.c:helper", "helper", "two.c:1:1", 256),
        _node("g", "g", "two.c:2:1", 16),
        _edge("g", "two.c:helper", "two.c:3:1"),
    ])
    g, files = sd.parse([build])
    assert files == 2
    assert g.frame["one.c:helper"] == 8 and g.frame["two.c:helper"] == 256
    assert sd.deepest(g, "f", dict(g.frame), {}, {})[0] == 24, (
        "f reaches its own 8-byte helper, not the other unit's 256-byte one")


# --- roots ------------------------------------------------------------------

def test_a_function_reached_only_indirectly_is_not_a_root(tmp_path):
    """Otherwise every dispatch handler reads as an entry point.

    The edge the graph records runs to the placeholder, not to the handler, so
    a naive in-degree test makes all 50 console handlers look like places
    execution starts. They are one dispatch away from main.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("t.c:h_one", "h_one", "t.c:2:1", 8),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("main", sd.INDIRECT, "t.c:9:3"),
    ])
    g, _ = sd.parse([build])
    bare = sd.roots_of(g, [], {}, {})
    assert "t.c:h_one" in bare, "with nothing resolved it is unreachable"
    resolved = sd.roots_of(g, [], {"main": {"h_one"}},
                           {"h_one": "t.c:h_one"})
    assert resolved == ["main"], (
        "once the indirect edge resolves, the handler has a caller")


# --- the tracked claims ----------------------------------------------------

def test_declarations_are_read_per_track(tmp_path):
    """One file, three tracks; a track gets its own lines and no others."""
    f = tmp_path / "d.list"
    f.write_text("b indirect console.c:260 console_bindings  # a table\n"
                 "c indirect timers.c none\n"
                 "\n"
                 "# a whole-line comment\n"
                 "b leaf vendor_blob 16\n")
    assert sd.read_declarations(str(f), "b") == [
        ("indirect", "console.c:260", "console_bindings"),
        ("leaf", "vendor_blob", "16")]
    assert sd.read_declarations(str(f), "c") == [
        ("indirect", "timers.c", "none")]
    assert sd.read_declarations(str(f), "a") == []


def test_a_malformed_declaration_stops_rather_than_being_skipped(tmp_path):
    """A skipped line is a claim nobody made being treated as one nobody
    needed - the site it was meant to cover silently goes back to being
    refused, or worse, another line's spec reaches it."""
    f = tmp_path / "d.list"
    f.write_text("b indirect console.c:260\n")          # three fields, not four
    with pytest.raises(ValueError) as exc:
        sd.read_declarations(str(f), "b")
    assert "d.list:1" in str(exc.value), "name the line, not just the file"

    f.write_text("b nonsense console.c:260 x\n")
    with pytest.raises(ValueError):
        sd.read_declarations(str(f), "b")


def test_the_committed_declarations_parse(tmp_path):
    """The file in the tree is the one the canonical invocation reads.

    A syntax error in it would surface as a build-report failure on
    whichever bench ran next, which is a long way from the commit that
    caused it.
    """
    for track, want in (("b", True), ("c", True), ("a", False)):
        got = sd.read_declarations(sd.DECLARATIONS, track)
        assert bool(got) is want, (
            f"track {track}: {'expected' if want else 'expected no'} "
            f"declarations, got {got}")
    b = dict((k, v) for _kind, k, v in
             sd.read_declarations(sd.DECLARATIONS, "b"))
    assert b.get("console.c:260") == "console_bindings", (
        "the console dispatch must resolve exactly, not by assertion")


# --- the diagram ------------------------------------------------------------

def _graph_fixture(tmp_path):
    """main -> {cheap, deep -> leaf}, so pruning has something to drop."""
    return _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("t.c:deep", "deep", "t.c:2:1", 80),
        _node("t.c:leaf", "leaf", "t.c:3:1", 48),
        _node("t.c:cheap", "cheap", "t.c:4:1", 8),
        _edge("main", "t.c:cheap", "t.c:10:1"),
        _edge("main", "t.c:deep", "t.c:11:1"),
        _edge("t.c:deep", "t.c:leaf", "t.c:12:1"),
    ])


def test_the_diagram_says_what_it_pruned(tmp_path, capsys):
    """A picture that quietly drops two thirds of the graph is the same
    failure as a depth that quietly drops an edge: the reader cannot tell a
    small graph from a filtered one. The count and the threshold are inside
    the output, not beside it."""
    build = _graph_fixture(tmp_path)
    assert sd.main([build, "--mermaid", "--prune", "100"]) == 0
    out = capsys.readouterr().out
    assert "of 4 functions" in out and ">= 100 B" in out
    assert "cheap" not in out, "8 B under a 100 B floor should be gone"
    assert "deep" in out, "128 B below it should survive"


def test_the_diagram_marks_the_deepest_path(tmp_path, capsys):
    """Otherwise it is a picture of the call graph rather than of the cost."""
    build = _graph_fixture(tmp_path)
    assert sd.main([build, "--mermaid", "--prune", "0"]) == 0
    out = capsys.readouterr().out
    assert "==>" in out, "the critical path needs a distinct edge"
    assert "-->" in out, "and the rest needs a plain one, or nothing is marked"


def test_the_diagram_refuses_on_the_same_terms_as_the_number(tmp_path):
    """The one that matters.

    A diagram is an output like any other and shares the refusal gate. Drawing
    from a graph with an edge we could not follow would put a confident picture
    on top of an unknown - worse than printing nothing, because a picture is
    believed harder than a table.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("main", sd.INDIRECT, "t.c:9:3"),
    ])
    assert sd.main([build, "--mermaid"]) == 3
    assert sd.main([build, "--dot"]) == 3


def test_dot_and_mermaid_describe_one_graph(tmp_path, capsys):
    """Two renderings, one pruning. A reader comparing them must not find
    different graphs."""
    build = _graph_fixture(tmp_path)
    sd.main([build, "--dot", "--prune", "0"])
    dot = capsys.readouterr().out
    sd.main([build, "--mermaid", "--prune", "0"])
    mer = capsys.readouterr().out
    for name in ("main", "deep", "leaf", "cheap"):
        assert name in dot and name in mer
    assert dot.count("->") == mer.count("==>") + mer.count("-->")


def test_an_empty_scan_does_not_pass(tmp_path):
    """A report that prints nothing and exits 0 is the guard that cannot fail.

    The same failure `tools/stack_frames.py` guards against: an empty scan
    means the build flag was never on, not that the firmware has no stack.
    """
    (tmp_path / "build").mkdir()
    assert sd.main([str(tmp_path / "build")]) == 1
    assert sd.main([str(tmp_path / "nope")]) == 2
