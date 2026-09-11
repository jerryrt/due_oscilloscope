#!/usr/bin/env python3
"""Worst-case stack depth along the deepest reachable call chain.

    cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
          -DCMAKE_BUILD_TYPE=Release -DFIRMWARE_CALLGRAPH=ON
    cmake --build build -j
    python3 tools/stack_depth.py build --elf build/baremetal_bringup.elf \
            --indirect console.c:260=console_bindings \
            --indirect console_cmds.c:44=noreturn

and, for the same graph as a picture rather than a bound,

    ... --mermaid > graph.md          # renders in a GitHub issue as-is
    ... --dot | dot -Tsvg > graph.svg # if graphviz is installed

WHAT THIS IS FOR. `tools/stack_frames.py` reports one function's frame and
says so about itself: "It is not a worst-case stack depth: depth is the sum of
the frames along the deepest reachable call chain ... and nothing here walks
the call graph." This walks it. The two answer different questions and neither
replaces the other - a census finds an unbounded frame, a depth bound finds a
chain that does not fit.

Invariant 7 asks for a bounded worst case in every ISR and every main-loop
pass. This is the arithmetic half of that check.

IT REFUSES RATHER THAN GUESSES, and that is the whole design. A stack tool
that prints a number when it could not follow an edge is the guard that cannot
fail: the report is green, the property is unwatched, and nobody looks again.
So every answer carries one of three states.

    exact        every edge on the chain was resolved
    upper bound  some edge was over-approximated, and the report says which
    unresolved   an edge could not be followed at all - NO NUMBER IS PRINTED

GCC makes the third state possible by being explicit. An indirect call is not
dropped from the graph; it becomes an edge to a `__indirect_call` placeholder
node carrying the source location, so an unfollowable edge is a loud unknown
rather than a silent subtraction.

THREE KINDS OF EDGE HAVE TO BE RESOLVED, and each has its own rung.

`__indirect_call` - a call through a function pointer. `--table SYM` names a
dispatch table; its entries are read out of the linked ELF's read-only data,
Thumb bit masked, and mapped back through the symbol table, which is exact and
is re-derived from every build rather than being an annotation that can drift.
`vtable:Class` resolves a C++ virtual call, and it is the EASY case
rather than the hard one this tool first assumed. C++ emits the target
set into the binary: a vtable is a named, typed, const array of function
pointers with a fixed layout, which is exactly what a dispatch table is.
A raw function pointer assigned at runtime has no such structure
anywhere - so it is C, not C++, that defeats a static call graph. Bare
`vtable` takes every vtable in the image, which is sound for a virtual
call and tight enough to be useful, and marks the answer a ceiling.

`noreturn` declares a site that does not come back - the deliberate jump to a
bad address that proves the fault handler - and `none` asserts that no target
is ever registered, which is what a FreeRTOS software-timer callback dispatch
needs on a build that creates no timers. Both are CLAIMS, not deductions: they
belong in the invocation where a reader can see them and in the commit that
adds them.

THERE IS NO "just over-approximate it" OPTION, and that is the result of
building one and measuring it. The obvious sound fallback is the address-taken
set - every function whose address appears anywhere in the image - and it does
not survive contact with a linked Cortex-M binary: read-only data lives in
`.text`, `nm` types it `t`, and a USB descriptor whose bytes happen to look
like a Thumb address is indistinguishable from a function pointer. The scan
returned `desc_device` and a compiler-generated switch table alongside the real
handlers. An over-approximation that cannot tell code from descriptors is not
a ceiling, it is a guess with a ceiling's manners, so the rung was removed
rather than shipped.

A library leaf - `memcpy`, `memset`, `__aeabi_uldivmod` and friends have no
`.ci` because they are not compiled here. Their frames are read out of the
linked image by prologue analysis; `--leaf SYM=BYTES` declares one the
disassembly will not yield, and the declaration is expected to say in the
commit how it was measured.

A weak alias - `shape : triangle`, one per unused interrupt vector, aliasing
`Default_Handler`. It has no byte count but is not external, and the two
compilers disagree about whether to emit it at all: xPack 15.2.1 writes 49 of
them for this firmware and Debian 14.2.1 writes none. Frame zero, and the edge
already in the graph carries the walk to the real handler.

A cross-translation-unit call - not a problem, but worth knowing why. A
function defined elsewhere appears in the caller's `.ci` as a frameless
placeholder AND as a real node in the `.ci` of the unit that defines it. The
framed one wins. Statics carry their defining path in the node title, so two
files' `static void helper()` are two different nodes and are never merged.

RECURSION IS A FAILURE, not a large number. A cycle in the call graph has no
worst-case depth, and invariant 7 forbids it on the working path, so a cycle
is reported and the tool exits non-zero.

Stdlib only, like the rest of the build-side tooling here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

#: `node: { title: "T" label: "name\nfile:line:col\nN bytes (qual)\nM dynamic
#: objects" }`. The byte count is absent for a function with no `.ci` of its
#: own, and THAT is the discriminator for "external", not the absence of a
#: node - GCC emits a node for an extern too. A check keyed on the node
#: existing reports zero externals and cannot fail; this one was written that
#: way first and corrected after a planted call to an undefined function
#: failed to move it.
_NODE = re.compile(r'^node: \{ title: "(?P<title>.*?)" label: "(?P<label>.*?)"'
                   r'(?P<rest>.*)$')
_EDGE = re.compile(r'^edge: \{ sourcename: "(?P<src>.*?)" '
                   r'targetname: "(?P<dst>.*?)" label: "(?P<at>.*?)"')
_FRAME = re.compile(r"\\n(\d+) bytes \((?P<qual>[^)]*)\)")

INDIRECT = "__indirect_call"


#: The tracked claims. Read by default so the canonical invocation is
#: short and the declarations are reviewable, rather than living in
#: whoever-ran-it-last's shell history.
DECLARATIONS = os.path.join(os.path.dirname(HERE), "tools", "stack_depth.list")


def read_declarations(path, track):
    """[(kind, key, value)] for `track`, from the tracked list.

    Missing file is not an error: a bench analysing a tree without one
    can still pass every declaration on the command line. A file that
    exists and cannot be parsed IS an error, because a silently skipped
    line is a claim nobody made being treated as one nobody needed.
    """
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 4:
                raise ValueError(f"{path}:{n}: want "
                                 f"'<track> <kind> <key> <value>', got {line!r}")
            trk, kind, key, value = parts
            if kind not in ("indirect", "leaf"):
                raise ValueError(f"{path}:{n}: unknown kind {kind!r}")
            if trk == track:
                out.append((kind, key, value))
    return out


def _short(path):
    """The source path relative to the working directory where that is
    shorter. GCC writes whatever path it was handed, which under CMake is
    absolute and pushes the useful column off the terminal."""
    try:
        rel = os.path.relpath(path)
    except ValueError:                      # different drive on Windows
        return path
    return rel if len(rel) < len(path) else path


def _tool(name):
    """Absolute path to an arm-none-eabi binutil, or the bare name.

    Through tools/toolchain.py, never PATH: on a bench with a host binutils of
    the wrong architecture the bare name resolves to something that will read
    the file and answer about a different machine.
    """
    try:
        import toolchain
        directory = toolchain.arm_toolchain_dir()
    except Exception:                                        # noqa: BLE001
        directory = None
    if directory:
        for suffix in ("", ".exe"):
            candidate = os.path.join(directory, name + suffix)
            if os.path.exists(candidate):
                return candidate
    return name


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True,
                          check=True).stdout


class Graph:
    """Nodes keyed by `.ci` title, with frames where the compiler emitted one."""

    def __init__(self):
        self.frame = {}       # title -> bytes
        self.qual = {}        # title -> "static" / "dynamic" / ...
        self.name = {}        # title -> plain symbol name
        self.where = {}       # title -> "file:line"
        self.edges = {}       # title -> set of target titles
        self.sites = {}       # (src, dst) -> [source locations of the calls]

    def add_node(self, title, label, rest=""):
        pretty = label.split("\\n")[0]
        self.name.setdefault(title, pretty)
        parts = label.split("\\n")
        if len(parts) > 1 and ":" in parts[1]:
            self.where.setdefault(title, _short(parts[1]))
        if "shape : triangle" in rest:
            # A WEAK ALIAS, NOT AN EXTERNAL, and the distinction is load
            # bearing. xPack 15.2.1 emits one of these per weak interrupt
            # vector - 49 of them in bsp/startup_sam3x8e.c, each with a single
            # edge to Default_Handler - where Debian 14.2.1 emits none at all.
            # They carry no byte count, so a tool that keys only on "no frame"
            # calls all 49 unresolved and refuses to report anything on the
            # container while working fine on the bench.
            #
            # The alias costs no frame of its own: it IS the target, at the
            # same address. Zero here, and the edge already in the graph
            # carries the walk on to the real handler and its frame.
            self.frame.setdefault(title, 0)
            self.qual.setdefault(title, "alias")
            return
        m = _FRAME.search("\\n" + label)
        if m:
            # A framed node wins over any frameless placeholder for the same
            # title: the defining unit knows the frame, the caller's unit does
            # not. Identical titles across units are the same function.
            size = int(m.group(1))
            if self.frame.get(title, -1) < size:
                self.frame[title] = size
                self.qual[title] = m.group("qual")

    def add_edge(self, src, dst, at):
        self.edges.setdefault(src, set()).add(dst)
        self.sites.setdefault((src, dst), []).append(_short(at))

    @property
    def externals(self):
        """Titles that are called but carry no frame - library or asm."""
        called = {d for ds in self.edges.values() for d in ds}
        called |= set(self.edges)
        return sorted(t for t in called
                      if t not in self.frame and t != INDIRECT)


def parse(roots):
    """Every .ci under `roots` into one Graph."""
    g = Graph()
    seen = 0
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                if not name.endswith(".ci"):
                    continue
                seen += 1
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for raw in fh:
                        m = _NODE.match(raw)
                        if m:
                            g.add_node(m.group("title"), m.group("label"),
                                       m.group("rest"))
                            continue
                        m = _EDGE.match(raw)
                        if m:
                            g.add_edge(m.group("src"), m.group("dst"),
                                       m.group("at"))
    return g, seen


# --- resolving what the .ci files cannot say -------------------------------

def _name_key(label):
    """A comparable name from either a .ci label or `nm -C` output.

    GCC writes a DEMANGLED SIGNATURE WITH ITS RETURN TYPE into the call
    graph - `void watchdogSetup()`, `int CDC_GetInterface(uint8_t*)` -
    while `nm -C` writes the signature without one. Neither matches the
    mangled symbol `objdump --disassemble=` wants. Reducing both sides to
    the qualified name is what lets a C++ track be looked up at all.

    Issue #45 hit the same wall doing dead-function analysis here and
    reported live functions as dead. A plain-name match against C++ is
    wrong in both directions; this is the same fix, one tool over.
    """
    head = label.split("(")[0].strip()
    return head.split()[-1] if head else head


def mangled_index(elf):
    """{demangled key: mangled symbol} for every defined function.

    `objdump --disassemble=` matches the MANGLED name, the call graph
    writes a demangled signature, and `nm -C` writes a third spelling
    with no return type. Paired BY ADDRESS rather than by line order,
    because the two nm runs are only guaranteed to agree on what is at
    each address, not on how they sorted it.
    """
    def table(flags):
        out = {}
        for ln in _run([_tool("arm-none-eabi-nm"), *flags, "--defined-only",
                        elf]).splitlines():
            parts = ln.split(None, 2)
            if len(parts) >= 3 and parts[1] in ("t", "T", "w", "W"):
                out[int(parts[0], 16)] = parts[2].strip()
        return out

    try:
        plain, demangled = table([]), table(["-C"])
    except subprocess.CalledProcessError:
        return {}
    idx = {}
    for addr, mangled in plain.items():
        pretty = demangled.get(addr)
        if pretty:
            idx.setdefault(_name_key(pretty), mangled)
        idx.setdefault(mangled, mangled)
    return idx


def survives_link(name, present):
    """Is `name` still in the linked image?

    PERMISSIVE ON PURPOSE, and the asymmetry is the whole design. A false
    "absent" drops a live function and under-reports the bound; a false
    "present" only leaves an edge to resolve, which at worst refuses. One
    of those is a wrong answer and the other is no answer.

    So three spellings are tried: the name as the call graph writes it,
    the demangled key, and the name with GCC's clone suffix removed -
    `ctl_dispatch.constprop` in the graph is `ctl_dispatch.constprop.0`
    in the symbol table. An exact match alone took Track B's bound from
    916 to 708 the first time this ran, and only the control caught it.
    """
    # BOTH SIDES ARE NORMALISED, not just this one. Relying on the
    # caller to have keyed `present` already couples two functions
    # silently, and the coupling is invisible until someone builds the
    # set another way - at which point a live function reads as absent
    # and the bound falls without a word.
    keys = set(present) | {_name_key(n) for n in present}
    bases = {n.split(".", 1)[0] for n in keys}
    for form in (name, _name_key(name)):
        if form in keys or form.split(".", 1)[0] in bases:
            return True
    return False


def image_names(elf):
    """Every function name the LINKED image actually contains.

    Both spellings, because callers arrive with either: the mangled
    symbol and the demangled one reduced by _name_key().
    """
    out = set()
    for flag in ((), ("-C",)):
        try:
            dump = _run([_tool("arm-none-eabi-nm"), *flag, "--defined-only",
                         elf])
        except subprocess.CalledProcessError:
            continue
        for ln in dump.splitlines():
            parts = ln.split(None, 2)
            if len(parts) >= 3 and parts[1] in ("t", "T", "w", "W"):
                out.add(parts[2].strip())
                out.add(_name_key(parts[2]))
    return out


def symbols(elf):
    """{address without the Thumb bit: name} for defined .text symbols.

    DEMANGLED, so that what comes out of a table or a vtable is in the
    same vocabulary the call graph writes. `nm` gives
    `_ZN9UARTClass5writeEh` where the graph says
    `UARTClass::write(unsigned char)`, and a target that cannot be
    matched to a node is refused - so reading a vtable in the mangled
    vocabulary refuses on every slot it resolves, which is the worst of
    both. For C the two spellings are the same and nothing changes.
    """
    out = {}
    for ln in _run([_tool("arm-none-eabi-nm"), "-nC", "--defined-only",
                    elf]).splitlines():
        parts = ln.split(None, 2)
        if len(parts) >= 3 and parts[1] in ("t", "T", "w", "W"):
            out.setdefault(int(parts[0], 16) & ~1, parts[2].strip())
    return out


def table_targets(elf, table, syms):
    """The functions a `const` dispatch table points at.

    Exact: the array is in the image, so its contents ARE the target set. Read
    the bytes, mask the Thumb bit, look the address up. Nothing is inferred
    from the C, and nothing can go stale between the source and the build.
    """
    base = size = None
    for ln in _run([_tool("arm-none-eabi-nm"), "-S", elf]).splitlines():
        parts = ln.split()
        if len(parts) >= 4 and parts[-1] == table:
            base, size = int(parts[0], 16), int(parts[1], 16)
    if base is None:
        raise LookupError(f"no symbol {table!r} in {elf}")

    found, unknown = set(), []
    for word in _read_words(elf, base, size):
        if word & 1 and (word & ~1) in syms:      # a Thumb code address
            found.add(syms[word & ~1])
    return sorted(found), unknown


def _read_words(elf, base, size):
    """The bytes of a const array in the image, as 32-bit little-endian
    words. One place, because a vtable and a dispatch table are the same
    thing to a reader: an array of function pointers the linker laid
    down."""
    dump = _run([_tool("arm-none-eabi-objdump"), "-s",
                 f"--start-address={base}", f"--stop-address={base + size}",
                 elf])
    raw = bytearray()
    for ln in dump.splitlines():
        m = re.match(r"\s+([0-9a-f]+)\s((?:[0-9a-f]{2,8}\s){1,4})", ln)
        if m:
            raw += bytes.fromhex(m.group(2).replace(" ", ""))
    return [int.from_bytes(raw[i:i + 4], "little")
            for i in range(0, len(raw) - 3, 4)]


def vtables(elf):
    """{class name: (address, size)} for every vtable in the image.

    Located by the DEMANGLED symbol - `nm -C` writes "vtable for
    UARTClass" - rather than by rebuilding `_ZTV9UARTClass` from the
    class name. Reconstructing the mangling works for a plain class and
    stops working the moment one is namespaced or templated, and a
    lookup that silently finds nothing would read as "this class has no
    virtual methods".
    """
    out = {}
    for ln in _run([_tool("arm-none-eabi-nm"), "-SC", "--defined-only",
                    elf]).splitlines():
        parts = ln.split(None, 3)
        if len(parts) == 4 and parts[3].startswith("vtable for "):
            out[parts[3][len("vtable for "):].strip()] = (int(parts[0], 16),
                                                          int(parts[1], 16))
    return out


def vtable_targets(elf, cls, syms):
    """The virtual methods `cls` dispatches to, read out of its vtable.

    A VIRTUAL CALL IS THE EASY CASE, which is the opposite of what this
    tool assumed at first. C++ emits the target set into the binary: a
    vtable is a named, typed, const array of function pointers with a
    fixed layout, which is exactly the shape a dispatch table is. A raw
    function pointer assigned at runtime has no such structure anywhere,
    so it is C - not C++ - that defeats this analysis.

    The first two slots of an Itanium-ABI vtable are the offset-to-top
    and the typeinfo pointer. Neither is a code address, so neither
    survives the Thumb-bit-and-known-symbol filter every table read here
    goes through; nothing special is done about them.

    `cls` of None means every vtable in the image, which is a SOUND
    over-approximation for a virtual call whose static type the call
    graph does not record: a virtual call reaches a virtual method, and
    every virtual method of an instantiated class is in one of these.
    Tight, too - this firmware has four.
    """
    found, missing = set(), []
    tabs = vtables(elf)
    names = list(tabs) if cls is None else [cls]
    for name in names:
        if name not in tabs:
            missing.append(name)
            continue
        base, size = tabs[name]
        for word in _read_words(elf, base, size):
            if word & 1 and (word & ~1) in syms:
                found.add(syms[word & ~1])
    if missing:
        raise LookupError("no vtable for " + ", ".join(missing)
                          + " in " + os.path.basename(elf)
                          + "; the image has: " + ", ".join(sorted(tabs)))
    return sorted(found), []


#: `push {r4, r5, lr}` is 4 bytes per register; `sub sp, #N` is N. Only the
#: prologue is read, so this is right for a leaf and an underestimate for
#: anything that adjusts sp later - which is why a symbol whose prologue does
#: not parse is left UNRESOLVED rather than assumed to be zero.
_PUSH = re.compile(r"\bpush\s+\{([^}]*)\}")
_SUBSP = re.compile(r"\bsub\s+sp,\s*(?:sp,\s*)?#(\d+)")


def symbol_extents(elf):
    """{name: (address, size)} for defined functions, under every spelling.

    Address and size rather than name alone, because that is what lets a
    prologue be read for a symbol `objdump --disassemble=` will not
    print. It declines on small weak stubs - `watchdogSetup` is 4 bytes
    and `svcHook` is 2 - emitting section headers and no instructions, so
    a name-based read calls them unreadable and the tool refuses on two
    functions that plainly have no frame.
    """
    out = {}
    for flags in ([], ["-C"]):
        try:
            dump = _run([_tool("arm-none-eabi-nm"), "-S", *flags,
                         "--defined-only", elf])
        except subprocess.CalledProcessError:
            continue
        for ln in dump.splitlines():
            parts = ln.split(None, 3)
            if len(parts) == 4 and parts[2] in ("t", "T", "w", "W"):
                try:
                    addr, size = int(parts[0], 16), int(parts[1], 16)
                except ValueError:
                    continue
                name = parts[3].strip()
                out.setdefault(name, (addr, size))
                out.setdefault(_name_key(name), (addr, size))
    return out


def leaf_frame(elf, sym, extents=None):
    """Bytes `sym`'s prologue reserves, or None if it cannot be read."""
    # GCC names an unexpanded builtin `__builtin_memset` in the call graph
    # while the linker calls the thing `memset`. Looking the prefixed name up
    # finds nothing, which reads as "unreadable prologue" and refuses on a
    # symbol that is sitting right there in the image.
    if sym.startswith("__builtin_"):
        sym = sym[len("__builtin_"):]
    where = None
    if extents:
        where = extents.get(sym) or extents.get(_name_key(sym))
    if where and where[1]:
        addr, size = where
        try:
            dis = _run([_tool("arm-none-eabi-objdump"), "-d",
                        f"--start-address={addr}",
                        f"--stop-address={addr + size}", elf])
        except subprocess.CalledProcessError:
            return None
    else:
        try:
            dis = _run([_tool("arm-none-eabi-objdump"), "-d",
                        f"--disassemble={sym}", elf])
        except subprocess.CalledProcessError:
            return None
    body = [ln for ln in dis.splitlines() if re.match(r"\s+[0-9a-f]+:", ln)]
    if not body:
        return None
    total = 0
    for ln in body[:6]:                      # the prologue, not the function
        m = _PUSH.search(ln)
        if m:
            total += 4 * len([r for r in m.group(1).split(",") if r.strip()])
        m = _SUBSP.search(ln)
        if m:
            total += int(m.group(1))
    return total


# --- the walk --------------------------------------------------------------

def deepest(g, root, frames, indirect_by_src, title_of):
    """(bytes, [chain]) for the deepest chain from `root`.

    Raises RecursionError naming the cycle, and KeyError naming an edge that
    could not be followed. Neither returns a number, deliberately.
    """
    memo = {}
    stack = []

    def walk(title):
        if title in stack:
            cycle = stack[stack.index(title):] + [title]
            raise RecursionError(" -> ".join(g.name.get(t, t) for t in cycle))
        if title in memo:
            return memo[title]
        if title not in frames:
            raise KeyError(title)
        stack.append(title)
        best, chain = 0, []
        for dst in sorted(g.edges.get(title, ())):
            targets = [title_of[t] for t in indirect_by_src.get(title, ())] \
                if dst == INDIRECT else [dst]
            for tgt in targets:
                sub, sub_chain = walk(tgt)
                if sub > best:
                    best, chain = sub, sub_chain
        stack.pop()
        memo[title] = (frames[title] + best, [title] + chain)
        return memo[title]

    return walk(root)


def find_cycle(g, frames, indirect_by_src, title_of):
    """A cycle anywhere in the graph, or None.

    OVER EVERY NODE, not just the ones reachable from a root, and that is not
    thoroughness for its own sake. A graph whose nodes are ALL in cycles has no
    roots at all, so a root-driven walk visits nothing, finds nothing, and
    exits 0 on a report with no rows in it - the empty green run this project
    keeps having to relearn. The first version of this tool did exactly that,
    and its own test caught it.
    """
    colour = {}
    stack = []

    def visit(title):
        state = colour.get(title)
        if state == "done":
            return None
        if state == "open":
            cycle = stack[stack.index(title):] + [title]
            return " -> ".join(g.name.get(t, t) for t in cycle)
        colour[title] = "open"
        stack.append(title)
        for dst in sorted(g.edges.get(title, ())):
            targets = [title_of[t] for t in indirect_by_src.get(title, ())] \
                if dst == INDIRECT else [dst]
            for tgt in targets:
                if tgt not in frames:
                    continue                # refused elsewhere, not here
                found = visit(tgt)
                if found:
                    return found
        stack.pop()
        colour[title] = "done"
        return None

    for title in sorted(frames):
        found = visit(title)
        if found:
            return found
    return None


def cost_below(g, frames, indirect_by_src, title_of):
    """{title: the deepest total from here down, including its own frame}.

    The number a diagram has to be pruned on. Pruning on a function's OWN frame
    would keep every fat leaf and drop the cheap frames that lead to them,
    which is the opposite of what a reader needs: `h_occ` has a 0-byte frame
    and is the only way to reach a 504-byte one.
    """
    below = {}

    def walk(title, seen=()):
        if title in below:
            return below[title]
        if title in seen:
            return 0                       # a cycle is caught elsewhere
        best = 0
        for dst in g.edges.get(title, ()):
            targets = [title_of[t] for t in indirect_by_src.get(title, ())] \
                if dst == INDIRECT else [dst]
            for tgt in targets:
                if tgt in frames:
                    best = max(best, walk(tgt, seen + (title,)))
        below[title] = frames.get(title, 0) + best
        return below[title]

    for title in frames:
        walk(title)
    return below


def _pruned(g, frames, below, floor, indirect_by_src, title_of):
    """(kept titles, [(src, dst)] edges between them)."""
    keep = {t for t in frames if below.get(t, 0) >= floor}
    edges = []
    for src in sorted(keep):
        for dst in sorted(g.edges.get(src, ())):
            targets = [title_of[t] for t in indirect_by_src.get(src, ())] \
                if dst == INDIRECT else [dst]
            for tgt in targets:
                if tgt in keep:
                    edges.append((src, tgt))
    return sorted(keep), edges


def emit_graph(g, frames, below, floor, edges, keep, critical, fmt, deepest_of):
    """The pruned call graph as DOT or Mermaid.

    IT SAYS WHAT IT LEFT OUT. A diagram that quietly drops two thirds of the
    graph is the same failure as a depth that quietly drops an edge - the
    reader cannot tell a small graph from a filtered one, so the node count and
    the threshold are printed as part of the picture, not beside it.
    """
    ids = {t: f"n{i}" for i, t in enumerate(keep)}
    crit = set(zip(critical, critical[1:]))
    note = (f"{len(keep)} of {len(frames)} functions, "
            f"those carrying >= {floor} B; deepest {deepest_of} B")

    if fmt == "dot":
        print("digraph stack {")
        print('  rankdir=LR; node [shape=box, fontname="monospace"];')
        print(f'  label="{note}"; labelloc=b; fontname="monospace";')
        for t in keep:
            heavy = ", penwidth=2" if t in set(critical) else ""
            print(f'  {ids[t]} [label="{g.name.get(t, t)}\\n'
                  f'{frames.get(t, 0)} B  ({below[t]} total)"{heavy}];')
        for src, dst in edges:
            style = " [penwidth=3, color=red]" if (src, dst) in crit else ""
            print(f"  {ids[src]} -> {ids[dst]}{style};")
        print("}")
        return

    print("```mermaid")
    print("graph LR")
    for t in keep:
        print(f'  {ids[t]}["{g.name.get(t, t)}<br/>'
              f'{frames.get(t, 0)} B &middot; {below[t]} total"]')
    for src, dst in edges:
        print(f"  {ids[src]} {'==>' if (src, dst) in crit else '-->'} "
              f"{ids[dst]}")
    for t in set(critical) & set(keep):
        print(f"  style {ids[t]} stroke-width:3px")
    print(f"  %% {note}")
    print("```")


def _record(args, g, frames, rows, state, sites, targets, files,
            indirect_by_src, title_of):
    """The row a report is generated from. Schema version travels with it."""
    import hashlib
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "host"))
    prov, cc = {}, "unknown"
    try:
        import provenance
        prov = provenance.collect()
    except Exception:                                        # noqa: BLE001
        prov = {}
    if args.elf:
        try:
            import image_fingerprint
            cc = image_fingerprint.compiler(args.elf)
        except Exception:                                    # noqa: BLE001
            cc = "unknown"

    # WITH the resolved indirect edges. Computing this on an empty map
    # silently drops the console dispatch and every figure below
    # console_feed comes out too small - which is the under-report this
    # whole tool exists to refuse, arriving through the back door of a
    # convenience argument.
    below = cost_below(g, frames, indirect_by_src, title_of)
    sha = None
    if args.elf and os.path.exists(args.elf):
        with open(args.elf, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()[:16]

    return {
        "schema": "stack-depth/1",
        "tool": "tools/stack_depth.py",
        "track": args.track,
        "state": state,
        "bench": prov.get("bench"),
        "repo_rev": prov.get("repo_rev"),
        "host_os": prov.get("host_os"),
        "taken_at": prov.get("taken_at"),
        "elf": os.path.basename(args.elf) if args.elf else None,
        "elf_sha256": sha,
        "cc": cc,
        "ci_files": files,
        "functions": len(g.frame),
        "indirect_sites": len(sites),
        "indirect_targets": len(targets),
        "declarations": os.path.relpath(args.declarations,
                                        os.path.dirname(HERE))
                        if args.track else None,
        "roots": [{"root": r, "bytes": b,
                   "chain": [{"function": g.name.get(t, t),
                              "frame": frames[t],
                              "below": below.get(t, frames[t])} for t in c]}
                  for b, r, c in rows],
    }


def roots_of(g, named, indirect_by_src, title_of):
    """Explicitly named roots, else every node nothing calls.

    RESOLVED INDIRECT EDGES COUNT AS CALLS. Without that, every one of the 50
    console handlers looks like an entry point, because the edge the graph
    records runs to the `__indirect_call` placeholder and not to the handler -
    so the report grows 50 spurious roots that are really one dispatch away
    from main.
    """
    if named:
        by_name = {}
        for title, plain in g.name.items():
            by_name.setdefault(plain, []).append(title)
        out = []
        for want in named:
            out.extend(by_name.get(want, []))
        return sorted(set(out))
    called = {d for ds in g.edges.values() for d in ds if d != INDIRECT}
    for src, targets in indirect_by_src.items():
        called.update(title_of[t] for t in targets if t in title_of)
    return sorted(t for t in g.frame if t not in called)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Worst-case stack depth from GCC .ci call graphs. "
                    "Refuses rather than guessing when an edge cannot be "
                    "followed.")
    ap.add_argument("build", nargs="*", default=["build"],
                    help="build directories to scan (default: build)")
    ap.add_argument("--elf", help="the linked image, for dispatch tables and "
                                  "library leaf frames")
    ap.add_argument("--track", choices=("a", "b", "c"),
                    help="read this track's declarations from "
                         "tools/stack_depth.list, which is where they belong: "
                         "they are claims, and a claim in shell history is a "
                         "claim nobody can review")
    ap.add_argument("--declarations", default=DECLARATIONS, metavar="PATH",
                    help="where those live (default: tools/stack_depth.list)")
    ap.add_argument("--record", action="store_true",
                    help="emit one provenance-stamped JSON row describing this "
                         "IMAGE, for records/ and tools/stack_report.py")
    ap.add_argument("--indirect", action="append", default=[],
                    metavar="LOC=SPEC",
                    help="what one indirect call site reaches, matched on its "
                         "source location. SPEC is a const dispatch table's "
                         "symbol (exact); `vtable:Class` for a C++ "
                         "virtual call, or bare `vtable` for every vtable in "
                         "the image (sound, an upper bound); `noreturn` for a "
                         "site that does not come back; `none` to assert no "
                         "target is ever registered. A site with no "
                         "declaration is refused")
    ap.add_argument("--leaf", action="append", default=[], metavar="SYM=BYTES",
                    help="declare a library frame the disassembly will not "
                         "yield; say in the commit how it was measured")
    ap.add_argument("--root", action="append", default=[], metavar="NAME",
                    help="entry point to measure (repeat). Default: every "
                         "function nothing calls")
    ap.add_argument("--top", type=int, default=10,
                    help="how many roots to list (default 10, 0 for all)")
    ap.add_argument("--json", action="store_true",
                    help="emit the result as JSON instead of a table")
    ap.add_argument("--dot", action="store_true",
                    help="emit the pruned call graph as graphviz DOT")
    ap.add_argument("--mermaid", action="store_true",
                    help="emit the pruned call graph as Mermaid, which renders "
                         "in a GitHub issue with no local tool")
    ap.add_argument("--prune", type=int, default=None, metavar="BYTES",
                    help="keep only functions carrying at least this much "
                         "worst-case depth below them. Default: half the "
                         "deepest root, which is a readability heuristic and "
                         "nothing more - the picture states what it dropped")
    args = ap.parse_args(argv)

    missing = [d for d in args.build if not os.path.isdir(d)]
    if missing:
        print(f"no such build directory: {', '.join(missing)}", file=sys.stderr)
        return 2

    # The tracked claims first: everything below consumes them, and a
    # bad line is a hard stop rather than a silently skipped declaration.
    want, declared_leaf_specs = [], []
    if args.track:
        try:
            for kind, key, value in read_declarations(args.declarations,
                                                      args.track):
                if kind == "leaf":
                    declared_leaf_specs.append(f"{key}={value}")
                else:
                    want.append((key, value))
        except (OSError, ValueError) as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

    g, files = parse(args.build)
    if not files:
        # A report that prints nothing and exits 0 is the guard that cannot
        # fail. An empty scan means the flag was never on.
        print("no .ci files under " + ", ".join(args.build)
              + "\nConfigure with -DFIRMWARE_CALLGRAPH=ON and build again.",
              file=sys.stderr)
        return 1

    frames = dict(g.frame)
    declared = {}
    for spec in list(declared_leaf_specs) + list(args.leaf):
        sym, _, val = spec.partition("=")
        if not val.isdigit():
            print(f"--leaf wants SYM=BYTES, got {spec!r}", file=sys.stderr)
            return 2
        declared[sym] = int(val)

    # --- drop what the linker threw away -------------------------------
    #
    # THE CALL GRAPH IS PRE-LINK AND THE IMAGE IS POST-GC, and until this
    # existed the difference read as a tool failure. GCC records what each
    # translation unit called; `--gc-sections` then discards every section
    # nothing reaches. On Track A that is most of the Arduino core's
    # reach into the C library - 25 of 33 unresolved leaves were malloc,
    # free, atof, sin, strcpy, String::String, none of which is in the
    # linked binary at all.
    #
    # A function that is not in the image cannot execute, so it
    # contributes no depth, and neither does anything only it reaches.
    # Dropping it is sound rather than lenient - and it is REPORTED,
    # because a graph that quietly shrank is the thing this tool refuses
    # to be.
    gc_dropped = []
    extents = symbol_extents(args.elf) if args.elf else {}
    if args.elf:
        present = image_names(args.elf)
        def _kept(title):
            return survives_link(g.name.get(title, title), present)

        # Targets first: an edge to a discarded function is not a chain.
        for title in list(g.externals):
            if _kept(title):
                continue
            gc_dropped.append(g.name.get(title, title))
            for src in g.edges:
                g.edges[src].discard(title)

        # Then SOURCES, which is the half that reaches the indirect
        # sites. attachInterrupt(), emac_phy_read() and
        # efc_perform_command() each call through a function pointer and
        # each is discarded by the linker on this firmware, so their call
        # sites cannot execute and refusing on them is refusing to bound
        # code that is not there.
        #
        # A node is dropped only when NEITHER spelling is in the image.
        # Over-pruning here would be an under-report, which is the one
        # direction that matters, so Track B's bound is the control: it
        # must not move.
        for title in list(g.frame):
            if _kept(title):
                continue
            gc_dropped.append(g.name.get(title, title))
            g.frame.pop(title, None)
            g.edges.pop(title, None)
            for src in g.edges:
                g.edges[src].discard(title)

    # --- resolve the library leaves ---
    unresolved = []
    for title in g.externals:
        plain = g.name.get(title, title)
        if plain in declared:
            frames[title] = declared[plain]
            continue
        size = leaf_frame(args.elf, plain, extents) if args.elf else None
        if size is None:
            unresolved.append((plain, "no frame: not compiled here, and its "
                                      "prologue could not be read"))
        else:
            frames[title] = size
            g.qual[title] = "prologue"

    # --- resolve the indirect calls, one site at a time ---
    #
    # PER SITE, not one shared target set, and that was a bug before it was a
    # design. With every named table pooled and applied to every site, the two
    # sites here cross-contaminated: console_trigger_fault's deliberate jump to
    # a bad address inherited console_feed's 50 handlers, one of which (h_fault)
    # calls console_trigger_fault - and the tool reported a recursion cycle in
    # firmware that has none. An over-approximation that manufactures a cycle
    # is worse than one that inflates a number.
    indirect_sites = []          # [(src_title, location)]
    for (src, dst), locs in g.sites.items():
        if dst == INDIRECT:
            indirect_sites.extend((src, loc) for loc in locs)

    for spec in args.indirect:
        loc, _, how = spec.partition("=")
        if not how:
            print(f"--indirect wants LOC=SPEC, got {spec!r}", file=sys.stderr)
            return 2
        want.append((loc, how))

    exact_indirect = True
    indirect_by_src = {}
    all_targets = set()
    syms = symbols(args.elf) if (indirect_sites and args.elf) else {}
    for src, loc in indirect_sites:
        how = next((h for pat, h in want if pat in loc), None)
        if how is None:
            unresolved.append((f"indirect call at {loc}",
                               "no --indirect declaration says what it reaches"))
            continue
        if not args.elf:
            unresolved.append((f"indirect call at {loc}",
                               "declared, but there is no --elf to resolve it"))
            continue
        if how == "noreturn":
            got = []                       # it does not come back; no chain
        elif how == "none":
            got = []                       # asserted: no target is registered
        elif how == "vtable" or how.startswith("vtable:"):
            cls = how.split(":", 1)[1] if ":" in how else None
            try:
                got, _ = vtable_targets(args.elf, cls, syms)
            except LookupError as exc:
                unresolved.append((f"indirect call at {loc}", str(exc)))
                continue
            # Naming the class is exact. The bare form is every vtable in
            # the image, which is sound for a virtual call - it reaches a
            # virtual method and they are all in one of these - but is an
            # over-approximation, so the whole answer becomes a ceiling.
            if cls is None:
                exact_indirect = False
        else:
            try:
                got, _ = table_targets(args.elf, how, syms)
            except LookupError as exc:
                unresolved.append((f"indirect call at {loc}", str(exc)))
                continue
        indirect_by_src.setdefault(src, set()).update(got)
        all_targets.update(got)

    # An indirect target is a linker symbol; the graph is keyed on .ci titles,
    # and a static's title carries its defining path. Map one to the other, and
    # refuse on any name that is ambiguous or absent rather than picking.
    # Indexed under both spellings and under the reduced key, because the
    # three sources disagree: the call graph writes a demangled signature
    # WITH its return type, nm -C writes one without, and a constructor
    # has none at all. Reducing to the qualified name is what makes them
    # comparable.
    by_name = {}
    for title, plain in g.name.items():
        by_name.setdefault(plain, []).append(title)
        key = _name_key(plain)
        if key != plain:
            by_name.setdefault(key, []).append(title)
    title_of = {}
    for t in sorted(all_targets):
        hits = by_name.get(t) or by_name.get(_name_key(t)) or []
        if len(hits) == 1:
            title_of[t] = hits[0]
        elif len(hits) > 1:
            unresolved.append((t, "the name is defined in more than one unit, "
                                  "so an indirect edge to it cannot be pinned"))
        else:
            # No .ci node at all - a vector-table entry into hand-written asm,
            # say. Refused rather than dropped: dropping it is the silent
            # under-report this tool exists to avoid.
            unresolved.append((t, "an indirect target with no call-graph node"))

    # --- the three-state contract ---
    if unresolved:
        print("REFUSED: the call graph has edges this cannot follow, so no "
              "depth is reported.\n", file=sys.stderr)
        for what, why in unresolved:
            print(f"  {what}: {why}", file=sys.stderr)
        print("\nA number here would be an under-report. Resolve these with "
              "--indirect / --leaf, or fix the call site.", file=sys.stderr)
        return 3

    cycle = find_cycle(g, frames, indirect_by_src, title_of)
    if cycle:
        print(f"RECURSION: {cycle}\n\nA cycle has no worst-case depth, and "
              "invariant 7 forbids one on the working path.", file=sys.stderr)
        return 4

    roots = roots_of(g, args.root, indirect_by_src, title_of)
    if not roots:
        print("no entry points: every function in the graph has a caller.\n"
              "That is not a clean result - it means the scan is partial, or "
              "--root named something absent.", file=sys.stderr)
        return 1

    rows = []
    for root in roots:
        try:
            total, chain = deepest(g, root, frames, indirect_by_src,
                                   title_of)
        except RecursionError as exc:
            print(f"RECURSION: {exc}\n\nA cycle has no worst-case depth, and "
                  "invariant 7 forbids one on the working path.",
                  file=sys.stderr)
            return 4
        except KeyError as exc:
            print(f"REFUSED: no frame for {g.name.get(exc.args[0], exc.args[0])}",
                  file=sys.stderr)
            return 3
        rows.append((total, g.name.get(root, root), chain))
    rows.sort(key=lambda r: -r[0])

    state = "exact" if exact_indirect else "upper bound"

    if args.record:
        # ONE ROW, DESCRIBING AN IMAGE, and that is why it does not use
        # provenance.run_fields(): that reads a *board* to label a run,
        # and nothing here has one. What makes this row attributable is
        # the ELF - its sha256 and the compiler out of .comment, which is
        # the producer that actually made these frames rather than the one
        # PATH would use next. `bench` and `repo_rev` come from
        # host/provenance.py, which requires a bench: an undeclared bench
        # cannot record, here as everywhere else.
        print(json.dumps(_record(args, g, frames, rows, state,
                                 indirect_sites, all_targets, files,
                                 indirect_by_src, title_of),
                         sort_keys=True))
        return 0

    if args.dot or args.mermaid:
        # AFTER the refusals, deliberately. A diagram is an output like any
        # other: drawing one from a graph with an edge we could not follow
        # would put a confident picture on top of an unknown, which is worse
        # than printing nothing because a picture is believed harder.
        below = cost_below(g, frames, indirect_by_src, title_of)
        deepest_total, critical = rows[0][0], rows[0][2]
        floor = args.prune if args.prune is not None else deepest_total // 2
        keep, edges = _pruned(g, frames, below, floor, indirect_by_src,
                              title_of)
        if not keep:
            print(f"nothing carries {floor} B or more; lower --prune",
                  file=sys.stderr)
            return 1
        emit_graph(g, frames, below, floor, edges, keep, critical,
                   "dot" if args.dot else "mermaid", deepest_total)
        return 0

    if args.json:
        print(json.dumps({
            "state": state,
            "ci_files": files,
            "functions": len(g.frame),
            "indirect_sites": len(indirect_sites),
            "indirect_targets": len(all_targets),
            "roots": [{"bytes": b, "root": r,
                       "chain": [g.name.get(t, t) for t in c]}
                      for b, r, c in rows],
        }, indent=2))
        return 0

    shown = rows[:args.top] if args.top else rows
    width = max((len(r[1]) for r in shown), default=8)
    print(f"{'bytes':>7}  {'root':<{width}}  depth")
    for total, root, chain in shown:
        print(f"{total:>7}  {root:<{width}}  {len(chain)} frames")

    if rows:
        total, root, chain = rows[0]
        # A running total rather than an indent tree: this is one path, and
        # what a reader wants from it is where the depth accumulates.
        print(f"\nDeepest chain: {total} B through {root}")
        print(f"  {'frame':>6}  {'cumulative':>10}  function")
        running = 0
        for title in chain:
            running += frames[title]
            print(f"  {frames[title]:>6}  {running:>10}  "
                  f"{g.name.get(title, title)}")
    print(f"\n{len(g.frame)} functions over {files} .ci file(s), "
          f"{len(indirect_sites)} indirect call site(s) "
          f"resolving to {len(all_targets)} target(s).")
    if gc_dropped:
        print(f"{len(gc_dropped)} call target(s) were compiled and then "
              f"discarded by --gc-sections, so they cannot run: "
              + ", ".join(sorted(gc_dropped)[:6])
              + (" ..." if len(gc_dropped) > 6 else ""))
    print(f"State: {state}."
          + ("" if exact_indirect else
             " Some edge was over-approximated; the figure is a ceiling, "
             "not a measurement."))
    print("Depth only. Interrupt nesting is not added here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
