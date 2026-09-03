# Build container

A pinned image that builds the firmware and runs the board-free tests,
so the build environment stops being an unrecorded variable and this
repository can have a CI at all. **It does not touch the board tier.**
Nothing here changes how a measurement is taken.

Before any of it, the image has to be able to say what it is. That is
phase 0, it is source-side and independent of every container question
below it, and it has landed: an image names the commit it was built
from and two builds of one clean commit are identical to the byte.

This document is live work: it names open issues, and the decisions it
records have been taken rather than proposed.

## Scope

| in | out |
|---|---|
| build identity - what an image says it is | anything that opens a serial port |
| Track A and Track B firmware builds | the board tests |
| the board-free tier, `-m "not board"` | flashing - `bossac`, the 1200-baud touch, re-enumeration |
| static analysers over firmware and shared source | measurement of any kind |
| build provenance: commit, compiler, image digest, and the symbol map with the caveat #63 puts on `layout` | |

## What this is not

**Not a test environment.** The board tier stays on metal. Three
container facts, measured on `linux-x1` rather than assumed:

| fact | consequence |
|---|---|
| `/sys` is the host's and is not namespaced - a container with no `--device` lists `ttyACM0/1/2` under `/sys/class/tty` with `vid=2341 pid=003d/003e` - but `/dev` holds no node, and pyserial's Linux backend globs `/dev` before it annotates from sysfs | so `comports()` returns nothing and `find_all_ports()` returns `(None, None, None)`. The board fixture skips, and a skip matches no failure pattern. **Pass `/dev` in and discovery starts working**, which is where the trap moves to: the row below recommends exactly that for surviving re-enumeration |
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

## Build identity

**An image names its own commit and the build is byte-reproducible.**
`FW_GIT_REV` is the short revision, plus `+` and eight characters of the
working-tree delta hash on a dirty tree, or `unknown` where git could
not answer; `cmake/fw_git_rev.cmake` writes it from a `cmake -P` step
run by every firmware build of every track, because a configure-time
value is right on the day the tree was configured and silently wrong
every day after. It reaches the `v` identity line and the `DUEC`
control-channel IDENTITY body, and `tools/reproducible.py` reports 0
differing bytes on both tracks.

Every question a build identity is asked is then a graph question, with
no clock in it:

| question | how it is answered |
|---|---|
| distinguish two builds of one version | two builds of one clean source state **are** one image. The case that remains is a dirty tree, and the delta hash covers it - `tools/flash.py` logs it in full as `dirty_sha`, the image carries its first eight characters |
| recover the commit on the board (`firmware()`) | the board states it; the flash log is matched by equality against it |
| detect a stale image (`build_is_current()`) | whether the newest commit touching that track's firmware source is **reachable** from the image's commit. Equality would be wrong: most images are built at a commit that touched no firmware source at all, and would read stale every afternoon |

Reachability rather than a clock is what makes the answer the same in
every timezone. A wall clock carries no zone: `_build_epoch()` parses
one reader-local while `build_is_current()` compares it against `git
log --format=%at`, a true epoch, so nothing cancels and one image reads
current in one zone and stale in another. US Eastern moves to `-0500`
on 2026-11-01, and an image parsed an hour late reads as *newer* than
the commit that obsoleted it - the unsafe direction, in the one check
that exists because a build cache shipped a stale image. Images built
before the field carried a commit still go down that path; nothing new
does.

## Decisions taken

| # | decision | what follows from it |
|---|---|---|
| **D1** | **Docker.** | Installed on `linux-x1` and working. The `docker` group is root-equivalent, so a shared CI runner would later want rootless; that is a migration, not a blocker |
| **D2** | **xPack 15.2.1-1.1, not the host's Debian toolchain.** | The container and the host therefore **do not** agree byte for byte, and are not meant to. The property is that two container builds agree, and two benches on the same pinned inputs agree. GCC 15's `gnu23` default cannot drift in: `CMAKE_C_STANDARD 11 REQUIRED` and `track_a.cmake`'s explicit `-std=gnu11`/`-std=gnu++11` pin it |
| **D3** | **Track A is in scope; the Arduino SAM core 1.6.12 ships in the image.** | `ARDUINO_SAM_CORE` is a `-D` and `cmake/track_a.cmake` errors with the install line when it is absent, so no code changes. `toolchains.json` rejects `*/packages/arduino/tools/arm-none-eabi-gcc/*` by pattern, so the core cannot shadow the xPack with the bundled 4.8.3 |
| **D4** | **`clang` and `clang-tidy` ship in the image, pinned. Wiring `clang-tidy` up, and clang as a firmware compiler, are both later.** | The two halves cost differently. `clang-tidy` needs a `compile_commands.json` and a filter for arm-gcc-only flags it rejects. Clang as a *firmware* compiler is a port - target triple, a sysroot at the GCC toolchain's newlib and libgcc, and linking through the GCC driver - so it is phase 5, with its own exit criterion. `CLAUDE.md`'s "no second C dialect" is amended in the same change: its argument was MSVC's `#pragma pack` against `__attribute__((packed))`, and clang honours the GCC attribute |
| **D5** | **Built from a `Dockerfile` in the tree, cached locally, no registry.** | "Same Dockerfile" is then not "same image" unless every input is pinned - see the constraint below. With no registry there is no shared digest, so the cross-bench claim is **same pinned inputs**, not same image ID |
| **D6** | **An `-O`-level matrix is deferred.** | Consistent with #34: optimisation level is the free source of binary variation, and this plan is not justified by wanting any |
| **D7** | **`-Werror` on every bench, with one option to turn it off, which the image never uses.** | `-DFIRMWARE_WERROR=OFF`. Both tracks build 0 warnings on GCC 14.2.1, and on both it is cleanliness: `cmake/track_a.cmake` silences Track A's **vendored core only**, so the sketch and the shared sources it compiles are held to the project warning set. The escape hatch is for the three-compiler reality - a warning that only 15.2.1 emits must not fail someone else's build while they are mid-diagnosis on something unrelated |
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
| **A change to a wire contract is proven on hardware before it merges**, not after. `FRAME_VERSION`, `CTL_VERSION`, and the meaning of any field they carry. A version bump is a commitment every bench must act on: it obliges a reflash of all three tracks and takes the control channel down until they do, so a board on the old firmware cannot answer while the new host is asking. A merge is the wrong gate for that. Phase 0's bump landed with the round trip unexercised, and the board went out of contact with `main` until it was reflashed - the bump was right and its ordering was not | D9 |
| **Every input to the image is pinned by digest** - base image, apt package versions, the xPack tarball, the SAM core. Otherwise two benches build one `Dockerfile` weeks apart and get different compilers, which silently destroys the property D2 was chosen for | D5 |
| Every build is a full build, enforced by `enforce_clean_build` and `tests/test_clean_build.py`. A container must not become the reason to relax it | an incremental build shipped a mixed-revision image here |
| A second-compiler pass must **not** go in the test suite | #34; roughly doubles it, against #50's ceiling |
| MSVC never. `frame.h` is `__attribute__((packed))` and MSVC wants `#pragma pack`, so admitting it would change the packing semantics of the shared wire contract | `CLAUDE.md` |
| Sanitizers cannot run on bare metal. They belong on the host-run tier, which already exists behind `stream_port.h` | `tests/test_framer_close.py`, `tests/test_console_out.py` |
| `ctl_wire.h`'s `build[24]` is a wire field. `FW_GIT_REV` fits in 16 characters and `cmake/fw_git_rev.cmake` fails the build rather than truncating past 23, because a silently shortened commit is a wrong commit | `docs/control-protocol.md` |

## Phases

Each phase lands on `main` on its own and is useful alone.

| # | state | phase | exit criterion | how it is broken on purpose |
|---|---|---|---|---|
| 0 | **done** | Build identity: the image carries the commit and a dirty marker; `firmware()` resolves by commit and `build_is_current()` by reachability; `parse_identity` follows | build twice with no commit between and `tools/reproducible.py` reports **0** differing bytes | `git commit --allow-empty` and rebuild: the embedded value must change |
| 1 | **done** | The image: xPack plus the SAM core, building Track A and Track B, with the bit-identity script under `tools/` run by the build | two builds in the image are byte-identical, and a second machine building from the same pinned inputs reproduces them | unpin one input - the base image tag, an apt version - and watch the bytes move |
| 2 | **done** | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | **done** | Analysers that do not change codegen. `-Werror` is on by default with `-DFIRMWARE_WERROR=OFF` to leave; `-DFIRMWARE_ANALYZER=ON` and `-DFIRMWARE_STACK_USAGE=ON` are opt-in, because a noisy pass on by default stops every bench building the day a new compiler disagrees; `cppcheck` runs from `docker/run-cppcheck.sh`, which separates *found nothing* from *analysed nothing*; `clang-tidy` runs from `docker/run-clang-tidy.sh`, which rewrites the compile database rather than passing extra arguments - it has to select which target's copy of a shared source to analyse, and clang-tidy takes the first match without saying so | each finds a real finding or is proven able to, **and** the analysed build stays byte-identical to the plain one | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | | Provenance: commit read off the board, image digest and compiler recorded with the build | a row written after a containerised build carries a non-null commit, compiler and layout, which #59 says 696, 8 and 1 rows respectively manage today. `layout` is the weak one of the three - it is partly a property of the reader's `nm`, and #63 is open on it | build from a second image and watch the digest change |
| 5 | **builds; not executed** | Clang as an optional firmware compiler, `-DFIRMWARE_CLANG=ON`: explicit triple, libc headers harvested from the resolved cross compiler rather than hardcoded, `-fshort-enums` to match GCC's arm-none-eabi enum ABI, and linking through `arm-none-eabi-gcc` so newlib, libgcc and the linker script come from the toolchain that owns them | Tracks B and C build and `image_fingerprint.py` reads clang back out of `.comment`. **Track A does not build**: the Arduino core declares `uint32_t baud()` and defines `unsigned long Serial_::baud()`, which is one type under GCC and two under clang. **No clang image has run on a board** | build with the harvested include list removed and the build fails rather than reaching `/usr/include` |
| 6 | **done** | Host-run tier hardening: ASan and UBSan over every native harness, and a fuzzer over the shared control parser behind `ctl_port.h`. The fast tier gets a deterministic corpus and a fixed-seed grind; a coverage-fed campaign is `docker/run-fuzz.sh`, one target with two entry points so the halves cannot drift | no defect found, and the null has a denominator: 4.05M executions, 89.9% of `ctl.c`'s wire-reachable lines, and a positive control the campaign crashes in 42 units. Four oracles, not only the sanitizers - a reply is re-parsed and its CRC recomputed, at most one reply may leave one `ctl_service()` call, and a pass must consume a byte or ask for more | inject one defect per check and watch each caught; run the campaign against a parser with its length check removed and require the crash |

Phase 1's exit criterion is a byte comparison rather than a layout
hash because phase 0 made one possible, which is why it came first.
Phases 0-4 are the plan; 5 and 6 are what is worth doing after it.

## What this plan does not answer

Whether a containerised build should ever produce an image that goes on
a board. It can - the artifact is a `.bin` and flashing is a host step -
but every measurement then attributes to an image built somewhere no
bench can reproduce by hand. That is a provenance question for #59, not
a build question.
