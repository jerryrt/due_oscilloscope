# Handoff

**What is current and what to pick up.** Read `CLAUDE.md` first for the
invariants and the facts that are easy to get wrong.

This file is **state, not findings.** A finding lives in the `docs/`
file that owns it and in the commit that made it; this one goes stale
by design and should be short enough to rewrite rather than amend.

## Where things stand

| | |
|---|---|
| **Loop** | Full, both tracks. HOST -> DAC0 -> A0 -> HOST at zero underruns, tone at the theoretical maximum. Bulk data moves by UOTGHS endpoint DMA on both |
| **Tracks** | A and B are peers and the oracle pair. **C** is the FreeRTOS build — boots, schedules, answers `v`, and is opt-in in the suite |
| **Host** | A daemon owning the ports (`host/daemon/`) and a Qt front end drawing from it (`gui/`). Both have board-free suites |
| **Bring-up** | Stages 1-6 done. Stage 7 (FreeRTOS) is Track C, in progress |
| **Branch** | `main` only. Everything else is short-lived — `CONTRIBUTING.md` |
| **Board** | Ask it: `v`, or `measure.which_track`. Never assume from this file |
| **Build identity** | Every image states its commit. `v` and the control channel's IDENTITY carry `build=<sha>`, or `<sha>+<8 hex>` when the tree was dirty. A clean build is byte-reproducible - `tools/reproducible.py` |
| **Checks** | `docker/run-ci.sh` runs the lot from one entry point in about three minutes: both tracks, the board-free tier, a control proving the board absent, byte reproducibility, cppcheck, clang-tidy, a fuzz pass. Five states in one column, and an exit code no classifier recognises is DID NOT RUN, never PASS |
| **Container** | `docker/`, pinned to xPack 15.2.1-1.1 with every input checksum-verified. It builds and tests; it does **not** touch the board, and `docs/build-container.md` says why |

**Per-bench state is on the status boards, not here** — #31 macOS, #32
linux-x1, #34 windows-desk. Each carries its own toolchain, ports,
wiring and what it is doing. There is no single "the environment" and
this file used to pretend otherwise.

## What to pick up

| item | state |
|---|---|
| **The front end** (objective 1a) | The largest open build. Trigger, cursors, measurements, spectrum. Needs no board. `docs/frontend.md` |
| **Track C** (#45) | C1-C4 done and a scheduler costs nothing measurable on the data path. Open: whether four debug-only console commands get ported |
| **The 0-series re-validation** (0h) | The oldest debt. Figures above 200 ksps predate a feed fix. Half answered — see below |
| **printf stages 3-4** (#49) | Design accepted. A 110-site migration, and it will redraw every issue #5 figure on every bench at once |
| **Native-port control channel** (objective 8) | Transport and six opcodes built. Left: the state-changing commands |
| **A shared divide with no guard** (#68) | `console_cmd_rate_sweep()` divides by an argument it does not check; both tracks that bind `t` clamp it in their own `main()`. One line, and the test that fails without it is already written |
| **Wire the last two arms in** | `DUE_HOSTCC_ABI=32` and the console fuzz campaign both work and neither is run by anything. One line each, in `docker/run-ci.sh` and `docker/run-fuzz.sh` |
| **Cross-bench reproduction** (#61) | Two benches building `docker/` from the same pinned inputs must produce one `.bin`. Needs a second bench and nothing else |

## The 0-series

The loss investigation. Detail is in `docs/usb.md`; this is the state.

| | what | state |
|---|---|---|
| 0a/0b | Playback starves at three rates | **Fixed.** The host's stack discarded bytes `write()` had counted. Constant 512 B writes |
| 0c | `close()` wedges holding both ports | **Diagnosed, macOS-only.** 0 in 52 cycles on Windows. Recover with `=<ms>Z` from the *programming* port — never pull the cable |
| 0h | Re-validation debt above 200 ksps | **Half answered.** `Feeder.WRITE_SIZE` is a macOS workaround; the honest high-rate figures are the Windows ones. The rest is unre-taken |
| 0i | Oversupply at RC 44 and 39 | **Cause found** — the converter runs slow, and it is `DACC_MR_REFRESH` (#48). A closed loop exists and is off by default |
| 0j | Why constant write size is lossless | **Open, macOS-only.** A cheap experiment would corner it |
| 0k | Intermittent large loss at 1,218,750 sps | **Open.** Tracked by outcome, so it turns green by itself |
| 0l | `play_endtx_seen` disagreed with `consumed` | **Fixed.** A counter not cleared at start |

## Standing decisions, not tasks

| decision | why it is waiting |
|---|---|
| **`DACC_ACR`** — adopt the datasheet's value on Track B? | Spec conformance and Track A parity, **not** an issue #5 fix — measured, and it is not one. Take it *with* the 0-series re-take so the baseline moves once |
| **A full-suite time ceiling?** (#50) | The board-free tier is bounded; the full suite is not. Blocked on whether the 25% cross-bench spread is a cost or a defect |
| **Track C's four console commands** (#45) | Answering "no" costs three tests, all of which validate the load monitor under a deliberate stall |

## Which document answers what

| question | file |
|---|---|
| Invariants, and facts that are easy to get wrong | `CLAUDE.md` |
| What works, measured figures, recorded mistakes | `docs/status.md` |
| Transport ceilings, host I/O policy, the loss findings | `docs/usb.md` |
| The generator, and the issue #5 mechanism with its evidence | `docs/awg.md` |
| What #5 costs the instrument | `docs/issue5-impact.md` |
| The suite: tiers, domains, what a board-free test runs against | `docs/testing.md` |
| Daemon protocol and its guarantees | `docs/daemon-api.md` |
| Front-end design and the rules the UI must obey | `docs/frontend.md` |
| What the tracks share, and why | `docs/shared-source.md` |
| Per-host validation | `docs/windows.md`, `docs/linux.md` |
| Board, clocks, converters | `docs/hardware.md` |
| How to write one of these | `docs/writing.md` |

## Running it

Ports move with cables. **Discover them** — `python3 host/ports.py` —
and never copy a path out of a document.

```sh
# Track B
cmake --build build -j
tools/flash.sh build/baremetal_bringup.bin

# Track A (configure once with -DBUILD_TRACK_A=ON)
cmake --build build-a --target firmware_track_a
tools/flash.py --bin build-a/track_a_bringup.bin

# Track C (configure once with -DBUILD_TRACK_C=ON)
cmake --build build-c --target firmware_rtos

# suite
.venv/bin/python -m pytest --track=b -q            # add -m "not board" for the fast loop

# daemon and front end, no hardware needed
python3 -m daemon --fake
.venv-gui/bin/python -m gui --spawn-fake
```

Console commands: ask the board with `h`. It is authoritative and this
file's copy of it was not. `v` is the cheap one — one line, fixed
format, and it says which track is actually on the board.

## Starting on a new machine or a new board

**Venvs are not committed and never travel** — they hold absolute paths
and platform wheels. Rebuild from the pinned requirements; `CLAUDE.md`
lists the interpreters.

**`tests/baseline.json` is calibrated against one specific board** and
says so in its own header. On a second Due, expect timing-sensitive
thresholds to need re-measuring. **A failure there is a recalibration,
not a regression** — re-measure and record, never widen a tolerance to
make a test pass.

**Ask `tools/toolchain.py` where the tools are.** On Windows none of
them is on `PATH`.
