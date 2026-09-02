# Build container

A pinned image that builds the firmware and runs the board-free tests,
so the build environment stops being an unrecorded variable and this
repository can have a CI at all. **It does not touch the board tier.**
Nothing here changes how a measurement is taken.

This document is live work: it names open issues, and the decisions at
the end are the owner's rather than settled.

## Scope

| in | out |
|---|---|
| Track B firmware build | anything that opens a serial port |
| the board-free tier, `-m "not board"` | the board tests |
| static analysers over firmware and shared source | flashing - `bossac`, the 1200-baud touch, re-enumeration |
| build provenance: compiler, layout, image digest | measurement of any kind |

## What this is not

**Not a test environment.** The board tier stays on metal. Three
container facts, measured on `linux-x1` at `b9bff64` rather than assumed:

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
is therefore a **capability the plan may expose, never its
justification.**

## Why, then

| reason | the evidence, checked in this tree |
|---|---|
| **There is no CI, and no analysis beyond warnings.** No workflow directory, no `-Werror`, no `-fanalyzer`, no `cppcheck`, `clang-tidy`, `-fstack-usage` or sanitizer anywhere. `-Wall -Wextra` in `CMakeLists.txt` is the entire surface | a pinned image is what makes any of it runnable on every bench at once |
| **Build provenance exists as fields and is empty as data.** #59: of 6,658 stored rows, 1 carries a layout and 8 carry a compiler; `fw_layout` is present on 64 rows and null on all 64 | an image digest plus a compiler read back out of the ELF makes the field mechanical instead of remembered |
| **The board-free tier has never run without a board.** `docs/testing.md` says the `board` marker is verified two ways and both are static | a container is the dynamic check, and the marker is what the whole tier rests on |

## Constraints carried in

| constraint | source |
|---|---|
| Every build is a full build, enforced by `enforce_clean_build` and `tests/test_clean_build.py`. A container must not become the reason to relax it | an incremental build shipped a mixed-revision image here |
| A second-compiler pass must **not** go in the test suite | #34; roughly doubles it, against #50's ceiling |
| GCC for the firmware, MSVC never. `tests/hostcc.py` already accepts `clang` for the host-run tier | `CLAUDE.md`; `frame.h` is `__attribute__((packed))` |
| Sanitizers cannot run on bare metal. They belong on the host-run tier, which already exists behind `stream_port.h` | `tests/test_framer_close.py`, `tests/test_console_out.py` |
| The image is not bit-reproducible: `__DATE__ __TIME__` is compiled into the identity string in `console.c` and both `ctl_port` implementations | which is also why `sha256` cannot discriminate - `tools/image_fingerprint.py` says so |
| `vendor/` holds CMSIS only. Track A globs its sources out of an installed Arduino SAM core 1.6.12 | `cmake/track_a.cmake`; a Track A image must supply it |

The build path does **not** leak into the image - no absolute path and
no `__FILE__` survives into `baremetal_bringup.bin` - so building at a
container path rather than a home directory does not perturb the
artifact. That is what makes phase 1's exit criterion meaningful.

## Phases

Each phase lands on `main` on its own and is useful alone. No phase
depends on a decision below it being answered a particular way.

| # | phase | exit criterion | how it is broken on purpose |
|---|---|---|---|
| 1 | An image that builds Track B, toolchain resolved through `toolchains.json` or `ARM_TOOLCHAIN_DIR` | `tools/image_fingerprint.py` gives the **same `layout` twice** in the container, and the same value the host gives for the same commit when the image carries the same toolchain package. A difference is a finding: something else in the environment is a variable | point `ARM_TOOLCHAIN_DIR` at a different toolchain and watch the layout move |
| 2 | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | Analysers that do not change codegen: `-fanalyzer`, `-Werror` in the image only, `cppcheck`, `-fstack-usage` | each finds a real finding or is proven able to, **and** `tools/image_mnemonics.py` gives identical per-function hashes with and against the analyser build | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | Provenance: image digest recorded with the build, compiler read back out of the ELF | a row written after a containerised build carries a non-null compiler and layout, which #59 says 8 and 1 rows respectively manage today | build with a second image and watch the digest change |
| 5 | Host-run tier hardening: UBSan and a fuzzer over `stream_core.c` and the control parser | the mutant harness still fails, as `test_framer_close.py` requires | as that test already does |

Phases 1-4 are the plan. Phase 5 is the first thing worth doing after
it, and is listed so it is not mistaken for scope.

## Decisions

Indexed for reply. None of these blocks phase 1.

| # | decision | what hangs on it |
|---|---|---|
| **D1** | Docker, or Podman rootless? | Podman needs no daemon group and matches how a CI runner would be sandboxed; Docker is what is installed on `linux-x1` today |
| **D2** | Does the image pin **this bench's** toolchain (Debian `gcc-arm-none-eabi` 14.2.1, generator A) or a downloaded xPack? | pinning Debian's makes phase 1's exit criterion an equality against the host and is the cheaper first move; xPack makes the image independent of a distribution |
| **D3** | Is Track A in scope? It needs the Arduino SAM core 1.6.12 in the image | the core is currently found per machine by pattern, so putting it in the image pins a version that nothing pins today. Cost is image size and a licence question |
| **D4** | Does `clang-tidy` count as a second dialect? | the ruling's stated reason is MSVC's packing of `frame.h`, and `hostcc.py` already reaches for `clang`. An analyser emits no artifact, but extending the ruling is the owner's |
| **D5** | Where does the image live - built from a `Dockerfile` in the tree on demand, or pushed to a registry and pulled by digest? | a digest in `provenance` is only meaningful if the image is addressable. Building on demand keeps the tree self-contained and makes the digest local |
| **D6** | Does a build matrix over `-O` levels get built in phase 1, or deferred? | #34 argues optimisation level is the free source of binary variation. It is one CMake flag per arm and needs no second toolchain, but it is out of scope as justification |
| **D7** | Is `-Werror` in the image only, or on every bench? | in the image it cannot break someone mid-diagnosis; on every bench it catches the warning at the moment it is introduced |

## What this plan does not answer

Whether a containerised build should ever produce an image that goes on
a board. It can - the artifact is a `.bin` and flashing is a host step -
but every measurement then attributes to an image built somewhere no
bench can reproduce by hand. That is a provenance question for #59, not
a build question.
