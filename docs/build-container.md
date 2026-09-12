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
| | **Track C's firmware.** `apps/rtos_bringup` fetches FreeRTOS at configure time and `docker/run.sh` runs `--network none`, so the RTOS track cannot be configured in the image at all. Neither analyser sees it either, and `docker/run-ci.sh` says so in its own summary rather than leaving the coverage implied |
| static analysers over firmware and shared source | measurement of any kind |
| build provenance: commit, compiler, the environment that ran the compiler, and the symbol map - `layout` hashes in a total order, so it compares across benches and across `nm` builds | |

## Using it

```sh
docker/build-image.sh                    # once, and again when the Dockerfile changes
docker/run.sh docker/run-ci.sh           # every check there is
docker/run.sh docker/run-ci.sh --fast    # without the three elastic steps
docker/run.sh docker/build-firmware.sh   # both tracks, clean, nothing else
docker/run-ci.sh                         # on a bench, same shape, host tools
```

`docker/run.sh` is the only file that knows about the container. Everything
it runs - `build-firmware.sh`, `run-tests.sh`, `run-cppcheck.sh`,
`run-clang-tidy.sh`, `run-fuzz.sh`, `run-ci.sh` - carries no container
knowledge and runs on a bench unchanged.

Nine steps, in the order they run:

| step | what it answers | gates |
|---|---|---|
| `firmware` | do Track B and Track A build, clean, from the pinned toolchain | yes |
| `host tier` | `-m "not board"`, the whole board-free suite | yes |
| `board absent` | the board tests, under `--require-board`, must **error** for want of hardware | yes |
| `reproducible-b`, `reproducible-a` | two builds a second apart, differing bytes counted | yes |
| `stack report` | does `docs/stack-depth.md` match the record it is generated from | yes |
| `cppcheck`, `clang-tidy` | static analysis over firmware and shared source | findings are advisory; **analysing nothing** gates |
| `fuzz` | a campaign over the shared control parser, with a positive control | a crash gates, and so does a fuzzer that could not be built |

The five states and what each means are in that script's own header. The
one to know is **DID NOT RUN**: an unanswered question is not a passing
one, so it gates and the run reports `INCOMPLETE` rather than a verdict
on the tree.

**The build directories are not the bench's.** `docker/run.sh` mounts
`docker/out/build` and `docker/out/build-a` over `/work/build` and
`/work/build-a`, so a container run never touches a bench's own `build/`
and the two toolchains' artifacts cannot be confused for each other.

### It runs on every bench, and not the same way on each

| bench | how | wall time |
|---|---|---|
| `linux-x1` | a native daemon | 194 s |
| `mac-bench` | **colima plus QEMU, from MacPorts.** Docker Desktop needs macOS 13+ and this desk is 12.7.6 | 774 s |
| `windows-desk` | WSL2, which is a real Linux kernel and therefore the native case | not yet taken |

The spread is the runtime, not the work: the same nine steps, the same
pinned tools, the same counts.

**One trap, paid for on `mac-bench`.** `toolchains.json` searches
`{repo}/tools/xpack-*/bin` before `/opt`, and `run.sh` mounts the repo -
so a toolchain unpacked in-tree shadows the image's own. It was loud
there only because that binary is Mach-O; on a Linux host with a Linux
toolchain in-tree it would have built with the wrong compiler while
`build_env` still said `container`. The image now declares
`ARM_TOOLCHAIN_DIR` and the cache entry is `FORCE`d, so a mis-resolved
tree is repairable rather than sticky.

### The container may hold the checks; it must not hold the board

Nothing in the image opens a serial port, and the section below says why
that is a measurement rather than a preference. The consequence for a
bench is a boundary: builds and every board-free check inside the
container, and anything that opens a port - the board tier, `measure.py`,
`tools/flash.py`, the daemon, the GUI - on the host. On Windows that
distinction is sharpest, because WSL2 reaches a board only through
`usbipd`, whose error is **optimistic** - `docs/windows.md`.

### One row per run, so three benches can be compared

`tools/container_report.py` writes one provenance-stamped row per run to
`records/container-universality.jsonl`:

```sh
docker/run.sh docker/run-ci.sh; rc=$?
python3 tools/container_report.py --exit "$rc" \
        --append records/container-universality.jsonl
```

It reads the artefacts rather than the summary prose - `build-env.json`
as the build wrote it, the counts the analysers print about themselves,
the pytest summary lines, the per-artifact differing-byte counts - and
takes the verdict from the script's exit code, which is the one fact no
artefact carries. It refuses a row whose image does not carry the
tree's own commit, because `FW_GIT_REV` is compiled in and a row
labelled with a commit the binary was not built from voids the
comparison it feeds.

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
| **The checks run from one entry point.** `docker/run-ci.sh` builds both tracks, runs the board-free tier, proves the board absent, checks byte reproducibility, checks the stack-depth document against its record, and runs `cppcheck`, `clang-tidy` and a deterministic fuzz pass. Five states in one column - PASS, FINDINGS, FAIL, **DID NOT RUN**, NOT SELECTED - and an exit code a classifier does not recognise is DID NOT RUN, never PASS | a pinned image is what makes any of it runnable on every bench at once, and one entry point is what makes it get run |
| **Build provenance exists as fields and is empty as data.** #59: of 6,658 stored rows, 1 carries a layout and 8 carry a compiler; `fw_layout` is present on 64 rows and null on all 64 | a commit read off the board, plus the environment that built the artifact, makes the field mechanical instead of remembered |
| **The board-free tier has never run without a board.** `docs/testing.md` says the `board` marker is verified two ways and both are static | a container is the dynamic check, and the marker is what the whole tier rests on |

## Is it the same thing on three platforms

Asked of all three benches and answered by all three, one row each in
`records/container-universality.jsonl` from `tools/container_report.py`.

| | `linux-x1` | `mac-bench` | `windows-desk` |
|---|---|---|---|
| host | Debian, x86-64 metal | macOS 12.7.6, Intel | Windows 10, WSL2 Ubuntu 26.04 |
| runtime | native daemon, docker 29.7.2 | colima + QEMU, docker 29.5.2 | WSL2, docker 29.8.0 |
| steps that did not run | 0 | 0 | 0 |
| verdict | 0 | **2** - the wall clock, below | 0 |
| wall time | 194 s | 817 s | 410 s |
| `cppcheck` / `clang-tidy` | 33 / 40 | 33 / 40 | 33 / 40 |
| board-free tier | 657 / 5 / 141 | **654 / 8 / 141** | 657 / 5 / 141 |
| board-absent control | 141 errors | 141 errors | 141 errors |
| reproducibility | 0 differing bytes | 0 differing bytes | 0 differing bytes |

**It is the same build on all three.** `windows-desk` rebuilt
`linux-x1`'s recorded commit and got both artifacts byte-identical -
`baremetal_bringup.bin d791b858…` and `.elf facaa22e…` - which is
phase 1's second half and closes it. The layouts agree, the analyser
counts agree exactly, and on two of the three benches the analyser logs
agree to the **byte**: 3,899 and 7,056 in both. That is a stronger
result than equal totals, because two totals can agree by coincidence
and two logs cannot.

**It is not the same check set, and the reason is below the image.**
`mac-bench` skips three tests the other two run: the `needs_sanitizer`
fuzz mutations, whose oracle is a sanitizer rather than a return code.
A 32-bit ASan binary hangs under `qemu-i386`, reproduced there on a
five-line program that only returns 0. The same 662 tests are selected
on every bench and three of them cannot execute on a QEMU-backed host -
so **an identical image does not guarantee an identical check set**, and
what varies is the host's virtualisation. `windows-desk` runs them, which
is what a real kernel on metal predicts.

**Two questions turned out to be badly formed, and both were caught by a
bench rather than by the person who wrote them.**

`build_image_content` **cannot** match across benches, and two
independent mechanisms say so. It hashes `RootFS.Layers`, which are
diffIDs over the uncompressed layer tars, and those carry file mtimes -
two builds of one instruction seconds apart on one bench give different
values, measured. And it hashes what `docker image inspect` prints, so
two docker versions disagree about the fields: 29.5.2, 29.7.2 and 29.8.0
across the three benches, and three different hashes. `docker/run.sh`
already said the value "compares within a bench with certainty and
across benches only as far as their docker agrees"; it does not compare
across benches at all. It is a within-bench environment identity.

What **does** compare, and what the claim was always supposed to be, is
the **recipe**: `docker/Dockerfile`'s own sha256 plus the pinned
`XPACK_VERSION` and `XPACK_SHA256`, which every bench computes without
building anything. All three agree -
`4fc62fe9ae55ab081a173f4e1b53f007fe0c4b38a297e9df571e37a2bc709e00`,
`15.2.1-1.1`, `da6a49ad…`. `docker/build-image.sh`'s header had it right
from the start: *"same image across benches is not a claim this makes;
same pinned inputs is."* The byte-identical artifacts are then the
behavioural evidence that the pin did its job, which is a better answer
than a layer hash would have been even if one had matched.

`mac-bench`'s **exit 2 is the wall clock and nothing else**. Zero tests
fail; the board-free tier took 538 s against a 300 s ceiling and the step
is red on elapsed time. A slow bench therefore reports a gating failure
for the one quantity everybody agrees is not a finding - the ratio shows
up twice, once as a number a reader correctly ignores and once as a
verdict they cannot. Whether the ceiling should be a property of the
machine belongs to whoever owns the suite's time budget.

**So: universal in what it builds, universal in what it analyses, and
not universal in what it can execute.** The one gap is a host's
virtualisation reaching through an identical image, which is worth
knowing before a null from a QEMU-backed bench is read as a clean run.

## What a bench gives up by not using it

Measured on `linux-x1` - the bench that owns the image - by running the
same script with the container out of the path:

```
cppcheck           DID NOT RUN   cppcheck is not installed
clang-tidy         DID NOT RUN   clang-tidy is not installed
fuzz               DID NOT RUN   clang is not installed
board absent       NOT SELECTED  a board is attached
VERDICT: INCOMPLETE. 3 step(s) DID NOT RUN                       exit 1
```

So the container is not a convenience on one platform. **Three of the
nine steps are where it is, on every bench**, because the three tools
that are not compiler flags do not ship with a compiler. The four that
are - `-Werror`, `-fanalyzer`, `-fstack-usage`, and the host-tier
sanitizers - are CMake options and a host resolver, and never needed a
container at all.

| given up | workaround |
|---|---|
| `cppcheck`, `clang-tidy`, `fuzz` - three of nine steps, and the run reports `INCOMPLETE` | install all three per bench. It works, and then they are three versions on three benches and the finding counts stop comparing - which is the variable this image removes |
| The **board-absent positive control**, on any bench with a board attached. It is `NOT SELECTED` there by design: running it would open the port it exists to prove absent | none. A machine with no board, or the container |
| **Cross-bench reproduction.** The claim is *same pinned inputs*, and a host toolchain is deliberately not a pinned input | none. It is structural, and it is what phase 1's second half is still waiting for |
| On `mac-bench`, the arm that proves the misaligned-load canary works: it fires under the image's GCC and not under Apple clang 14 | install another host compiler |
| The 32-bit ABI arm, which has never executed on any bench natively - multilib absent on `linux-x1`, and a `qemu-i386` shadow-mapping hang on `mac-bench` | install the multilib runtimes |

What is **not** given up is the project: all three tracks build on a
host toolchain, Track C builds only there, every measurement is a host
step, and every figure in this tree was taken on a host build. The
container is where a third of the checks live, not where the work
happens.

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

## What ran the compiler

A commit is not an image and a compiler is not an environment.
`docker/build-firmware.sh` writes what it was running inside beside the
artifacts, `tools/flash.py` copies it into the flash log, and
`provenance.run_fields()` carries it onto every row a tool writes.

A process in a container cannot ask docker what it is running in, so
`docker/run.sh` reads the two values and passes them in as environment.
That file already holds every other piece of container knowledge, and
one home for it is the right number.

| recorded | what it proves | what it does not |
|---|---|---|
| `build_env` - `container`, `host`, or `unrecorded` | which kind of build produced these bytes, stated by the build | `unrecorded` is a build that did not say, and **null** is a flash logged before the field existed. Neither may be read as `host` |
| `build_image` - the tag | what the bench called it | a tag moves |
| `build_image_id` - docker's `.Id` | which object ran | not content, and not even one environment: four builds of this `Dockerfile` from a full cache gave four ids |
| `build_image_content` - a hash of the layer chain and the image config | the environment. Equal across those same four builds, and it moves when the recipe's content does | not a registry digest - D5 takes no registry. It is a hash over what `docker image inspect` printed, so it inherits docker's choices, and compares across benches only as far as their docker agrees |

Layers alone would not do: `ENV` adds no layer, and `HOME` is what
points the Track A build at the SAM core.

**The record is accepted only when it hashes to the binary being
flashed.** A build directory outlives the build that filled it, so a
record that merely sits in the right place names the environment of
whatever was built there last - and a stale field reads as a
measurement, where a missing one gets questioned. Two builds producing
identical bytes stay indistinguishable, here as everywhere else in this
project.

A build that does not go through `docker/build-firmware.sh` writes no
record and lands as `unrecorded`, which is what a plain `cmake --build`
is.

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
| 1 | **built; half its exit criterion is open** | The image: xPack plus the SAM core, building Track A and Track B, with the bit-identity script under `tools/` run by the build | two builds in the image are byte-identical - **met**, 0 differing bytes on both tracks on every bench that has run it - and a second machine building from the same pinned inputs reproduces them, which **no two benches have yet compared**. One bench cannot: the comparison is one `sha256sum` against another bench's, and #61 carries the target hashes | unpin one input - the base image tag, an apt version - and watch the bytes move |
| 2 | **done** | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | **done** | Analysers that do not change codegen. `-Werror` is on by default with `-DFIRMWARE_WERROR=OFF` to leave; `-DFIRMWARE_ANALYZER=ON` and `-DFIRMWARE_STACK_USAGE=ON` are opt-in, because a noisy pass on by default stops every bench building the day a new compiler disagrees; `cppcheck` runs from `docker/run-cppcheck.sh`, which separates *found nothing* from *analysed nothing*; `clang-tidy` runs from `docker/run-clang-tidy.sh`, which rewrites the compile database rather than passing extra arguments - it has to select which target's copy of a shared source to analyse, and clang-tidy takes the first match without saying so | each finds a real finding or is proven able to, **and** the analysed build stays byte-identical to the plain one | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | **done** | Provenance: commit read off the board, compiler and build environment recorded with the build | a row written after a containerised build carries a non-null commit, compiler and layout, which #59 says 696, 8 and 1 rows respectively manage today. `layout` is the weak one of the three - it is partly a property of the reader's `nm`, and #63 is open on it | build from a second image and watch the recorded environment move while the artifact's bytes do not; rebuild in the directory and watch the record refuse to describe the new binary |
| 5 | **done, and the answer is not to use it for analog work** | Clang as an optional firmware compiler, `-DFIRMWARE_CLANG=ON`: explicit triple, libc headers harvested from the resolved cross compiler rather than hardcoded, `-fshort-enums` to match GCC's arm-none-eabi enum ABI, and linking through `arm-none-eabi-gcc` so newlib, libgcc and the linker script come from the toolchain that owns them | Tracks B and C build and `image_fingerprint.py` reads clang back out of `.comment`. **Track A does not build**: the Arduino core declares `uint32_t baud()` and defines `unsigned long Serial_::baud()`, which is one type under GCC and two under clang. A clang image **runs**: it boots, enumerates all three ports, answers `ctlver=4`, and passes 635 of 636 board tests. The one failure is issue #5, whose displacement reaches **+38 codes against a 25-code reopening threshold** where the GCC image of the same commit sits at +6 - so `-DFIRMWARE_CLANG=ON` is an instrument for that issue and not a compiler to ship analog work with | build with the harvested include list removed and the build fails rather than reaching `/usr/include` |
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
