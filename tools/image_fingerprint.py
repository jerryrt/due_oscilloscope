#!/usr/bin/env python3
"""What is actually on the board, in a form two benches can compare.

`records/` requires `fw_repo_rev` because a version string says what
someone intended and a commit says what was compiled. That was the right
fix and it is not sufficient: **a commit does not determine an image
either.** Three benches build this repository with three different code
generators - xPack GCC 15.2.1 on mac-bench, Debian's 14.2.1 on linux-x1,
and arduino-cli's bundled 4.8.3 on whichever Track A path is in use -
and none of it is recorded anywhere. Two benches building "the same
commit" produce two different layouts and no field in any record says
so.

That matters for one open defect in particular. Issue #5's displacement
site is, in CLAUDE.md's own words, "a lottery over code layout": the
same source built differently draws a different site. So an experiment
that pins a commit across two benches and compares site tables has
pinned the *source* and left the *image* free, which is the variable.

The obvious fingerprint does not work, and it is worth saying why so
nobody reaches for it twice. **sha256 of the .bin is not stable on one
machine**, let alone across two: the image carries `__DATE__ __TIME__`,
so two builds of one commit in one directory differ. Measured here -
a3e551b4 and f02aeb9a, same tree, same compiler, minutes apart. A
sha256 mismatch between benches therefore proves nothing at all.

What is stable is the *layout*: the defined-symbol address map, which
carries no timestamp. Two builds of 3aadf90 on linux-x1 gave layout
c4cd8445987b5261 twice, with identical text/data/bss. So this is a
fingerprint that is silent when nothing has changed and loud when the
code generator has - which is what a cross-bench comparison needs.

    python3 tools/image_fingerprint.py build/baremetal_bringup.elf

Prints one JSON object. Compare `layout`, `text` and `cc` across
benches; if they differ, the two boards were not running the same image
however well the commit matched.
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


def compiler(elf: str) -> str:
    """The code generator, read out of .comment rather than off PATH.

    PATH says which compiler would be used next; .comment says which one
    produced this file. They disagree exactly when it matters.
    """
    try:
        out = _run([_tool("arm-none-eabi-readelf"), "-p", ".comment", elf])
    except subprocess.CalledProcessError:
        return "unknown"
    hit = re.search(r"GCC[^\n]*", out)
    return hit.group(0).strip() if hit else "unknown"


def sizes(elf: str) -> dict:
    out = _run([_tool("arm-none-eabi-size"), elf]).splitlines()
    text, data, bss = out[-1].split()[:3]
    return {"text": int(text), "data": int(data), "bss": int(bss)}


def layout(elf: str) -> str:
    """Hash of the defined-symbol address map.

    `-n` sorts by address and `--defined-only` drops undefined symbols,
    so this is where the code generator put things - the quantity #5 is
    a lottery over - and nothing else. No build stamp reaches it.
    """
    out = _run([_tool("arm-none-eabi-nm"), "-n", "--defined-only", elf])
    return hashlib.sha256(out.encode()).hexdigest()[:16]


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
