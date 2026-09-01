# Testing

`host/measure.py` is the measurement library and `tests/` is the suite
over it. Tracks A and B run the same tests, and a divergence between
them is the oracle working - they are two independent programmings of
one silicon, so a disagreement points at one of them. Track C is a
third track and **not** a third oracle: it shares Track B's drivers, so
a C-versus-B divergence points at `main()` or at the kernel, never at
the register programming. See invariants 3 and 4 in `CLAUDE.md`.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --track=b -q
```

pytest is not stdlib, so the suite needs the venv. Read
`docs/HANDOFF.md` first for the board, the ports and the build
environment.

## 1. What the suite is for

Ordinary TDD, with one local reason it is not optional: **the counters
lie.** A clean `seq_gaps=0 crc_bad=0 under=0` has coexisted with a
badly degraded signal, and a whole-run tone average has reported a
collapse that was not happening. Before the suite, every regression was
caught by a person noticing an odd figure, and several were caught
late.

So the oracles are automatic, and A and B check each other.

## 2. Running it

Three selections. They answer different questions and none substitutes
for another.

| tier | select with | needs | answers |
|---|---|---|---|
| board-free | `-m "not board"` | nothing | did I break the host code |
| smoke | `-m smoke` | the board | is the board still doing the basics |
| full | *(no selection)* | the board | everything |

`smoke` is **not** a subset of board-free - it holds board tests and
needs hardware.

**Board-free is the per-change loop.** It is about a minute and a half,
needs no hardware, and it is the tier that catches the class of thing
that otherwise hides: two failures in `test_banner_order.py` cost 0.05 s
each and sat red on three benches for days, because a fifteen-minute run
is read for its total and not for its failures.

Board tests are roughly a third of the files and the large majority of
the clock. **Ask the suite for counts and durations rather than reading
them here** - a number written down is a number that rots:

```sh
pytest --track=b -m "not board" --collect-only -q | tail -1
pytest --track=b --durations=25
```

`--track=a|b|c|both`, defaulting to `both`. Track is a session fixture
that flashes once and yields a `Board`. Markers: `smoke`, `slow`,
`awg`, `scope`, `track_a`, `track_b`.

**`both` means A and B, deliberately - Track C is opt-in.** It is
excluded from the default until it passes, so that a track still
growing its command surface cannot turn every bench's suite red. Most
of what fails there today is one cause counted many times: a test
drives a console letter Track C does not bind, which is a capability
gap rather than evidence about the test's subject. Run it with
`--track=c` when working on it, and do not read its totals as an
oracle result.

**Quote a duration with its bench and its commit, or do not quote it.**
The slowest bench was once slowest because of a defect, so a
ceiling enforced against it that week would have been calibrated against
the bug and would have looked perfectly reasonable.

## 3. Design

### Ground rules

Each of these cost real time to learn. They are requirements on the
suite, not style preferences.

| Rule | Why |
|---|---|
| Judge tone purity **per window**, never whole-run | At 453,488 sps the whole-run Goertzel reads 232 against a theoretical 1370.5 while nearly every window reads above 1360. One phase discontinuity cancels the average |
| Prove **freshness** on every measurement | Stale kernel-buffered frames from a previous run once manufactured a "frozen DAC" that cost a full session |
| Express rates as **RC**, not Hz | A TC compare against an integer RC is the entire set of rates the hardware has. Anything between two of them rounds down and shifts every derived frequency |
| Never scale a measured ceiling arithmetically | Halving the two-channel RC 86 gives 43, which is off the cliff. The measured one-channel floor is 44 |
| Assert **refusals**, not only successes | An over-fast trigger is silently halved with no status bit set. The guard is the only thing between that and corrupt data presented as clean |
| Tolerances come from **measured spread** | Five runs per mode give 35-59% spread on the DMA benchmarks. Floors come from the minima, justified by what they must catch rather than by how close they sit to the typical figure |

### What a board-free test runs against

§2 says how the tier is selected and what it costs. This says what is on
the other side of the assertion - with no board attached, what is being
tested?

Four substitutes for the hardware. **The last column is the useful one:**
each fails in its own way, and every failure listed there has happened
here rather than being imagined for the table.

| substitute | what it is | what it CANNOT prove |
|---|---|---|
| **synthetic signals** | waveforms whose answer is known by construction, with thresholds taken from real runs - `level_census` asserts 778-780 on a defective run and 0 on a healthy one because that is what 25 runs on hardware gave | that an instrument survives the **nuisance**. A synthetic built only from the hypotheses certifies a detector the real artifact walks straight through. One arm here was voided for exactly that: its synthetic pairs were built in perfect alignment, so not one ever straddled a DAC level change - which was then the thing that dominated every real capture |
| **a fake device** | `host/daemon/device.py`, answering the same API a board answers, deterministically. `test_gui` drives the front end against a synthetic daemon the same way | anything about the board. And **a fake that invents a field is worse than no fake**: this one once returned `mean_us`, which the device does not, so the first script written against it failed on hardware instead of in the suite |
| **the built image, and the source tree** | `nm` over the linked ELF, and greps over CMake and the sources. `test_no_heap` reads the ELF rather than grepping for `printf`, because a grep misses `puts`, `fwrite` and `fputs` and fires on a comment | anything about runtime. And a static check is the **easiest kind to write so that it cannot fail** - four were written here in one day, all green, none able to fail |
| **firmware C on the host compiler** | `lib/due_shared/src/stream_core.c` compiled and run natively with its seam mocked, which is possible only because `stream_port.h` is a complete record of what the framer touches outside itself. Built twice, real and mutant; the mutant must fail | anything about registers or timing - the mocked seam is the point. It needs a **host** GNU compiler: a cross compiler cannot run what it builds, so a bench without one skips it |

**The tier's limit, stated against itself.** "Needs nothing" is verified
two ways and **both are static** - the `board` marker comes from
`fixturenames`, which is transitive, and a grep over every board-free
file finds no `measure.Board(`, `ports.find_*` or `open_raw(`. Nobody
has run the tier on a machine with no Due attached. If you are the
first and it wants hardware, that is a bug in the marker.

### The board marker is derived, not written

`pytest_collection_modifyitems` marks a test `board` when it resolves
the `board` fixture, directly or through any fixture that does. It is
applied there rather than written on each test because **a fixture
cannot be forgotten and a marker can**, and because it stays right the
first time a helper grows a dependency.

### `test_link_health` runs first

The native cable has failed hard - VBUS present, D+/D- dead - and a
physical fault imitates a firmware regression exactly. `FILE_ORDER` in
`conftest.py` puts the link check first so that failure is diagnosed
rather than attributed. Flashing is flaky for the same reason the
fixture retries it: SAM-BA drops, and a retry-less fixture reports false
failures.

### One board, held open

Whether opening the control port resets the board is a **platform
difference** - measured both ways, and `CLAUDE.md` carries the table. A
reset also re-enumerates the native port under a possibly new name.

Either way the fixture is session-scoped and holds the port open for the
whole run. Paid per test, that cost is a reset, a settle and a re-glob -
about 15 s each. Held open it is about half a second. **That one
decision is the difference between a suite that finishes in minutes and
one that takes half an hour.**

`measure.Board` is a context manager. A script that dies holding the
control port makes every later run fail with "Access is denied", which
looks exactly like a board fault.

## 4. What each domain tests

What each domain is for and the trap in it. The ladders,
parametrisations and assertions are in the test files; do not copy them
here.

**Rates** - `test_rates.py`. Ladders are RC and the Hz are derived,
because `39 MHz / RC` for integer RC is the whole set of rates the
hardware has. `test_every_ladder_rate_is_a_real_divider_value` holds the
round-trip, and a rate-exactness test catches truncation:
`header.sample_rate_hz == 39_000_000 // RC`. The AWG ladder is play-only
so a DAC fault cannot be masked by, or blamed on, the capture path.
*The trap:* one channel is **slower** in conversions per second than two
(886,363 against 906,976), because a two-channel trigger converts its
pair back to back and amortises overhead a lone conversion pays in full.
A test assuming one channel runs at twice the two-channel trigger rate
encodes a bug.

**Signal integrity** - `test_integrity.py`. The most important domain
and the easiest to under-build, because counters have been clean while
the signal was wrong. The **slew test** is the one to understand first:
maximum absolute delta between consecutive same-tag samples against the
analytic `2*pi*f*A/fs`. It needs no spectral analysis, it is cheap, and
it fails on exactly what invariant 5 exists to prevent - data spliced
across two points in time that still passes its header CRC. The
**negative control** matters as much: with playback stopped, A0 must
show no tone. That is the test that would have caught the frozen DAC. And when a
counter says everything is fine while the signal disagrees, reach for a
**ramp** - `measure.build_ramp` and `ramp_discontinuities`. Every
sample encodes its own position, which is what turned "the output
jumped" into "313 bytes never arrived"; `docs/status.md` has that
defect.
*The trap:* the gate identifies the displaced-sample artifact
(`docs/awg.md`) with `pair_fold()` rather than thresholding a count. The two parities are 24x apart on
device data, so the selection is not a coin flip - but the wrong parity
does not merely misreport, it reports something plausible, and `hold_ok`
is what refuses it.

**Channels and ceilings** - `test_channels.py`, `test_contract.py`.
Cheap, mostly contract, so it runs before the long streaming tests.
*The trap:* assert the refusal and assert that the loop does not start.
A ceiling that is accepted and silently halved is the failure this
domain exists for.

**Transport** - `test_transport.py`, marked slow.
*The trap:* see the tolerance rule above. These are the benchmarks whose
spread was assumed at 5% and measured at 35-59%.

**Freshness is not a domain.** It is a shared helper on *every*
measurement, not a standalone test.

## 5. Baselines

`tests/baseline.json` holds this board's calibrated thresholds. It is
committed, and it is **a record of one board, not a datasheet.** The
constants tests need live there and in `docs/hardware.md`; they are not
copied into this file.

`pytest --calibrate` writes the measured figures. **It writes only at
session end**, so a run that hangs at 90% yields nothing - a full
calibrated run once took twelve minutes and produced no data at all.
Run it per file instead, each flushing its own `baseline.measured.json`,
and merge. That file is not in `.gitignore`: it is for a human to
promote into `baseline.json`, never to land as it is.

**A track divergence gets an explicit entry with its cause written
down, never a loosened global tolerance.** A widened tolerance hides the
next regression; a named divergence closes itself when the cause is
fixed. There is no such table in the tree today, and that is the correct
state rather than an omission - the last one recorded was Track A's
capture resyncs, caused by the core's blocking `USBD_Send`, and it
closed when Track A moved to endpoint DMA.

## 6. Working on the suite

Rules that apply to everything here.

**Interleave before believing, especially when the first numbers look
decisive.** A cyclic-GC hypothesis separated perfectly on its first four
measurements and fell apart at five rounds interleaved. Two sequential
batches of eight on the ramp test disagreed by a factor of two and a
half. Any claim about a flaky test - including "my change fixed it" -
needs interleaved arms, exactly as a firmware A/B does. `tools/ab.py`.

**Break a new check on purpose and watch it fail, then put it back.** A
guard that passes because it cannot fail is worse than no guard: the
suite goes green, the property goes unwatched, and nobody looks again.
Four such were written here in one day, all green, none able to fail,
and not one was caught by reading.

**Score a run by grepping for the PASS, never for the absence of the
failure.** `1 skipped` does not match `1 failed` and lands in whichever
bucket the harness defaults to. That voided a ten-step bisect;
`--require-board` refuses the substitution for the board case, but a
test that errors or is deselected by a stale `-k` is the same trap
uncovered.

**Coverage is not traded away for speed.** Where a test is slow because
it is measuring something slow, mark it and keep it out of the default
selection - never weaken it. The rate ladders are the clean example:
each case is a distinct RC needing its own run, there is nothing to
share, and the cost is the same on every bench. And several tests here
*are* the finding rather than a check on it - `OVERSUPPLIED`,
`RESIDUAL`, the banner-order guards, `test_no_heap`. Speed comes from
removing duplication and from moving work out of the per-run path.

**Never truncate a suite run's output.** One failure was lost to a
`| tail -3` and never reproduced. `-rf --tb=short`, keep all of it.

**Sharing a board run is right when the measurement is the same
measurement** - see `helpers.shared_run`, whose docstring carries the
rule. The caution is that a bad shared run fails every test keyed to it,
which is one measurement failing several assertions rather than several
measurements agreeing.

**A listed serial node is not an openable one.** `CreateFile` can accept
the open and never return, so a generous deadline never gets tested.
`Board.open_native()` runs each attempt in a daemon thread and abandons
it rather than hanging the run.

**Heal the ports before believing a board fault**, in this order. The
bench is a test rig, not a patient.

1. **Close what you opened.** `measure.Board` is a context manager.
   Most of one session's "unstable enumeration" was a dead process
   holding the control port.
2. **Kill any stray process** still holding a node - a blocked open
   holds the port until its process exits. One force-kill made five
   consecutive per-file runs error at fixture setup in 0.05 s each,
   reading as five broken files rather than one unreleased port.
3. **Reflash.** `tools/flash.py` does a 1200-baud touch and a full
   re-enumeration, and reliably clears a device that has stopped
   answering.

## 7. Tests known to fail intermittently

**Do not wave any of these away as known flakiness.** Read the next
failure before re-running it - everything in this table came from
someone doing that.

| test | established | ruled out |
|---|---|---|
| `test_host_fed_ramp_loses_no_samples` | Real, unexplained, and its rate drifts by era: 5, then 2, then 1 of 8 in sequential batches on one firmware, and 0 of 10 against 1 of 10 when two firmwares were interleaved with a reflash between arms. Fails byte conservation with losses that are *not* whole 128-byte chunks, which the assertion reads as the device losing data it received | Attribution to any build. The sequential batches were measuring the hour, not the image |
| `test_a_client_that_stops_reading...` | **Two disjoint host levers for one assertion**: CPU contention on Linux (0/33 → 11/18), suite context on Windows (3/20 → 6/10), each inert on the other host. Blast radius is **1 of 7** tests in the file on both. Signature is `first_seq=5`, one gap mid-stream | That a cheap standalone reproducer can stand in for it - the Windows lever fires 3 of 4 full suites and **0 of 38** reproducer runs |
| `test_the_fanout_cost_is_recorded_per_frame` | Board-free, off by one on a tolerance, and only inside a full run: 6 of 6 standalone and 47 of 47 within its own file, on the same tree | Nothing yet |

These share only that none reproduces outside a long session. **Do not
assume a shared cause** - one is a host feed rate against real hardware,
one is a daemon under contention, one is accounting over a fake device.

### One that is resolved, kept because the resolution is instructive

`test_awg_ladder_play_only[*-32]` was on this list for weeks as a
bimodal host feed rate: `fed_mbs` landed at 2.431-2.434 or 2.281-2.283
and never between, across three sessions and two suite compositions, and
the entry concluded that something discrete was switching and that it
was host-side because Track A showed the same low mode.

**Both halves were right about the data and wrong about the cause.**
The discrete thing is the device: at RC 32 the DACC draws a mode that
consumes 15/16 of nominal, behind `DACC_MR_REFRESH`, and 2.283/2.438 is
0.9364 against a lattice value of 0.9375. Track A showed it because it
is the **silicon**, not because it is the host. And the test failed
because it compared the feed against *nominal* on a host that
backpressures, so a correct run read 93.6% against a 95% gate.

The guard now measures the feed against what the device actually
consumed, and the test is not flaky. **The general lesson is that a
test asserting a rate must assert it against what the other end took,
not against what was asked for** - `helpers.py` makes the same
correction five times for the same platform fact. `docs/awg.md`
carries the mechanism.
