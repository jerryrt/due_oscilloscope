#!/usr/bin/env python3
"""Build the firmware twice and say whether the bytes agree.

A build that is not reproducible cannot be identified. Two builds of one
source state that differ have no single answer to "which image is on the
board", so the commit, the compiler and the image hash recorded against
a measurement would describe a *class* of images rather than one.
Everything that pins an image to a source state rests on this property,
and this is the only thing that checks it.

Both tracks build to the byte on a clean tree, so this reports 0 and is
a standing guard rather than a measurement: what it watches for is the
next thing to leak in - an absolute build path, a wall clock, a
container that left an input unpinned. Everything that identifies an
image by its bytes stops working the day one of those arrives, and it
arrives silently.

    python3 tools/reproducible.py                  # Track B
    python3 tools/reproducible.py --track a        # Track A
    python3 tools/reproducible.py --compare one.bin other.bin

Exit status is 0 when every artifact is byte-identical and non-zero when
any differs, so it can be a build step.

`--compare` takes the two builds as given files instead of producing
them, which is how two benches - or a container and its host - compare
images neither of them can build in the same place.

**The two builds are separated in time on purpose.** A Track B build is
well under a second, so two back-to-back builds can capture one reading
of a clock and come out identical for a reason that has nothing to do
with reproducibility - a green result from a check that could not have
gone red. `--gap` separates them, and its default of one second is
enough that a stamp of one-second resolution must differ; defeating a
coarser one is what a larger value is for.

No clean step of its own. `enforce_clean_build` already makes every
build of every track a full build, and a second clean here would mask a
build path that had lost it.

Stdlib only: this runs during bring-up, before any venv exists.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import toolchain  # noqa: E402

#: Per track: the build directory, the rest of the `cmake --build` line
#: as the documented build in CLAUDE.md spells it, and the artifacts.
#: Track B's default target is its clean-build wrapper, so it needs no
#: `--target`; the other tracks are behind an option and name theirs.
TRACKS = {
    "b": {
        "dir": "build",
        "args": ["-j"],
        "artifacts": ("baremetal_bringup.bin", "baremetal_bringup.elf"),
        "configure": (
            "cmake -B build "
            "-DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake "
            "-DCMAKE_BUILD_TYPE=Release"),
    },
    "a": {
        "dir": "build-a",
        "args": ["--target", "firmware_track_a"],
        "artifacts": ("track_a_bringup.bin", "track_a_bringup.elf"),
        "configure": (
            "cmake -B build-a "
            "-DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake "
            "-DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON"),
    },
}

#: Bytes of context either side of a differing byte. Wide enough to the
#: left that a string the difference sits at the end of - a timestamp,
#: a version - is readable whole.
CONTEXT_BEFORE = 44
CONTEXT_AFTER = 16

#: Differing offsets closer than this share one context block, so a
#: changed string is reported as one place rather than as each of its
#: bytes.
REGION_GAP = 12


def cmake_exe() -> str:
    """cmake's path, from the registry rather than from PATH.

    On Windows none of the build tools is on PATH - cmake comes from the
    copy bundled with Visual Studio - so a bare "cmake" is not portable
    even where it happens to work. The registry marks cmake optional
    because a host may have it on PATH already, which is why there is a
    fallback rather than an error.
    """
    _directory, exe = toolchain.resolve("cmake")
    return exe or shutil.which("cmake") or "cmake"


def build(spec: dict, cmake: str) -> float:
    """Run one full build, returning the wall-clock seconds it took.

    The command is spelled inside the spawn rather than assembled into a
    variable first, because `tests/test_clean_build.py` reads the 300
    characters after a `subprocess` call to find every file that reaches
    a build tool. A spawn it cannot see is a build path its allowlist
    does not govern, and this file belongs on that list.
    """
    start = time.monotonic()
    done = subprocess.run([cmake, "--build", spec["dir"]] + spec["args"],
                          cwd=REPO, capture_output=True, text=True)
    took = time.monotonic() - start
    if done.returncode != 0:
        sys.stderr.write((done.stdout or "")[-4000:])
        sys.stderr.write((done.stderr or "")[-4000:])
        raise SystemExit("cmake --build %s failed" % spec["dir"])
    return took


def read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def diff_offsets(first: bytes, second: bytes) -> list[int]:
    """Every offset at which the two differ, a length difference included.

    A shorter artifact counts its missing tail as differing, so a
    truncated build is a loud result rather than a silent equal prefix.
    """
    common = min(len(first), len(second))
    offsets = [i for i in range(common) if first[i] != second[i]]
    offsets.extend(range(common, max(len(first), len(second))))
    return offsets


def regions(offsets: list[int]) -> list[tuple[int, int]]:
    """Differing offsets grouped into (first, last) runs for display."""
    grouped: list[tuple[int, int]] = []
    for off in offsets:
        if grouped and off - grouped[-1][1] <= REGION_GAP:
            grouped[-1] = (grouped[-1][0], off)
        else:
            grouped.append((off, off))
    return grouped


def _printable(data: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in data)


def _byte(data: bytes, off: int) -> str:
    if off >= len(data):
        return "(past end)"
    value = data[off]
    glyph = chr(value) if 32 <= value < 127 else "."
    return "0x%02x %r" % (value, glyph)


def show_region(first: bytes, second: bytes, span: tuple[int, int],
                indent: str = "    ") -> None:
    """One differing run, with enough context to see what changed.

    The point of the context is that a reader should not have to go and
    look anything up: a clock, a path or a version string is
    self-evident once the bytes around it are decoded.
    """
    lo, hi = span
    print("%sat %d (0x%x)%s: %s -> %s"
          % (indent, lo, lo,
             "" if lo == hi else " through %d (0x%x)" % (hi, hi),
             _byte(first, lo), _byte(second, lo)))
    start = max(0, lo - CONTEXT_BEFORE)
    stop = min(max(len(first), len(second)), hi + 1 + CONTEXT_AFTER)
    for label, data in (("first ", first), ("second", second)):
        window = data[start:min(stop, len(data))]
        print("%s  %s |%s|" % (indent, label, _printable(window)))
    print("%s         %s%s" % (indent, " " * (lo - start),
                               "^" * (hi - lo + 1)))


def compare(name: str, first: bytes, second: bytes,
            max_regions: int) -> int:
    """Report one artifact, returning the number of differing bytes."""
    size = "%d bytes" % len(first)
    if len(first) != len(second):
        size = "%d and %d bytes" % (len(first), len(second))
    offsets = diff_offsets(first, second)
    print("  %-24s %-22s %d differing byte%s"
          % (name, size, len(offsets), "" if len(offsets) == 1 else "s"))
    if not offsets:
        return 0
    spans = regions(offsets)
    for span in spans[:max_regions]:
        show_region(first, second, span)
    if len(spans) > max_regions:
        print("    ... and %d more differing region%s, not shown"
              % (len(spans) - max_regions,
                 "" if len(spans) - max_regions == 1 else "s"))
    return len(offsets)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--track", default="b", choices=sorted(TRACKS),
                    help="which firmware to build twice (default: b)")
    ap.add_argument("--gap", type=float, default=1.0, metavar="SECONDS",
                    help="wait between the two builds, so a wall-clock "
                         "reading of one-second resolution cannot be "
                         "captured identically twice (default: 1.0)")
    ap.add_argument("--max-regions", type=int, default=12, metavar="N",
                    help="context blocks printed per artifact; the byte "
                         "count is always exact (default: 12)")
    ap.add_argument("--compare", nargs=2, metavar=("FIRST", "SECOND"),
                    help="compare two existing files instead of building")
    args = ap.parse_args()

    if args.compare:
        first, second = args.compare
        for path in args.compare:
            if not os.path.exists(path):
                print("no such file: %s" % path, file=sys.stderr)
                return 2
        print("comparing %s against %s" % (first, second))
        differing = compare(os.path.basename(first), read(first),
                            read(second), args.max_regions)
        print("\n%s" % ("identical" if differing == 0
                        else "%d differing byte%s"
                             % (differing, "" if differing == 1 else "s")))
        return 0 if differing == 0 else 1

    spec = TRACKS[args.track]
    build_dir = os.path.join(REPO, spec["dir"])
    if not os.path.exists(os.path.join(build_dir, "CMakeCache.txt")):
        # Say what to run. A bench that has not configured this track
        # meets it once, and cmake's own "not a directory" three steps
        # away from here reads as something else entirely.
        print("Track %s is not configured on this bench. Run:\n  %s"
              % (args.track.upper(), spec["configure"]), file=sys.stderr)
        return 2

    cmake = cmake_exe()
    print("track %s, %s, %s" % (args.track.upper(), spec["dir"], cmake))

    first_pass = {}
    took = build(spec, cmake)
    for name in spec["artifacts"]:
        path = os.path.join(build_dir, name)
        if not os.path.exists(path):
            print("the build produced no %s" % path, file=sys.stderr)
            return 2
        first_pass[name] = read(path)
    print("  build 1: %.2f s" % took)

    if args.gap > 0:
        time.sleep(args.gap)
    took = build(spec, cmake)
    print("  build 2: %.2f s, %.1f s after the first" % (took, args.gap))
    print()

    total = 0
    for name in spec["artifacts"]:
        total += compare(name, first_pass[name],
                         read(os.path.join(build_dir, name)),
                         args.max_regions)

    print()
    if total == 0:
        print("reproducible: every artifact is byte-identical")
        return 0
    print("NOT reproducible: %d differing byte%s across %d artifact%s"
          % (total, "" if total == 1 else "s", len(spec["artifacts"]),
             "" if len(spec["artifacts"]) == 1 else "s"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
