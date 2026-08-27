#!/usr/bin/env python3
"""Build Track A with the build properties it cannot run without.

The implementation; tools/sketch.sh is a shim onto it and the CMake
track_a / flash_track_a targets invoke it. Ported from the shell version
so Windows and Linux can build Track A too - the logic and the reasons
below are that script's, unchanged.

Two build properties, and each is silent when it is missing:

  build.f_cpu=78000000L   MCK is 78 MHz here, not the 84 boards.txt
                          declares. micros() divides by this, so a wrong
                          value makes every measured rate wrong by 7.7%
                          and nothing complains.

  build.ldscript=...      linker/arduino_due_x_sram1.ld, which pins the
                          ADC capture ring to SRAM bank 1. Without it
                          the ring lands in .bss in bank 0 and contends
                          with the USB DMA for the same bus matrix
                          slave; it still links and still runs, and
                          costs 35-44 ADC overruns per 4 s at the full
                          rate.

platform.txt links with "-T{build.variant.path}/{build.ldscript}", so
the script path is resolved relative to the *installed variant
directory* rather than to the sketch or the repository. That is why the
path is computed here instead of written down: it is a chain of "../"
out of the Arduino data directory and back, and it is different on every
machine.

This is the ONLY place that knows those two properties. Repeating them
in CMakeLists.txt is how a Track A that links, runs, and silently
overruns gets built.

    python3 tools/sketch.py compile
    python3 tools/sketch.py upload            # discovers the port
    python3 tools/sketch.py upload COM7
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain                                            # noqa: E402

REPO = toolchain.REPO
SKETCH = os.path.join(REPO, "sketches", "bringup")
FQBN = "arduino:sam:arduino_due_x_dbg"
LDSCRIPT = os.path.join(REPO, "linker", "arduino_due_x_sram1.ld")

VID, PID_CONSOLE = 0x2341, 0x003D


def arduino_cli(explicit=None):
    if explicit:
        return explicit
    _dir, exe = toolchain.resolve("arduino_cli")
    if not exe:
        sys.exit("arduino-cli not found. Add a pattern to toolchains.json, "
                 "or pass --arduino-cli. Run: python3 tools/toolchain.py")
    return exe


def variant_path(cli):
    """Ask arduino-cli where the variant actually is.

    Asked for rather than assumed: it moves with the installed core
    version.
    """
    out = subprocess.run([cli, "board", "details", "--fqbn", FQBN,
                          "--show-properties"],
                         capture_output=True, text=True).stdout
    hits = [line.split("=", 1)[1].strip() for line in out.splitlines()
            if line.startswith("build.variant.path=")]
    if not hits:
        sys.exit(f"could not read build.variant.path for {FQBN}")
    return hits[-1]


def find_port(explicit=None):
    """The programming port, by USB VID/PID - the same on every OS."""
    if explicit:
        return explicit
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("needs pyserial to discover the port, or pass a port")
    hits = [p.device for p in list_ports.comports()
            if (p.vid, p.pid) == (VID, PID_CONSOLE)]
    if not hits:
        sys.exit("no programming port found (VID 2341 PID 003D); "
                 "pass one explicitly")
    if len(hits) > 1:
        sys.exit(f"more than one programming port: {hits}; pass one "
                 f"explicitly")
    return hits[0]


# One place decides where Track A builds and where it uploads from.
#
# These used to disagree: compile passed --build-path only when asked,
# so arduino-cli built into its own cache, while upload defaulted to
# build/track_a and flashed whatever had last been left there. The board
# then ran an image nobody had built, with no error anywhere - a Track A
# measurement taken nine hours after the source changed was still
# measuring the old firmware. Silent staleness on the path the oracle
# depends on is worse than a build failure.
BUILD_PATH = os.path.join(REPO, "build", "track_a")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", nargs="?", default="compile",
                    choices=["compile", "upload"])
    ap.add_argument("port", nargs="?")
    ap.add_argument("--arduino-cli")
    ap.add_argument("--build-path")
    ap.add_argument("--bin", help="binary to upload; found in the build "
                                  "path if omitted")
    args, passthrough = ap.parse_known_args()

    cli = arduino_cli(args.arduino_cli)

    if args.action == "upload":
        # Do NOT use `arduino-cli upload` here.
        #
        # The sam core's recipe does the 1200-baud touch and then points
        # bossac at the programming port with -U false. That works on
        # macOS, where ROM SAM-BA is reachable through the 16U2's UART.
        # On Windows the erased chip brings SAM-BA up on the NATIVE port
        # as 03EB:6124 instead, so bossac reports "No device found on
        # COM7" - having already erased the board. Measured: it wipes
        # Track B and leaves nothing behind.
        #
        # tools/flash.py already knows how to find SAM-BA and attribute
        # it to the right board, so hand it the binary arduino-cli built
        # rather than keeping a second, worse flash path here.
        binary = args.bin
        if not binary:
            build = args.build_path or BUILD_PATH
            cands = [os.path.join(build, f) for f in os.listdir(build)
                     if f.endswith(".bin")] if os.path.isdir(build) else []
            if len(cands) != 1:
                sys.exit(f"expected exactly one .bin in {build}, found "
                         f"{len(cands)}. Build first, or pass --bin.")
            binary = cands[0]

        argv = ["--bin", binary]
        if args.port:
            argv += ["--port", args.port]
        import flash
        saved, sys.argv = sys.argv, ["flash.py"] + argv
        try:
            return flash.main()
        finally:
            sys.argv = saved

    variant = variant_path(cli)
    # platform.txt links with -T{build.variant.path}/{build.ldscript}, so
    # this has to be relative and there is no absolute escape hatch. On
    # Windows the repository and the Arduino data directory can sit on
    # different drives, and then no relative path exists at all - say so
    # rather than letting relpath raise something unreadable.
    try:
        ldscript = os.path.relpath(LDSCRIPT, variant).replace("\\", "/")
    except ValueError:
        sys.exit(
            f"the linker script and the Arduino variant directory are on "
            f"different drives, so no relative path exists between them:\n"
            f"  script  {LDSCRIPT}\n"
            f"  variant {variant}\n"
            f"platform.txt resolves build.ldscript relative to the variant "
            f"directory, so move the repository onto the same drive as the "
            f"Arduino data directory, or move that with ARDUINO_DIRECTORIES_DATA.")
    print(f"==> variant  : {variant}")
    print(f"==> ldscript : {ldscript}")
    cmd = [cli, "compile", "--fqbn", FQBN,
           "--build-property", "build.f_cpu=78000000L",
           "--build-property", f"build.ldscript={ldscript}",
           # Where the shared wire contract lives. arduino-cli searches
           # this directory for Arduino libraries; CMake reaches the same
           # source through include_directories + an explicit file list.
           "--libraries", os.path.join(REPO, "lib")]
    cmd += ["--build-path", args.build_path or BUILD_PATH]
    return subprocess.call(cmd + passthrough + [SKETCH])


if __name__ == "__main__":
    sys.exit(main())
