# Build container

A pinned image that builds the firmware and runs the board-free tests,
so the build environment stops being an unrecorded variable and this
repository can have a CI at all. **Every firmware image comes from here,
and from nowhere else**: `CMakeLists.txt` refuses a configure that
`docker/run.sh` did not launch, and `tools/flash.py` refuses an image the
container did not build. **It does not touch the board tier**; a bench
flashes these images and measures with them.

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
| Track A, Track B and Track C firmware builds | the board tests |
| the board-free tier, `-m "not board"` | flashing - `bossac`, the 1200-baud touch, re-enumeration |
| static analysers over firmware and shared source | measurement of any kind |
| build provenance: commit, compiler, the environment that ran the compiler, and the symbol map - `layout` hashes in a total order, so it compares across benches and across `nm` builds | |

## Using it

```sh
docker/build-image.sh                    # once, and again when the Dockerfile changes
docker/run.sh docker/run-ci.sh           # every check there is
docker/run.sh docker/run-ci.sh --fast    # without the three elastic steps
docker/run.sh docker/build-firmware.sh   # all three tracks, clean, nothing else
```

`docker/run.sh` is the only file that knows about the container. Everything
it runs - `build-firmware.sh`, `run-tests.sh`, `run-cppcheck.sh`,
`run-clang-tidy.sh`, `run-fuzz.sh`, `run-ci.sh` - carries no container
knowledge. The firmware steps run nowhere else all the same, because
CMake refuses to configure outside the image.

**Track C needs no network.** The image carries FreeRTOS at the hash
`cmake/freertos.cmake` pins, in `DUE_FREERTOS_DIR`, and the configure
refuses a copy that is not that commit or has local changes. Track C
compiles with the checkout's and FreeRTOS's paths mapped away
(`FREERTOS_PREFIX_MAP`), so its image does not depend on where either
sits: without the maps, one FreeRTOS copy moved between two directories
changed 18,203 bytes.

Eleven steps, in the order they run:

| step | what it answers | gates |
|---|---|---|
| `firmware` | do Tracks B, A and C build, clean, from the pinned toolchain | yes |
| `host tier` | `-m "not board"`, the whole board-free suite | yes |
| `board absent` | the board tests, under `--require-board`, must **error** for want of hardware | yes |
| `reproducible-b`, `reproducible-a`, `reproducible-c` | two builds a second apart, differing bytes counted | yes |
| `stack report` | does `docs/stack-depth.md` match the record it is generated from | yes |
| `cppcheck`, `clang-tidy` | static analysis over firmware and shared source | findings are advisory; **analysing nothing** gates |
| `fuzz` | a campaign over the shared control parser, with a positive control | a crash gates, and so does a fuzzer that could not be built |
| `working tree` | did the run leave the tree as it found it. `FW_GIT_REV` stamps a delta hash into every image built from a dirty tree, so a step that drops a file into the repository changes every image after it while each still reproduces itself. The change is blamed on the step it happened in | yes, and after a change the reproducible steps do not run. A tree already dirty when the run began is watched for change, not refused |

The five states and what each means are in that script's own header. The
one to know is **DID NOT RUN**: an unanswered question is not a passing
one, so it gates and the run reports `INCOMPLETE` rather than a verdict
on the tree.

**The images land in `docker/out/`.** `docker/run.sh` mounts
`docker/out/build/`, `docker/out/build-a/` and `docker/out/build-c/` over
the container's `build`, `build-a` and `build-c`, beside the
`build-env.json` each build writes. `provenance.CONTAINER_IMAGES` names
the three images, and `measure.flash()`, the board suite and
`tools/flash.py` read them from there. A flash from the suite also
passes `--require-tree`, so the image has to carry exactly the flashing
tree's commit.

### It runs on every bench, and not the same way on each

| bench | how | wall time |
|---|---|---|
| `linux-x1` | a native daemon | 194 s |
| `mac-bench` | **colima plus QEMU, from MacPorts.** Docker Desktop needs macOS 13+ and this desk is 12.7.6 | 774 s |
| `windows-desk` | WSL2, which is a real Linux kernel and therefore the native case | 410 s |

The spread is the runtime, not the work: the same steps, the same
pinned tools, the same counts. What differs per bench is measured -
processor speed on `windows-desk`, and on `mac-bench` the filesystem the
checkout arrives on.

#### The macOS mount is sshfs, and that is not a tunable

colima shares `$HOME` into its VM and `run.sh` bind-mounts the repo out
of it, so `/work` is `fuse.sshfs`. The container's `/` is overlay on the
VM's own disk, which is why anything written under `/tmp` is fast and
everything read from `/work` is not: a full tree walk costs 23.7 s
there against 0.024 s on a native daemon.

**All three ways out are closed, and each is closed on its own.**

| | |
|---|---|
| **virtiofs** | needs the `vz` VM type, which is macOS 13+. That desk is 12.7.6, which is also why it is on colima rather than Docker Desktop |
| **9p** | the only alternative the QEMU VM type accepts, and colima's own configuration says `sshfs` is **faster** than `9p` - `9p` is the more *stable* choice under concurrent reads, not the quicker one. It predicts a regression |
| **tuning sshfs** | the colima and Lima configuration expose `location` and `writable` and nothing else. No cache, `sftpDriver` or `msize` key exists to set without hand-editing Lima's own yaml |

**And the mount type cannot be changed on a running VM at all.**
colima's configuration says the value is fixed at creation, so changing
it means deleting and recreating the VM - which discards the build image
and makes every container figure that bench has taken a
pre-recreate figure. That is a bench rebuild, not a flag.

**So the mount is a constant on that bench**, and the way past it is to
stop reading the tree across it rather than to make it faster. What the
tier pays is latency on the 824 tracked files it opens - not file count,
which is what a tree walk measures and what hiding the venvs behind a
tmpfs would reduce to no effect.

### So the board-free tier runs against a copy, on every bench

`docker/populate.sh` copies git's own view of the tree into a
container-local directory and `docker/in-copy.sh` runs a command there;
`run-ci.sh` and `run-tests.sh` use it. The tree is read once,
sequentially, and every later read is local.

**`docker/run.sh` is deliberately not involved.** It is also how short
commands run - an interactive shell, a one-off `find`, a toolchain query
- and the populate costs 12.5-13.5 s on sshfs. A launcher that paid it
would charge the commands that gain nothing.

| | mounted | copied |
|---|---|---|
| `mac-bench` host tier | 315.9 / 396.0 / 398.7 s | **218.6 / 214.7 / 213.7 s** |
| `linux-x1` host tier | 131.0 s | 132.1 s |

ABAB at one commit with the first cycle dropped. **It is not faster
everywhere and is not meant to be** - what a bench with a local mount
buys is one procedure rather than three.

**The same arm explains why that bench's figures were never points:**
26% spread mounted against 2% copied. The variance is the mount.

**`DUE_COPY_GIT` chooses how `.git` is reached, because the answer
inverts with the filesystem.** On sshfs a copy costs 5,151 ms once and
then ~28 ms an operation, against ~420 ms through a bridge - breaking
even near 13 operations, and a gate makes far more. Over drvfs the copy
is 30-52 s and the bridge wins. Same semantics either way; a bench picks
its side and records it.

#### The whole gate runs against the copy, and there are no build mounts

Moving the tier alone was not enough. **Eight steps read the tree** -
the firmware build, both analysers, and three reproducibility builds
that each build *twice*. `run-ci.sh` re-enters itself once in the copy
and every step after that is local; `repo=$PWD` is what makes it work,
because the copy's own `run-ci.sh` finds the copy.

**`mac-bench`, post-restart against post-restart, the change alone:**

| step | before | after |
|---|---|---|
| **cppcheck** | 25.1 s | **7.7 s** — 3.3×, the largest single gain |
| clang-tidy | 48.6 s | 37.2 s |
| firmware | 30.2 s | 19.4 s |
| `reproducible-b` / `-c` | 12.5 / 14.3 s | 4.3 / 5.4 s |
| host tier | 197.8 s | 186.8 s |
| **wall** | **428.4 s** | **331.3 s** |

**The analysers were the surprise** - `cppcheck` reads every source
once and was paying the mount for all of it. Nobody predicted that; the
firmware step was where everyone was looking.

**And the ground did not move this time**, which is the point of having
the instrument: fuzz did **228,786 executions against 231,716** at the
same fixed duration, 1.3% apart. So unlike the VM restart, these deltas
are attributable to the change rather than to the machine.

**The three build bind mounts are gone with it.** They existed only so
`cmake -B build` landed in `docker/out`; `build-firmware.sh` names the
destination, which is the same directory whether it runs against the
mounted tree or a copy that bridges `docker/out`. Repo-level `build/`,
`build-a/` and `build-c/` stop existing, and `image_fingerprint.py` and
`stack_depth.py` default to `docker/out` rather than to directories
that are no longer written.

**It stops writing them; it does not remove what is already there.**
`mac-bench` found **162 MB** of stale CMake trees from before the
change, `linux-x1` 1,600 files - including a Track B image under its
pre-rename name, sitting exactly where a tool used to default. Delete
them once: a missing directory is an error and a stale one is a wrong
answer that looks right.

#### The objects are written locally too, and the artifacts are copied out

The same argument one layer down. `build/`, `build-a/` and `build-c/`
are bind mounts onto `docker/out/`, so on a bench whose checkout is
outside the container's VM every object file is written across the
mount. `docker/build-firmware.sh` writes them to a container-local
directory and copies out the `.bin`, the `.elf`, the `.map` and
`build-env.json`.

| | into the mount | local + copy-out |
|---|---|---|
| `mac-bench` firmware | 56.7 s | **41.4 s** |
| `mac-bench` `reproducible-a` | 44.8 s | **22.0 s** |
| `mac-bench` gate wall *(both pre-restart, `binfmt: true`)* | 574.1 s | **518.4 s** |
| `windows-desk` firmware, mount already local | 27.76 s | **29.43 s** |

**The reproducible steps gain more than the firmware step** - 37 s
against 15 s on that bench - because each builds twice, so the change
pays there twice over.

**And on a bench whose mount is already local the redirect COSTS a
little.** `windows-desk` separated it with the knob, four runs an arm
and the first discarded: the publish and the clear are free at
**-0.28 s**, and the redirect itself is **+1.95 s, +7.1% of the firmware
step** - which is **+0.35% of a gate** that runs 467-479 s there. So it
is *free at gate level and not free at the step*, and the distinction
matters because the step is exactly where a slow mount's cost lives.

#### A fixed-duration step is a confound detector, and it earned that here

`mac-bench` set `binfmt: false` and restarted its VM, and the gate then
ran **428.4 s against 518.4 s**. **None of that 90 s is attributable to
the binfmt change**, and the step that says so is the fuzz campaign:
it runs for a **fixed time** and reported **231,716 executions against
115,864** - twice the work in the same 37 s.

Removing a binfmt entry cannot double native fuzzing throughput. That
VM had been up 12 days, so **the restart moved the machine as well as
the handler** and the two are not separable from one run.

**So a figure's label is its state, not its intent.** That bench's rows
are `post-restart, binfmt: false`; the pre-restart figures above stay
valid for the state they were taken in rather than being superseded by
a faster number taken in a different one.

**The general instrument is worth more than the instance.** A step that
consumes a fixed *duration* and reports *work done* measures the
machine, not itself - so when a change appears to improve everything,
that step says whether the machine moved underneath it.

**It was used twice in one morning, for opposite purposes.**
`mac-bench` read it as a *confound* - executions doubling across a VM
restart, which is why none of their 90 s was credited to the change
they had just made. It was then used a third time as a **control**, by the bench that had
been caught by it: executions steady to 1.3% across the whole-gate
change, which is what licenses reading those deltas as the change
rather than the machine. `windows-desk` read it as the *measurement*:
333,433 executions from the ext4 checkout against 100,163 from the
drvfs one, which is the cleanest single number for how much a
filesystem costs a whole gate. Isolating
binfmt alone would need a second restart with it re-enabled, which is
not worth a bench cycle for a number nothing depends on.

**The copy-out ends the firmware step, not the run.**
`tests/test_no_heap.py` reads `docker/out/build/*.elf` during the host
tier, which runs after, so an artifact appearing only at the end would
not be there when the tier looks for it. Each track publishes before
the next begins.

**Analysis builds are not redirected**, and that is the design rather
than an exemption: `-fstack-usage` and `-fcallgraph-info` output is not
among the copied artifacts, and neither option is ever passed by
`build-firmware.sh`, so a bench asking for either configures its own
tree and keeps every intermediate where `tools/stack_depth.py` and
`tools/stack_frames.py` expect it.

**`tools/reproducible.py` reuses the configured tree rather than
building its own**, so it reads the same variable rather than a
hard-coded path - the two cannot then disagree about where a build
went. `DUE_BUILD_LOCAL` set empty builds in place.

#### What git ignores is exactly what the build produces

That is the trap in selecting the copy with `git ls-files`. It is the
right selector for source and the wrong one for state the tier reads but
does not track: `tests/test_no_heap.py` reads the linked image to prove
the firmware allocates nothing, `docker/out/` is ignored, and a copy
without it took that guard from **passed to skipped** - silently, because
a skip is not a failure.

So `BRIDGES` names the ignored state the tier reads, and adding to it is
how a new one is handled.

**A bridge can be empty rather than missing, and that is not the same
thing.** `records/flash-log.jsonl` is written by flashing, so on a bench
that runs the container in one tree and flashes from another it is
absent from the tree the container sees - the bridge works and there is
nothing to bridge. The arm that reads it then **does not run, and the
gate is green**. Measured on `windows-desk`: it skips with their clone
as it is and passes with their real log copied in.

That is tolerable only because the spellings that arm guards are
**global** - they live in `provenance.track_of_binary()`, not per bench
- so one bench with a real log covers the hazard. **Which benches run
it is a per-bench fact and belongs on their pages**, because a reader
of a green gate cannot see it. Two of the four were found by reading the
selector rather than by a failure, and they are the more dangerous
shape: tests branch on `bench.json` **by name**, so a copy without it
takes a different path *and still passes*, which no outcome comparison
can see.

#### Three guards, because each is blind to what the others catch

| guard | fires on | blind to |
|---|---|---|
| the populate's `git status` comparison | a short or wrong copy of tracked content | a missing ignored bridge |
| an outcome comparison, every node id, both sides | a missing bridge | faithful content |
| `in-copy.sh`'s comparison after the run | a run that modifies tracked source | ignored output, which is expected |

**A run may leave ignored output behind and may not modify tracked
source.** The third guard exists because `run-ci.sh`'s `working tree`
step watches the mount, and a step that runs in the copy can no longer
reach it - so for that step the check would pass by construction.

**And a knob that cannot cross the container boundary is not a knob.**
A container inherits nothing from the invoking shell, so every `DUE_*`
a bench is expected to set has to be named in `run.sh`. Each is
forwarded empty when unset, so the default lives in the script that
reads it rather than in two places.

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
comparison it feeds. It refuses a dirty tree too, because the delta
hash is a function of the dirt and no other bench can reproduce it.

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
| **The checks run from one entry point.** `docker/run-ci.sh` builds all three tracks, runs the board-free tier, proves the board absent, checks byte reproducibility, checks the stack-depth document against its record, and runs `cppcheck`, `clang-tidy` and a deterministic fuzz pass. Five states in one column - PASS, FINDINGS, FAIL, **DID NOT RUN**, NOT SELECTED - and an exit code a classifier does not recognise is DID NOT RUN, never PASS | a pinned image is what makes any of it runnable on every bench at once, and one entry point is what makes it get run |
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
| wall time *(from each run's summary, not from the rows - the row does not carry it)* | 194 s | 817 s | 410 s |
| `cppcheck` / `clang-tidy` | 33 / 40 | 33 / 40 | 33 / 40 |
| board-free tier | 657 / 5 / 141 | **654 / 8 / 141** | 657 / 5 / 141 |
| board-absent control | 141 errors | 141 errors | 141 errors |
| reproducibility | 0 differing bytes | 0 differing bytes | 0 differing bytes |

**It is the same build on all three.** `windows-desk` rebuilt
`linux-x1`'s recorded commit and got both artifacts byte-identical -
`track_b_bringup.bin d791b858…` and `.elf facaa22e…` - which is
phase 1's second half and closes it. The third platform is in it by the
other pair: `mac-bench` and `windows-desk` both recorded at `f5db1e8`,
and both artifacts agree there too - `track_b_bringup.bin
0218619e…` and `.elf 5bf536cb…`. So byte-identity holds pairwise
across all three hosts and both commits, and macOS under colima and
QEMU is inside the claim rather than beside it. The layouts agree, the
analyser counts agree exactly, and on two of the three benches the
analyser logs agree to the **byte**: 3,899 and 7,056 in both. That is a
stronger result than equal totals, because two totals can agree by
coincidence and two logs cannot.

That second pair is also the sharpest thing said about
`build_image_content` below, because it is one comparison run twice with
opposite results: the two benches' image hashes differ - `ec031e1b…`
against `b3106b76…`, on docker 29.5.2 against 29.8.0 - while the
firmware those two images produced is identical to the byte. The value
that was supposed to certify sameness disagrees; the artifacts it stood
proxy for agree exactly.

**It is not the same check set, and the reason is below the image.**
`mac-bench` skipped three tests the other two run: the `needs_sanitizer`
fuzz mutations, whose oracle is a sanitizer rather than a return code.
A 32-bit ASan binary hung there, reproduced on a five-line program that
only returns 0. The same tests are selected on every bench, so **an
identical image does not guarantee an identical check set.**

**What varies is one line of kernel configuration in the VM, not the
host's virtualisation.** The VM that bench runs is `accel=hvf` on an
x86-64 kernel built `CONFIG_IA32_EMULATION=y`, which executes 32-bit
binaries itself. colima also registers a `binfmt_misc` handler for
i386, and a `binfmt_misc` entry is consulted before the kernel's own
ELF loader - so every `-m32` binary was handed to `/usr/bin/qemu-i386`
and ASan's shadow mapping never completed under it. Measured with the
handler disabled: the probe goes from a 120 s timeout to `True` in
0.2 s, the three mutations run, and a 32-bit fuzz grind goes from
31.7 s to 3.5 s, faster than the same grind at the native word size.

So the emulation was elective. Read a missing check set as a question
about what the kernel was asked to do with the binary, and reach for
`/proc/sys/fs/binfmt_misc` before concluding that a platform cannot run
something.

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
not universal in what it can execute.** The one gap reached through an
identical image from a `binfmt_misc` entry in the VM under it, and the
lesson outlives the gap: a bench can be executing a binary through an
emulator it never asked for, and the skip that follows reads as a
platform limit. Worth knowing before a null from such a bench is read
as a clean run.

### The analyser floors, and why the two are different kinds of number

Both analysers are advisory and neither gates. What each one's count
*means* is not the same thing, and the difference is a property of how
the scripts are configured rather than of how much work is left.

| analyser | dispositions available | what the floor is | current |
|---|---|---|---|
| `clang-tidy` | fixed, or a per-site `NOLINT` carrying its reason | **zero, and holdable** — on a case-sensitive filesystem, see below | **0** |
| `cppcheck` | fixed, or **standing**, with its reason in the source | **a list, not a zero.** There is no per-site suppression, so an answered finding still counts | **10** |

`docker/run-cppcheck.sh` offers no suppression list for this project's
code and does not pass `--inline-suppr`. That is deliberate: a
suppression written before anyone has decided what to do about a finding
is the failure the script exists to prevent. The only `--suppress`
entries are whole vendor trees and `missingIncludeSystem`.

**So cppcheck staying at 10 is the tool working as configured.** Read as
a backlog it invites the suppression list the script refuses to have.
Read correctly it is ten findings, ten reasons, and an eleventh would be
new.

**A count is worth quoting only once every finding under it has been
answered**, which is the state both are in. Before that, a standing
count hides its own increments: the whole hazard is that fifty-three
advisory findings conceal the fifty-fourth.

#### The clang-tidy count is a property of the HOST FILESYSTEM as well as the source

Measured on `windows-desk`, one image, **two checkouts of one commit -
one on ext4 in the WSL VM, one on NTFS through drvfs**: **0 findings
from the first and 4 from the second.** A directory sits on one
filesystem, so the cleaner experiment of one tree seen through two
mounts is not available; what licenses the comparison is that both
checkouts are at one commit and **all three images built from them are
byte-identical**, so the content is equivalent and the filesystem is
the only thing varying. All four findings are `non-portable path to
file "Stream.h"` in `sketches/bringup`.

drvfs is **case-insensitive**, so the Arduino core's `#include
"Stream.h"` matches this project's own lowercase `stream.h` — the
hazard `CLAUDE.md` records for Track A and `include_directories()`,
surfacing here through the analyser rather than the build.

That byte-identity is also what says the finding is not a defect: the
compiler resolved the include correctly from both, and what clang-tidy
reports is its portability check on the *lookup*.

**So a floor is a property of source, image and the filesystem the tree
sits on.** A bench working from a case-insensitive mount acquires four
permanent advisory findings that say nothing about its code, and
because the analysers are advisory its gate stays green while its count
disagrees with everyone else's. **Quote a clang-tidy count with the
filesystem, the way a figure is quoted with its bench.**

#### The ten that stand

Each carries its reason where a reader meets it; the source is the
record, not this table.

| where | class | count |
|---|---|---|
| `bsp/startup_sam3x8e.c`, `bsp/syscalls.c` | `comparePointers` on linker-symbol bounds and `_sbrk` | 3 |
| `bsp/syscalls.c`, `apps/rtos_bringup/main.c` | `constParameterPointer` on a newlib and a FreeRTOS signature | 2 |
| `drivers/gen.c`, `sketches/bringup/gen.cpp` | `badBitmaskCheck` on the `0u << 12` channel tag | 4 |
| `lib/due_shared/src/load.h` | `cstyleCast` on a memory-mapped register | 1 |

Three shapes recur, and they are the reason this class of finding cannot
be fixed rather than answered. **A linked image knows things no
translation unit does** - the linker symbols bound real regions, and
comparing them is undefined by the letter of C and correct here. **A
signature that is not ours cannot be narrowed** - newlib and FreeRTOS
declare the hook and will call through that type. **A shared source is
compiled as two languages** - Tracks B and C compile `load.h` as C and
Track A as C++, so `reinterpret_cast` would not build on two of the
three.

#### Two things that make a finding count move without any code changing

**A `NOLINT` marker silences the next *line*.** Written as the first
line of a block comment it silences the rest of the comment and nothing
else, so the marker looks placed, the reason reads well, and the count
does not move. It must be the last line before the code it answers.
This is invisible to review - the file reads correctly either way - and
only the analyser reports it.

**The analyser is more precise than its summary count.** An exact-match
edit driven by the class rather than the flagged line breaks where the
same line appears twice in a file and only one instance is flagged:
`stream_core.c`'s two `acq_frame_bytes()` sites, where the other
`memcpy`s into the buffer, and `ctl_port.cpp`'s two FIFO pointers, where
the other stores through it. Trusting the class there would have broken
the build in both places.

#### Neither floor means anything without a canary

A zero from a tool that analysed nothing is the same zero as a clean
run, and both scripts separate the two - by different means and to
different strengths.

`run-clang-tidy.sh` carries a **canary**: a source with planted
defects of the classes it is configured to catch, compiled on each
pass, every diagnostic required to fire. It also asserts the target is
ARM and the pointer is 32-bit, because a compile database that falls
back to the host triple analyses something real and answers about the
wrong machine. A missing diagnostic is `exit 1`, not a clean column.

`run-cppcheck.sh` has the weaker half of the same idea: no planted
defect, but a parse failure, an internal error or a missing include is
an `exit 1` rather than a finding, and `--error-exitcode` is
deliberately unused because it cannot tell a finding from a crash.

So a clang-tidy zero is proven live and a cppcheck ten is proven to
have parsed. **A run whose canary does not fire is not a pass**,
whatever the findings column says.
## What a bench cannot do without it

**Build firmware at all.** CMake refuses a host configure, and
`tools/flash.py` refuses a host image, so every image a bench flashes
came from here.

The analysers are the rest of it. Measured on `linux-x1` - the bench that
owns the image - by running the same script with the container out of
the path, before the firmware step was confined to it:

```
cppcheck           DID NOT RUN   cppcheck is not installed
clang-tidy         DID NOT RUN   clang-tidy is not installed
fuzz               DID NOT RUN   clang is not installed
board absent       NOT SELECTED  a board is attached
VERDICT: INCOMPLETE. 3 step(s) DID NOT RUN                       exit 1
```

So the container is not a convenience on one platform. **Three of its
steps are where it is, on every bench**, because the three tools
that are not compiler flags do not ship with a compiler. The four that
are - `-Werror`, `-fanalyzer`, `-fstack-usage`, and the host-tier
sanitizers - are CMake options and a host resolver, and never needed a
container at all.

| given up | workaround |
|---|---|
| `cppcheck`, `clang-tidy`, `fuzz` - three steps, and the run reports `INCOMPLETE` | install all three per bench. It works, and then they are three versions on three benches and the finding counts stop comparing - which is the variable this image removes |
| The **board-absent positive control**, on any bench with a board attached. It is `NOT SELECTED` there by design: running it would open the port it exists to prove absent | none. A machine with no board, or the container |
| **Cross-bench reproduction.** The claim is *same pinned inputs*, and a host toolchain is deliberately not a pinned input | none, and it is structural - but it is no longer outstanding: phase 1's second half is met on both pairs that share a commit, `windows-desk` against `linux-x1` at `6a7d122` and against `mac-bench` at `f5db1e8` |
| Nothing. The misaligned-load canary fires under Apple clang as well as under the image's GCC: clang does not instrument a *volatile* access for alignment, and the canary's load carried that qualifier | - |
| The 32-bit ABI arm, which has never executed on any bench natively - multilib absent on `linux-x1`, and a `qemu-i386` shadow-mapping hang on `mac-bench` | install the multilib runtimes |

Measurement stays on the bench: every measurement is a host step, run
against an image built here. Most figures in this tree predate that and
were taken on host builds; `fw_build_env` on a row says which.

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
already characterised here, and it is the generator every image is built
with. Figures from the benches' earlier host builds carry ARM GNU 14.x
or Debian 14.2.1, and `docs/toolchain.md` is where the generators are
told apart.

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
| 1 | **done** | The image: xPack plus the SAM core, building Track A and Track B, with the bit-identity script under `tools/` run by the build | both halves met. Two builds in the image are byte-identical - 0 differing bytes on both tracks on all three benches - and a second machine reproduces them: `windows-desk` rebuilt `linux-x1`'s recorded `6a7d122` under WSL2 and got `track_b_bringup.bin d791b858…` and `.elf facaa22e…`, identical to the row, having first had to find that figure in the record because the one quoted at it came from a dirty tree | unpin one input - the base image tag, an apt version - and watch the bytes move |
| 2 | **done** | The board-free tier in the image | `-m "not board"` collects and passes with no board reachable; then the **whole** suite in the image, where every board test must **skip** and none error | move one board test's marker and watch the tier fail; a test that errors instead of skipping is the marker bug `docs/testing.md` predicts |
| 3 | **done** | Analysers that do not change codegen. `-Werror` is on by default with `-DFIRMWARE_WERROR=OFF` to leave; `-DFIRMWARE_ANALYZER=ON` and `-DFIRMWARE_STACK_USAGE=ON` are opt-in, because a noisy pass on by default stops every bench building the day a new compiler disagrees; `cppcheck` runs from `docker/run-cppcheck.sh`, which separates *found nothing* from *analysed nothing*; `clang-tidy` runs from `docker/run-clang-tidy.sh`, which rewrites the compile database rather than passing extra arguments - it has to select which target's copy of a shared source to analyse, and clang-tidy takes the first match without saying so | each finds a real finding or is proven able to, **and** the analysed build stays byte-identical to the plain one | introduce a defect of the class the analyser claims to catch, and watch it fire; delete the tool from the image and watch the step fail rather than pass empty |
| 4 | **done** | Provenance: commit read off the board, compiler and build environment recorded with the build | a row written after a containerised build carries a non-null commit, compiler and layout, which #59 says 696, 8 and 1 rows respectively manage today. `layout` is the weak one of the three - it is partly a property of the reader's `nm`, and #63 is open on it | build from a second image and watch the recorded environment move while the artifact's bytes do not; rebuild in the directory and watch the record refuse to describe the new binary |
| 5 | **done, and the answer is not to use it for analog work** | Clang as an optional firmware compiler, `-DFIRMWARE_CLANG=ON`: explicit triple, libc headers harvested from the resolved cross compiler rather than hardcoded, `-fshort-enums` to match GCC's arm-none-eabi enum ABI, and linking through `arm-none-eabi-gcc` so newlib, libgcc and the linker script come from the toolchain that owns them | Tracks B and C build and `image_fingerprint.py` reads clang back out of `.comment`. **Track A does not build**: the Arduino core declares `uint32_t baud()` and defines `unsigned long Serial_::baud()`, which is one type under GCC and two under clang. A clang image **runs**: it boots, enumerates all three ports, answers `ctlver=4`, and passes 635 of 636 board tests. The one failure is issue #5, whose displacement reaches **+38 codes against a 25-code reopening threshold** where the GCC image of the same commit sits at +6 - so `-DFIRMWARE_CLANG=ON` is an instrument for that issue and not a compiler to ship analog work with | build with the harvested include list removed and the build fails rather than reaching `/usr/include` |
| 6 | **done** | Host-run tier hardening: ASan and UBSan over every native harness, and a fuzzer over the shared control parser behind `ctl_port.h`. The fast tier gets a deterministic corpus and a fixed-seed grind; a coverage-fed campaign is `docker/run-fuzz.sh`, one target with two entry points so the halves cannot drift | no defect found, and the null has a denominator: 4.05M executions, 89.9% of `ctl.c`'s wire-reachable lines, and a positive control the campaign crashes in 42 units. Four oracles, not only the sanitizers - a reply is re-parsed and its CRC recomputed, at most one reply may leave one `ctl_service()` call, and a pass must consume a byte or ask for more | inject one defect per check and watch each caught; run the campaign against a parser with its length check removed and require the crash |

Phase 1's exit criterion is a byte comparison rather than a layout
hash because phase 0 made one possible, which is why it came first.
Phases 0-4 are the plan; 5 and 6 are what is worth doing after it.

## Images on a board

Every image that goes on a board is built here. The provenance question
that raises - an image built somewhere a bench cannot reproduce by hand -
is answered by the record the build writes: `tools/flash.py` accepts an
image only when `build-env.json` hash-matches it as a container build,
and the flash log carries the image's tag, id and content hash beside
the commit, compiler and layout. Where the container runs on the
checkout it builds, the images are already where a flash reads them.
Where it runs in WSL against a clone, `docs/windows.md` has the copy and
the commit rule.
