# Build container

A pinned image that builds the firmware and runs the board-free tests,
so the build environment stops being an unrecorded variable and this
repository can have a CI at all. **It does not touch the board tier.**
Nothing here changes how a measurement is taken.

Before any of it, the image has to be able to say what it is, and today
it cannot: the build is byte-deterministic apart from a wall-clock
stamp that carries no timezone. That is phase 0 and it is source-side,
independent of every container question below it.

This document is live work: it names open issues, and the decisions it
records have been taken rather than proposed.

## Scope

| in | out |
|---|---|
| build identity - what an image says it is | anything that opens a serial port |
| Track A and Track B firmware builds | the board tests |
| the board-free tier, `-m "not board"` | flashing - `bossac`, the 1200-baud touch, re-enumeration |
| static analysers over firmware and shared source | measurement of any kind |
| build provenance: commit, compiler, layout, image digest | |

## What this is not

**Not a test environment.** The board tier stays on metal. Three
container facts, measured on `linux-x1` rather than assumed:

| fact | consequence |
|---|---|
| `/sys` is the host's and is not namespaced: a container with no `--device` still lists `ttyACM0/1/2` with `vid=2341 pid=003d/003e` | `ports.find_all_ports()` is pure sysfs through pyserial, so discovery **succeeds** and every open then fails. The board fixture skips, and a skip matches no failure pattern |
| `--device` binds the node that existed at container start | the 1200-baud touch destroys and re-creates it, and `wait_for_quiet_bus()` exists because it can return under another name. Surviving that needs `-v /dev:/dev:rslave`, which is most of the isolation back |
| default caps give `ulimit -r` 0 and `SCHED_FIFO` EPERM | `rt.py` degrades and reports rather than raising, so a run produces numbers with the promotion silently absent |

Windows and macOS have no USB passthrough at all; the only Windows route
is `usbipd`, whose error is **optimistic** - see `docs/windows.md`.

**Not a codegen-diversity programme.** The owner ruled on 2026-09-02
that the compiler is not a suspect, which closes the codegen-fragility
half of #54. Two things follow and both are on #34: optimisation level
varies the binary as freely as a compiler does, so binary variation
never needed an install; and `windows-desk` already runs two compilers
with `-DARM_TOOLCHAIN_DIR`, no container involved. Clang arrives here
for **diagnostics**, and a build matrix is a capability this plan may
expose, never its justification.

## Why, then

| reason | the evidence, checked in this tree |
|---|---|
| **There is no CI, and no analysis beyond warnings.** No workflow directory, no `-Werror`, no `-fanalyzer`, no `cppcheck`, `clang-tidy`, `-fstack-usage` or sanitizer anywhere. `-Wall -Wextra` in `CMakeLists.txt` is the entire surface | a pinned image is what makes any of it runnable on every bench at once |
| **Build provenance exists as fields and is empty as data.** #59: of 6,658 stored rows, 1 carries a layout and 8 carry a compiler; `fw_layout` is present on 64 rows and null on all 64 | a commit read off the board, plus an image digest, makes the field mechanical instead of remembered |
| **The board-free tier has never run without a board.** `docs/testing.md` says the `board` marker is verified two ways and both are static | a container is the dynamic check, and the marker is what the whole tier rests on |

## Build identity: the stamp goes, the commit arrives

**The build is already bit-deterministic except for one string.** Four
consecutive clean builds of Track B on one bench differ by **2 bytes in
39,716** in the `.bin` and 2 in 175,116 in the `.elf`, at two fixed
offsets: the seconds digit of `__TIME__`, once in the console identity
line and once in the `DUEC` control-channel IDENTITY body. Neither
artifact carries an absolute build path or a `__FILE__`. Over a longer
window more of the same two strings diverges and nothing else moves.

**A wall-clock stamp cannot be compared, because it carries no
timezone.** `provenance._build_epoch()` parses it with `mktime` -
reader-local - and `_iso_epoch()` slices the flash log's `when` to 19
characters, discarding the `-0400` the log took care to write. One
stamp and one log line, parsed in four zones, span **twelve hours**
against a sixty-second comparison window:

| TZ | `_build_epoch` | `_iso_epoch` |
|---|---|---|
| America/New_York | 1788365035 | 1788208488 |
| Europe/Paris | 1788343435 | 1788186888 |
| Asia/Shanghai | 1788321835 | 1788165288 |
| UTC | 1788350635 | 1788194088 |

All 139 records in `records/flash-log.jsonl` are `-0400`, so writer and
reader agree today and this is latent. Its two consumers then part
company: `firmware()` compares two reader-local values and is invariant,
while **`build_is_current()` compares one against `git log --format=%at`,
a true epoch, and nothing cancels.** US Eastern moves to `-0500` on
2026-11-01, after which an image built before the transition parses one
hour *late* - so a stale image reads as newer than the commit and is
reported current. That is the unsafe direction, in the one check that
exists because a cached build shipped a stale image.

**What the stamp is for, and what does each job better.** `fw_version.h`
gives it three, and a commit answers all three:

| job | better answer |
|---|---|
| distinguish two builds of one version | with a reproducible build, two builds of one source state **are** one image. The case that remains is a dirty tree, and `tools/flash.py` already hashes the working-tree delta as `dirty_sha` |
| recover the commit on the board (`firmware()`) | state it, rather than infer it from wall-clock proximity within 60 s of a log entry |
| detect a stale image from a build cache (`build_is_current()`) | equality against HEAD - no clock, no slack, no DST. The cache that motivated it is also gone: `arduino-cli` is invoked by nothing and `enforce_clean_build` cleans every build of every track |

`fw_version.h` refuses a git SHA because "both toolchains need build
plumbing that can silently disagree". There is one build system now, and
one `add_compile_definitions` reaches all three targets.

The wrinkle worth naming: a configure-time value goes stale the moment
HEAD moves. It needs a build-time step - a `cmake -P` script rewriting a
generated header only when the value changes - or the feature ships
right on the day it was configured and wrong every day after.

## Decisions taken

| # | decision | what follows from it |
|---|---|---|
| **D1** | **Docker.** | Installed on `linux-x1` and working. The `docker` group is root-equivalent, so a shared CI runner would later want rootless; that is a migration, not a blocker |
| **D2** | **xPack 15.2.1-1.1, not the host's Debian toolchain.** | The container and the host therefore **do not** agree byte for byte, and are not meant to. The property is that two container builds agree, and two benches on the same pinned inputs agree. GCC 15's `gnu23` default cannot drift in: `CMAKE_C_STANDARD 11 REQUIRED` and `track_a.cmake`'s explicit `-std=gnu11`/`-std=gnu++11` pin it |
| **D3** | **Track A is in scope; the Arduino SAM core 1.6.12 ships in the image.** | `ARDUINO_SAM_CORE` is a `-D` and `cmake/track_a.cmake` errors with the install line when it is absent, so no code changes. `toolchains.json` rejects `*/packages/arduino/tools/arm-none-eabi-gcc/*` by pattern, so the core cannot shadow the xPack with the bundled 4.8.3 |
| **D4** | **`clang` and `clang-tidy` ship in the image. `clang-tidy` runs now; clang as a firmware compiler is optional and later.** | The two halves cost differently. `clang-tidy` needs a `compile_commands.json` and a filter for arm-gcc-only flags it rejects. Clang as a *firmware* compiler is a port - target triple, a sysroot at the GCC toolchain's newlib and libgcc, and linking through the GCC driver - so it is phase 5, with its own exit criterion. `CLAUDE.md`'s "no second C dialect" is amended in the same change: its argument was MSVC's `#pragma pack` against `__attribute__((packed))`, and clang honours the GCC attribute |
| **D5** | **Built from a `Dockerfile` in the tree, cached locally, no registry.** | "Same Dockerfile" is then not "same image" unless every input is pinned - see the constraint below. With no registry there is no shared digest, so the cross-bench claim is **same pinned inputs**, not same image ID |
| **D6** | **An `-O`-level matrix is deferred.** | Consistent with #34: optimisation level is the free source of binary variation, and this plan is not justified by wanting any |
| **D7** | **`-Werror` on every bench, with one option to turn it off, which the image never uses.** | Free today: Track B and Track A both build **0 warnings** on GCC 14.2.1. The escape hatch is for the three-compiler reality - a warning that only 15.2.1 emits must not fail someone else's build while they are mid-diagnosis on something unrelated |
| **D9** | **`CTL_VERSION` is bumped when `build[24]` changes meaning.** | The layout is unchanged, so an old host does not fail - it silently parses a SHA as a date, which is what the hard break exists to prevent. `ctlver` 3 to 4 on all three tracks, reflashed together, with `docs/control-protocol.md`, `measure.parse_identity` and the suite's version assertions moving in the same change |
| **D10** | **Bit-identity is a script under `tools/`, run by the image build, not a test.** | Keeps a second build out of the board-free tier and away from #50's ceiling. It must still *run*: a check living in a stage nobody executes is the guard that cannot fail, which this project has already paid for |

The release is **xpack-arm-none-eabi-gcc-15.2.1-1.1**, which this project
already uses: `docs/toolchain.md` records it as `mac-bench`'s Track B
compiler and as `windows-desk`'s opt-in second arm. The container
therefore introduces no fourth code generator - it standardises on one
already characterised here. Its images carry that generator while both
other benches' default builds carry ARM GNU 14.x, so a container image
and a bench's own build are not expected to agree byte for byte, and
`docs/toolchain.md` is where the two generators are told apart.

## Constraints carried in

| constraint | source |
|---|---|
| **Every input to the image is pinned by digest** - base image, apt package versions, the xPack tarball, the SAM core. Otherwise two benches build one `Dockerfile` weeks apart and get different compilers, which silently destroys the property D2 was chosen for | D5 |
| Every build is a full build, enforced by `enforce_clean_build` and `tests/test_clean_build.py`. A container must not become the reason to relax it | an incremental build shipped a mixed-revision image here |
| A second-compiler pass must **not** go in the test suite | #34; roughly doubles it, against #50's ceiling |
| MSVC never. `frame.h` is `__attribute__((packed))` and MSVC wants `#pragma pack`, so admitting it would change the packing semantics of the shared wire contract | `CLAUDE.md` |
| Sanitizers cannot run on bare metal. They belong on the host-run tier, which already exists behind `stream_port.h` | `tests/test_framer_close.py`, `tests/test_console_out.py` |
| `ctl_wire.h`'s `build[24]` is a wire field holding 20 characters today. A short SHA and a dirty marker fit; the layout does not change and the meaning does | `docs/control-protocol.md` |

## Phases

Each phase lands on `main` on its own and is useful alone.

| # | phase | exit criterion | how it is broken on purpose |
|---|---|---|---|
| 0 | Build identity: the commit and a dirty marker replace `__DATE__ __TIME__`; `firmware()` and `build_is_current()` become equality tests; `parse_identity` follows | build twice with no commit between and `cmp` reports **0** differing bytes, where it reports 2 today | `git commit --allow-empty` and rebuild: the embedded value must change |
| 1 | The image: xPack plus the SAM core, building Track A and Track B, with the bit-identity script under `tools/` run by the build | two builds in the image are byte-identical, and a second machine building from the same pinned inputs reproduces them | unpin one input - the base image tag, an apt version - and watch the bytes move |
| 2 | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | Analysers that do not change codegen: `-fanalyzer`, `cppcheck`, `clang-tidy`, `-fstack-usage`, and `-Werror` with its off switch | each finds a real finding or is proven able to, **and** the analysed build stays byte-identical to the plain one | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | Provenance: commit read off the board, image digest and compiler recorded with the build | a row written after a containerised build carries a non-null commit, compiler and layout, which #59 says 696, 8 and 1 rows respectively manage today | build from a second image and watch the digest change |
| 5 | Clang as an optional firmware compiler: target triple, sysroot at the GCC toolchain, linking through the GCC driver | both tracks build and the images run on the board, with the compiler read back out of the ELF | build with the sysroot removed and watch the link fail rather than silently pick up host headers |
| 6 | Host-run tier hardening: UBSan and a fuzzer over `stream_core.c` and the control parser | the mutant harness still fails, as `test_framer_close.py` requires | as that test already does |

Phase 0 changes phase 1's exit criterion from a layout hash to a byte
comparison, which is why it comes first. Phases 0-4 are the plan;
5 and 6 are what is worth doing after it.

## What this plan does not answer

Whether a containerised build should ever produce an image that goes on
a board. It can - the artifact is a `.bin` and flashing is a host step -
but every measurement then attributes to an image built somewhere no
bench can reproduce by hand. That is a provenance question for #59, not
a build question.
