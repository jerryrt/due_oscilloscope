#!/usr/bin/env python3
"""What is actually on the board, in a form two benches can compare.

`records/` requires `fw_repo_rev` because a version string says what
someone intended and a commit says what was compiled. That is not
sufficient: **a commit does not determine an image either.** The benches
build this repository with different code generators - `docs/toolchain.md`
names them - so two benches building "the same commit" produce two
different images, and a record that carries only the commit does not say
so.

That matters for one open defect in particular. Issue #5's displacement
site follows the generated code: the same source built by a different
compiler draws a different site. So an experiment that pins a commit
across two benches and compares site tables has pinned the *source* and
left the *image* free, which is the variable.

**A byte hash is an identity and not a description.** The build is
byte-reproducible - `tools/reproducible.py` builds twice and holds it -
so `sha256` of the .bin is stable for one source state and moves when
the source, the working tree or the compiler does. What it will not do
is say *which*: two benches whose hashes disagree learn that they
disagree, and the code generator is the thing they have to tell apart
from a source difference.

This reports what a hash cannot. `cc` comes out of `.comment`, so it
names the compiler that produced the file rather than the one PATH
would reach for next; `text`/`data`/`bss` size it; and the
defined-symbol address map says where things were put. Whether two
images run the same *instructions* is a third question, and
`tools/image_mnemonics.py` is what answers it.

    python3 tools/image_fingerprint.py build/baremetal_bringup.elf

Prints one JSON object. Every field in it is a property of the ELF and
not of the tools that read it, so two benches compare them directly:
`cc`, `text` and `layout` first, and `symbols`/`addresses` when
`layout` disagrees and the question is which half moved. If they
differ, the two boards were not running the same image however well the
commit matched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import toolchain  # noqa: E402

#: Built by both tracks' documented build lines, tried in order.
DEFAULT_ELVES = (
    "build/baremetal_bringup.elf",
    "build-a/track_a_bringup.elf",
)


def _tool(name: str) -> str:
    """Absolute path to an arm-none-eabi binutil, or bare name as a fallback."""
    directory = toolchain.arm_toolchain_dir()
    if directory:
        for suffix in ("", ".exe"):
            candidate = os.path.join(directory, name + suffix)
            if os.path.exists(candidate):
                return candidate
    return name


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True,
                          check=True).stdout


#: Producer strings a compiler leaves in `.comment`, in the order they
#: are reported. An image built by clang and linked through the GCC
#: driver carries both, because newlib and libgcc are GCC's.
PRODUCERS = (r"[A-Za-z ]*clang version[^\n]*", r"GCC:[^\n]*")


def compiler(elf: str) -> str:
    """The code generator, read out of .comment rather than off PATH.

    PATH says which compiler would be used next; .comment says which one
    produced this file. They disagree exactly when it matters.

    EVERY producer, not the first one matched. A clang-built image links
    the GCC toolchain's newlib and libgcc, so its `.comment` carries a
    GCC string as well - and a reader that stops at the first `GCC:`
    reports a clang image as a GCC one, which is the single question
    this field exists to answer.
    """
    try:
        out = _run([_tool("arm-none-eabi-readelf"), "-p", ".comment", elf])
    except subprocess.CalledProcessError:
        return "unknown"
    found = []
    for pattern in PRODUCERS:
        for hit in re.findall(pattern, out):
            hit = hit.strip()
            if hit not in found:
                found.append(hit)
    return "; ".join(found) if found else "unknown"


def sizes(elf: str) -> dict:
    out = _run([_tool("arm-none-eabi-size"), elf]).splitlines()
    text, data, bss = out[-1].split()[:3]
    return {"text": int(text), "data": int(data), "bss": int(bss)}


def symbol_table(elf: str) -> list:
    """The defined symbols as `(address, name, type)`, in a total order.

    `--defined-only` drops the undefined ones, so what is left is where
    the code generator put things and nothing else.

    **Sorted here, and on every field, because `nm`'s own order is not a
    property of the image.** Addresses are shared - 8 of them in a
    Track B image, most of those weak aliases for `Default_Handler` at
    one address - and the order within a tie is whatever the tool
    emitted. Two binutils builds reading one ELF emit those ties
    differently, so a hash taken over `nm -n` output is partly a hash of
    the reader rather than of the file.

    Sorting on the whole tuple is what makes the order total: the only
    records that can tie are records equal in all three fields, and a
    tie between identical records cannot change what is hashed. A key
    covering less than the whole record - address alone, or address and
    name - leaves the residue to input order and is this defect again.
    """
    out = _run([_tool("arm-none-eabi-nm"), "-n", "--defined-only", elf])
    table = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        addr, kind, name = parts
        try:
            table.append((int(addr, 16), name, kind))
        except ValueError:
            continue
    return sorted(table)


def _hash(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def layout(elf: str) -> str:
    """Hash of the defined-symbol address map: one image, one value.

    Both columns in one hash, which is what makes it cheap. It is a
    property of the image alone - `symbol_table` holds that and says
    what it costs - so two benches may compare it directly whatever
    binutils each of them read the ELF with.

    `layout_parts` splits it into the two things that can differ inside
    it, which is what a disagreement then needs.
    """
    return _hash("%08x %s %s" % (addr, kind, name)
                 for addr, name, kind in symbol_table(elf))


def layout_parts(elf: str) -> dict:
    """`layout`, split into the two things that can differ inside it.

    A single hash says two images disagree and never says how, and that
    is the whole question when two benches compare. Two builds can agree
    on `text`, `data` and `bss` to the byte - 39212/32/72992, measured
    on `3aadf90` with xPack 15.2.1 on two benches - and still disagree
    on `layout`. That is either the same symbols at different addresses
    or different symbols; sizes cannot tell them apart and neither can
    one hash.

    So hash them separately:

    `symbols`   the sorted symbol names alone. Differs when the two
                builds do not contain the same things.
    `addresses` the address column alone, in address order. Differs when
                the same things were put in different places.

    Both read the table `layout` hashes, so the three answer one
    question about one ordering and cannot drift apart.
    """
    table = symbol_table(elf)
    return {"symbols": _hash(sorted(name for _, name, _ in table)),
            "addresses": _hash("%08x" % addr for addr, _, _ in table),
            "n_symbols": len(table),
            "n_addresses": len({addr for addr, _, _ in table})}


def repo_rev(elf: str) -> str:
    """The commit of the tree that produced *this ELF*, not of the cwd.

    Asked about REPO instead, this reported the checkout the tool was
    invoked from while fingerprinting an image built in a worktree at a
    different commit - a fingerprint that misstates its own commit,
    which is the failure `fw_repo_rev` exists to prevent. Ask git about
    the directory the ELF is in.
    """
    where = os.path.dirname(os.path.abspath(elf))
    try:
        rev = _run(["git", "-C", where, "rev-parse", "HEAD"]).strip()[:7]
        dirty = _run(["git", "-C", where, "status", "--porcelain"]).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"
    return rev + ("-dirty" if dirty else "")


def fingerprint(elf: str) -> dict:
    return {
        "elf": os.path.basename(elf),
        "repo_rev": repo_rev(elf),
        "cc": compiler(elf),
        "layout": layout(elf),
        **layout_parts(elf),
        **sizes(elf),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf", nargs="?", help="ELF to fingerprint")
    args = ap.parse_args()

    elf = args.elf
    if elf is None:
        for candidate in DEFAULT_ELVES:
            path = os.path.join(REPO, candidate)
            if os.path.exists(path):
                elf = path
                break
        else:
            print("no ELF given and none of %s exists; build one first"
                  % ", ".join(DEFAULT_ELVES), file=sys.stderr)
            return 2
    if not os.path.exists(elf):
        print("no such ELF: %s" % elf, file=sys.stderr)
        return 2

    print(json.dumps(fingerprint(elf), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
