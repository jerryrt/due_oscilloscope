#!/usr/bin/env python3
"""Per-function mnemonic hashes: what the compiler GENERATED, not where it put it.

Companion to `tools/image_fingerprint.py`, and it answers the question
that one could not.

`image_fingerprint.py` hashes the defined-symbol address map, which is
the right instrument for "is this the same image". It is the wrong one
for "does this image run the same instructions", and #5 needs the
second. Measured on 2026-08-31, one commit, three benches:

    linux-x1      GCC 14.2.1 Debian   layout c4cd8445987b5261
    windows-desk  ARM GNU 14.3.1      layout be84df15f77a3e36
    windows-desk  xPack 15.2.1        layout a49d8fb51ba4c391

All three layouts differ. The first two produce **identical #5 site
sets** and the third does not, so the site set is not a function of the
layout. Two builds can disagree about every address and agree about
every instruction; that is the common case across a compiler point
release, and it is invisible to an address-map hash.

**Mnemonics, not bytes, and not addresses.** The byte column moves under
relocation - CLAUDE.md records objdump reporting 152 differing functions
where 5 differ - and the operand column carries addresses for the same
reason. The mnemonic sequence is what the core fetches and executes, and
it is stable under relocation by construction.

Per function rather than whole-image, because a whole-image hash says
only "different" and the useful answer is *which* code differs. On the
pair above, 251 of 294 shared functions are identical and 43 differ; the
43 include `DACC_Handler`, `acq_start` and `build_table` - the DAC path
#5 draws from - while `ADC_Handler`, `UOTGHS_Handler` and `main` are
identical. That is a finding. "The images differ" is not.

The per-function counts above were taken before symbols were bounded by
their declared size, so a symbol that absorbed trailing data carries a
larger count there than it does now. Which functions differ is
unaffected.

Two benches can compare without sharing an ELF: the hashes travel in a
comment and the disassembly does not have to.

    python3 tools/image_mnemonics.py build/baremetal_bringup.elf
    python3 tools/image_mnemonics.py a.elf --only DACC_Handler,acq_start
    python3 tools/image_mnemonics.py a.elf --compare b.elf
"""
import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

# `0800012c <DACC_Handler>:`
_FUNC = re.compile(r"^([0-9a-fA-F]+)\s+<([^>]+)>:")

# `00086314 l     F .text\t00000050 __libc_init_array` - address, size, name
# from the symbol table, used to stop a symbol absorbing what follows it.
_SYM = re.compile(r"^([0-9a-fA-F]+)\s.*\s([0-9a-fA-F]+)\s+(\S+)\s*$")

# `    8000130:\t4770      \tbx\tlr`  - fields are tab separated, and the
# mnemonic is the first token of the third field. A line with only two
# fields is a raw-data word inside a literal pool and carries no
# mnemonic, which is why this is not a blind split.
_INSN = re.compile(r"^\s*([0-9a-fA-F]+):\s*\t[^\t]*\t\s*(\S+)")


def _objdump():
    """The objdump beside the ARM toolchain this repo resolves.

    Not `objdump` off PATH: on a bench with a host binutils that is the
    wrong architecture, and on Windows there is usually none at all.
    """
    try:
        import toolchain
        d = toolchain.arm_toolchain_dir()
    except Exception:                                        # noqa: BLE001
        d = None
    if not d:
        return "arm-none-eabi-objdump"
    for cand in ("arm-none-eabi-objdump.exe", "arm-none-eabi-objdump"):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return p
    return "arm-none-eabi-objdump"


def _sizes(elf):
    """{symbol: declared size} from the symbol table.

    objdump -d disassembles a whole section and labels each run with the
    symbol that starts it, so a symbol absorbs whatever follows it up to
    the next symbol - including trailing .rodata. Bounding each symbol by
    its declared size is what stops that.
    """
    out = subprocess.run([_objdump(), "-t", elf],
                         capture_output=True, text=True, check=True).stdout
    sizes = {}
    for line in out.splitlines():
        m = _SYM.match(line)
        if m:
            sizes[m.group(3)] = int(m.group(2), 16)
    return sizes


def mnemonics(elf):
    """{function: [mnemonic, ...]} in program order.

    Bounded by each symbol's declared size. Without that bound a symbol
    followed by data reports it as instructions: on the RTOS image
    __libc_init_array is 0x50 bytes of code and absorbed 5,156 bytes of
    .rodata, four strings of which are absolute source paths, so the
    "instruction" count tracked the length of the build directory - one
    per character, exactly - and the image was not comparable between
    two checkouts of the same commit.
    """
    out = subprocess.run([_objdump(), "-d", elf],
                         capture_output=True, text=True, check=True).stdout
    sizes = _sizes(elf)
    funcs = collections.OrderedDict()
    cur = None
    end = None
    for line in out.splitlines():
        m = _FUNC.match(line)
        if m:
            cur = m.group(2)
            start = int(m.group(1), 16)
            size = sizes.get(cur)
            end = start + size if size else None
            funcs.setdefault(cur, [])
            continue
        if cur is None:
            continue
        i = _INSN.match(line)
        if i:
            if end is not None and int(i.group(1), 16) >= end:
                continue
            funcs[cur].append(i.group(2))
    return funcs


SHARED_SRC = "lib/due_shared/src/*.c"


def shared_source_functions(root=ROOT):
    """Function names defined in lib/due_shared, for #54's question.

    Whether the two tracks still differ on the SHARED source is the
    oracle question, and a whole-image comparison cannot answer it: most
    of what differs between the tracks is per-track register
    programming, which invariant 3 requires to differ. Restricting to
    the shared library is what makes the number mean anything.

    Measured on windows-desk 2026-08-31, after #55 put both tracks on
    one toolchain: 64 shared-source functions present in both images,
    64 identical, 0 differing. Across the two toolchains this project
    installs - ARM GNU 14.3.1 and xPack 15.2.1 - 18 of 63 differ,
    including frame_crc32_update and the stream_core pair. So the
    codegen axis did not disappear; it moved from within a bench to
    between benches.

    Textual, and a LOWER bound on coverage: definitions at column zero,
    so anything declared unusually is missed. That is the safe direction
    for the question asked - a list that is too small cannot manufacture
    an "identical everywhere" result, only fail to notice a difference.
    """
    import glob
    pat = re.compile(r"^[A-Za-z_][\w \t \*]*?\b([a-z_]\w*)\s*\(", re.M)
    out = set()
    for path in sorted(glob.glob(os.path.join(root, *SHARED_SRC.split("/")))):
        text = open(path, encoding="utf-8", errors="replace").read()
        for m in pat.finditer(text):
            eol = text.find(chr(10), m.start())
            line = text[m.start():eol if eol >= 0 else len(text)]
            if line.rstrip().endswith(";"):
                continue
            if line.lstrip().startswith(("if", "for", "while", "return",
                                         "}", "#", "switch")):
                continue
            out.add(m.group(1))
    return out


def _h(seq):
    return hashlib.sha256(" ".join(seq).encode()).hexdigest()[:12]


def report(elf, only=None):
    f = mnemonics(elf)
    if only:
        f = collections.OrderedDict((k, v) for k, v in f.items() if k in only)
    whole = hashlib.sha256(
        "|".join(f"{k}:{' '.join(v)}" for k, v in sorted(f.items()))
        .encode()).hexdigest()[:16]
    return {
        "elf": os.path.basename(elf),
        "n_functions": len(f),
        "n_instructions": sum(len(v) for v in f.values()),
        "mnemonics": whole,
        "per_function": {k: {"n": len(v), "sha": _h(v)} for k, v in f.items()},
    }


def compare(a, b, only=None):
    fa, fb = mnemonics(a), mnemonics(b)
    keys = set(fa) & set(fb)
    if only:
        keys &= set(only)
    shared = sorted(keys)
    same = [k for k in shared if fa[k] == fb[k]]
    diff = [k for k in shared if fa[k] != fb[k]]
    return {
        "a": os.path.basename(a),
        "b": os.path.basename(b),
        "shared": len(shared),
        "identical": len(same),
        "differing": len(diff),
        "only_in_a": [] if only else sorted(set(fa) - set(fb)),
        "only_in_b": [] if only else sorted(set(fb) - set(fa)),
        # Same length and a different sequence is the interesting case:
        # the compiler chose other instructions rather than more of them,
        # which a size comparison reports as no change at all.
        "differing_functions": [
            {"name": k, "n_a": len(fa[k]), "n_b": len(fb[k]),
             "same_length": len(fa[k]) == len(fb[k])}
            for k in diff],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("--compare", help="a second ELF; report per-function agreement")
    ap.add_argument("--only", help="comma-separated function names")
    ap.add_argument("--shared-source", action="store_true",
                    help="restrict to functions defined in lib/due_shared - the oracle question on #54, which a whole-image "
                         "comparison cannot answer because invariant 3 requires the per-track code to differ")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None
    if args.shared_source:
        shared = shared_source_functions()
        only = (only & shared) if only else shared
    if args.compare:
        print(json.dumps(compare(args.elf, args.compare, only), indent=2))
    else:
        print(json.dumps(report(args.elf, only), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
