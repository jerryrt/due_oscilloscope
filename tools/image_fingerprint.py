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

Prints one JSON object. Across benches compare `cc`, `text`, and
`symbols`/`addresses` rather than `layout` - `layout_parts` says why
`layout` is partly a property of the reader's `nm`. If they differ, the
two boards were not running the same image however well the commit
matched.
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


def layout(elf: str) -> str:
    """Hash of the defined-symbol address map.

    `-n` sorts by address and `--defined-only` drops undefined symbols,
    so this is where the code generator put things and nothing else.

    One hash over both columns, which is what makes it cheap and what
    makes it fragile across benches - see `layout_parts`, which splits
    it and is the pair to compare when the two benches' binutils are not
    the same build.
    """
    out = _run([_tool("arm-none-eabi-nm"), "-n", "--defined-only", elf])
    return hashlib.sha256(out.encode()).hexdigest()[:16]


def layout_parts(elf: str) -> dict:
    """`layout`, split into the two things that can differ inside it.

    A single hash says two images disagree and never says how, and that
    is the whole question when two benches compare. Measured on
    `3aadf90` with xPack 15.2.1 on two benches: identical `text`, `data`
    and `bss` - 39212/32/72992 to the byte - and different `layout`.
    That is either the same symbols at different addresses, or different
    symbols; sizes cannot tell them apart and neither can one hash.

    So hash them separately:

    `symbols`   the sorted symbol names alone. Differs when the two
                builds do not contain the same things.
    `addresses` the address column alone, in order. Differs when the
                same things were put in different places.

    **A caveat this exposed and cannot fix, and it reaches `layout`.**
    `nm -n` sorts by address, and 8 addresses in this image carry more
    than one symbol - most of them share `Default_Handler`'s, since
    every unused vector is a weak alias for it. The order *within* a tie
    is the tool's, not the linker's, and two binutils builds order it
    differently: one ELF read by two of them hashes to two `layout`
    values while `symbols` and `addresses` agree exactly. So `layout` is
    a property of the reader as well as of the image, and the pair below
    is what a cross-bench comparison should read. Which of the two
    orderings `layout` should adopt is an open decision, so do not
    quietly settle it by changing this hash; `symbols` is sorted
    explicitly here and does not inherit the tie at all.
    """
    out = _run([_tool("arm-none-eabi-nm"), "-n", "--defined-only", elf])
    names, addrs = [], []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            addrs.append(parts[0])
            names.append(parts[2])
    def h(x):
        return hashlib.sha256("\n".join(x).encode()).hexdigest()[:16]
    return {"symbols": h(sorted(names)),
            "addresses": h(addrs),
            "n_symbols": len(names),
            "n_addresses": len(set(addrs))}


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
