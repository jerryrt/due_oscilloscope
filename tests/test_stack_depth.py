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
    # title_of maps a target name to EVERY candidate node, because a weak
    # C++ method emitted into two units appears twice and they are one
    # function; the walk maxes over them.
    resolved = sd.roots_of(g, [], {"main": {"h_one"}},
                           {"h_one": ["t.c:h_one"]})
    assert resolved == ["main"], (
        "once the indirect edge resolves, the handler has a caller")


# --- C++ virtual dispatch ---------------------------------------------------

#: `nm -SC --defined-only`, as the reader parses it: address, size, type,
#: demangled name. Canned rather than built, so the test needs no ELF and
#: no toolchain - the pattern tests/test_flash.py uses on
#: image_fingerprint.
_NM_SC = """\
0008d2dc 0000002c T vtable for UARTClass
0008d308 00000028 T vtable for Serial_
00087001 00000010 T UARTClass::write(unsigned char)
00087011 00000010 T UARTClass::read()
00087021 00000010 T Serial_::write(unsigned char)
"""


def test_a_vtable_is_located_by_its_demangled_name(monkeypatch):
    """Not by rebuilding `_ZTV9UARTClass` from the class name.

    Reconstructing the mangling works for a plain class and stops the
    moment one is namespaced or templated - and a lookup that silently
    found nothing would read as "this class has no virtual methods",
    which is a wrong answer rather than no answer.
    """
    monkeypatch.setattr(sd, "_run", lambda argv: _NM_SC)
    got = sd.vtables("x.elf")
    assert got == {"UARTClass": (0x8d2dc, 0x2c),
                   "Serial_": (0x8d308, 0x28)}


def test_an_absent_vtable_names_the_ones_that_exist(monkeypatch):
    """`Print` and `Stream` are abstract bases with no instances, so no
    vtable is emitted for them and `vtable:Print` cannot resolve. The
    refusal has to say so usefully, because the fix is to use the bare
    spec and a reader cannot guess that from "not found"."""
    monkeypatch.setattr(sd, "_run", lambda argv: _NM_SC)
    with pytest.raises(LookupError) as exc:
        sd.vtable_targets("x.elf", "Print", {})
    assert "UARTClass" in str(exc.value) and "Serial_" in str(exc.value), (
        "name what the image does have; 'no vtable for Print' alone "
        "leaves the reader nowhere")


def test_a_vtable_resolves_to_the_methods_it_holds(monkeypatch):
    """The point of the whole exercise: C++ emits the target set into the
    binary, so a virtual call is the EASY case and not the hard one."""
    # Vtable slots carry the Thumb bit set; symbols() masks it off, so
    # the two sides differ by exactly that bit and the reader has to
    # bridge it. Getting this wrong in the fixture produced an empty
    # result that looked like a parser bug.
    words = {0x8d2dc: [0, 0, 0x87001, 0x87011],   # 2 header slots first
             0x8d308: [0, 0, 0x87021]}

    monkeypatch.setattr(sd, "_run", lambda argv: _NM_SC)
    monkeypatch.setattr(sd, "_read_words",
                        lambda elf, base, size: words[base])
    syms = {0x87000: "UARTClass::write(unsigned char)",
            0x87010: "UARTClass::read()",
            0x87020: "Serial_::write(unsigned char)"}

    got, _ = sd.vtable_targets("x.elf", "UARTClass", syms)
    assert got == ["UARTClass::read()", "UARTClass::write(unsigned char)"]

    # The bare form is every vtable, which is what an abstract base's
    # virtual call needs: it lands in a concrete subclass, and they are
    # all here. Sound, and the caller marks the answer a ceiling.
    everything, _ = sd.vtable_targets("x.elf", None, syms)
    assert set(everything) == set(syms.values())


# --- the method filter, which is the rung that removes chains --------------
#
# Every other spec either reads a target set out of the image or ADDS a
# chain. This one subtracts, so it is the one that can under-report, and
# these tests are mostly about the guard rather than the arithmetic.

#: A base method that loops over a virtual call to a one-argument
#: overload of ITSELF - the shape that reported recursion on Track A.
#: Slot 1 of the derived class's table is the INHERITED two-argument
#: method, so an unfiltered read hands `Print::write(buf, len)` its own
#: address back.
_NM_INHERITED = """\
0008d2dc 0000002c T vtable for UARTClass
00087001 00000010 T UARTClass::write(unsigned char)
00087011 00000010 T Print::write(unsigned char const*, unsigned int)
"""
_SYMS_INHERITED = {0x87000: "UARTClass::write(unsigned char)",
                   0x87010: "Print::write(unsigned char const*, unsigned int)"}


def _inherited(monkeypatch):
    monkeypatch.setattr(sd, "_run", lambda argv: _NM_INHERITED)
    monkeypatch.setattr(sd, "_read_words",
                        lambda elf, base, size: [0, 0, 0x87001, 0x87011])


def test_an_unfiltered_vtable_read_manufactures_the_cycle(monkeypatch,
                                                          tmp_path):
    """The defect, pinned from both sides in one test.

    This is the break-on-purpose that CLAUDE.md asks for, kept rather
    than thrown away: remove the filter and the walk must refuse, put it
    back and it must bound. A test of only the filtered case would pass
    just as happily if the filter were ignored.
    """
    _inherited(monkeypatch)
    build = _ci(tmp_path, "t", [
        _node("Print::write(unsigned char const*, unsigned int)",
              "Print::write(unsigned char const*, unsigned int)",
              "Print.cpp:34:1", 16),
        _node("UARTClass::write(unsigned char)",
              "UARTClass::write(unsigned char)", "UARTClass.cpp:1:1", 8),
        _edge("Print::write(unsigned char const*, unsigned int)",
              "__indirect_call", "Print.cpp:38:14"),
    ])
    g, _ = sd.parse([build])
    frames = dict(g.frame)
    src = "Print::write(unsigned char const*, unsigned int)"

    def resolved(spec):
        cls, method = sd.parse_vtable_spec(spec)
        got, _unknown = sd.vtable_targets("x.elf", cls, _SYMS_INHERITED,
                                          method)
        return {src: set(got)}, {t: [t] for t in got}

    by_src, title_of = resolved("vtable:UARTClass")
    assert sd.find_cycle(g, frames, by_src, title_of), (
        "without the filter the inherited slot is a self-edge; if this "
        "stops firing the fixture no longer reproduces the defect")

    by_src, title_of = resolved("vtable:UARTClass/write/1")
    assert sd.find_cycle(g, frames, by_src, title_of) is None
    total, chain = sd.deepest(g, src, frames, by_src, title_of)
    assert total == 16 + 8
    assert [g.name[t] for t in chain] == [
        src, "UARTClass::write(unsigned char)"]


def test_a_filter_matching_no_slot_is_refused_not_resolved_to_nothing(
        monkeypatch):
    """The whole reason this rung is safe to have.

    A misspelt method and a method with no override are the same empty
    set from in here, and the empty set would subtract every chain below
    the call with nothing printed. So it refuses - and it names the
    slots the table does hold, because that is what tells the reader
    which of the two it was.
    """
    _inherited(monkeypatch)
    for spec, why in (("vtable:UARTClass/wirte/1", "a misspelt name"),
                      ("vtable:UARTClass/write/3", "a wrong arity")):
        cls, method = sd.parse_vtable_spec(spec)
        with pytest.raises(LookupError) as exc:
            sd.vtable_targets("x.elf", cls, _SYMS_INHERITED, method)
        assert "write/1" in str(exc.value), (
            f"{why} must name the slots that ARE there: {exc.value}")


def test_the_spec_parser_reads_every_form_and_rejects_a_half_written_one():
    """A declaration the tool half-understood is worse than none, so a
    malformed spec is a hard stop rather than a looser reading of it."""
    assert sd.parse_vtable_spec("vtable") == (None, None)
    assert sd.parse_vtable_spec("vtable:Serial_") == ("Serial_", None)
    assert sd.parse_vtable_spec("vtable/write/1") == (None, ("write", 1))
    assert sd.parse_vtable_spec("vtable:Serial_/accept/0") == ("Serial_",
                                                               ("accept", 0))
    for bad in ("vtable:Serial_/accept",      # no arity
                "vtable/write/two",           # arity not a number
                "vtable/write/1/2",           # too many fields
                "vtable/",                    # nothing after the slash
                "vtable:/write/1"):           # nothing before it
        with pytest.raises(ValueError):
            sd.parse_vtable_spec(bad)


# --- refusal is per root ---------------------------------------------------
#
# One undeclared site used to take every bound with it, including the
# bounds of roots whose subgraphs had nothing wrong with them. These
# check both halves: that a clean root still gets its number, and that a
# dirty one still gets none.

def _fake_elf(monkeypatch, names, vectors=()):
    """Enough of a linked image for main() to run with no toolchain.

    Only the four readers main() calls, and each returns the least that
    makes the path under test reachable: the name set so nothing is
    dropped as discarded by the linker, and the vector table so the
    nesting total has something to be made of.
    """
    present = set(names) | {sd._name_key(n) for n in names}
    monkeypatch.setattr(sd, "image_names", lambda elf: present)
    monkeypatch.setattr(sd, "symbol_extents", lambda elf: {})
    monkeypatch.setattr(sd, "symbols", lambda elf: {})
    monkeypatch.setattr(sd, "leaf_frame",
                        lambda elf, sym, extents=None: None)
    monkeypatch.setattr(sd, "table_targets",
                        lambda elf, table, syms: (list(vectors), []))


def test_a_clean_root_keeps_its_bound_while_a_dirty_one_is_refused(
        tmp_path, monkeypatch, capsys):
    """The positive control for per-root refusal, both halves in one test.

    A test of only the refusal would pass just as happily if refusal were
    still global, and a test of only the bound would pass if refusal had
    been dropped altogether.
    """
    build = _ci(tmp_path, "t", [
        _node("dirty_root", "dirty_root", "t.c:1:1", 8),
        _node("t.c:deep", "deep", "t.c:2:1", 800),
        _node("clean_root", "clean_root", "t.c:3:1", 40),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("dirty_root", "t.c:deep", "t.c:10:1"),
        _edge("t.c:deep", sd.INDIRECT, "t.c:11:3"),
    ])
    _fake_elf(monkeypatch, ["dirty_root", "deep", "clean_root"])
    rc = sd.main([build, "--elf", "fake.elf"])
    out = capsys.readouterr().out
    assert rc == 3, "a refused root must not let the run exit 0"
    assert "40  clean_root" in out.replace("     ", "  "), out
    assert "dirty_root" in out and "no --indirect declaration" in out
    # And the refused root must carry NO number anywhere.
    assert "808" not in out, "a refused root was given a figure anyway"


def test_a_refused_thread_root_refuses_the_nesting_total(
        tmp_path, monkeypatch, capsys):
    """The defect per-root refusal INTRODUCED, pinned so it cannot return.

    The nesting total's thread term is the deepest root that is not a
    vector handler, taken from the bounded rows. So the moment refusal
    became per root, a refused Reset_Handler fell out of those rows and
    the term dropped to whatever shallow root was left - and the total
    came out 716 B "exact" on Track A against a true figure of at least
    1516. It was caught by reading the output, not by a test, which is
    why there is one now.
    """
    build = _ci(tmp_path, "t", [
        _node("Reset_Handler", "Reset_Handler", "t.c:1:1", 8),
        _node("t.c:deep", "deep", "t.c:2:1", 800),
        _node("shallow_root", "shallow_root", "t.c:3:1", 40),
        _node("ADC_Handler", "ADC_Handler", "t.c:4:1", 16),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("Reset_Handler", "t.c:deep", "t.c:10:1"),
        _edge("t.c:deep", sd.INDIRECT, "t.c:11:3"),
    ])
    _fake_elf(monkeypatch,
              ["Reset_Handler", "deep", "shallow_root", "ADC_Handler"],
              vectors=["ADC_Handler", "Reset_Handler"])
    rc = sd.main([build, "--elf", "fake.elf", "--isr", "ADC_Handler=0"])
    out = capsys.readouterr().out
    assert rc == 3
    assert "NOT COMPUTED" in out, out
    # The wrong answer, spelled out: 40 B of the shallow root that was
    # left, plus one frame and the ADC handler's 16.
    assert str(40 + sd.EXC_FRAME + 16) not in out, (
        "the total was computed from the deepest root that happened to "
        "survive, which is exactly the under-report")


def test_the_diagram_refuses_when_any_root_does(tmp_path, monkeypatch):
    """All-or-nothing where the table is per root, and for a reason a
    table does not have: a picture of the deepest chain has nowhere
    inside it to say that four other roots were never walked."""
    build = _ci(tmp_path, "t", [
        _node("dirty_root", "dirty_root", "t.c:1:1", 8),
        _node("clean_root", "clean_root", "t.c:3:1", 40),
        _node(sd.INDIRECT, "Indirect Call Placeholder", "", shape="ellipse"),
        _edge("dirty_root", sd.INDIRECT, "t.c:11:3"),
    ])
    _fake_elf(monkeypatch, ["dirty_root", "clean_root"])
    assert sd.main([build, "--elf", "fake.elf", "--mermaid"]) == 3


def test_a_stale_edge_declaration_is_a_hard_stop(tmp_path, monkeypatch):
    """Not a refusal. An `edge` line names two symbols in this tree; if
    either is gone the claim is stale and wants re-reading, exactly as a
    stale --isr does. A refusal would leave it in the tracked list
    reading as though it still covered something."""
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
    ])
    _fake_elf(monkeypatch, ["main"])
    assert sd.main([build, "--elf", "fake.elf",
                    "--edge", "main=gone_from_the_tree"]) == 2


# --- interrupt nesting -----------------------------------------------------
#
# The per-root table is not a worst case, and these are about the
# arithmetic that makes it one. The dangerous answer here is the deepest
# SINGLE handler, which is smaller than the truth.

def test_a_frame_is_charged_per_LEVEL_and_not_per_handler():
    """The positive control, small enough to add by hand.

    Two handlers share a level and one sits above them. The hardware will
    not preempt on equal priority, so the shared level contributes one
    frame and its deeper member - not two frames and both.
    """
    chains = {"ADC": 40, "SysTick": 8, "TC2": 200}
    levels = {"ADC": 0, "SysTick": 0, "TC2": 3}
    total, rows = sd.nest_total(900, chains, levels)
    assert total == 900 + (sd.EXC_FRAME + 40) + (sd.EXC_FRAME + 200)
    assert [(r[0], r[2]) for r in rows] == [(0, ["ADC", "SysTick"]),
                                            (3, ["TC2"])]
    # And the wrong answer this exists to refuse: the deepest single ISR.
    assert total > 900 + sd.EXC_FRAME + 200


def test_an_undeclared_handler_nests_on_its_own():
    """A missing level is read as "this might nest with anything", which
    is the sound direction. It is the one declaration in this file whose
    absence costs a ceiling rather than a refusal, so the ceiling has to
    actually be larger than the declared answer."""
    chains = {"A": 40, "B": 8}
    declared, _ = sd.nest_total(0, chains, {"A": 0, "B": 0})
    ceiling, rows = sd.nest_total(0, chains, {"A": None, "B": None})
    assert declared == sd.EXC_FRAME + 40
    assert ceiling == 2 * sd.EXC_FRAME + 48 > declared
    assert [r[0] for r in rows] == [None, None], "each gets a level of its own"


def test_a_handler_claimed_off_is_charged_nothing():
    """`off` is a claim that REMOVES a chain, so it has to be visible in
    the arithmetic: a handler left out of `levels` contributes neither a
    frame nor a chain."""
    total, rows = sd.nest_total(100, {"A": 40, "UOTGHS": 500}, {"A": 0})
    assert total == 100 + sd.EXC_FRAME + 40
    assert all("UOTGHS" not in r[2] for r in rows)


def test_the_exception_frame_is_the_architecture_not_a_guess():
    """Eight words of hardware frame plus a word of STKALIGN padding.

    Pinned because it is the whole term a per-root table omits, and
    because a reader who sees 32 has to be able to tell a wrong constant
    from a deliberate one."""
    assert sd.EXC_FRAME == 4 * 8 + 4


def test_the_boot_entry_is_not_charged_as_an_interrupt(monkeypatch):
    """Vector 1 is Reset_Handler. Nothing preempts anything to reach it,
    so charging it a frame would double-count the thread chain it
    starts."""
    monkeypatch.setattr(sd, "table_targets",
                        lambda elf, table, syms: (["ADC_Handler",
                                                   "Reset_Handler"], []))
    assert sd.vector_handlers("x.elf", {}) == ["ADC_Handler"]


def test_a_declared_edge_joins_a_chain_the_compiler_could_not_see(tmp_path):
    """HardFault_Handler is naked asm ending in `b hard_fault_report`, so
    no .ci records the call. Without the edge the fault path is a
    spurious root AND the vector contributes a chain of zero - wrong
    twice, both times downward."""
    build = _ci(tmp_path, "t", [
        _node("HardFault_Handler", "HardFault_Handler", "fault.c:81:1", 0),
        _node("t.c:hard_fault_report", "hard_fault_report", "fault.c:20:1",
              56),
    ])
    g, _ = sd.parse([build])
    frames = dict(g.frame)
    assert sd.deepest(g, "HardFault_Handler", frames, {}, {})[0] == 0
    g.edges.setdefault("HardFault_Handler", set()).add("t.c:hard_fault_report")
    assert sd.deepest(g, "HardFault_Handler", frames, {}, {})[0] == 56


def test_the_name_of_an_aliased_address_is_the_strong_definition(monkeypatch):
    """One address, many names, and the choice is not nm's to make.

    `Default_Handler` shares its address with 40-odd weak aliases, one per
    unused vector. Reading them in file order made the reported name
    depend on how a bench's binutils sorted a tie - the defect CLAUDE.md
    records against a `layout` hash, one tool over.
    """
    dump = ("00080c2c W BusFault_Handler\n"
            "00080c2c W CAN0_Handler\n"
            "00080c2c t Default_Handler\n"
            "00080c2c W WDT_Handler\n")
    monkeypatch.setattr(sd, "_run", lambda argv: dump)
    assert sd.symbols("x.elf") == {0x80c2c: "Default_Handler"}

    # Reversed input, same answer. A test on one order proves nothing.
    monkeypatch.setattr(sd, "_run",
                        lambda argv: "\n".join(reversed(dump.splitlines())))
    assert sd.symbols("x.elf") == {0x80c2c: "Default_Handler"}


# --- what the linker threw away --------------------------------------------

def test_a_clone_suffix_is_not_mistaken_for_a_missing_function():
    """The regression that a control caught, pinned so it cannot return.

    GCC writes `ctl_dispatch.constprop` in the call graph and
    `ctl_dispatch.constprop.0` in the symbol table. Testing presence by
    exact match therefore calls a live function discarded, and the bound
    silently falls - Track B went 916 to 708 the first time this ran.

    An under-report is the one direction that matters, so presence is
    tested permissively: a false "absent" is a wrong answer, a false
    "present" is only an edge left to resolve.
    """
    present = {"ctl_dispatch.constprop.0", "main", "watchdogSetup()"}
    assert sd.survives_link("ctl_dispatch.constprop", present)
    assert sd.survives_link("main", present)
    assert sd.survives_link("void watchdogSetup()", present), (
        "the call graph writes a return type the symbol table does not")
    assert not sd.survives_link("malloc", present)


def test_the_demangled_key_drops_the_return_type():
    """A C++ track is unreadable without this, and issue #45 hit the same
    wall doing dead-function analysis here."""
    assert sd._name_key("void watchdogSetup()") == "watchdogSetup"
    assert sd._name_key("int CDC_GetInterface(uint8_t*)") == "CDC_GetInterface"
    assert sd._name_key("RingBuffer::RingBuffer()") == "RingBuffer::RingBuffer"
    assert sd._name_key("memcpy") == "memcpy"


def test_a_discarded_target_is_not_a_chain(tmp_path, capsys):
    """The call graph is pre-link and the image is post-GC.

    GCC records what each unit called; --gc-sections then discards what
    nothing reaches. A function absent from the image cannot execute, so
    it contributes no depth - but the drop is REPORTED, because a graph
    that quietly shrank is what this tool refuses to be.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 24),
        _node("malloc", "malloc", "stdlib.h:1:1", shape="ellipse"),
        _edge("main", "malloc", "t.c:9:3"),
    ])
    g, _ = sd.parse([build])
    assert "malloc" in g.externals
    # With no ELF there is nothing to prune against, so it must refuse
    # rather than assume the function is absent.
    assert sd.main([build]) == 3


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
    for track in ("a", "b", "c"):
        got = sd.read_declarations(sd.DECLARATIONS, track)
        assert got, f"track {track} declares nothing"
        # The console lives in shared source, so all three tracks compile
        # the same two sites and all three must resolve the dispatch
        # EXACTLY - by reading the table out of the image, never by
        # asserting something about it.
        by_key = dict((k, v) for _kind, k, v in got)
        assert by_key.get("console.c:260") == "console_bindings", (
            f"track {track}: the console dispatch must resolve exactly")
        assert by_key.get("console_cmds.c:44") == "noreturn"

        # bsp/fault.c is shared, so every track needs the naked branch
        # declared or its fault path is a spurious root with the whole
        # chain under it and the vector charged nothing.
        edges = [(k, v) for kind, k, v in got if kind == "edge"]
        assert ("HardFault_Handler", "hard_fault_report") in edges, (
            f"track {track}: the naked fault branch must be declared")

        # And every track must account for its interrupts. An empty `isr`
        # set is not a refusal - it is a ceiling - so nothing else here
        # would notice the whole block being deleted.
        isrs = dict((k, v) for kind, k, v in got if kind == "isr")
        assert isrs.get("HardFault_Handler") == "-1", (
            f"track {track}: HardFault's level is architectural")
        for want in ("ADC_Handler", "DACC_Handler", "TC2_Handler"):
            assert want in isrs, f"track {track}: {want} has no level"
        assert (isrs["ADC_Handler"], isrs["DACC_Handler"],
                isrs["TC2_Handler"]) == ("0", "1", "3"), (
            f"track {track}: the three levels this project sets itself are "
            "the same on every track by design, so a divergence here is a "
            "firmware change and not a declaration to update")


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


def test_an_alias_does_not_shadow_a_cxx_handler_of_the_same_name(
        tmp_path, monkeypatch, capsys):
    """The under-report xPack 15.2.1 exposed and Debian 14.2.1 hid.

    A vector-table entry is a LINKER symbol - `TC2_Handler` - and the
    indexes it is looked up in are keyed on `.ci` LABELS. A C++ handler's
    label carries its return type, `void TC2_Handler()`, so the bare
    symbol misses it; the core's weak definition of the same vector is
    labelled with the bare name and hits exactly. Take the most specific
    tier and the alias wins, the walk follows its edge to `__halt`, and
    the handler is charged ZERO - while the per-root table on the same
    page prints its real chain.

    Only the alias half is compiler-dependent, which is what made this
    quiet: Debian 14.2.1 emits no alias node, so the lookup falls through
    to the bare-name tier and finds the real body. Measured on Track A as
    196 B missing from the worst case, TC2 and DACC both.
    """
    build = _ci(tmp_path, "t", [
        _node("main", "main", "t.c:1:1", 100),
        # The real handler: C++, so its label is a signature.
        _node("TC2_Handler", "void TC2_Handler()", "t.cpp:378:17", 64),
        _node("t.cpp:emit", "emit", "t.cpp:9:1", 120),
        _edge("TC2_Handler", "t.cpp:emit", "t.cpp:381:24"),
        # The core's weak definition of the same vector, labelled bare.
        # It calls __halt rather than aliasing Default_Handler, so
        # following it is a dead end rather than a detour.
        _node("core.c:TC2_Handler", "TC2_Handler", "sam3x8e.h:229:6",
              shape="triangle"),
        _node("core.c:__halt", "__halt", "core.c:5:1", 0),
        _edge("core.c:TC2_Handler", "core.c:__halt", "sam3x8e.h:229:6"),
    ])
    _fake_elf(monkeypatch, ["main", "TC2_Handler", "emit", "__halt"],
              vectors=["TC2_Handler"])
    rc = sd.main([build, "--elf", "fake.elf"])
    out = capsys.readouterr().out
    assert rc == 0, out
    # 100 thread + 36 exception frame + 184 handler chain.
    assert "Worst case on one stack: 320 B" in out, out
    # And the handler is not ALSO counted as a thread root: its title is
    # a handler title whichever label the lookup arrived by.
    assert "184  thread mode" not in out, out
