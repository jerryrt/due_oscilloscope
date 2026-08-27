# Sharing the wire contract between the tracks

**Status: Phase 0 done and measured. Phases 1-6 open.**

Invariant 3 says the two toolchains share no source. This document
narrows that rule to the layer its own rationale is about, and plans the
move. Read `CLAUDE.md`'s invariant 3 first; this supersedes its blanket
wording, not its purpose.

## Why, and it is not a preference

The oracle argument is real: Track A is worth having because it programs
the same silicon independently, so a divergence in *behaviour* points at
one track's register sequence. That argument is about **hardware**. It
does not transfer to the wire contract, for a specific reason - two
hand-copies written from the same `docs/control-protocol.md` by the same
author are not independent. They are two homes for one misreading, plus
drift.

And the tracks already share protocol source. They just do it by hand:

- `sketches/bringup/playstat.h` says so in its own header - "Track A's
  copy of drivers/playstat.h, and deliberately a copy... byte-for-byte
  the other one and any edit belongs in both on the same day."
- `version.h` differs across tracks by one character (`FW_TRACK`) and a
  comment pointing at the other copy.

**It has already drifted, twice, and both were found rather than
predicted.**

- Track A's `frame.h` is missing `frame_crc32_update()` - the resumable
  CRC `ctl_respond()` needs, because the control protocol's checksum
  straddles the field it sits in. Track B's own comment on that function
  reads "a second copy of the polynomial loop is a second thing to get
  wrong", which is this document's argument written inside one track.
- `FW_VERSION_MAJOR/MINOR/PATCH` say **0.2.0** and `FW_VERSION_STR` says
  **0.1.0**, identically on both tracks. They reach different consumers:
  the numbers go to `CTL_OP_IDENTITY` (`drivers/ctl.c:172`), the string
  to the `v` console line (`main.c:45`, `bringup.ino:115`). So this
  board answers "which firmware are you" with 0.1.0 or 0.2.0 depending
  which channel you ask - while `measure.parse_identity` documents the
  two as interchangeable. Hand-copying kept them in sync at the wrong
  value.

## The boundary

**Shared.** The wire: frame layout and `FRAME_VERSION`, the CRC, the
playback-status record, `CTL_*` opcodes and packed structs,
`CTL_VERSION`, the firmware version numbers, and eventually `ctl.c`'s
framing and dispatch. `drivers/ctl.c` is 526 lines whose entire external
surface is three transport calls (`usb_ctl_read`/`usb_ctl_write`), the
CRC, `micros()`, and seven references to the load monitor. It touches no
register - grep it for `UOTGHS`, `DACC`, `ADC->`, `PIO`, `REG_` and the
count is zero.

**Not shared, and this is where invariant 3 keeps its force.** Register
programming: `usbdma`/`usb_cdc`, `acq`/`adc`/`dac`/`gen`/`play`
internals, clock, fault. Two independent programmings of the same
silicon is what the oracle is for.

**Legitimately per-track.** `FW_TRACK`, and essentially nothing else.

The test suite draws the same line without being asked to. Of six
track-conditional sites, five are "Track A has no control channel yet"
and dissolve; the sixth,
`test_link_health.py::test_core_did_not_rebuild_endpoints`, is about the
*Arduino core* rebuilding endpoint configuration, and Track B has no
core. Two independent lines of reasoning landing on the same boundary is
the best evidence available that it is drawn in the right place.

## The mechanism, measured 2026-08-26

**Phase 0 is done: an Arduino library, consumed by both builds.** No
symlinks - which matters on Windows - and no generated copies.

```
lib/due_shared/
  library.properties        # architectures=sam
  src/                      # the shared translation units
```

- **Track A**: `tools/sketch.py` passes `--libraries <repo>/lib`.
  `arduino-cli` finds `due_shared` and compiles `src/` into the sketch.
- **Track B**: `CMakeLists.txt` adds `lib/due_shared/src` to
  `include_directories` and lists the sources explicitly.

Verified at runtime rather than at compile time, because a header can be
found without its translation unit being linked: both binaries call a
function from the shared `.c` and print what it returns.

| build | reports |
|---|---|
| Track A, `arduino-cli` | `shared probe: 5eedbeef`, `track=A` |
| Track B, CMake | `shared probe: 5eedbeef`, `track=B` |

Smoke after: Track A 91 passed, Track B 110 passed.

`shared_probe.[ch]` was scaffolding and Phase 1 deleted it, as planned.

**Phase 1 found one constraint worth writing down.** A shared header
cannot include a per-track one: `arduino-cli` compiles a library with
the library's own include path and not the sketch's, so
`fw_version.h`'s `#include "track_id.h"` failed to resolve on Track A -
measured, as `track_id.h: No such file or directory` from inside the
shared file. The fix is also the better layering: the shared file is the
wire contract and does not need to know which track built the image, so
each track includes its own `track_id.h` alongside it. **Dependencies
point from per-track code into shared code, never back.**

## Phases

Each is independently verifiable, in the spirit of `CLAUDE.md`'s
bring-up order. Do not reorder.

| # | What | Verify | Status |
|---|---|---|---|
| 0 | The build mechanism | both binaries print the same value | **done** |
| 0.5 | Drain Track A's control bulk OUT; un-skip the command-port tests | 1 MB at the node, device counts every byte | **done** |
| 1 | `frame.h`, `playstat.h`, the version numbers; extract `track_id.h` | `v` and `CTL_OP_IDENTITY` agree - a new test | **done** |
| 2 | `frame_crc32_update` out of `drivers/stream.c` | both tracks link it; CRC tests pass | **done** |
| 3 | Split `ctl.h` into `ctl_wire.h` (shared) + device API | Track B control suite unchanged | **done** |
| 4 | Decouple `ctl.c` from `load_*` and the transport, behind accessors | Track B control suite unchanged | **done** |
| 5 | Share `ctl.c`; Track A implements the seam; `ctlver` 0 -> 3 | `test_control.py` runs on **both** tracks | open |
| 6 | Delete the hand-copies; rescope invariant 3; guard against regrowth | - | open |

## Two traps

**The binary selects which state issue #5 draws.** Every phase here
relocates code, and 2026-08-26 measured what that does: the same board
with the same wiring gives `all-DC` null on one image and 8 codes at z
69-148 on the next. **Re-baseline issue #5 after Phase 5, and never
compare arm amplitudes across a phase boundary.**

**One dependency is left in `ctl.c` on purpose, and Phase 5 must
settle it.** It still includes `sam.h` for `SystemCoreClock`, because
both tracks are the same silicon and spell that identically - and
`ctl_port.h` says in as many words that an accessor both tracks spell
the same is called directly, not wrapped. What is untested is whether a
file *inside the shared library* can reach the CMSIS header on Track A,
where the include path is the Arduino core's rather than the sketch's.
Phase 2 already found that a library cannot reach back into the sketch
folder. If it cannot reach CMSIS either, the answer is
`ctl_port_mck_hz()` and not a header hunt.

**A shared header is not a shared translation unit.** Phase 0 checks the
link and the runtime value for exactly this reason. Any later phase that
adds a shared `.c` must show it running on both tracks, not compiling on
both tracks.

**The two tracks are not the same language.** Track B is C throughout;
Track A is C++ - every sketch translation unit is `.cpp` or `.ino`. So
**every shared header that declares a function needs `extern "C"`
guards**, or the shared `.c` exports unmangled symbols that Track A
cannot link against. Phase 2 hit this with `frame.h` and it is now
guarded; `ctl_wire.h` and anything Phase 5 adds will need the same. The
failure is a link error with a mangled name in it, which reads as a
missing function rather than as a linkage mismatch.
