# Build container

A pinned image that builds the firmware and runs the board-free tests,
so the build environment stops being an unrecorded variable and this
repository can have a CI at all. **It does not touch the board tier.**
Nothing here changes how a measurement is taken.

Before any of it, the image has to be able to say what it is, and today
it cannot: the build is byte-deterministic apart from a wall-clock
stamp that carries no timezone. That is phase 0 and it is source-side,
independent of every container question below it.

This document is live work: it names open issues, and the decisions at
the end are the owner's rather than settled.

## Scope

| in | out |
|---|---|
| build identity - what an image says it is | anything that opens a serial port |
| Track B firmware build | the board tests |
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
with `-DARM_TOOLCHAIN_DIR`, no container involved. A build matrix here
is a **capability the plan may expose, never its justification.**

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
one `add_compile_definitions` reaches all three targets. The choice
between a commit and a frozen stamp is settled: **the commit.**

The wrinkle worth naming: a configure-time value goes stale the moment
HEAD moves. It needs a build-time step - a `cmake -P` script rewriting a
generated header only when the value changes - or the feature ships
right on the day it was configured and wrong every day after.

## Constraints carried in

| constraint | source |
|---|---|
| Every build is a full build, enforced by `enforce_clean_build` and `tests/test_clean_build.py`. A container must not become the reason to relax it | an incremental build shipped a mixed-revision image here |
| A second-compiler pass must **not** go in the test suite | #34; roughly doubles it, against #50's ceiling |
| GCC for the firmware, MSVC never. `tests/hostcc.py` already accepts `clang` for the host-run tier | `CLAUDE.md`; `frame.h` is `__attribute__((packed))` |
| Sanitizers cannot run on bare metal. They belong on the host-run tier, which already exists behind `stream_port.h` | `tests/test_framer_close.py`, `tests/test_console_out.py` |
| `ctl_wire.h`'s `build[24]` is a wire field holding 20 characters today. A short SHA and a dirty marker fit; the layout does not change and the meaning does | `docs/control-protocol.md` |
| `vendor/` holds CMSIS only. Track A globs its sources out of an installed Arduino SAM core 1.6.12 | `cmake/track_a.cmake`; a Track A image must supply it |

## Phases

Each phase lands on `main` on its own and is useful alone. No phase
depends on a decision below it being answered a particular way.

| # | phase | exit criterion | how it is broken on purpose |
|---|---|---|---|
| 0 | Build identity: the commit and a dirty marker replace `__DATE__ __TIME__`; `firmware()` and `build_is_current()` become equality tests; `parse_identity` follows | build twice with no commit between and `cmp` reports **0** differing bytes, where it reports 2 today | `git commit --allow-empty` and rebuild: the embedded value must change |
| 1 | An image that builds Track B, toolchain resolved through `toolchains.json` or `ARM_TOOLCHAIN_DIR` | the container and the host produce a **byte-identical** `.bin` for one commit when the image carries the same toolchain package. A difference is a finding: something else in the environment is a variable | point `ARM_TOOLCHAIN_DIR` at a different toolchain and watch the bytes move |
| 2 | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | Analysers that do not change codegen: `-fanalyzer`, `-Werror` in the image only, `cppcheck`, `-fstack-usage` | each finds a real finding or is proven able to, **and** the analysed build stays byte-identical to the plain one | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | Provenance: image digest recorded with the build, compiler read back out of the ELF | a row written after a containerised build carries a non-null commit, compiler and layout, which #59 says 696, 8 and 1 rows respectively manage today | build with a second image and watch the digest change |
| 5 | Host-run tier hardening: UBSan and a fuzzer over `stream_core.c` and the control parser | the mutant harness still fails, as `test_framer_close.py` requires | as that test already does |

Phase 0 changes phase 1's exit criterion from a layout hash to a byte
comparison, which is why it comes first. Phases 0-4 are the plan; phase
5 is the first thing worth doing after it, listed so it is not mistaken
for scope.

## Decisions

Indexed for reply. None of these blocks phase 0 or phase 1.

| # | decision | what hangs on it |
|---|---|---|
| **D1** | Docker, or Podman rootless? | Podman needs no daemon group and matches how a CI runner would be sandboxed; Docker is what is installed on `linux-x1` today |
| **D2** | Does the image pin **this bench's** toolchain (Debian `gcc-arm-none-eabi` 14.2.1, generator A) or a downloaded xPack? | pinning Debian's makes phase 1's exit criterion an equality against the host and is the cheaper first move; xPack makes the image independent of a distribution |
| **D3** | Is Track A in scope? It needs the Arduino SAM core 1.6.12 in the image | the core is currently found per machine by pattern, so putting it in the image pins a version that nothing pins today. Cost is image size and a licence question |
| **D4** | Does `clang-tidy` count as a second dialect? | the ruling's stated reason is MSVC's packing of `frame.h`, and `hostcc.py` already reaches for `clang`. An analyser emits no artifact, but extending the ruling is the owner's |
| **D5** | Where does the image live - built from a `Dockerfile` in the tree on demand, or pushed to a registry and pulled by digest? | a digest in `provenance` is only meaningful if the image is addressable. Building on demand keeps the tree self-contained and makes the digest local |
| **D6** | Does a build matrix over `-O` levels get built in phase 1, or deferred? | #34 argues optimisation level is the free source of binary variation. It is one CMake flag per arm and needs no second toolchain, but it is out of scope as justification |
| **D7** | Is `-Werror` in the image only, or on every bench? | in the image it cannot break someone mid-diagnosis; on every bench it catches the warning at the moment it is introduced |
| **D9** | `ctl_wire.h`'s `build[24]` keeps its layout and changes its meaning. Is that a `CTL_VERSION` bump? | a host that parses the field as a date misreads a SHA. `CTL_VERSION` is a hard break by design, and the device rejects a frame whose version is not its own |
| **D10** | Is bit-identity enforced by a test that builds twice and requires `cmp` = 0, or documented? | enforcing it costs a second build in the board-free tier, against #50's ceiling |

## What this plan does not answer

Whether a containerised build should ever produce an image that goes on
a board. It can - the artifact is a `.bin` and flashing is a host step -
but every measurement then attributes to an image built somewhere no
bench can reproduce by hand. That is a provenance question for #59, not
a build question.
