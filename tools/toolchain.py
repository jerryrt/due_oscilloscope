#!/usr/bin/env python3
"""Resolve build tools from toolchains.json.

The registry is committed and shared; this reads it the same way
cmake/arm-none-eabi-toolchain.cmake does, so a host described once is
described for both the CMake build and the scripts around it.

    python3 tools/toolchain.py                  # what resolved, and what did not
    python3 tools/toolchain.py --dir arm_toolchain
    python3 tools/toolchain.py --exe bossac

Stdlib only: this runs during bring-up, before any venv exists.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import platform
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(REPO, "toolchains.json")
LOCAL = os.path.join(REPO, "toolchains.local.json")


def _expand(pattern: str) -> str:
    return (pattern
            .replace("{repo}", REPO.replace("\\", "/"))
            .replace("{home}", os.path.expanduser("~").replace("\\", "/")))


def load() -> dict:
    """Shared registry, with toolchains.local.json layered on top.

    A local entry PREPENDS its patterns to the shared ones rather than
    replacing them, so an override for one machine cannot quietly break
    the fallbacks every other machine relies on.
    """
    with open(SHARED, encoding="utf-8") as fh:
        reg = json.load(fh)
    if not os.path.exists(LOCAL):
        return reg
    with open(LOCAL, encoding="utf-8") as fh:
        local = json.load(fh)
    for name, spec in local.get("tools", {}).items():
        shared = reg["tools"].setdefault(name, {"search": {}})
        for plat, pats in spec.get("search", {}).items():
            shared["search"][plat] = pats + shared["search"].get(plat, [])
        for key in ("requires", "reject"):
            if key in spec:
                shared[key] = spec[key]
    return reg


def _has_exe(directory: str, name: str) -> str | None:
    for cand in (name, name + ".exe"):
        full = os.path.join(directory, cand)
        if os.path.isfile(full):
            return full.replace("\\", "/")
    return None


def resolve(tool: str, reg: dict | None = None,
            system: str | None = None) -> tuple[str | None, str | None]:
    """Return (directory, executable) for `tool`, or (None, None).

    Directories are searched in the order the registry lists them, and the
    first one that exists AND holds the required executable wins - existence
    alone is not enough, because a stale install directory outlives its
    contents and would otherwise shadow a working toolchain further down.
    """
    reg = reg if reg is not None else load()
    spec = reg["tools"].get(tool)
    if spec is None:
        raise KeyError(f"no such tool in the registry: {tool}")

    system = system or platform.system()
    requires = spec.get("requires", tool)
    reject = spec.get("reject", [])

    for pattern in spec.get("search", {}).get(system, []):
        for hit in sorted(glob.glob(_expand(pattern)), reverse=True):
            hit = hit.replace("\\", "/")
            if not os.path.isdir(hit):
                continue
            if any(fnmatch.fnmatch(hit, _expand(r)) for r in reject):
                continue
            exe = _has_exe(hit, requires)
            if exe:
                return hit, exe
    return None, None


def arm_toolchain_dir() -> str | None:
    """The one tool with an environment override, because CMake has one too."""
    env = os.environ.get("ARM_TOOLCHAIN_DIR")
    if env and os.path.isdir(env):
        return env.replace("\\", "/")
    return resolve("arm_toolchain")[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", metavar="TOOL", help="print the directory only")
    ap.add_argument("--exe", metavar="TOOL", help="print the executable only")
    args = ap.parse_args()

    reg = load()
    if args.dir or args.exe:
        directory, exe = resolve(args.dir or args.exe, reg)
        found = directory if args.dir else exe
        if not found:
            print(f"not found: {args.dir or args.exe}", file=sys.stderr)
            return 1
        print(found)
        return 0

    print(f"host     : {platform.system()} {platform.machine()}")
    print(f"registry : {SHARED}")
    print(f"local    : {LOCAL if os.path.exists(LOCAL) else '(none)'}")
    print()
    # Exit status reports only what the build actually needs. cmake and
    # ninja are marked optional in the registry because a host may have
    # them on PATH already, or use a different generator - counting them
    # made this exit 1 on a fully working machine, and took
    # `cmake --build build --target tools` down with it.
    missing = 0
    for name, spec in reg["tools"].items():
        directory, _ = resolve(name, reg)
        optional = bool(spec.get("optional"))
        if directory is None and not optional:
            missing += 1
        mark = "" if directory else ("  (optional)" if optional else "")
        print(f"{name:15} {directory or '-- NOT FOUND --'}{mark}")
        if directory is None:
            print(f"{'':15} {spec.get('what', '')}")
    if missing:
        print(f"\n{missing} required tool(s) missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
