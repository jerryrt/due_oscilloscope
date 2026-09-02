#!/usr/bin/env python3
"""The largest per-function stack frames in a build.

    cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
          -DCMAKE_BUILD_TYPE=Release -DFIRMWARE_STACK_USAGE=ON
    cmake --build build -j
    python3 tools/stack_frames.py build

WHAT THIS MEASURES, AND WHAT IT DOES NOT. `-fstack-usage` makes the
compiler write one `.su` line per function it emits: the bytes that
function's own frame occupies, and whether the compiler could bound it.
That is all this reports. It is **not** a worst-case stack depth: depth
is the sum of the frames along the deepest reachable call chain, plus
whatever an interrupt pushes on top of the chain it preempts, and
nothing here walks the call graph. A 512-byte frame in a leaf that runs
once at boot is harmless; three 200-byte frames nested under an ISR are
not, and this report shows the same number for both.

Invariant 7 asks for a bounded worst case in every ISR and every
main-loop pass. A frame census is a step towards checking that and is
not the check: read it as "what is large, and is anything unbounded",
then follow the call chain by hand.

THE QUALIFIER IS THE PART TO READ FIRST. GCC tags each frame `static`,
`dynamic`, or `dynamic,bounded`. `static` is a constant known at compile
time. `dynamic` is an alloca or a variable-length array - a frame whose
size depends on a value the function was given, which is what invariant
7 forbids on the working path, and it is the one finding here that is a
defect on sight rather than a number to weigh.

The `.su` files sit beside the objects, so a build directory is the
argument. They are not tracked by CMake, so a source file that has been
deleted can leave one behind; `--since` drops anything older than the
newest, which is what a clean build produces.

Stdlib only, like the rest of the build-side tooling here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

#: `<file>:<line>:<column>:<function>\t<bytes>\t<qualifier>`. The file
#: field is matched non-greedily so a Windows drive letter does not eat
#: the line number, and the function field greedily so a C++ `A::b`
#: survives.
_SU = re.compile(r"^(?P<file>.*?):(?P<line>\d+):(?P<col>\d+):(?P<func>.*)$")


def _short(path):
    """The source path relative to the working directory where that is
    shorter. GCC writes whatever path it was handed, which under CMake is
    absolute and pushes the useful column off the terminal."""
    try:
        rel = os.path.relpath(path)
    except ValueError:                      # different drive on Windows
        return path
    return rel if len(rel) < len(path) else path


def collect(roots):
    """[(bytes, qualifier, function, source, su_path, mtime)] over every .su."""
    rows = []
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                if not name.endswith(".su"):
                    continue
                path = os.path.join(dirpath, name)
                mtime = os.path.getmtime(path)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for raw in fh:
                        raw = raw.rstrip("\n")
                        if not raw:
                            continue
                        parts = raw.split("\t")
                        if len(parts) < 3:
                            continue
                        loc, size, qual = parts[0], parts[1], parts[2]
                        m = _SU.match(loc)
                        if not m or not size.isdigit():
                            continue
                        src = _short(m.group("file"))
                        rows.append((int(size), qual, m.group("func"),
                                     f"{src}:{m.group('line')}",
                                     path, mtime))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Largest per-function stack frames from GCC .su files. "
                    "Per function, not a call-graph depth bound.")
    ap.add_argument("build", nargs="*", default=["build"],
                    help="build directories to scan (default: build)")
    ap.add_argument("--top", type=int, default=20,
                    help="how many frames to list (default 20, 0 for all)")
    ap.add_argument("--min", type=int, default=0,
                    help="only list frames of at least this many bytes")
    ap.add_argument("--since", type=float, default=None, metavar="SECONDS",
                    help="ignore .su files older than the newest by more "
                         "than this, which drops files left behind by a "
                         "source that has since been deleted")
    ap.add_argument("--json", action="store_true",
                    help="emit the rows as JSON instead of a table")
    args = ap.parse_args(argv)

    missing = [d for d in args.build if not os.path.isdir(d)]
    if missing:
        print(f"no such build directory: {', '.join(missing)}", file=sys.stderr)
        return 2

    rows = collect(args.build)
    if not rows:
        # A report that prints nothing and exits 0 is the guard that
        # cannot fail. An empty scan means the flag was never on.
        print("no .su files under " + ", ".join(args.build)
              + "\nConfigure with -DFIRMWARE_STACK_USAGE=ON and build again.",
              file=sys.stderr)
        return 1

    if args.since is not None:
        newest = max(r[5] for r in rows)
        rows = [r for r in rows if newest - r[5] <= args.since]

    rows.sort(key=lambda r: (-r[0], r[2]))
    unbounded = [r for r in rows if not r[1].startswith("static")]

    if args.json:
        print(json.dumps({
            "functions": len(rows),
            "largest": rows[0][0],
            "unbounded": len(unbounded),
            "frames": [{"bytes": b, "qualifier": q, "function": f,
                        "source": s} for b, q, f, s, _p, _m in rows],
        }, indent=2))
        return 0

    shown = [r for r in rows if r[0] >= args.min]
    if args.top:
        shown = shown[:args.top]

    width = max((len(r[2]) for r in shown), default=8)
    print(f"{'bytes':>7}  {'qualifier':<15}  {'function':<{width}}  source")
    for size, qual, func, src, _path, _mtime in shown:
        print(f"{size:>7}  {qual:<15}  {func:<{width}}  {src}")

    print(f"\n{len(rows)} functions, largest frame {rows[0][0]} B.")
    if unbounded:
        print(f"{len(unbounded)} frame(s) the compiler could not size "
              "statically:")
        for size, qual, func, src, _path, _mtime in unbounded:
            print(f"  {func} ({qual}, {size} B) {src}")
    else:
        print("Every frame is statically sized.")
    print("Per function. Call-graph depth is not measured here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
