# Sharing the wire contract between the tracks

**Status: phases 0-8 done, 2026-08-28.** What is left is not in
this plan: Track A has no rate trace, and answers
that opcode with `CTL_ERR_OPCODE`. That is honest rather than
missing.

Invariant 3 keeps the two toolchains' *hardware* source apart and
shares the rest. This document is the reasoning behind that line, the
plan that moved the code across it, and what the move found. Read
`CLAUDE.md`'s invariant 3 first; the boundary is stated there, and this
is why it sits where it does.

## Why, and it is not a preference

The oracle argument is real: Track A is worth having because it programs
the same silicon independently, so a divergence in *behaviour* points at
one track's register sequence. That argument is about **hardware**. It
does not transfer to the wire contract, for a specific reason - two
hand-copies written from the same `docs/control-protocol.md` by the same
author are not independent. They are two homes for one misreading, plus
drift.

And before the move the tracks already shared protocol source. They
did it by hand:

- `sketches/bringup/playstat.h` said so in its own header - "Track A's
  copy of drivers/playstat.h, and deliberately a copy... byte-for-byte
  the other one and any edit belongs in both on the same day."
- each track's `fw_version.h` differed from the other's by one character
  (`FW_TRACK`) and a comment pointing at the other copy.

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
framing and dispatch.

**And, from Phase 7, the application layer above the drivers**: the
console's command surface (`console.c`) and the main-loop load monitor
(`load.c`). The boundary below is unchanged - what moved is code that
was never register programming and had been written twice because the
first rescope stopped at the wire. `drivers/ctl.c` is 526 lines whose entire external
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

- **Track A**: `cmake/track_a.cmake` globs `lib/due_shared/src/*.c` into
  the image directly (`A_SHARED_C`).
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
| 5 | Share `ctl.c`; Track A implements the seam; `ctlver` 0 -> 3 | `test_control.py` runs on **both** tracks | **done** |
| 6 | Delete the hand-copies; rescope invariant 3; guard against regrowth | the guard fails on a planted violation | **done** |
| 7 | Share the console surface and the load monitor | both tracks answer `h` with the same list and report no missing commands | **done** |
| 8 | Share the framer: `stream_core.c` behind `stream_port.h` | the seam check holds header and extraction equal both ways; full suites both tracks | **done** |

## Phase 7: the console and the load monitor, 2026-08-28

Phase 6 rescoped invariant 3 for the *wire* and stopped there. The
console was left as two hand-written dispatchers, and issue #13 measured
what that cost: **29 commands shared, 8 on Track B only, 4 on Track A
only.** Divergence was the default state rather than an oversight,
because every console command had to be written twice or it existed on
one track only.

It cost a measurement. Running the metric pipeline on Track A the board
hit objective 0c - the macOS `close()` wedge - and Track A had no `Z`,
the software unplug that releases it, because `Z` had been written on
the track where the wedge was being chased. Two metrics are missing from
`docs/metric-baseline-macos-track-a.md` for that reason.

**The split is the one the control channel already uses.** Shared:
which letters are commands, what arguments they take, what `h` says, and
what happens to a letter this track has not got. Per track: what a
letter does, because every handler ends at a register.
`console_port.h` is the seam and it is two functions, held there by the
same rule `ctl_port.h` states about itself.

**The behaviour that could not exist before.** A command in the shared
table that a track has not bound is *answered* - "not implemented on
this track" - rather than falling into `default: break`. It is the
console's `CTL_ERR_OPCODE`, for the same reason: silence is a
measurement. Typing `Z` at Track A was indistinguishable from typing it
at a board that had detached and come back. A letter that is not a
command at all is still ignored in silence, which is what keeps stray CR
and LF free.

`console_missing()` computes the parity list from the binding table, so
the count is never again something anyone holds in their head. Both
tracks now print `not implemented on this track: none`.

**The load monitor moved for a different reason and it is worth keeping
the two apart.** `load.c` is an instrument, not a surface. The only
register it touches is DWT's cycle counter, which is core rather than
peripheral and is the same counter on both builds by construction, so
invariant 3's "two programmings of one peripheral" argument has nothing
to bite on. Transliterating it would have bought a second place for the
histogram arithmetic to be wrong.

**Costs, measured on the macOS bench.** Splitting the boot banner from
the command list made boot cheaper and `h` dearer:

| | bytes | ms |
|---|---|---|
| boot banner, before | - | 89 (recorded) |
| boot banner, after | 384 | 33 |
| `h` (banner + 47-line list + parity) | 2417 | **208.10** on the load monitor, 210 by byte count |

The two `h` figures agree to 1%, which is one more confirmation of
invariant 8's rule that the cost of a console command is the bytes it
puts on the wire. The load monitor reproduced `B` at 13.14 ms and `O` at
15.40 ms - both exactly the recorded figures - which is why the rest is
trusted.

**What sharing the console found, the way sharing the parser found the
per-track opcodes.** Three divergences that had nothing to do with the
console and were invisible while each track was read on its own:

- **Track A's idle main loop is 2.14x slower.** 75.1 k passes/s against
  Track B's 160.4 k, three trials each, spread under 0.2%. Invariant 3
  requires the tracks to be comparable in performance and on the idle
  loop they are not.
- **The two tracks held different ADC configurations while idle.**
  Track B calls `adc_init()` in `main()`; Track A called `acq_init()`
  only on the paths that need it, so before a stream it answered
  `adcmr=10380200` - written by `analogRead()` inside the core - against
  Track B's own `2f3f0100`. Visible only once `?` read the register back
  instead of echoing what was asked for. Closed 2026-08-28: Track A
  initialises its own converters at boot.

  **The DAC half of this was wrong when first written and is retracted.**
  The idle `acr=000001aa` was reported as the core's too. It is not:
  Track B, which contains no Arduino core anywhere in the image, reads
  the same `000001aa` at boot after its own `DACC_CR_SWRST`. So `0x1aa`
  is what the DACC holds when nothing has written ACR, on either track,
  and only the ADC half was ever a divergence. The mistake was reading
  two unfamiliar register values side by side and attributing both to
  the one explanation that fitted the first.
- **Being on the Arduino core is not the same as getting the core's
  register writes.** The core sets `DACC_ACR` in `wiring_analog.c` the
  first time a DAC channel is enabled; Track A's gen and play never go
  through that path, so the sketch had been running at reset bias
  exactly as the bare-metal track was.

The first is open in issue #13. The second is closed - Track A
initialises its own converters at boot from 2026-08-28 - with the
retraction above attached to it. The third is closed: both tracks now
write ACR after every `DACC_CR_SWRST`.

## Two traps

**The binary selects which state issue #5 draws.** Every phase here
relocates code, and 2026-08-26 measured what that does: the same board
with the same wiring gives `all-DC` null on one image and 8 codes at z
69-148 on the next. **Re-baseline issue #5 after Phase 5, and never
compare arm amplitudes across a phase boundary.**

**Phase 5 settled it, and not the way Phase 4 guessed.** `ctl.c` no
longer includes `sam.h` or anything else per-track, because the
constraint turned out broader than one header: **a file inside the
shared library cannot include a header from a track's own folder at
all.** Measured, on moving `ctl.c` into `lib/due_shared/src`:
`track_id.h: No such file or directory`. On Track A `acq.h`, `play.h`,
`stream.h` and `track_id.h` all live in the sketch folder.

So the split is not "protocol versus hardware", which is where this
document started. It is **what every board does the same way versus what
a board has to look up locally.** Framing, the CRC, header validation,
the receive state machine, the idle timeout, dispatch and every error
path are the same everywhere and are shared - about two thirds of the
file. Filling a response body means reading this track's counters, and
that is `ctl_port.c`, one function per opcode.

**And two of the eight opcodes turned out not to be protocol at all.**
`ctl_stream_stats_t` and `ctl_bench_t` carry `usb_reset`, `usb_setup`,
`usb_stall`, `usb_configured`, `usb_devisr`, `usb_ep0isr` and
`usb_devimr` - counters kept by Track B's *own USB stack*. Track A
enumerates through the Arduino core and has none of them. Sharing the
parser is what made that visible; it had been sitting inside a document
described as a contract between the two tracks.

**Hence the rule: an opcode a track does not implement is answered with
`CTL_ERR_OPCODE`, never with a body of zeroes.** Zero is a measurement -
"the counter is there and read nothing" - and a host cannot tell that
from "this firmware does not count that". It covers stream stats, bench,
the load monitor and the rate trace. `tests/test_control.py` carries the
capability table, so a refusal is tolerated only where it is expected
and Track B losing its stream stats still fails.

**One more language fact.** `_Static_assert` is C11 and Track A is C++,
which spells it `static_assert`. A header both tracks compile can use
neither name directly; `ctl_wire.h` defines `CTL_STATIC_ASSERT`.

**Phase 7 answered the `SystemCoreClock` question, and not by finding a
header.** `load.c` needs the master clock to turn cycles into
microseconds. It does not include `sam.h` or `Arduino.h` - it writes

    extern uint32_t SystemCoreClock;

and links. The symbol is CMSIS-standard, `system_sam3xa.c` defines it on
both tracks, and a declaration needs no include path at all. Verified by
the value rather than by the link: `=500S` on both tracks reports
499,183 us and 499,580 us for a 500 ms stall, which only comes out right
if the divisor is 78 MHz.

The same trick covers DWT and DEMCR, which are spelled by address
(0xE0001000, 0xE000EDFC). They are architectural on Cortex-M3 and
identical on both builds, so there is nothing for a device header to
tell us.

**The earlier note, kept because the guess was wrong:** It still includes `sam.h` for `SystemCoreClock`, because
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

## Phase 8: the framer, 2026-08-28 (issue #14)

`stream.c` and `stream.cpp` were 780 lines of policy written twice,
five register lines between them. Frame building, sequencing, overrun
accounting and the resync rule now live once in
`lib/due_shared/src/stream_core.c`; `stream_port.h` records every name
the framer reaches outside itself, and `tests/test_shared_source.py`
holds that record equal to a fresh extraction in both directions
(`tools/stream_seam.py`). The seam is functions *and extern data* -
the framer reads `acq_produced`, `acq_consumed`, the overrun counters
and `play_consumed` directly, which the issue's hand-made table
missed and extraction found.

What stayed per track, on purpose: the transport shims
(`stream_port_write`/`stream_port_ready` - uart/usb_cdc on B, the
core's Serial objects on A), the bench arms and their buffers, the
reports and STREAM_STATS (per-track surface, #7), and every register.
The bench arms are the remaining candidate for a later pass, after
their numbers are re-taken either side of this move.

The move paid for itself before it landed: reading the two copies
side by side surfaced that `6c96eed` had armed capture DMA in one of
Track B's two start functions and not the other, so every capture-only
stream ran the CPU path for six days (`db08d76` fixed it, and the fix
in turn handed issue #20 its strongest constraint yet). One shared
start function is why that cannot recur.

## Phase 9: the frame's own numbers, 2026-08-30 (issue #45)

The boundary above says the wire is shared. Three of the wire's numbers
were not.

**The geometry.** `ACQ_BUF_SAMPLES` 2032, `ACQ_HDR_BYTES` 32 and the
frame-size expression sat in `drivers/acq.h` *and*
`sketches/bringup/acq.h`. `frame.h` described them in prose - including
why the size is load-bearing, since moving `ACQ_BUF_SAMPLES` off 2032
cost the ramp test 4 runs in 15 against 0 in 15 - while defining none of
them. They now live in `frame.h` and each track's `acq.h` keeps its own
spelling.

Two things improved rather than moved. `FRAME_HDR_BYTES` is derived from
`sizeof(frame_header_t)` instead of asserted by a comment: both copies
wrote `32` with a comment *claiming* it was the struct's size and
nothing checked it, so a field added to the header would have left the
number behind on both tracks at once and the payload would have started
inside the header. And the static assert that a frame is a whole number
of 512-byte packets travels with the constants, which matters because
**only Track B had one**.

**The channel tags.** `ADC_CH_A0/A1/A2` in `drivers/analog.h`,
`ACQ_CH_A0/A1/A2` in `sketches/bringup/acq.h`, and `CH_A0/A1/A2` in
`host/measure.py` - one wire fact in three homes. Every sample carries
its channel index and the header carries `channel_mask` over the same
indices, so these are precisely what a reader on the far end matches
against. The two firmware copies now spell them from `FRAME_CH_*`.

The third home is the host and cannot include a C header, so it is held
by a test instead (`test_the_host_channel_tags_match_the_firmware`).
That failure mode deserves the test: a tag the host does not recognise
produces an **empty series rather than an error**, so a divergence would
read as a dead channel rather than as a bug.

The A-label table moved with the values, because the numbers are not
obvious - Arduino's A0..A7 map to ADC channels in *descending* order, so
A0 is AD7 - and it existed only in Track B's header. Track A carried
7, 6 and 5 with no note of where they came from.

**What was deliberately left alone.** The TC and ADC register bit
constants (`WAVSEL_UP_RC`, `ACPA_CLEAR`, `TRGSEL_TIOA0`) differ in
comments between the tracks and could trivially be shared. They are not,
and should not be: a datasheet bit transcribed twice is two independent
readings of the datasheet, which is the oracle doing its job. Sharing
them would buy tidiness with the thing invariant 3 exists to protect.

The measured rate floors (`ACQ_MIN_RC` 86, `ACQ_MIN_RC_1CH` 44,
`ACQ_MIN_RC_3CH` 132) are left per track for the same reason: each is a
measurement, and one measurement reaching both tracks is not two
measurements.

**A capability gap this surfaced, deferred rather than fixed.** Track B
accepts 1, 2 or 3 channels; Track A refuses more than 2 and therefore
has no three-channel floor. That is invariant 3's "debt with a date on
it", and it already cost something: issue #43's three-channel
measurement - A0 driven, A1 undriven, A2 bare, one matched capture -
**cannot be reproduced on Track A**, so the oracle cannot check it.
Tracked in issue #46, which the owner will schedule; the headers and
this document were consolidated first so the gap is visible rather than
implied.
