# Handoff

Read this first, then `docs/status.md` (what works, measured figures,
recorded mistakes) and `docs/usb.md` (transport ceilings and host I/O
policy). `docs/windows.md` is the 2026-08-25 validation on a second host
and a second board: it settles objective 0c, and it shows the playback
byte loss is macOS's driver rather than anything on the device. If you are here to build the test suite, the whole plan is in
`docs/testing.md` - start there and read this for the environment.

## PR #3 from the Windows team, merged 2026-08-25

**Both PRs are merged and there are no open PRs.** #4 into
`windows-validation`, then #3 into `main`, both fast-forwards. All four
macOS review blockers were re-verified fixed first: `loop.py` analysing
`args.tone`, `flash.sh` reaching a system python without pyserial,
`toolchain.py` exiting 1 on the optional ninja, and `flash.py` ignoring
`--port` when a board sits in ROM SAM-BA. The record below is kept
because the review is what made them findable.

The history was rewritten on 2026-08-25 to correct 32 commits authored
with the wrong email; every tree is byte-identical and the commit count
is unchanged, but every SHA from `91cfe35` onward differs from what the
text below quotes.

`windows-validation`, 4 commits, +1811/-126. It is the first validation
of this project on a host other than macOS and it settles the biggest
open question in this file: **0c does not reproduce off macOS** (0 wedges
in 40 cycles against 9 in 30 here), **and neither does the playback byte
loss** - Windows loses 0 B at all eight rates from 200 k to 1.393 M sps,
including the two that lose most here. `usbser.sys` paces the writer at
the device's consumption rate, so the backlog macOS discards is never
built. 0c and 0a/0b/0i/0k are two symptoms of one macOS behaviour.

It also *confirms* 0i rather than dismissing it: RC 44 and RC 39 run
1.6% slow on Windows too, by the device's own `runus`. The slow converter
is the device's. Nothing is lost there only because Windows never
oversupplies.

**Reviewed on macOS with the board. Three things block a merge, and one
review finding closes the PR's own open question.**

- **Its "Left open" item is its harness, not the ADC.** `tools/loop.py`
  passes `args.tone` to `windows()` where `run_loop` correctly uses the
  tone `build_waveform` actually emitted. At 453,488 sps the requested
  1000 Hz becomes 1001.077 (453488/453), the window stops being a whole
  number of real cycles, and Goertzel leakage reads ~4 codes low. Run
  against a perfect synthetic 1371-code sine with their `windows()`
  unmodified: 1371.00 at the real tone, 1366.05-1367.59 at `args.tone`,
  22 of 22 windows "outside 1371 +/- 2". At 200,000 sps the two agree
  exactly because 200000/1000 is exactly 200. That is the whole reported
  asymmetry, and no ADC settling is implicated.
- **`tools/flash.sh` no longer flashes on this Mac.** The shim runs
  `${PYTHON:-python3}`, and `flash.py` imports pyserial unconditionally -
  `touch_1200` does, so `--port` does not avoid it. Reproduced on
  hardware. `requirements-dev.txt` states the rule it breaks. With
  `PYTHON=.venv/bin/python` the whole path works and is *better* than the
  old one: it takes the native-port ROM SAM-BA route and verifies.
- **`python3 tools/toolchain.py` exits 1 on a fully working machine** -
  it counts the optional `ninja` as missing - so
  `cmake --build build --target tools` fails.
- **`flash.py` ignores `--port` when anything is in ROM SAM-BA**, with no
  multi-device guard where `find_console` has one. Two boards attached,
  one blank, and it flashes the wrong one.

Everything else in the review is non-blocking and listed on the PR. What
*is* verified good on macOS: every Darwin pattern in `toolchains.json`
resolves, and a clean configure + build links GNU 15.2.1.

The full review is posted on the PR. It has not been merged. `main` was
pushed on 2026-08-25 with this session's eight commits, so the PR now
sits behind the Track A DMA work and the identity line; a trial merge
against the pre-push main conflicted only in `CLAUDE.md` and
`docs/toolchain.md`, both doc-only, and both were touched again by the
push - expect the same two conflicts, slightly larger.

## Read this first: the development platform is changing (2026-08-25)

**Windows becomes the main development platform; macOS becomes a
porting target.** The user's decision, taken on the Windows team's
feedback and on the evidence in this file: the defects that have
dominated the last several sessions - 0a, 0b, 0h, 0i, 0j, 0k, and 0c -
are all macOS CDC-ACM host defects, and the firmware has been clean
underneath every one of them. Developing against the host with the
broken stack has meant spending sessions proving the device innocent.

**Nothing measured here is invalidated by that, and nothing is
confirmed by it either.** What is measured is what this host does. The
first job on Windows is not to build - it is to re-take the 0-series
against a host that does not silently discard bytes:

- **0h's re-validation debt should be re-taken on Windows, not macOS.**
  Every figure above 200 ksps is suspect because of a macOS write-size
  defect. If Windows does not have it, the honest numbers are the
  Windows ones and `Feeder.WRITE_SIZE` becomes a macOS workaround rather
  than a rule.
- **0c has a prediction and a tool.** `tools/soak0c_portable.py` is
  pyserial-only and runs anywhere; it was fidelity-checked on macOS
  first (6 wedges in 25 cycles against the POSIX original's 9 in 30). If
  it never wedges on Windows, 0c is macOS's and the firmware is done
  with it.
- **0i and 0j are the two remaining losses.** Both were characterised
  entirely through a macOS write path. Re-measure before theorising
  further.

**The porting work is real and none of it is in the GUI.** Every line
of `host/` is POSIX-only - `os.open`, `termios`, `fcntl`/`TIOCM_DTR`,
globbing `/dev/cu.usbmodem*`, `select` on raw descriptors - and
`host/rt.py` returns "no promotion (not macOS)" everywhere else.
`docs/frontend.md` ("Portability: the work is not in the GUI") has the
backend split already sketched: Linux is a different glob, Windows is
pyserial or ctypes over `CreateFile`/`ReadFile` with overlapped I/O, and
real-time promotion needs `timeBeginPeriod` plus a time-critical thread
priority. Port *identification* is already portable and stays as it is:
the control port is the one that answers `h` with the banner.

Two things that do not move: the firmware, and the byte accounting. The
device's `play_bytes_in` against the host's `write()` count is what
found the macOS defect and is what will find the Windows one. Build the
Windows backend so that test runs first.

**Nothing in this section is measured.** It is a decision and its
consequences as predicted. Treat every "Windows will" here as a
hypothesis with a test attached.

## Start here: the Windows session handoff (2026-08-25)

**Do this first: unplug and replug the Due's native USB cable.** The
native port stopped enumerating at the end of the session and no
software remedy reaches it - `=400Z`, three reflashes and a SAM-BA
round trip all failed, while SAM-BA itself enumerates fine over the same
cable, so the hardware is good and the Windows USB stack is not. It
follows a run of `usbipd` bind/attach/detach cycles and there are seven
phantom `VID_2341&PID_003E` registrations left behind (COM8, COM9,
COM11, COM12 and three composite instances). Nothing below can be
measured until the port is back.

### The agreed order of work (2026-08-25, approved)

**1 -> loose ends -> 2 -> 3 -> 4.**

1. **Settle whether issue #5 is a defect at all.** Step 1 no longer means
   the ADC-timing sweep: this board has stopped exhibiting the defect
   (see the retraction below), so there is nothing here for that sweep to
   act on. The tool is built and waiting on `issue5-adc-timing`
   (`=<tt>,<st>A`, runtime, one image sweeps the whole range). **Step 1
   now means confirming on macOS, which has never been tried**, and
   pulling the DAC1->A1 jumper on a board that does reproduce.
2. **Objective 1c, first half**: port `O`, `occmin` and `play_run_us` to
   `sketches/bringup/play.cpp`. A straight transliteration; turns the 18
   Track A failures in `test_play_counters.py` into 18 passes or 18
   honest findings, and nobody knows which.
3. **Objective 1c, second half**: Track A's control channel. The gate for
   everything else. Port `ep_realloc_control()`'s second half *with* the
   feature - Track A's `ep_apply_autosw()` hazard goes live the day that
   track grows EP4, which is the day the control channel arrives.
4. **printf stages 3 and 4**: poison `printf`, `dbg()` literal-only, and
   opcodes or demotions for `t x r s V D u`.

Loose ends worth an hour: rebase `wip/refusal-reporting` onto `main` and
land it on its own merits, post the issue #5 correction, and watch the
next few full runs for the load-dependent flake that stopped appearing
after the stage 2 stalls were removed (n=2, a hypothesis and not a fix).

### Objective 1c's first half is done, and it found three things

Ported to `sketches/bringup/play.cpp` with the same names, the same
decimation and byte-for-byte the same output format: `play_occ_hist`,
`play_occ_min`, `play_occ_trace`, `play_occ_traced`, `play_run_us`,
`occmin=` on `B`, and the `O` command. The host's existing parser reads
it with no change. `pytest --track=a tests/test_play_counters.py` goes
from **18 failed / 0 passed to 9 failed / 9 passed**; the remaining nine
need the binary status-record carrier on bulk IN and the closed-loop
rate feed, which are the other half of 1c.

**1. Track A had been flashing an image nobody built.** `sketch.py
compile` passed `--build-path` only when given one, so arduino-cli built
into its own cache, while `upload` defaulted to `build/track_a` and
flashed whatever had last been left there. The artifacts here were nine
hours stale and the board had been running them all evening with no
error anywhere. **Any Track A figure taken before 2026-08-25 evening may
have been measuring source that had already changed** - on the track
whose entire job is to be the reference oracle. One constant now decides
both paths.

**2. `measure.flash()` could not reach Track A on Windows at all.** It
ran `tools/sketch.sh` through subprocess; win32 answers "%1 is not a
valid Win32 application" and every Track A test errors in the fixture.
It also called `arduino-cli upload`, which `sketch.py`'s own comment
records as destructive here - the sam recipe points bossac at the
programming port after the 1200-baud touch, but on Windows the erased
chip brings SAM-BA up on the *native* port, so it wipes the board and
then reports no device. Both go through `sketch.py` now.

**3. Track B's prime fix does transfer - and the first measurement of
it here was wrong.** `PLAY_PRIME_BUFS` is now 24 on both tracks, measured
on this one. Three runs per rate, two builds verified distinct by
checksum, counters read inside the run:

| prime | underruns | occmin |
|---|---|---|
| 4 | 0-7 | 2-8 |
| 24 | **0 in all nine** | **21-29** |

Objective 0i's Track B result exactly.

**The wrong version of that table is worth keeping, because the error is
one this project makes.** The first sweep read the counters with `B`
after `run_loop` returned - which is *after the drain*. Track A has no
playback-abandon timeout (a known 1c gap), so it keeps repeating for
about 2 s of deliberate starvation once the feeder stops: `run_us` is
5.00 s for a 3 s run where Track B's is 3.5 s. Every underrun and the
whole of occmin came from that tail. It produced 3382 "underruns" at
RC 44 and an occmin pinned at 2 no matter what the prime was, and it was
written up here as the largest open number on the project. It was the
shutdown, not the run.

`run_loop` already snapshots the counters before it drains, under a
comment that says "counters first, while they still describe the run".
**A counter read after the drain describes the drain.** The same audit
clears Track A of the rest of the suspicion: `endtx * 512 / run_us`
tracks the requested rate to 1.000 on both tracks, so every ENDTX is one
emitted buffer and none are spurious, and `consumed` matches Track B
within 1% at every rate.

### Windows answers the macOS session (2026-08-25, later)

**The three corrections from macOS are accepted, not argued with.**

- `level_census()` at threshold 45 cannot see the macOS form. Agreed,
  and `flat_census()` is the right instrument for a DC channel.
- The TIOA phase sweep, the printf placement switch and the bss padding
  series are **void**, for the reason the retraction already gave about
  everything else: no arm in any of them ever went dirty, and all three
  ran inside the clean stretch. A control reading zero measures the era.
  They were promoted to "what survives" because a negative result does
  not look like a comparison. It is a comparison, and it had no control.
- "Verify successful" is not evidence that a flash ran. Every image A/B
  taken on Windows this session used exactly that check and nothing
  else.

**What Windows can add, checked rather than asserted.**

*The Windows clean stretch was not instrument blindness.* The obvious
worry was that a probe at threshold 30 would miss a 26-32 code
displacement. All fourteen captures kept from the session were
re-censused with `flat_census()` at threshold 20, and the two agree on
every one - the clean captures sit at `max_dev` 8-9 with sd 0.84-0.89,
nowhere near either threshold. The board really was not reproducing.

*The amplitude differs between the two hosts, and the period does not.*

| host | `GEN_TABLE_LEN` | displacement | sd, dirty | sd, clean |
|---|---|---|---|---|
| Windows | 512 | 63-68, always bit 6 | 3.0 | 0.86 |
| Windows | 1024 | 49-50, no common bit | 1.7 | 0.86 |
| macOS | 512 | 26-32, no common bit | 1.66 | 0.87 |

Same period, same 777-of-777 regularity, same flat-channel single-sample
shape - and roughly a factor of two in size, with the single-bit form
appearing only in the 512/Windows corner. On Windows the amplitude fell
from 68 to 49 when the table was doubled, so it is not a fixed quantity
of the defect. **Anything proposed as a mechanism has to explain the
amplitude, not just the period**, and a mechanism that produces exactly
one bit cannot be it, because three of the four rows above do not.

**But the `sd, dirty` column is not independent evidence, and should
not be read as three different behaviours.** A flat line carrying one
`+A` displacement every `period` samples has
`sd = sqrt(sd_clean^2 + A^2 * p * (1-p))` for `p = 1/period`, and all
three rows sit inside what their own amplitude and period predict:

| host | table | A | predicted sd | measured |
|---|---|---|---|---|
| Windows | 512 | 63-68 | 2.91-3.12 | 3.0 |
| Windows | 1024 | 49-50 | 1.76-1.78 | 1.7 |
| macOS | 512 | 26-32 | 1.44-1.66 | 1.66 |

So sd is amplitude and period restated, which is what makes it a cheap
discriminator - it needs no threshold and no census - and also what
stops it being a fourth measurement. The 3.0 against 1.7 on one host is
the table doubling, not the defect behaving differently.

*Nothing here provokes it.* Nineteen software detach cycles across three
timings (3x400 ms, 6x150 ms, 10x60 ms), five runs measured after each
group: 0 dirty in 15. So a plain re-enumeration is not the trigger, and
the "it followed the wedge and replug" story needs something stronger
than a detach to stand on.

*The bootloader-after-flash failure has not been seen on Windows.* Not
yet a difference between the hosts - it was never looked for here, and
every flash this session was judged by the string macOS has now shown to
be worthless. It is checked from now on, on both.

### Where the branches are

| Branch | State |
|---|---|
| `main` | Both PRs merged. Carries the splice census and the issue #5 write-up |
| `printf-stage1` | Stages 1-2 of taking measurement off the console. Full suite green |
| `wip/stream-stop-race` | Tested 2026-08-25. **Do not merge as a fix** - see below |
| `wip/refusal-reporting` | Off `wip/stream-stop-race`. Names which refusal it is; moves preset M's printfs off the capture. Local only |

`windows-validation` and `host-transport-port` are merged and can go.

Issue #5 is open and its recorded diagnosis is wrong; the correction is
below and should be posted to the issue, whose title is also wrong.

The macOS team has stopped. Both PRs carry their full review history and
every finding they raised is answered in the comments.

### Objective 0i's underrun half is closed, and it was cheap

`PLAY_PRIME_BUFS` was 4 - the DAC started on an eighth of a ring, 1.4 ms
of runway at the top rate. At 24 the AWG ladder is **zero underruns at
every rate**, byte conservation untouched, occmin 2 -> 18-26.

The method matters more than the fix: **run the same rate for 1 s, 3 s
and 9 s.** All three gave 21-24 underruns, so it was a startup burst and
nothing else. That question is now in `CLAUDE.md` ahead of the
invariants. Track A still primes at 4 (objective 1c).

### Issue #5's diagnosis is wrong, and the branch is not a fix

**Do not merge `wip/stream-stop-race` as a fix for issue #5.** It was
built on the model above - `stream_stop()` aborts an IN transfer, the
channel stays enabled, the next run arms the PDC over buffers it is
still reading, the two race. Tested on hardware 2026-08-25 (later
session), that model does not survive any of the following, and neither
does "780 splices" as a description.

**Vocabulary, because the rest of this section is unreadable without
it.** A **run** is one 3 s capture at preset `M`. A **dirty** run is one
that contains the artifact, a **clean** run is one that does not, and
the two do not shade into each other - a run carries either ~778 events
or exactly 0, at sd 1.66 against sd 0.87. So "6/10 dirty" means six of
ten captures showed it on the same board and image, which is the whole
difficulty: the defect is intermittent per run, not per build.

An **arm** is one condition of an experiment - the untreated control, or
the board with some change applied. A **dirty arm** is one that actually
produced the artifact. The distinction carries the retraction below: a
treatment arm reading zero is only evidence when the control arm read
dirty, because otherwise nothing was there to fix while you were
watching.

**It is not a splice.** On the flat channel every event is one sample
displaced by +62..68 codes, and with the original table every one was
exactly bit 6 set - clearing that bit recovers the neighbouring value
exactly. Sequence numbers, header CRCs and byte counts stay perfect. One
disturbed sample is not data joined from two points in time, and calling
it a splice is what sent a session to the stop path.

**Its period is the generator's table, not anything in the capture or
USB path.** Events are spaced exactly 512 samples per channel, single
phase, 779 of 779 gaps. `GEN_TABLE_LEN` is `GEN_SINE_POINTS * 2` = 512.
Doubling `GEN_SINE_POINTS` moved the spacing to exactly 1024 and changed
the displacement to +45..50, which also stops it being a clean bit 6. The
event is locked to the DAC's buffer wrap.

**It does not happen on the ordinary capture path.** Same firmware, same
200 kHz, alternating presets three times each: preset `3` is clean on the
flat channel (sd 1.0, nothing over 10 codes) while preset `M` shows 779
events at spacing 512. Under `3` the generator is still running and its
ENDTX still firing, so ENDTX alone is not it either. Only `M` shows this.

**RETRACTED: "the variable is the binary" is wrong.** This file said,
and the commits and the draft issue comment said, that incidence tracked
the image - that four bytes of bss took a 25/25 clean build back to
baseline. That claim does not survive its own control. Rebuilding and
flashing the *identical* binary later the same day - `wip/refusal-reporting`,
text 28316, bss 73024, same board, same host - gives **0 dirty runs in
10**, where it gave 5/10 dirty twice that morning.

**What actually changed across the session is time.** The board went
from roughly 60% of runs dirty in the morning to zero by the evening,
and stayed there: about 200 runs across ten distinct images, all clean.
Deliberate bss padding does not bring it back - eight images from bss
73028 to 73284, 0/5 dirty every one. Neither does printf placement,
tested properly at last on **one** image with a runtime switch: preset
`M` printing its two lines after `gen_go_tioa1()` versus before it,
alternated, 0/10 dirty both ways.

**So every A/B comparison between builds in this investigation is
confounded by when it was taken**, including the 25/25 that made
`wip/stream-stop-race` look like a fix. That branch was never shown to
fix anything, and the bss story that replaced it was no better. Do not
compare a number from one hour to a number from another; interleave the
conditions or do not run the experiment.

**What does survive**, because it was measured within one session and
mostly within one image:

- it is not a splice - one sample displaced, mean 2058.24 over the 5000
  samples before and 2058.24 over the 5000 after;
- the period is `GEN_TABLE_LEN` and follows it when the table doubles;
- it does not appear on preset `3` at the same rate on the same
  firmware, only on preset `M`;
- it appears on macOS too, at the same period and the same 777-of-777
  regularity (2026-08-25, `16b68a2`, 6 runs in 10 dirty).

**RETRACTED with the rest: the three "eliminated" hypotheses are
unpowered, not negative.** This list used to carry the TIOA0/TIOA1
phase (16/16 clean across a swept spin), the printf placement (0/10
both ways) and the bss layout (eight images, 0/5 each). **In none of
the three did any arm ever go dirty.** All were taken inside the same
clean stretch this section has just finished describing - about 200
runs across ten images, all clean - so with a ~60% base rate a control
arm reading zero says the board was not reproducing the defect, and the
treatment arm's zero says nothing about the treatment.

That is the retraction above applied to negative results instead of to
A/B comparisons, and it was missed because a negative result does not
look like a comparison. It is the same trap either way: **an experiment
without a positive control measures the era it was run in.** So all
three go back to open, and "already eliminated, do not re-run" is
withdrawn.

The macOS track/settling sweep is the worked example. Four conditions
by eight reps, interleaved, 32 of 32 clean - which reads as three
treatments that all work until you notice the fourth condition was the
untreated baseline, 6/10 dirty ninety minutes earlier. Only a live
baseline arm in the same interleave makes that visible; a remembered
one does not.

**The live hypothesis is host or USB state, not code.** It fits when the
defect appeared: early in the session, shortly after the native port had
been wedged and replugged following a run of `usbipd` bind/attach/detach
cycles, and it faded over many clean enumerations afterwards. It also
fits this project's history, where 0a, 0b, 0c, 0h, 0i and 0k all turned
out to be host CDC-ACM defects with the firmware clean underneath.

**It has now been recorded on both hosts, and it fades on both.**
The macOS run (2026-08-25) reproduced it at 6/10 and then went to 0 in
about 50 consecutive runs over ninety minutes, the same shape the
Windows board showed. Two differences worth carrying: the displacement
is 26-32 codes here rather than 64, and it is **not** a single bit - the
XOR against the neighbour takes 13 distinct values across 0x20-0x2f, so
"bit 6 set" is not the invariant. A displacement that varies by +/-3
codes reads analog rather than digital.

Because it is 26-32 codes, `level_census()` at `STEP_SPLICE_CODES = 45`
cannot see it: on one capture whose A1 census counted 778 periodic
events, A0 censused `count=0 max_step=42.5`. `tools/splices.py` run as
the brief specified would have reported "does not reproduce on macOS"
about a board that was reproducing it. `measure.flat_census()` is the
companion instrument; census the flat channel, never A0 alone.

**The blocking question is no longer analog-versus-digital, it is what
makes a board go dirty.** The jumper test is still the most decisive
run available, but it is only decisive while a board is reproducing -
pulled against a clean board it reports zero either way, which is
exactly how the three eliminations above got their zeros. Nothing here
is measurable on demand until the defect is.

**Settle whether this is a defect in the product before doing more
firmware work on it.** The question is not "what corrupts the sample" but
"does preset `M`'s setup produce this on its own". Two things to read
first. `docs/hardware.md` records the DAC0->A0 / DAC1->A1 crosstalk
baseline as +/-1 code and says in the same section that it was taken at
maximum `TRACKTIM` and `SETTLING` with software-triggered single
conversions milliseconds apart, and that this "does not retire the
crosstalk risk" because "crosstalk bites when tracking time is short" -
while `acq.c` streams at `TRACKTIM(0)`, `SETTLING(0)`, `TRANSFER(1)`. And
A1 is not an unconnected channel: `gen` drives DAC1 with DC 2048 through
the same PDC stream in TAG mode, so both channels come from the wrap the
period is locked to.

**And fix the control before trusting it.**
`test_device_generated_waveform_is_continuous` is described as "the
control for everything below, and it must stay green", and its signal is
absent from every other capture path. Preset `M` was built for objective
0c - its own banner says "press D and read cdr7: swing = USB at fault,
frozen = trigger path" - and was promoted to continuity control later. A
control that fires only on one diagnostic preset is not controlling what
it claims to.

### The instrument, which is the part that holds

`measure.level_census()` and `tools/splices.py`, with board-free tests in
`tests/test_census.py`. Collapse the staircase to its levels and count the
steps above a threshold, instead of judging the largest step against
`slew_limit()`: `gen` emits a staircase whose honest ceiling is ~38 codes
against that function's 16.85, so the old "3x margin" was really 1.3x and
a real defect could only make the test wobble. The count separates where
the maximum does not - 778-780 against 0, where the maximum moves 38 to 58.

**It reports the void it judges in, and that has already earned its
keep.** The threshold is not tuned: the healthy distribution ends at 38
and the defective one starts at 51, so 45 sits in a twelve-bin gap and any
value across it returns the same count. When `GEN_SINE_POINTS` was doubled
the DAC step grew into that gap, and the tool said so - "the void around
45 is under 4 codes wide on 10 run(s)" - on the same runs where `max_step`
had gone bimodal at 24 and 42 and the count was still reporting 0. A count
under a closed void is not a measurement.

**Judge this by `count`, never by `max_step`.** That is the whole lesson
of the defect it was built for.

### Two host-side traps this left behind

- **A stream that never ran censuses as zero splices.** The device can
  refuse to start now, so this is reachable rather than theoretical, and
  it reads as exactly the result a fix is hoping for. `tools/splices.py`
  raises instead of reporting when a run's level count is far below what
  its rate and duration require.
- **Preset `M` printed over its own capture.** Two printfs and a
  `uart_flush` ran immediately after `gen_go_tioa1()` - about 7 ms of
  blocked main loop on the first samples of every capture, on the path
  the suite calls its continuity control. Invariant 8. Moved ahead of the
  converters on `wip/refusal-reporting`. It was never inside the analysed
  window (`SETTLE_US` is 1 s) and is not an explanation for any of the
  above, but it had no business being there.

### Taking measurement off the printf channel (stages 1-4)

The rule is invariant 8 and it was not holding. It had been in CLAUDE.md
the whole time while `measure.py` - the apparatus every test measures
with - read its counters by sending `B` and scraping the printf, twice
*inside* run_loop, under a comment saying "counters first, while they
still describe the run". That is 13.14 ms of blocked main loop for `B`
and 15.40 ms for `O`, spent in the middle of the run being measured,
draining no bulk OUT for any of it. The daemon had been moved to the
control channel when it was built; `measure.py` never was.

**Stage 1, done.** `CTL_OP_STREAM_STATS` (0x0023, 23 counters, what `?`
prints) and `CTL_OP_BENCH` (0x0025, bytes and microseconds, what `B`'s
bench half prints). The device does not compute a rate - a throughput is
arithmetic over two counters and does not need a Cortex-M3 mid-benchmark
to do it. `stream.c` fills its own struct rather than un-static'ing its
counters, and `_Static_assert` guards the memcpy between the two
layouts so a divergence is a build error rather than wrong numbers on
the wire. CTL_VERSION 2 -> 3, FW_VERSION 0.1.0 -> 0.2.0, baseline.json
with them. Validated against the console on one running stream, field by
field.

**Stage 2, done.** `measure.play_counters()` and `measure.occupancy()`
prefer the control channel and report which path they used as `.via`.
Validated against the console on a real host-fed run: bytes_in 820224,
produced 801, consumed 799, underruns 171, isr 209711, endtx 970, spans
138, occ_min 2 - identical both ways, and the occupancy histogram too.

**Playback figures do not compare across stage 2.** Removing two 13 ms
stalls from inside a run removes the underruns those stalls caused. The
measurement got more honest; the device did not change.

**Stage 3, blocked on objective 1c.** The enforcement is
`#pragma GCC poison printf` plus a `dbg()` that takes only a string
literal - `#define dbg(s) dbg_puts("" s "")`, which will not compile with
a runtime value. Both were checked against arm-none-eabi-gcc 14.3 and
give the errors they should. It cannot be applied yet: **Track A has no
control channel at all**, so the console is the only instrument it has,
and poisoning one track and not the other creates exactly the asymmetry
invariant 3 forbids. Stage 3 lands the day 1c does, and not before.

**What holds the line meanwhile.**
`test_measurement_does_not_come_from_the_console_on_this_track` asserts
that where a control channel exists, the suite used it. It failed on its
first run and caught two real bugs - a wrong key name, and a bare
`except Exception` that swallowed it and degraded silently back to
printf. That second one is the failure mode worth naming: a fallback
that hides a bug behind a working-looking measurement taken the slow way
is worse than no fallback. `_LINK_GONE` is now (OSError, ValueError)
only.

**Still on the console, deliberately.** `test_core_did_not_rebuild_endpoints`
reads `rebuilds`, a Track A counter with no opcode, on a Track A only
test. `t`, `x`, `r`, `s`, `V`, `D` and `u` are bring-up and dump
commands run between runs rather than during them; they are stage 4,
along with the Track A half of all of the above.

### The rest, in brief

- **Objective 0h answered**: `Feeder.WRITE_SIZE` is a macOS workaround.
  24 runs across four write policies and six rates, 0 B deficit in every
  one; 23.48 MB through the legacy path at RC 39 loses nothing.
- **WSL2 is tier 2, native Linux tier 1 deferred.** usbip measured, and
  it does *not* degrade throughput or conservation - it *flatters* the
  host, because the tunnel is another queue in front of the ring. See
  `docs/windows.md`.
- **Track A runs on Windows**: 89/21 smoke, 198/19 full, same three
  failure classes as Track B. `arduino-cli upload` cannot flash a Due
  here and fails destructively; `sketch.py` routes through `flash.py`.

## Where the work stands (2026-08-25)

**Track A parity is a precondition for front-end work (set 2026-08-25).**
Objective 1b is done; **objective 1c is what remains, and it comes
before 1a.** The two tracks must be peers in design, feature set and
performance - both are bare metal on the same silicon, and Arduino is
an abstraction layer rather than a different architecture, so a gap
between them is debt with a date on it and not a property of the track.

**Start at 1c.** Its cheapest first step is named by the suite:
`test_playback_counters_describe_one_run_not_several` is the one Track
A failure in `pytest --track=a`, and it fails because Track A has no
`O`. Port the occupancy instruments, then the control channel.

If you are here to build G2 - trigger, measurements, FFT - objective 1a
has everything you need and none of it requires a board; read it, but
clear 1c first. The rest of this file is a measurement-integrity
investigation running for several sessions; it matters when you quote a
number, not when you write a view.

**Also added 2026-08-25: the firmware says what it is.** A board could
not tell you which track or which build it was running - the only answer
was prose in the console banner, matched host-side as a substring, on a
banner that costs 89 ms and lives on a port a deployed board does not
have. Now both tracks emit one identity line in one format, `v` prints
it for the cost of one line, and Track B's `IDENTITY` carries the
firmware version over the control channel, which is the deployed path.
Three version numbers now, deliberately: `FRAME_VERSION` and
`CTL_VERSION` are wire contracts a host refuses a pairing on,
`FW_VERSION_*` says which build is on the board when both are unchanged.
`CTL_VERSION` went to 2 for it. See `drivers/version.h`, which carries
the bump rule.

**What the 2026-08-25 (later) session changed:** objective 1b, which
had been recorded for weeks as blocked by the Arduino linker. It was
not. Track A now sends capture frames by endpoint DMA out of a ring
pinned to SRAM bank 1, with `linker/arduino_due_x_sram1.ld` and
`tools/sketch.sh`, and it measures zero ADC overruns at the full rate
where the same port in bank 0 costs 35-44. The invariant-1 violation on
that track is gone. Read 1b for the two build properties, the trap in
the stock `ram` region, and the purity result that Track B's version of
this change did not produce.

What the 2026-08-24/25 session changed, in one pass:

- **The native port carries a control channel.** Two CDC functions on
  one cable, a framed protocol, and six working opcodes - `PING`,
  `IDENTITY`, `COUNTERS`, `OCCUPANCY`, `RATE_TRACE`, `LOAD`. The daemon
  reads counters and the occupancy trace over it instead of the
  console, which took a status poll from 13.14 ms of blocked main loop
  to 146 us. Objective 8.
- **The device measures its own load** (`bsp/load.c`, `GET_LOAD`,
  console `l`). Cycle-counter based, validated against host-chosen
  stalls, and it is what found the two defects below.
- **printf is not an instrument** - now invariant 8 in `CLAUDE.md`, with
  the measurements behind it.
- **Constant memory and constant time on the working path** - invariant
  7, which immediately condemned code written the same day.
- **Objective 0c is answered.** The device is innocent and that is
  measured, not argued; a software detach recovers a wedged host 9 times
  out of 9. See 0c.
- The main loop went 9.72 us -> 6.70 us a pass by gating two polls that
  were asking a UOTGHS register about events that happen tens of times a
  second.

**Suite on Track A, 2026-08-25, first full run ever on that track:
198 passed, 18 failed, 23 skipped, 2 xfailed in 10:39.** Every one of
the 18 is in `tests/test_play_counters.py`, and every one is objective
1c - Track A has no `O`, no `play_run_us`, no rate trace and no closed
loop, so the tests that measure the measuring apparatus have nothing to
read. The two xfails are the known oversupply at RC 44 and RC 39. Nothing
in capture, integrity, streaming or transport fails. The run ends in a
0c wedge, which is the cascade of the failures above it rather than a
new symptom.

Suite on Track B: **234 and 232 passed, 0 failed**, on the last two
runs; the 2026-08-25 smoke pass after the stop-path fix is 108 passed,
0 failed. `.venv-gui/bin/python -m pytest tests/test_gui.py` is 14/14 -
worth knowing that those skip in `.venv`, which is how four of them sat
broken for a while.

## Where the work stood (2026-08-23, later session)

**Host-fed playback was losing samples at every rate above 200 ksps,
and had been all along. That is fixed; two narrower losses remain.**

The host's USB stack discards bytes `write()` has counted - silently,
with nothing erroring and every counter on both sides green. It was the
cause of the playback starvation that was objective 0a, and it was
objective 0b measured properly rather than at the one rate that happens
not to show it.

**The fix is one line of policy: write a constant 512 bytes per
`write()`** instead of "whatever is due, capped at 16 KB"
(`Feeder.WRITE_SIZE`). Same sizes on the wire, same pacing, same rate -
and no loss where the old policy lost 0.45% to 0.85%. The AWG and
one-channel ladders now run clean with no xfails, `STARVES` is empty,
and the three rates that starved report `under=0` with the ring at
21-30 slots instead of 5.

**What still loses samples, and neither shows up as an underrun:**

- **Oversupply at 886,363 and 1,000,000 sps** - 1.35% and 2.15%. Those
  converters run slow (1.58% and 2.35% by the device's own clock), the
  host feeds more than they can take, and the surplus is discarded
  rather than queued. Both report `under=0` while losing more than any
  other rate on the ladder.
- **An intermittent residual at 1,218,750 sps** - exact on most runs,
  then 384 B or 452,352 B with no pattern yet.

**So the rule this session earned: the underrun counter is not evidence
of a clean run.** It agreed with every wrong theory in this
investigation. Judge this path by byte conservation
(`test_device_receives_every_byte_the_host_sent`) and purity per
window, never by counters being green. Nothing above 200 ksps that was
measured before this session should be quoted until it has been re-read
that way - see objective 0h.

**The instruments that found it, all new this session:** the device
keeps its own playback-ring occupancy histogram and a decimated trace
of it (`O`), and times its own run (`play_run_us`); `run_play(drain_s=)`
and `run_bench(drain_s=)` let the pipeline empty before reading the
device's byte count, without which the comparison measures what is
still in flight rather than what was lost; and `Feeder(scale=)` and
`Feeder(write_size=)` are the knobs that turned inference into
measurement. `write_size=0` selects the old lossy policy and exists
only as the control arm.

The rest of the board is a working instrument with a front end on top
of it. What the previous session added was a spine on the host side: a
daemon that owns the ports, a socket API with its own test suite, and a
Qt window that draws from it.

**The daemon.** `host/daemon/` owns both ports and the real-time
feeder and serves clients over TCP - `docs/daemon-api.md` is the
reference, `docs/frontend.md` says why it is a separate process.
Frames cross verbatim, so `measure.parse_frames` reads a socket and a
serial port identically. `python3 -m daemon --fake` runs it with no
hardware at all, which is what front end work should be built against.

**The front end.** `gui/` is G1: a live trace with min/max decimation,
timebase and channel controls, and a health panel built first rather
than last. Run it with `.venv-gui/bin/python -m gui --spawn-fake`.

**Capture no longer touches the processor** (Track B). Each capture
buffer carries 32 bytes of headroom, so a finished frame is 4096
contiguous bytes sent by one DMA per packet. That closes the last
violation of invariant 1. It did **not** improve purity, which was the
reason the objective existed - see objective 1 below and the A/B in
`docs/status.md`. Track A got the same change on 2026-08-25, and on
that track it *did* improve purity - which is its own small puzzle. See
objective 1b.

**The daemon runs free-threaded.** With four busy Python threads in
its process, the GIL build underran playback 13 times and read 132
frames where a quiet run reads ~890; the free-threaded build of the
same version underran zero times and read 891. It is stdlib only, so
it needs no free-threaded wheels: `python3.14t -m venv` is the whole
setup.

**Latency is measured, not inferred.** `host/jitter.py` records the
device read gap, the fan-out cost and the feeder's write interval in
log-2 microsecond buckets, and the daemon reports them in `status`.
Every scheduling argument in this project used to be conducted in
units of "13 underruns"; it can now be conducted in milliseconds.

### The suite

`pytest --track=both -q`: **261 passed, 2 skipped, 5 xfailed in
15:10**. About 15 minutes for both tracks, of which the board-free
tests are seconds. No failures and no xpasses - every xfail is one of
the two remaining losses, named:

| xfail | |
|---|---|
| `receives_every_byte[a-44]` | 113,664 B, 2.13% |
| `receives_every_byte[a-39]` | 129,536 B, 2.15% |
| `receives_every_byte[b-44]` | 72,576 B, 1.36% |
| `receives_every_byte[b-39]` | 129,536 B, 2.15% |
| `receives_every_byte[b-32]` | 446,336 B - the intermittent residual, absent on most runs |

**Both tracks are byte-exact everywhere else**, including 600,000,
1,218,750 and 1,392,857 sps, which is the constant-size feed working on
Track A as well - the fix is host-side and needs nothing from the
firmware. Track A shows the same oversupply at 886,363 and 1,000,000,
which makes it a device-side property rather than a quirk of one
build.

| Venv | Interpreter | Runs |
|---|---|---|
| `.venv` | 3.14.6 | the suite - `--track=a|b|both`, `-m smoke` for a ~2 min pass |
| `.venv-gui` | 3.13.14 | the GUI and `tests/test_gui.py` (PySide6 is `<3.14`) |
| `.venv-ft` | 3.14.6 free-threaded | the daemon, and the suite when checking it there |

The GUI tests skip in `.venv` rather than failing, because that venv
deliberately has neither Qt nor numpy.

### Things that were believed and turned out to be wrong

Three, all disproved with measurement rather than argument, and all
worth not re-deriving:

- **The capture CPU copy was not limiting purity.** A/B in loop mode
  at the full-rate pair: median window 1291-1298 codes on DMA against
  1292-1306 on the copy, `resync=2` either way.
- **Objective 0a is not a clock-drift problem.** Two separate "6%
  drift" figures were measurement artifacts - see 0a.
- **The slew test's margin was never exercised** while the test was an
  xfail, so it inherited a number that the mechanism it measures
  exceeds routinely.

And five more from this session, every one of which was believed on
good-looking evidence and killed by an independent instrument rather
than by argument. The pattern is the lesson:

- **"Occupancy is decided in the first milliseconds and holds."** No.
  Every run starts at 20 slots, exactly where the lead puts it, and
  then decays or does not. The device's own trace showed it the moment
  one existed.
- **"Span count diagnoses the feed."** Backwards. The arming code
  spans *all* contiguous free slots, so span size is a function of
  occupancy. Spans are a symptom.
- **"Write size is irrelevant."** Tested only at 1,000,000 sps, which
  is oversupplied and which no write policy can fix. At 200,000 sps the
  threshold is plain: 0.000% at 512 B and 1024 B, 0.28-0.39% at
  2048 B, 0.56-0.76% above.
- **"The OUT bench reproduces the same defect."** It does not. The
  bench free-runs, which is saturation - a different regime, in which
  *smaller* writes lose *more* (512 B: 6.7%, 16384 B: 2.16%), the
  inverse of the paced feed. The 128-byte-granularity argument that
  linked them was vacuous because both bench counters are 512-aligned
  anyway.
- **"The constant-size feed costs ADC overruns."** Two runs said so
  (93 and 20 against 19 and 15). Three more rounds destroyed it: the
  due-sized feed gave 7, 16, 18, 140 and 573, the constant one 3, 10,
  11, 19 and 100. Overruns at the full-rate pair do not separate the
  two feeds at all.

Work is on `main` and **pushed** as of 2026-08-25. The board was last
flashed with **Track B**, and both tracks carry the identity line, so
`v` will tell you rather than this paragraph; `pytest` reflashes
whichever track it needs.

Of the three things separated out of the lost-sample defect two
sessions ago, two turned out to be one and are now fixed: **the rate
starvation and the host's sample loss were the same defect** - see
0a/0b. The `close()` wedge (0c) is still its own unreproduced thing.

Track A matches Track B on the sample path as of 2026-08-25: same
command letters, same output format, same refusals, same wire format,
same throughput, and now the same capture path - endpoint DMA out of a
capture ring pinned to SRAM bank 1. Its bulk endpoints were taken away
from the Arduino core and put on UOTGHS DMA; the core still enumerates.
What it is still missing is the 2026-08-24/25 session's *instruments*
and the control channel - objective 1c. Typical figures are
OUT ~27, IN ~31-32, duplex ~15-16 MB/s, but **the run-to-run spread is
35-59%, not the ~5% this file used to claim**: five 4 s runs per mode
gave IN 19.8-30.5, OUT 17.9-28.2, duplex 8.2-20.0. The suite's floors
are set from the minima for that reason, and a single benchmark run is
not evidence of a change. See "Track A parity" in `docs/status.md`.

The 900 ksps loop runs on both: `--dac-sps 906976 --adc-hz 453488` is
906,976 conversions per second, because two channels convert
round-robin. Single-channel capture now exists too (`--adc-channels 1`,
or `=<dac>,<adc>,1` on the console) and both tracks run a matched loop
at its ceiling of 886,363 sps each way with `under=0`. **Read `under=0`
in that sentence with objective 0h in mind**: it was measured with the
feed that lost bytes, and 886,363 sps is one of the two oversupplied
rates that lose most while reporting exactly that.

Track B runs the complete instrument loop on one channel pair:

```
HOST -> USB bulk OUT -> DAC0 -> jumper -> A0 -> ADC -> USB bulk IN -> HOST
```

Endpoint DMA works (the historical one-transfer stall is fixed), the
playback ring is fed by DMA with no CPU byte-copy, and every measured
regime is validated by the tone-amplitude oracle (theoretical maximum
~1370.5 ADC codes for a full-scale sine), not by counters alone:

| Regime | State | Evidence |
|---|---|---|
| Matched loop up to 453,488 sps each way (ADC in-spec ceiling) | under=0, gaps=0, median window 1371 | at 200 ksps the loop is now byte-exact end to end: `play_bytes_in` equals the host's `write()` count and a host-fed ramp has no discontinuities |
| AWG play-only up to 1.393 Msps (DACC hardware ceiling, RC 28) | **runs; loses samples above 200 ksps** | the underrun pattern (RC 195/98/44/39 clean, 65/32/28 not) is a *symptom*: the host discards 0.45-2.25% of what it writes at every rate above 200 ksps, and the rates that report under=0 are among the worst losers. See objective 0a/0b |
| Full-rate pair: DAC 906,976 + capture 906,976 aggregate | **runs, under=0**, both tracks | windows 1074-1345 (B), 1028-1338 (A) |
| Transport via endpoint DMA | measured; **OUT byte-perfect withdrawn** | IN 32.0 / OUT 26.6 / duplex 16.95 MB/s, all bytes *offered*. Drained, the OUT bench delivers 26.3-28.0 depending on block size and is short by 2.2-6.8%; the benches free-run into saturation. See objective 0h |
| Two-channel DAC (tag-interleaved) | routing verified | purity open, see objective 4 |

The `~1.7 MB/s "gated OUT" cap` that once blocked full-rate duplex is
explained and gone: it was DMA/FIFO re-arm latency times transfer
granularity, removed by multi-slot DMA spans with mid-flight progress
publishing.

## Current firmware/host design, in one pass

- **Playback**: host streams 16-bit tagged samples over bulk OUT; a
  32-slot (32 KB) ring in SRAM bank 1 is filled by endpoint DMA
  (multi-slot spans, `BUFF_COUNT` progress publishing, stream variant
  without END_TR so short packets never fragment a span); DACC + PDC
  drain it at TIOA1's rate; underrun repeats a buffer and is counted,
  never concealed. Progress is read from **one** snapshot of
  `DEVDMASTATUS` per pass - byte count and channel-enabled both come
  out of that single read, and `play_bytes_in` follows it continuously
  so it can be compared against the host's `write()` count byte for
  byte. `play_partial` counts spans that ended off a slot edge and
  must stay zero.
- **Capture**: TIOA0-triggered ADC, PDC ping-pong into a 4-buffer ring,
  frames (32 B header + 2032 samples = 4096 B). **Both tracks send them
  by endpoint DMA**: each buffer carries the header in 32 bytes of
  headroom in front of its payload, so a finished frame is contiguous
  and goes out in packet-sized transfers the processor never reads. The
  ring is pinned to SRAM bank 1 for that reason - see the hard-won
  facts. Track A gets there with `linker/arduino_due_x_sram1.ld`, passed
  by `tools/sketch.sh`; build it any other way and the ring lands in
  bank 0, which still links, still runs, and costs 35-44 ADC overruns
  per 4 s at the full rate.
- **Host feed** (`host/loopback.py`): real-time thread (`host/rt.py`,
  QoS + Mach time-constraint; XNU has no core pinning), clock-paced at
  the DAC byte rate with a 20 KB lead, blocking writes of whole
  512-byte packets only. Safe because the DMA-fed ring drains the tty
  queue at wire speed, so the macOS pressure-drop condition cannot
  form. The older TIOCOUTQ empty-queue gate was correct for the
  manual-FIFO device and is obsolete; do not resurrect it without
  re-reading `docs/usb.md`.
- **Rates**: `=<dac>[,<adc>]` before `L`/`P` on the console;
  `--dac-sps/--adc-hz` on `loopback.py`. Refusals name the limit.

## Next objectives, in order

**Start here**: objective 1c, the rest of Track A parity. It is a
precondition for the front end now, not a background chore - see the
note at the top of this file. 1b is done.

**Then** objective 1a, the front end. It needs no board, and the path it
stands on was checked end to end on 2026-08-25 rather than assumed.

**If you are chasing numbers instead**: objective 0i, the oversupply
loss. It is the largest
remaining hole in the data path - 1.35% and 2.15% of the waveform at
886,363 and 1,000,000 sps - it has a clear cause, and the fix (closed
loop on the device's own consumption) is now a real fix rather than a
mask, because the byte loss underneath it is gone.

**Objective 8**, the native-port control channel, is the one thing
standing between this and a board deployable on one cable. Its transport
and six opcodes are built and measured; what is left is the
state-changing commands - and Track A, which is part of the parity gate
above.

Note what this ordering replaced: this file used to say G2 "needs no
board at all and cannot be blocked". That is still true of the *cable*
and the *board*. It is no longer the whole story, because the gate is
Track A parity rather than hardware.

**Before quoting any number in this file, read objective 0h.** Most
figures above 200 ksps were measured with a feed that silently lost
0.45-0.85% of what it wrote, and were judged by an underrun counter
that stays at zero through exactly that.

The 0-series is what came out of the lost-sample defect two sessions
ago, plus what came out of taking it apart properly. 0a/0b and 0l are
fixed; 0i, 0j, 0h and 0c are what is left. 0i's gate is discharged -
the slow-converter instrument is validated - but it grew a new
sub-question: RC 44 reads one of two discrete converter rates.

0a/0b. ~~**Playback starves at RC 65, 32 and 28.**~~ **Fixed, and it
   was never a feed-policy problem.** The host's USB stack was
   discarding bytes `write()` had counted, and the ring drained at
   exactly that rate. Writing a **constant 512 bytes** per `write()`
   instead of "whatever is due" removes it: the AWG and one-channel
   ladders now run 14/14 clean with no xfails over repeated passes,
   `STARVES` is empty, and the three rates that starved report
   `under=0` with the ring at 21-30 slots instead of 5.

   Two things are still open and are tracked below: an oversupply
   effect at RC 44 and 39 that no write policy can fix, and a residual
   intermittent loss at the top of the ladder. Neither starves the
   ring; both lose samples. Read on before quoting any figure above
   200 ksps.

   The original entries follow, because the evidence is what makes the
   remaining items tractable.

   These were two objectives. They are one defect, and the second one
   caused the first.

   **What was measured.** Stop feeding, let the pipeline drain, then
   compare the host's `write()` count against `play_bytes_in`, which is
   exact because it follows the OUT DMA's `BUFF_COUNT`. Two runs per
   rate on a quiet machine, agreeing within 1%: 200,000 sps loses
   nothing; 397,959 loses 0.45%; 600,000 loses 0.67%; 886,363 loses
   1.48%; 1,000,000 loses 2.25%; 1,218,750 loses 0.67%; 1,392,857 loses
   0.85%. Every deficit is a whole multiple of 128 bytes while the host
   only ever writes multiples of 512. Held by
   `test_device_receives_every_byte_the_host_sent`, which asserts the
   128-byte granularity at every rate (a ragged loss would be the
   device dropping data it received, which is worse) and xfails above
   200 ksps naming the chunk count.

   **The drain is what makes it a measurement.** Counters read straight
   after the feeder stops show a deficit that is mostly pipeline - 55
   to 450 KB sits in the CDC driver below the tty layer. That the rest
   is genuinely gone was established by reading the device once a second
   for six seconds afterwards: `play_bytes_in` and `play_consumed`
   freeze while `play_underruns` climbs. The device sits starved with an
   empty ring and the bytes never arrive. It is not the wire either -
   bulk OUT is CRC'd with retries and NAK backpressure.

   **So the old 0b figure was an artifact of where it was measured.**
   "Roughly one 3 s run in eight under load, none in 22 on a quiet
   machine" was measured at 200 ksps, the one rate that loses nothing.
   Above it the loss is continuous and reproducible on an idle machine.

   **And it explains 0a exactly.** The ring drains at the rate bytes go
   missing: RC 65 loses 0.67% and decays at 0.73% per second; RC 32
   loses 0.67% and decays at 0.79%. Everything the old entry blamed -
   scheduling, feed policy, lead size, span arming - was this.

   **Three things the old 0a entry asserted are wrong**, disproved by
   the device's own occupancy trace (`O`, added this session):

   - *"Decided in its first milliseconds and holds for the whole run."*
     No. Every run starts at 20 slots, exactly where the 20 KB lead puts
     it. RC 32 then decays linearly to 4 over 850 ms; RC 65 over 2 s.
     What differs between rates is the slope, not the start.
   - *"A starving run arms few large spans and a healthy one many
     small ones."* True but backwards as a diagnosis. The arming code
     spans **all** contiguous free slots, so span size is a function of
     occupancy. Spans are a symptom; the feed is the cause.
   - *"`B` costs no underruns."* Rate-dependent. At 200 ksps the ring
     holds 51 ms and it is free; at RC 65 with the ring at 5 slots,
     polling at 20 Hz took the run from 6 underruns to 30. Where you
     most want to observe, observing is what breaks it. That is why the
     occupancy instrument lives on the device.

   **The floor is a servo, which is why it is stable at ~5 slots.** The
   ENDTX guard needs 3 slots; below that it repeats a buffer, and a
   repeat consumes time but not data, so the device's data consumption
   falls until it matches whatever the host actually delivered. The
   underrun count is that error signal: at RC 65, 0.0031 of 3516 ENDTX
   events found fewer than three slots, which is the 11 underruns
   reported.

   **Do not "fix" this by over-feeding.** Feeding 1-2% surplus takes
   every failing rate to `under=0` - measured at scales 1.005 through
   1.05 - while the dropped samples stay missing. The counter goes green
   and the waveform stays broken, which is exactly what invariant 5
   exists to prevent. For the same reason **the clean rates are not
   clean**: 886,363 and 1,000,000 sps lose the most (1.48%, 2.25%) and
   report `under=0` only because the device's own timing shows its
   converter running slow there by nearly the same fraction. Two errors
   cancelling. Judge this path by byte conservation, never by the
   underrun counter.

   **Also ruled out.** It is not the device's clock: the device times
   its own run now (`play_run_us`) and agrees with the host to 0.02%.
   It is not a rate-dependent quirk: sweeping a deliberate feed-rate
   offset puts the balance point - where the ring neither fills nor
   drains - at 1.0077 for both RC 65 and RC 32, two rates a factor of
   two apart, so the shortfall is a constant fraction. And a feed loop
   closed on `TIOCOUTQ` cannot work: it reports the tty layer only,
   reading 0 while tens to hundreds of KB sit in the CDC driver, so it
   computes that it is at its target depth while the ring holds five
   slots. Any feedback needs a signal from the device.

   **Two candidate mechanisms are already eliminated**, so do not
   re-run them:

   - *Write size and cadence.* Forcing every write to a fixed size at a
     fixed rate leaves the deficit unchanged: at RC 39 it is 2.04-2.25%
     at every size from 512 B to 16384 B, a 32x span of size and of
     inter-write interval. Rate is the variable; what it is made of is
     not.
   - *Queue pressure, for the floor.* Feeding deliberately under the
     device's rate - ring draining hard, queue certainly empty - does
     not reduce it. At RC 65 the deficit is 0.62-0.78% at every feed
     scale from 0.96 to 1.00. Only the surplus above 1.00 is pressure
     related, and it is steep: 1.01 loses ~1.06%, 1.02 loses ~1.86%.

   So there are two components: a **rate-dependent floor that happens
   with an empty queue**, and a surplus-shedding term above it. The
   floor is the open question, and it is the one that makes the
   waveform wrong.

   **The next experiments, in order:**

   1. ~~**Drain the benches.**~~ **Done, and it changes the problem.**
      `run_bench` now drains, and `out-dma` at ~28.5 MB/s is short by
      2.15-2.25% at drain lengths of 0.3, 1.0, 3.0 and 6.0 seconds -
      flat, so none of it is in flight - with no flush on any run and
      every deficit a whole multiple of 128.

      **So this is the OUT path, not the playback feed.** It reproduces
      with no DAC, no ring, no pacing and no real-time thread: a plain
      writer thread and a device that sinks by DMA. Attack it there;
      it is by far the simplest reproduction, it runs at 15x the rate,
      and nothing about the DAC or the feed policy is involved.

      It also means **"OUT 26.6 MB/s byte-perfect" is withdrawn**. The
      OUT throughput figures in this project are bytes offered, not
      bytes delivered.
   2. **Check capture IN the same way.** Nothing has ever compared
      device-sent against host-received with a drain. If IN loses too,
      every purity figure in this project is suspect.
   2a. **Separate host drop from device under-count.** Not yet done,
      and it decides everything downstream. The 128-byte granularity
      points at the host - a device-side DMA counter would be granular
      in packets (512 B) or in span size - and bulk OUT cannot lose
      data on the wire. But the device's counting has not been audited
      against an independent measure, and blaming macOS without doing
      that is exactly the mistake this project made for a fortnight
      over `DEVDMASTATUS`. Cheap version: throttle the bench writer and
      see whether the loss falls to zero at low rates the way the
      playback feed does at 200 ksps.

   3. **Leave CDC-ACM for the OUT path** if the floor survives 1 and 2:
      claim the interface with libusb or take the bulk endpoints
      through IOKit. That removes the layer losing the bytes and also
      removes the TIOCOUTQ blindness, so a real closed loop becomes
      possible afterwards.

   Do **not** start with a feed-policy or flow-control redesign for the
   *floor*. Every such policy compensates for a loss rather than
   removing it, takes the underrun counter to zero, and leaves the
   waveform broken. That warning does not apply to 0i, where the host
   genuinely oversupplies and matching the rate is the actual fix.

0i-underruns. **Solved, and it was one constant.**

   The underrun half of this objective is closed. `PLAY_PRIME_BUFS` was
   4: the DAC's timer started once four of thirty-two ring slots held
   data, which is 1.4 ms of runway at the top rate. Raised to 24, the
   AWG ladder reports **zero underruns at every rate from 200,000 to
   1,392,857 sps**, five runs each, with byte conservation untouched and
   occmin going from 2 to 18-26.

   Measured, five runs per rate, underruns per run:

   | prime | RC 44 | RC 39 | RC 28 |
   |---|---|---|---|
   | 4 (was) | 4-7 | 7-10 | 22-25 |
   | 12 | 1-5 | 5-11 | 14-21 |
   | 20 | 3-6 | 1-7 | 13-20 |
   | 22 | 0 | 0 | 0 |
   | **24 (now)** | **0** | **0** | **0** |

   The threshold is sharp because nothing drains while the timer is
   stopped: the ring fills to exactly the prime and that is where it then
   sits. **The prime sets the operating point, not just the start.**

   What found it, after this was chased across many sessions and blamed
   on feed policy, write size, scheduling, thread priority, driver
   buffering and three operating systems: **run the same rate for 1 s,
   3 s and 9 s.** At RC 28 all three gave 21-24. Nine times the duration,
   the same count - so it was a burst at the start and nothing else, and
   only the ring's state at t=0 could explain it.

   Raising the prime creates one hazard and it is handled: a playback
   shorter than the prime would never start, because the ring never
   reaches the threshold and the abandon timer drops a waveform that
   arrived intact. `play_service` now also primes on a host that has
   gone quiet with at least `PLAY_PRIME_MIN` slots. Verified: 8 KB and
   16 KB transfers, both under the 24-slot threshold, play.

   **Still open in 0i: the oversupply byte loss**, which is a different
   defect and macOS's - see below and `docs/windows.md`. Windows loses
   0 B at every rate, so the underrun half and the byte half were never
   the same problem, and treating them as one is part of why this took
   as long as it did.

   **Track A has not had this change** and its prime is still 4;
   objective 1c.

0i. **Oversupply at 886,363 and 1,000,000 sps: 1.35% and 2.15% of the
   waveform, with `under=0`.** The largest remaining loss, and the
   place to start.

   **The premise is now confirmed on single runs, not inferred across
   rates.** RC 44 picking one of two converter states per run makes it
   a controlled experiment: same commanded rate, same feed, same write
   policy, and the state is the only thing that moves. Over eight
   drained runs, seven took the fast state and lost 1.35% against a
   converter 1.56% slow; the one that took the slow state lost 2.13%
   against a converter 2.34% slow. Control at RC 65: six runs, 0.00%
   both. **The deficit follows the converter, not the rate.** Held by
   `test_the_deficit_is_the_oversupply`.

   One loose end: the deficit is consistently **0.21 pp less** than the
   converter's shortfall, in both states, reproducible to 0.01 pp. It
   is not explained. Do not design against it until it is, and do not
   assume it is a constant at other rates - it has only been measured
   at RC 44.

   Those converters run slow - 1.58% and 2.35% measured against the
   device's own clock (`play_run_us` with `play_consumed`). The host
   feeds the declared rate, the device cannot take it, and the surplus
   is discarded by the host's USB stack rather than queued. The
   deficits are those same figures, which is the giveaway. No write
   policy can fix this: the bytes are genuinely surplus.

   **The closed loop is built, and it works.** `run_play(closed_loop=
   True)`. The device reports a monotonic total of buffers consumed; a
   slow outer loop trims the feed's *rate* model - never its position -
   while the inner loop stays clock-paced and constant-size. Measured,
   interleaved against its own open-loop control:

   | rate | open loop | closed loop |
   |---|---|---|
   | 600,000 (RC 65) | 0.000% | 0.000% |
   | 886,363 (RC 44) | 1.344%, 1.352% | 0.434%, 0.213% |
   | 1,000,000 (RC 39) | 2.151%, 2.151% | 0.480%, 0.472% |

   `under=0` in every closed-loop run, which matters: the loop trims
   *down* toward the converter, so the failure it could have bought is
   starvation, and the opposite trap - over-feeding to make the counter
   read zero while the samples stay missing - is what `docs/usb.md`
   warns about. Neither happened.

   **It is off by default**, because turning it on changes what every
   measurement in this file measures and the ladders that set the
   baseline have to keep meaning what they meant.

   **What is left is startup, not rate error.** The feed runs open loop
   until the first trim can be made, and those bytes are lost once per
   run rather than continuously. At RC 39: 27,648 B over 3 s and
   28,544 B over 6 s - the *bytes* are flat and the percentage halves,
   0.466% to 0.242%. A wrong rate model would lose proportionally. So
   the residual shrinks with run length and matters least where it
   matters least: a scope streams for minutes.

   Shortening it means shortening the dead head, which is not the
   loop's: `run_play` issues `P` and then spends about half a second on
   console reads before the feeder starts, and the device sits
   play-active with nothing to play for all of it. Fixing that changes
   the startup timing of every measurement in the file, so it was left
   alone.

   **The carrier is built and validated.** It could not be the console:
   `B` polling at 20 Hz took RC 65 from 6 underruns to 30 when the ring
   was short, because printf holds the main loop. It is now a 28-byte
   record on the native port's bulk IN, emitted from the main loop every
   20 ms in play-only - `drivers/playstat.h`, parsed by
   `measure.parse_playstats`, read as a rate by `measure.playstat_rate`.
   Loop mode is untouched: the emitter is gated on `stream_in_in_use()`,
   because there IN carries frames on DMA and the FIFO path must not
   share the endpoint.

   **Loop mode has its carrier too, in the frame header - but the plan
   recorded for it was wrong about the cost.** This file said the header
   "already has spare fields and costs nothing". It had none: all 32
   bytes were allocated, and the size is load-bearing - `acq.h` sizes
   the payload so header plus payload is 4096 bytes, `8 x 512`, one DMA,
   whole packets.

   So the frame format went to **version 2**: `play_consumed` at offset
   28, CRC at 32, header 36 bytes, and the payload down from 2032
   samples to 2030 to hold the 4096. The header is shared verbatim
   between the tracks, so both were changed together along with both
   host parsers and `docs/protocol.md`. Track A builds and Track B runs.

   The field completes a pair rather than adding one: the header already
   carried `timestamp_us` from the same device clock, so
   `measure.playstat_rate` reads frame headers with no change at all -
   `ParsedStream.play_stats` is a list of the same `PlayStat` the
   bulk-IN records parse into.

   Validated the same way as play-only, against the console trace in the
   same run: at RC 44 the frame carrier reads +1.58% against the trace's
   +1.56%. `run_loop(closed_loop=True)` retunes without disturbing
   capture - no CRC failures, no sequence gaps, no underruns - which is
   the case that matters, because there the correction and the
   measurement share a wire.

   It agrees with the console trace to **0.001-0.018 pp** at RC 65, 44
   and 39 - two paths sharing only the device's clock - and costs the
   playback path nothing measurable: deficit 0.00%, 1.35% and 2.15% at
   those rates with `under=0`, matching the baseline taken before it
   existed. Held by `test_the_carrier_reports_what_the_console_trace_reports`
   and `test_the_carrier_stays_silent_in_loop_mode`.

   **Read the rate over an interval where `consumed` is moving, and
   start it one record after consumption begins.** Three estimators were
   wrong before this one, all plausible: spanning every record reads 55%
   slow, because a drained run collects seconds of starvation; spanning
   to the last record with a *frozen* tail still reads 0.1-0.7 pp slow,
   because the ring and pipeline empty raggedly; and selecting the
   longest run with no underruns selects everything, because before the
   ring primes the DACC trigger has not started, so `underruns` is
   frozen at 0 alongside `consumed`. The remaining trap is an
   off-by-one: the span must not begin on the last frozen record, or the
   partial interval in which playback started costs up to 0.6 pp and
   wanders run to run. ~~And verify the
   slow-converter figure before designing against it.~~ **The figure is
   verified; the instrument is sound.** `OccHist.device_byte_rate()`
   divides `consumed` by `run_us`, and both are reset per run, so the
   estimator was never the problem. Measured undrained, three runs per
   rate: 600,000 reads -0.01/-0.02/-0.01%, 1,000,000 reads
   -2.36/-2.35/-2.35%, 1,218,750 reads +0.00/-0.01/-0.01%. Spread is
   0.01-0.02 percentage points. The recorded RC 32 -6.26% outlier did
   not reproduce in thirteen runs and is unexplained; it is not a
   property of the estimator as written. Design against these figures.

   Why those two rates and not 600,000 or 1,392,857 is unexplained. It
   is not the DACC ceiling (1,392,857 *is* the ceiling and measures
   exact) and not RC truncation (RC 39 divides 39 MHz to exactly
   1,000,000).

   **RC 44 is bimodal, and the state is latched at `play_start`.**
   886,363 sps does not read one slow rate - it reads one of exactly
   two, chosen per run and then held for the whole of it. Measured with
   the per-window rate trace (`play_rate_us`, now off by default - see
   below): across
   twelve runs the median of the first third and of the last third
   agreed to **0.000 pp every time**, and the spread across ~160
   windows was 0.010-0.021 pp, which is the trace's resolution rather
   than movement in the converter. The two states are -1.56%
   (872,4xx sps) and -2.34% (865,5xx sps); nothing between them has
   ever been seen. Roughly seven runs in twelve take the fast one.

   `under=0` and `occ_p50=30` in both states, so the ring is backed up
   either way and the converter is device-limited rather than starved.
   Neither rate is 39 MHz over an integer, so it is not the trigger
   divisor. 1,000,000 sps shows no such split - it reads -2.34% every
   time - and that is also RC 44's slow state, which may or may not be
   a coincidence.

   **What this means for the loop.** It is designable: the converter
   holds one rate per run, so a rate model can be *measured at the
   start of a run* and trusted for the rest of it. What it must not do
   is carry a rate across `play_start`, or average the two states into
   a figure the hardware never produced. The mechanism that picks the
   state is still unknown, and does not have to be known to close the
   loop - only to predict which state a run will take.

   **The instrument that found this is now off by default, and that is
   a correctness decision.** Sampling `micros()` in the ENDTX handler
   perturbs the path it measures. Placed between `play_consumed++` and
   the TNPR store - inside the window that handler exists to keep short
   - it broke `test_host_fed_ramp_loses_no_samples` in 2 runs of 6, with
   1,600 to 2,500 forward jumps of 10 to 12 bytes: the sub-slot
   signature of a late pointer load, with `under=0`, no CRC failures and
   no sequence gaps. Bisected - the same test was clean 6 of 6 at the
   commit before the trace existed. Moved after the PDC re-arm it fell
   to about 1 run in 8, better and still not nothing, so it is behind
   `PLAY_RATE_TRACE_ENABLED` (default 0). Turn it on to re-check the
   bimodality; do not judge sample integrity on a build that has it on.

   That is also 0e's signature - "losses of exactly 10 bytes" - which
   this file recorded from one Track A run and could not explain. Worth
   checking whether 0e was ever something else.

   The instrument to use instead is the carrier: `measure.playstat_rate`
   over `PlayResult.stats` in play-only, or over
   `ParsedStream.play_stats` in loop mode, or `trace` on the It is keyed on *consumed* buffers rather than on ENDTX, so a
   window is exactly `PLAY_RATE_DECIM` buffers of data whatever the
   underruns, and it survives a drained run - which is the only way to
   read the deficit and the converter's rate from the same run, and so
   the only way to test the oversupply claim directly rather than by
   comparing two runs that may have taken different states.

0j. **Why a constant write size is lossless and a varying one is not.**
   The fix works and the mechanism is unknown, which is worth one more
   session before it is forgotten.

   The contradiction is sharp. A constant 512 B loses nothing. A
   constant 1024 B loses nothing. `min(due, 1024) & ~511`, which can
   only ever emit 512 or 1024, loses 0.47-0.84%. Same sizes, same rate,
   same pacing, same real-time thread. A 50x finer idle sleep changes
   nothing.

   Ruled out already: it is not a startup artifact (the deficit scales
   with run length - 2 s loses 19,840 B, 4 s 36,096 B, 8 s 67,712 B, so
   ~8-10 kB/s continuously), and it is not queue pressure (feeding 4%
   *under* the device's rate, with the ring draining and the queue
   certainly empty, still loses 0.68%).

   **The experiment that isolates it**, and it is cheap: strictly
   alternate 512 B and 1024 B writes at a rate that is clean with
   either size alone. If alternation alone reproduces the loss with
   nothing else changed, the mechanism is cornered - and the untested
   guess to aim at is that the CDC driver packs payloads into
   fixed-size internal buffers that a uniform stream stays aligned to.

0k. **An intermittent large loss at 1,218,750 sps.** Exact on most
   runs, then 384 B, then 452,352 B, with no pattern found. Always a
   whole multiple of 128. Tracked as `RESIDUAL` in
   `tests/test_integrity.py`, by outcome rather than by mark, so a
   clean run passes and it turns green by itself.

0l. ~~**`play_endtx_seen` disagrees with `play_consumed`.**~~ **Fixed.
   It was not ISR re-entry.** `play_start()` cleared every other
   playback counter and left `play_endtx_seen` alone, so the `O` line
   reported a total accumulated since boot while `consumed` and
   `run_us` were per-run. The disagreement was therefore whatever the
   previous runs in that session had added, which is why it looked
   rate-dependent: the ratio is a function of how many runs preceded,
   not of the rate.

   Seen directly by running the same rate three times in one session:
   `endtx` came back 3565, 7097, 10642, each the previous total plus
   this run's `consumed`. One line in the reset block fixes it. After
   it, `endtx == consumed + underruns` at 600,000, 886,363, 1,000,000
   and 1,218,750 sps, three runs each.

   **The occupancy histogram was never affected.** `play_occ_hist` is
   reset in the same block and incremented once per ENDTX, so its
   distribution was always sound - the earlier worry that its sample
   counts were inflated was wrong. Only the reported scalar and the
   *trace* decimation phase, which is derived from the same counter at
   `drivers/play.c:330`, were wrong; the trace's interval was always
   right, only its offset from the run start was arbitrary.

0h. **Re-validation debt: most figures above 200 ksps are unproven.**
   Not a defect, a bookkeeping obligation, and it is large.

   Every AWG and loop figure in `docs/status.md` and this file above
   200 ksps was measured with the feed that lost 0.45-0.85% of what it
   wrote, and was judged by the underrun counter, which stays at zero
   through exactly that kind of loss. The full-rate pair, the 900 ksps
   loop, the tone-amplitude oracle results, the "matched loop at 886,363
   each way with under=0" claim - none has been re-read against byte
   conservation. Some will hold. The two oversupplied rates will not.

   Re-run them with `run_play(drain_s=...)` or the loop equivalent and
   record the deficit alongside every figure, then correct the docs.
   Purity is judged **per window**, never per run - a phase
   discontinuity cancels a whole-run Goertzel, which is how a constant
   1024 B write looked fine on counters while its whole-run tone fell
   to 500 codes.

   **Answered on Windows: `Feeder.WRITE_SIZE` is a macOS workaround, not
   a rule** (2026-08-25, `docs/windows.md`). The constant-512 policy
   exists because "whatever is due, capped at 16 KB" lost 0.45-0.85%
   above 200 ksps here. Swept against rate on Windows - four write
   policies including the legacy due-sized path and the 1536 B size that
   loses most, across six rates from 200,000 to 1,392,857 sps - **24
   runs, 0 B deficit in every one.** Confirmed at volume: 23.48 MB
   through the legacy path at RC 39, the worst rate on record here,
   deficit 0 B. macOS loses about 516 KB on that same run.

   So the byte-conservation half of this debt does not transfer. The
   Windows figures are the honest ones and they were taken with drains.

   **The policy keeps its place, for a different reason.** Underruns do
   depend on write size on Windows even though bytes do not: 16384 B
   roughly doubles them against 512 B at every rate (0 -> 3 at RC 195,
   0 -> 15 at RC 65, 21 -> 37 at RC 28). Constant 512 is still the right
   default; the justification in the comment above it is the wrong one
   off macOS, and should say ring stability rather than byte loss.

0c. **Answered, and now confirmed host-specific. The host is stuck, the
   device is not, and a software detach releases it.**

   Not fixed - it is a macOS defect this firmware cannot reach - but
   diagnosed, reproducible in thirty seconds, and recoverable without
   touching the cable.

   **The prediction has been tested and it held** (2026-08-25, Windows
   11, second board; `docs/windows.md`). Same firmware, same
   reproducer, no wedge: 0 in 40 cycles of the standard soak and 0 in 12
   of a harder variant that closes with a write actively transferring
   430 KB/s, against 9 in 30 on macOS. It is this host.

   **But the mechanism is not the one that was assumed, and that is the
   part that matters.** Windows does not survive the backlog - it never
   builds one. `usbser.sys` paces the writer at the device's consumption
   rate, so a 256 KB write returns in 0.193 s having delivered all but
   about 1 KB, and `close()` then has nothing to dispose of. macOS
   buffers 55-450 KB below the tty layer and hangs disposing of it.

   **That single difference also explains the byte loss.** A driver that
   applies backpressure cannot silently discard, and Windows loses zero
   bytes at every rate from 200,000 to 1,392,857 sps. So 0c and
   0a/0b/0i/0k are two symptoms of one macOS behaviour rather than two
   faults - worth knowing before any more of either is attributed to the
   device.

   **The device is innocent, measured rather than assumed.** During a
   live wedge, read over the control channel (a different interface,
   which keeps answering while the sample port is stuck):

   ```
   loop passes  +145049 in 1.00 s     145 k passes/s
   drain polls  +145049               a drain on every single pass
   ```

   Both EP2 banks free, nothing pending, not stalled, AUTOSW off. The
   device is draining an empty pipe as fast as the hardware allows.

   **It is not the tty layer either.** `TIOCOUTQ` answers `EBADF` while
   the hang is in progress: `close()` is past the file-table stage and
   blocked inside the driver.

   **`z` does not help, and that is a fact about `z`.**
   `RSTC_CR_PROCRST` resets the processor only; the UOTGHS keeps running
   with its pull-up attached, so the host never sees a disconnect.
   Twenty seconds, still hung. Do not read that as "the device cannot
   release it".

   **A software unplug releases it in milliseconds.**
   `usb_cdc_detach_cycle()` drops the pull-up, waits, and restores it -
   the recorded physical recovery, in software. Console `=<ms>Z`, and it
   must be commanded from the *programming* port because detaching takes
   the control channel down with it. First attempt: 0.02 s. A soak of 30
   open/close cycles wedged 9 times and recovered **9 of 9**, 0.01 to
   0.23 s.

   `close_native()` now tries it before giving up, so a wedge costs a
   re-enumeration instead of the rest of the session.

   **The reproducer**, `tools/soak0c.py`, about thirty seconds: soak
   port open/close cycles with write URBs outstanding, which is what 0c
   hangs in. Closing with playback still running wedges roughly one
   cycle in three; closing after stopping it ran 40 cycles clean with a
   worst close of 0.005 s.

   **The prediction worth testing, and the tool is already written.** If
   this is macOS's CDC-ACM close path, the same firmware and the same
   soak should not wedge on Linux or Windows.

   `tools/soak0c_portable.py` is that experiment: pyserial and nothing
   else, no dependency on POSIX-only `host/`, ports matched on USB
   VID/PID (2341:003D programming, 2341:003E native) which reads the
   same on every OS.

   ```sh
   pip install pyserial
   python tools/soak0c_portable.py --cycles 40      # --stop-first = control arm
   ```

   Fidelity checked on macOS before it was trusted anywhere else: 6
   wedges in 25 cycles, 6 recovered, against 9 in 30 for the POSIX
   original. **The payload must go out in one blocking write.** pyserial
   keeps a POSIX fd non-blocking and feeds the tty queue in select-sized
   chunks, and written that way it did not wedge in 65 cycles on a host
   where the blocking version wedges one in four - so how much is
   outstanding at close is part of the condition, not merely that
   something is. Windows blocks in WriteFile anyway.

   **Run on Windows 11, 2026-08-25: 0 wedges in 40 cycles, worst close
   0.002 s.** So 0c is macOS's and this firmware is done with it.

   One caveat on reading that as a verdict on the close path: the
   standard soak cannot wedge Windows, because WriteFile is paced by the
   device and returns with ~1 KB outstanding, so `close()` never faces a
   backlog. The condition had to be built deliberately - a slow DAC, a
   4 MB write from a writer thread, `close()` from another thread one
   second in - and the device counted `in=430080` during that second,
   proving the write was moving data at full rate when the close hit it.
   Twelve cycles, no wedge. Details in `docs/windows.md`.

   Linux is still untried, and would say whether this is macOS
   specifically or every CDC-ACM stack that buffers.

   The earlier entries follow, including the DPRAM re-allocation defect
   found and fixed on the way - real, confirmed by a counter, and not
   the cause of this.

   **It is host-side. The device is draining throughout.**

   Measured, finally, because the control channel is a different
   interface and keeps answering while the sample port is stuck. Taken
   during a live wedge:

   ```
   loop passes  +216408 in 1.51 s     143 k passes/s
   drain polls  +216408               every single pass
   ```

   Both EP2 banks free, nothing pending, not stalled, AUTOSW off. The
   device is draining an empty pipe as fast as the hardware allows while
   macOS waits in `close()`. **The recorded mechanism - a NAKing pipe
   that never completes the host's write URBs - is not what happens.**
   Every earlier diagnosis had to assume the device's side; none could
   read it.

   **A thirty-second reproducer**, `tools/soak0c.py`: soak port
   open/close cycles with write URBs deliberately outstanding, which is
   the one thing the previous session listed as never tried. Closing
   with playback still active wedged at cycles 8, 5 and 2 across three
   runs; closing after stopping it ran 40 cycles clean with a worst
   close of 0.005 s.

   **Where to look next, given the device is exonerated:** what differs
   between those two cases on the *host* side. Stopping playback makes
   the device consume the queue before close; not stopping leaves data
   queued below the tty layer. So the condition is likely "close() with
   bytes still outstanding", and the device's readiness to accept them
   is irrelevant - which would explain why fourteen *drained* runs closed
   in 0.00 s and why `tcflush` never helped.

   Two things worth trying that have not been: `ioreg`/`ioclasscount`
   on the pipe state during a wedge, and whether a `libusb` handle on
   the same device can complete or abort the pipe from outside the
   wedged process.

   The earlier entry follows, including the DPRAM re-allocation defect
   that was found and fixed on the way - real, confirmed by a counter,
   and not the cause of this.

   **A real cause found and fixed. The wedge still happens.**

   **Read the correction at the end of this entry before quoting the
   233-passed run.** One clean full-suite run was taken as confirmation
   and it was not: the same firmware wedged on the next two runs.

   `ep_apply_autosw()` switched an endpoint between FIFO and DMA by
   rewriting `DEVEPTCFG` with `ALLOC` still set, which re-allocates it -
   and datasheet 40.5.1.6 says the next endpoint's memory window then
   slides up and loses its data. It fires twice per capture start and
   stop, from eight call sites. Inert while EP3 was the last endpoint;
   live the moment the control channel added EP4 to EP6 above it.

   Fixed by not writing when the bit already holds the wanted value, and
   by re-allocating the control endpoints in ascending order when a
   write is needed. `usb_ctl_reallocs` on `u` reads 2 after one capture
   cycle, so the hazard is visible rather than inferred.

   | | before | after |
   |---|---|---|
   | the 41 s reproducer | wedged, twice | clean, 3:54 |
   | full Track B suite | wedged, five times | 233/0 once, then wedged twice |

   **The correction.** The 233-passed run was one run. The next two runs
   of the same code wedged - one with a drain-gating experiment applied,
   one with it reverted and the binary behaviourally identical to the
   one that passed. So the DPRAM re-allocation was a real defect and its
   removal is worth keeping, but it was not the only cause and this
   objective is not closed.

   **Also tried and rejected: gating the idle bulk OUT drain to 1 kHz.**
   It is worth 1.68 us of a 6.77 us pass, and it narrows the drain to
   about 2 MB/s against a host that writes ~1.8 MB/s during playback.
   The margin is the guarantee, so the throughput of that loop is
   load-bearing and not a poll to be economised. Reverted; the comment
   in main.c says so.

   **Still open: the original.** The four earlier occurrences are dated
   2026-08-22 and 2026-08-23 and the second CDC function landed on the
   24th, so EP4-EP6 cannot have been the victim. The same mechanism with
   EP3 as the victim is the obvious candidate - re-allocating EP2 slides
   EP3, which carries frames - and half of this fix helps, because the
   redundant writes are gone. But EP3 is deliberately still not
   re-allocated: it can have an armed DMA transfer. Closing it means
   ceasing to toggle AUTOSW at run time, which needs the manual-FIFO
   users (the playback status record, the idle bulk OUT drain) dealt
   with first. That is the next move on this objective.

   The reproducer and the printf measurements that led here follow.

   **A deterministic reproducer, and a measured mechanism (2026-08-24).**

   Two for two, wedging at 41 seconds each time, with a stopwatch
   agreement that leaves little room for coincidence:

   ```
   .venv/bin/python tools/loadwatch.py /dev/cu.usbmodemB_013 log stop &
   .venv/bin/python -m pytest tests/test_play_counters.py --track=b
   ```

   `test_play_counters.py` alone is clean. Add a process polling
   `GET_LOAD` on the native control channel at 10 Hz beside it and the
   suite wedges in `close()` both times. That is the first reproducer
   this objective has ever had; four earlier occurrences were all
   after the fact.

   **The mechanism is printf, and it is now measured rather than
   suspected.** The load monitor reports the worst main-loop pass, and
   a console command is one pass. During that pass the main loop drains
   no bulk OUT - which is precisely the NAKing pipe `docs/usb.md` says
   hangs macOS in `close()`:

   | console command | blocks the main loop |
   |---|---|
   | `B` bench stats | 13.14 ms |
   | `?` stream stats | 20.18 ms |
   | `O` occupancy histogram | 15.40 ms |
   | `l` load report | 13.03 ms |
   | `h` banner | 89.03 ms |
   | `u` usb registers | 113.35 ms |
   | 20 x `GET_LOAD` over the control channel | 0.29 ms **total** |

   The control channel is about a thousand times cheaper per query,
   because it writes 164 bytes to an endpoint instead of formatting
   text into a 115200-baud UART.

   **So the suite is a participant, not just a witness.** It polls
   `B`, `?` and `O` *during playback*, and each poll stops the drain
   for 13-20 ms. The control-channel poller did not introduce a new
   defect; it added enough extra main-loop pressure to turn an
   intermittent wedge into a reliable one - which is the most useful
   thing it could have done.

   What follows from it, in order:

   - **Move the suite's in-flight polling off the console.** Any status
     read taken while the sample path is running should go over the
     control channel. That is what it is for, and the figures above are
     the argument.
   - **printf is a debug method, not an instrument.** Recorded in
     `CLAUDE.md` as a rule rather than an observation. `l` is in the
     table above for a reason: the console form of the load report
     costs 13 ms and must not be used during active work. `GET_LOAD` is
     the supported path.
   - It is still worth knowing whether a drain gap alone is sufficient,
     or whether a host-side condition has to coincide. The stall
     injector (`=<ms>S`) can now produce a drain gap of any chosen
     length on demand, so that is a designed experiment rather than a
     wait for it to happen again.

   The original entry follows.

   **The suite wedged once in `close()` after the duplex DMA bench**,
   on 2026-08-22, and it was unexplained. All 134 tests reported and
   none failed; the session then hung in `close()` on the native port
   for 50 minutes with the board's heartbeat still flashing and both
   USB activity LEDs dark - the device had stopped draining bulk OUT,
   which is the hazard `docs/usb.md` describes: macOS's `close()` waits
   for in-flight write URBs and `tcflush` cannot recall them.

   **Reproduced on 2026-08-23, and confirmed from the inside for the
   first time.** A script doing 13 drained `run_play` calls back to
   back (RC 44 x8, RC 39 x3, RC 65 x2) wedged with CPU time frozen -
   3.63 s of CPU unchanged across 21 s of wall clock, which is what
   distinguishes blocked from slow. `sample <pid> 2 -mayDie` put all
   1435 samples of the main thread in `os_close` -> `close()` in
   libsystem_kernel. Previous occurrences were diagnosed from the LEDs;
   this one has a stack. The board was fine afterwards, both ports
   still enumerating, exactly as the entry predicts.

   Note `close_native()` already does `tcflush(TCIOFLUSH)` before
   `os.close`, and it still hung - which is the recorded behaviour, not
   a surprise: `tcflush` reaches the tty queue and cannot recall a URB
   already at the controller.

   **The obvious hypothesis is wrong.** Oversupply looked like the
   trigger - those rates leave bytes the converter can never take - so
   a soak ran 6 drained runs at RC 65 then 8 at RC 44, timing every
   close. All 14 closed in 0.00 s. Oversupply alone does not do it, and
   the run that wedged is still the only one that has.

   **And a second time the same day**, during a full `--track=b` run,
   about 68% of the way through. Same signature and same confirmation:
   CPU time frozen at 44.18 s across two samples while wall clock ran to
   42 minutes for a suite that takes 11, and all 1618 samples of the
   main thread in `os_close`. Board healthy afterwards, both ports
   enumerating.

   **Two stack-confirmed occurrences in one session, against one in the
   weeks before.** That may be chance, and it may not: this session
   added an emitter that writes bulk IN every 20 ms during play-only.
   The wedge is a *write* URB on bulk OUT, so there is no mechanism
   connecting them that survives a second's thought - but the
   coincidence is recorded rather than dismissed, because the last four
   things this session was sure of were wrong.

   **Not reproduced on demand**: eight consecutive duplex-dma and
   out-dma benches after the first occurrence closed in 0.00 s each,
   and the 14-run soak above adds to that. What has never been tried is
   a soak of *port open/close cycles* rather than of benches - both
   occurrences this session came during long sequences of them, which is
   the one thing the two have in common. So this is a candidate, not a
   cause - but a specific one. `usb_cdc_dma_mode()` stops both DMA
   channels and flips AUTOSW and **never issues `EPRST`**, while the
   fact recorded below says stopping the channel is not enough and the
   endpoint must be reset too. Track A implements exactly that
   (`ep_reset_fifo()` in `sketches/bringup/usbdma.cpp`); Track B has no
   `EPRST` anywhere. A DMA stopped mid-bank leaves a bank nothing
   frees, and the endpoint then NAKs for good.

   **The `EPRST` theory is dead. Do not implement it.** A wedge was
   finally caught with the device interrogated at the moment of the
   hanging close, and `ep2(OUT)` read `CFG=00003066 ISR=00044188` -
   bit-identical to the healthy baseline taken from several hundred
   good closes, with `NBUSYBK` clear. **No bank was held.** The fix
   this entry recommended for weeks would have changed nothing and
   cleared the data toggle for nothing.

   Also withdrawn, because it was the same mistake made faster: the
   wedge's OUT DMA showed `BUFF_COUNT` of 16,896 bytes outstanding,
   which looked like a smoking gun against a three-sample baseline. At
   106 samples a non-zero `BUFF_COUNT` is simply normal - 30,720 is the
   commonest value. Nothing measured at the wedge yet differs from a
   healthy close.

   **What the evidence now points at.** The board is healthy throughout
   and its heartbeat runs in the main loop, so the main loop is alive.
   A live main loop drains bulk OUT only when nothing owns it:

       if (!play_active() && !stream_out_in_use())

   so the one state that produces a NAKing pipe with a healthy endpoint
   is a device that still believes a playback or a bench is running
   while nothing consumes. Confirming that needs the *mode* at a wedge,
   which is what `B` reports and what the trap below now captures. It
   has not been caught yet: 318 healthy closes across three suite runs
   all read `bench=off`.

   **Four occurrences, none reproducible on demand.** Ruled out by
   measurement, not argument: oversupply (14 drained runs), bench mode
   switching (40 cycles), a large undeliverable backlog (25 undrained
   runs at ~2 MB each), the transport benches alone (3 clean runs), and
   console pressure - a suite run with *extra* console traffic on every
   close passed clean.

   **A wedge costs the bench, not just the run.** The stuck thread is
   blocked in the driver, so `kill -9` leaves the process in `STAT ?E`
   - exiting, unkillable - still holding both port fds. The next
   process to open the port then blocks in `open()` rather than
   `close()`, which is how a 12-minute suite run became an 11-hour one.
   Recovery is physical: unplug and replug the board. There is no
   software route.

   **The trap is armed, so stop hunting it.** `close_native` now closes
   on a thread with a 3 s deadline. On a wedge it reads the device's
   state over the control port - a different fd, still working, which
   is why every earlier diagnosis had to guess - and then re-sends the
   stop. If the drain-gate theory is right the close completes and the
   run continues; if not, the run fails with the device's state
   attached. Either way the suite stops being un-runnable, and the next
   occurrence arrives already diagnosed.

   It did not recur in the 2026-08-22 two-track pass, which ran the
   same benches on both tracks and closed in the usual time. Still
   unreproduced, so the reasoning above stands unchanged.

0e. **One gross ramp failure on Track A - and its signature came back.**
   The 10-byte quantum is what a late DACC pointer load looks like: this
   session put `micros()` in the ENDTX handler and reproduced 1,600 to
   2,500 losses of exactly 10 to 12 bytes, on demand, on Track B. That
   does not explain the original - Track A had no such code - but it
   names the mechanism the signature points at, which is more than this
   entry had. Anything that lengthens the ENDTX path is now a suspect,
   including on Track A. Original entry follows.

   On
   2026-08-22 `test_host_fed_ramp_loses_no_samples[a]` failed with
   73,314 losses of **exactly 10 bytes each** - not the host's 128-byte
   signature, and far too many to be the beat in 0f. Every loss being
   the same size says something systematic, not noise. It has since
   passed 9 runs on Track A, one of them xfailing with the ordinary
   host signature, so it is not reproducible on demand. Recorded rather
   than dismissed: if it returns, capture the run's raw stream before
   anything else, because the pattern is the whole evidence.

0f. **The slew alarm was the sampling beat, and the margin was wrong.**
   Closed, and written up in `docs/status.md`. Kept here for the rule
   it produced: **a threshold that has only ever run under an xfail has
   not been tested.** When the xfail comes off, the numbers it was
   hiding need re-deriving rather than inheriting.

0g. ~~**The firmware does not refuse a DAC rate past the DACC
   ceiling.**~~ **Fixed on both tracks.** `play_start` now refuses
   below `PLAY_MIN_RC` (28) and both consoles name the limit the way
   the ADC path always has. `tests/test_contract.py` holds it: RC 28 is
   accepted, RC 27 and RC 20 are refused, and a refusal must contain
   the word "max". Original entry follows.

   **The firmware does not refuse a DAC rate past the DACC ceiling.**
   `=906976,906976,2L` is refused with the limit named - `# loop: ADC
   906976 Hz x2 ch refused (max 453488)` - which is the behaviour the
   documentation describes. But `=1950000,200000,2P` is *accepted*:
   RC 20, well past the ~1.393 Msps the DACC can convert at ~54.7 MCK
   cycles per conversion. Observed on both tracks while testing the
   daemon's refusal path.

   It matters more now than it did. `host/daemon/rates.py` refuses it,
   so nothing gets through the daemon - but that makes the host the
   only check rather than a courtesy, and a console user still walks
   straight into it. Refuse it in firmware, on both tracks, naming the
   limit the way the ADC path already does.

0d. **The pytest suite** - built, and it is the instrument that found
   all four defects on this page. `docs/testing.md` is the design and
   records what building it found. About 5 minutes per track, ~138
   tests for both. `--track=a|b|both`, `--reflash` to force a flash,
   `-m smoke` for a ~2 minute iteration pass.

1. **Capture IN over endpoint DMA** - **done on Track B**, and its
   premise was wrong. The design was as sketched here: 32 B of headroom
   per capture buffer, PDC on the payload, CPU writing only the header.
   What it did not do is improve purity - measured against the old
   firmware in loop mode at the full-rate pair, the two paths are
   indistinguishable and both show resync=2. Whatever limits purity
   there is not the copy.

   Two things had to be measured to make it safe, and the first version
   lost samples while looking perfect: transfers are packet-sized and
   the capture ring is pinned to bank 1, because a 4096-byte transfer
   from bank 0 costs 439 ADC overruns per 4 s at the full rate. Full
   table in `docs/status.md`.

   **Track A now does the same** - objective 1b, done 2026-08-25. The
   81 overruns per run recorded here as the cost of that port were the
   port *in bank 0*, not the cost of copying; the copy path measures
   zero, re-measured three times.
1b. ~~**Capture over endpoint DMA on Track A.**~~ **Done, 2026-08-25.**
   Same struct as Track B - 32 bytes of header headroom in front of the
   payload, so a finished frame is 4096 contiguous bytes - packet-sized
   512-byte transfers, per-direction DMA mode setters, and the capture
   ring pinned to SRAM bank 1.

   **The blocker on record never existed, and had never been checked.**
   It said "Track A links against the Arduino core's script and cannot
   pin a buffer to bank 1". Two facts out of the installed toolchain say
   otherwise:

   - The stock Due linker script already declares the region.
     `variants/arduino_due_x/linker_scripts/gcc/flash.ld`:
     `sram1 (rwx) : ORIGIN = 0x20080000, LENGTH = 0x00008000`.
   - The script itself is an ordinary build property. `platform.txt`
     links with `-T{build.variant.path}/{build.ldscript}`, and
     `boards.txt` sets `arduino_due_x_dbg.build.ldscript=linker_scripts/gcc/flash.ld`.
     So `--build-property build.ldscript=<your copy>` substitutes it -
     the same mechanism this project already relies on for
     `build.f_cpu`, without which `micros()` is silently wrong.

   `linker/arduino_due_x_sram1.ld` is that copy. **Two changes, and the
   second one is the trap:** a `.sram1` output section over the existing
   region, *and* `ram` shrunk from the stock 96 KB to bank 0's 64 KB -
   because the stock `ram` spans 0x20070000..0x20088000 and therefore
   *includes* bank 1. Before this, the sketch's `.bss` ended at
   0x20081B6C, 6.5 KB inside the bank, and the stack top was at
   0x20088000. Placing a buffer at 0x20080000 without shrinking `ram`
   puts it under `.bss` with no diagnostic. The `.sram1` section is also
   placed *last* in the script, so `_end` - the heap base
   `syscalls_sam3.c`'s `_sbrk()` starts from - stays in bank 0.

   The path has to be relative to the *installed variant directory*, so
   it is computed rather than written down: `tools/sketch.sh` is the one
   place that knows both build properties, and `measure.flash("a",
   build=True)` calls it.

   **Measured, three firmwares in one session, capture-only at the full
   rate, 4 s, three runs each:**

   | Track A build | GOVRE per 4 s |
   |---|---|
   | CPU copy (the path it replaces) | 0, 0, 0 |
   | DMA, ring in bank 0 | 42, 44, 35 |
   | **DMA, ring in bank 1** | **0, 0, 0** |

   `dma-frames` equals `frames` and `dma-stalls` is 0, so no frame falls
   back to the copy path. Same shape as Track B's 2x2, same cause.

   **Purity improved, unlike Track B's.** Median window over six
   full-rate loop runs each: 1213.3 copy, 1255.6 DMA, and every DMA run
   beat every copy run (1252.2-1266.7 against 1207.5-1218.9), against a
   theoretical maximum of 1370.5. The bank-0 arm reaches the same
   1255.6, so it is the DMA path buying this and not the placement.
   Track B's A/B found the two paths indistinguishable at the same
   rates; **why the same change separates them here and not there is
   open**, and it is the interesting residue of this objective.

   **Loop-mode GOVRE does not separate the arms and six runs each is not
   enough that it ever will:** copy 1, 13, 67, 93, 480, 881; DMA in bank
   1 9, 12, 14, 24, 145, 473. Do not quote a loop-mode overrun figure
   from a single run in either direction.

1c. **Track A has fallen further behind, and the list is now long.**
   Missing relative to Track B: the second CDC function and the whole
   control channel, the load monitor (`l`, `GET_LOAD`), the software
   detach (`Z`), the stall injector (`S`), the playback-abandon
   timeout, and the drain-poll counter - on top of what it was already
   missing below. The project rule is that anything added to one track
   is added to the other with the same commands and output format, and
   that debt has grown faster this session than any other.

   **One landmine, half defused.** Track A's `ep_apply_autosw()` in
   `sketches/bringup/usbdma.cpp` rewrites `DEVEPTCFG` with `ALLOC` set,
   re-allocating the endpoint and sliding the next one's memory window -
   the version that cost Track B a session. Objective 1b ported the
   first half of the fix: the write is skipped when the bit already
   holds the wanted value, which is what most calls were doing. **The
   second half is still missing** - re-allocating the endpoints above,
   in ascending order, when the write does happen - and it is inert only
   while Track A stops at EP3. The day this track grows EP4 the hazard
   goes live, which is the same day the control channel arrives. Port it
   with the feature, not after it; `drivers/usb_cdc.c`'s
   `ep_realloc_control()` is the model.

   The wire format is the thing that matters most: `docs/control-protocol.md`
   says both tracks must present *identical* descriptors and identical
   response bytes, and the suite is where that is enforced. The two
   on-board control tests in `tests/test_link_health.py` and all of
   `tests/test_control.py` skip on Track A today; they are what will
   stop skipping.

   **Track A has none of the earlier session's instrumentation either.** `O`, the
   `occmin` key on `B`, and `play_run_us` are Track B only, so Track A
   cannot be measured against the defect that dominated this session.
   **The suite has measured how far behind: `pytest --track=a` is 198
   passed, 18 failed, and all 18 are `tests/test_play_counters.py`.**
   They fail rather than skip, because `O` returns nothing and the tests
   assert on lines that were never printed. That file is therefore the
   whole of this objective's first half, and it is a straight port:
   `sketches/bringup/play.cpp` is deliberately a transliteration of
   `drivers/play.c`, so the ENDTX hook goes in the same place. Port the
   instruments and 18 failures become 18 passes or 18 honest findings -
   either is progress, and nobody knows which yet, because Track A's
   playback has never been measured by them.
   The project rule is that anything added to one track is added to the
   other with the same commands and output format, and this is a
   straight port - `sketches/bringup/play.cpp` is deliberately a
   transliteration of `drivers/play.c`, so the ENDTX hook goes in the
   same place.

   The host-side fix (`Feeder.WRITE_SIZE`) is track-independent and
   already applies to both, but nobody has run the byte-exactness test
   against Track A. Do that before quoting any Track A playback figure:
   its numbers were taken with the feed that loses bytes.

1a. **G2 on the front end**: trigger (edge, level, pulse; auto, normal,
   single), automatic measurements (Vpp, RMS, frequency, duty, rise and
   fall), math including A-B, and FFT with a window choice. The decode,
   ring and reduction are already Qt-free in `gui/stream.py` and tested
   there, so this is mostly new views over existing data.

   **Verified working on 2026-08-25, so start from here rather than
   from doubt:**

   ```sh
   .venv-gui/bin/python -m gui --spawn-fake      # the whole thing, no board
   .venv-gui/bin/python -m pytest tests/test_gui.py -q     # 14/14
   .venv/bin/python -m pytest tests/test_daemon_api.py -q  # no board
   ```

   Driven headless against a real `--fake` daemon, the real
   `MainWindow` ingested 1178 frames across two channels at 200 ksps.
   The front end does not auto-start: `start_capture()` is what the
   Start button calls, which is worth knowing before concluding that no
   frames arrive.

   **What you already have, and it is most of what G2 needs.**
   `ChannelRing.window(n)` returns `(samples, breaks)` - a contiguous
   numpy array *and* a discontinuity mask. That mask is not decoration:
   invariant 5 forbids presenting spliced data as continuous, so a
   trigger must not arm across a break and an FFT must not transform
   across one. `minmax(samples, columns, breaks)` already puts NaN at
   breaks for the decimated draw, and is the model to follow.

   The fake daemon emits a real sine - `2048 + amplitude * sin(phase)`,
   1 kHz by default - so every measurement and the FFT can be developed
   *and validated against a known answer* with no hardware. Use that:
   a frequency readout that has never been checked against a tone whose
   frequency you chose is not a measurement.

   `.venv-gui` has numpy 2.5.2, scipy 1.18.1, PySide6 6.9.3 and
   pyqtgraph 0.14.0. `.venv` deliberately has none of them, which is why
   `tests/test_gui.py` skips there - the skip reason names the command.

   **Three design facts that will bite, none of them blockers.**

   - **Channel skew is real.** Conversions are ~0.95 us apart, not
     simultaneous. Single-channel work is unaffected; **A-B math must
     correct for it host-side** or it produces a phase artefact that
     looks like a signal. `docs/hardware.md` has the figures.
   - **The DAC is not rail-to-rail** (~0.55-2.75 V), so absolute voltage
     readouts against the loopback need that calibration and not a naive
     full-scale mapping. `codes_to_volts` is the place.
   - **Do not put a throughput or sample-rate figure above 200 ksps in
     the UI yet.** Objective 0h: most were measured through a feed that
     silently lost 0.45-0.85%. Samples in hand are fine; quoted rates
     are not.

   **Where the design already is:** `docs/frontend.md` has the scope
   feature list and the reasoning, including why the trigger is software
   today and what a hardware trigger (`ADC_EMR`'s window comparator)
   would buy later.

   One cheap piece of polish that is not a prerequisite: the daemon now
   reports `via: "control"` on `counters()` and `trace()`, and the
   health panel does not surface it. That panel is also the natural home
   for `GET_LOAD`.

2. **Replace the marginal native-port cable** before attributing any
   further purity variance to software. It failed hard twice on
   2026-08-21 (VBUS present, D+/D- dead: enumerates nowhere) and the
   run-to-run variance has the signature of link-level retransmits.
3. **The second pair** (DAC1 -> A1 as an independent instrument pair).
   Bandwidth is trivial after the DMA work; the loop code needs
   two-channel waveforms and per-channel analysis.
4. **Two-channel DAC purity.** Tag routing is verified correct
   (975 Hz only on A0, 1500 Hz only on A1 at 97.5 ksps/channel), but
   dual mode shows two unexplained signatures with all counters clean:
   A0 phase jumps aligned to ring-slot boundaries, A1 steps at an
   exact 32-sample period. Retest after objectives 1-2; either may
   explain both.
5. **Equivalent-time reconstruction**: DAC and ADC dividers share MCK,
   so coprime RC values walk the ADC's sample phase through the DAC
   waveform in 25.6 ns steps - a sampling-scope view of the DAC
   through the slow ADC. The single-channel capture mode it needed now
   exists; what remains is the host reorder script.
6. **`usb_cdc_write`/DMA bank overcommit when the host stops
   draining** (status.md "Next" item 0): flood counters read far above
   the wire; harmless in normal operation, meaningless benches.
7. **MCK 40 for a capture-only scope mode** - investigated and shelved,
   recorded so it is not re-derived. `PMC_MCKR_PRES_CLK_3` makes MCK a
   multiple of 4, so MCK 40 with `PRESCAL=0` reaches exactly 20.0 MHz
   of ADC clock against today's 19.5 - the only in-spec way to clear
   900 ksps on a single channel (predicted 909,090, and 930,232
   aggregate for two). It is not worth it for the loop: the DACC is
   MCK-limited at ~54.7 cycles per conversion (measured, see
   hardware.md), so halving MCK roughly halves the AWG to ~730 ksps,
   below the new ADC ceiling. Only interesting as a runtime-switchable
   capture-only mode. **Trap if anyone tries it:** `ACQ_MIN_RC` is
   MCK-independent only while `PRESCAL=1` keeps the timer clock at
   twice the ADC clock. With `PRESCAL=0` they are equal and every cliff
   RC halves - 86 becomes 43, 44 becomes 22 - so the guard must be
   expressed in ADC clocks (22 isolated, 43 per pair) and derived from
   the live clock ratio.

8. **The native-port control channel** - the deployed board is one
   cable, and that cable is the native port, so a control path that
   lives behind the programming port does not exist in deployment at
   all. `docs/control-protocol.md` is the design and carries its own
   status table. What is done:

   - the command layer is split out of `main.c`'s switch, so parsing
     and execution are separate and a second transport can reach the
     same executor (Track B);
   - the native port presents **two** CDC functions on one cable, which
     enumerate as two device nodes - samples on interfaces 0/1,
     commands on 2/3;
   - `usb_ctl_read()` / `usb_ctl_write()` carry bytes both ways, tested
     byte-exact at 2048 bytes each way with a temporary echo build;
   - the main loop drains the command endpoint although nothing
     consumes it, because an undrained bulk OUT hangs the host in
     `close()`;
   - `host/ports.py` returns all three nodes and tells the native pair
     apart by USB interface number rather than by name order.

   What is not:

   - **the frame parser and the executor binding.** The header, opcodes
     and error convention are designed in `docs/control-protocol.md`
     and nothing implements them. Bytes written to the command node are
     currently drained and discarded.
   - **the heartbeat and asynchronous notifications**, which are the
     reason this is an endpoint pair rather than EP0.
   - **Track A**, which still has one CDC function. Both tracks must
     present identical descriptors and identical responses, and the
     suite is where that is enforced - `--track=both`, comparing, not
     two tests asserting separately. The two on-board tests in
     `tests/test_link_health.py` skip on Track A today and are what
     will stop skipping when it follows.

   One figure that is settled and should not be re-derived: the UOTGHS
   has 4096 bytes of endpoint DPRAM, 2240 of it already spent, and the
   control function costs 1088 more. It costs that much rather than the
   384 the design first assumed because USB 2.0 requires a high-speed
   bulk endpoint to be exactly 512 bytes, so the endpoints are 512 and
   single-banked rather than 64 and double-banked. Two 512-byte
   double-banked pairs need 4416 and do not fit.

## Hard-won facts the next session must not rediscover

- **The underrun counter is not evidence of a clean run.** It agreed
  with every wrong theory in the starvation investigation. Playback
  loss on the host side of the wire produces no underrun, no sequence
  gap, no CRC failure and no counter movement, because the device
  counts what *it* drops and these bytes never reach it. Judge by byte
  conservation and by purity per window.
- **Write a constant size to the CDC port.** A constant 512 B is
  lossless; "whatever is due" loses 0.45-0.85% at every rate above
  200 ksps even when every write it emits is 512 or 1024. The
  mechanism is unknown (objective 0j); the measurement is not.
- **Do not raise that to 1024 for syscall economy.** It is byte-exact
  in play-only and halves the syscalls, and in the full-rate loop the
  whole-run tone falls to 500-984 codes against 1215-1290 - the phase
  discontinuity signature. Measured, and it looked like a free win
  right up to the point it was measured in duplex.
- **Sleep until the next write is due, not on a fixed tick.** A fixed
  100 us poll costs 10k wakeups a second and 0.14 of a core at the
  full-rate pair; the arrival time is known exactly from the byte rate.
  With it, the constant-size feed costs no measurable CPU over the
  due-sized one it replaced.
- **A byte comparison against the device means nothing without a
  drain.** 55 to 450 KB sits in the CDC driver below the tty layer, and
  read straight after the feed stops it all looks like loss.
  `run_play(drain_s=)` and `run_bench(drain_s=)` exist for this. To
  prove a shortfall is real rather than in flight, read the device
  repeatedly: `play_bytes_in` and `play_consumed` freeze while
  `play_underruns` climbs.
- **Counters read across a drain describe the shutdown.** A 1.5 s drain
  at RC 39 adds ~6,000 underruns to a run that had none, and the
  occupancy histogram spans the starvation too. `run_play` therefore
  takes byte counts from after the drain and everything else from
  before it, and reports occupancy as empty on a drained run.
- **`TIOCOUTQ` is blind here.** It reports the tty layer only, reading
  0 while tens to hundreds of KB sit in the CDC driver beneath it. A
  feed loop closed on it computes that it is at its target ring depth
  while the ring holds five slots. Any feedback needs a signal from the
  device.
- **The OUT benches free-run, which is saturation, and they are not a
  model for the paced feed.** In that regime *smaller* writes lose
  *more* - 512 B loses 6.7% where 16384 B loses 2.16% - the inverse of
  the paced case. Their throughput figures are bytes offered: delivered
  is 26.3 MB/s at 512 B against 28.0 at 16384 B, and **"OUT 26.6 MB/s
  byte-perfect" is withdrawn.**
- **The playback ring's floor is a servo, not a resting place.** The
  ENDTX guard needs three slots; below that it repeats a buffer, and a
  repeat consumes time but not data, so device consumption falls until
  it matches whatever the host actually delivered. A ring pinned at
  ~5 slots with a steady underrun rate is measuring the feed deficit,
  not a scheduling problem.
- **Asking the device costs underruns exactly where you need to ask.**
  `B` polling at 20 Hz took RC 65 from 6 underruns to 30 with the ring
  at 5 slots, and costs nothing at 200 ksps where the ring holds 51 ms.
  The "B is free" note below is rate-dependent. This is why the
  occupancy instrument lives on the device.
- **Asking the board for its banner while it plays costs eleven
  underruns**, and `B` is only free when the ring has margin - see the
  entry above.** Every time, measured. The banner is a long console
  print, the main loop is inside it, and `play_service()` does not run
  while it is. `B`, the short counters report, costs none. The rule the
  daemon now follows: **on a poll path, ask the device nothing** - its
  `status` is answerable from the host alone and the device
  description is cached, because it used to be fetched per call.
- **Measure a firmware change against the firmware it replaces, not
  against expectation.** Capture over DMA streamed with no gaps, no CRC
  failures and no stalls while losing 439 ADC conversions per 4 s run.
  Reflashing the old build took three minutes and was the only reason
  that was attributed to the change rather than to the board.
- **The two SRAM banks are separate enough for placement to matter**,
  which `docs/scope.md` had listed as an open question. USB DMA reading
  the same bank the ADC's PDC writes costs 439 overruns per 4 s at the
  full rate; the other bank halves it; packet-sized transfers remove
  the rest. Track B therefore pins capture to bank 1 and playback to
  bank 0 - a swap, not a shrink.
- **A frame is 4096 bytes because the header sits in front of the
  payload**, in the same allocation. `acq_slot_t` is that struct, and
  `_Static_assert` holds both its size and the frame's 512-byte
  alignment. Growing the header silently breaks every short-packet rule
  in `docs/protocol.md`.
- **The GIL couples the daemon's own work to its real-time threads.**
  Four busy Python threads in the process: 13 underruns and 132 frames
  read against ~890 on the GIL build, none and 891 free-threaded. Load
  in *other* processes is the scheduler's business and is unaffected.
- **A drain loop with no bound never returns** when the producer is
  faster than the display. It hung the GUI's first test run for ten
  minutes. The daemon is built to drop toward a slow client and count
  it, so leaving frames queued is the designed behaviour.
- **Do not derive a ring's write position from a running total.** It is
  correct until one append is larger than the ring, and then the window
  silently returns samples that are not the newest.
- **A threshold that has only ever run under an xfail has not been
  tested.** When the xfail comes off, the numbers it was hiding need
  re-deriving rather than inheriting.
- **Both "the device clock drifts 6%" figures were artifacts.** The
  first anchored on a frame that was already 0.19 s old; the second
  lagged by however deep the kernel buffer was. The device clock is
  right to a tenth of a percent - 600,725 sps measured against a
  declared 600,000 once the pre-roll is removed.
- **Never analyse a capture without proving it is fresh.** Stale
  kernel-buffered frames from a previous run manufactured a "frozen
  DAC" that cost a full session. Sequence numbers near zero and device
  timestamps spanning the host window are the proof; `loopback.py`
  enforces both.
- **macOS CDC-ACM drops ~128-byte chunks from a pressured tty queue**,
  silently, with `write()` having counted them. The current safe feed
  relies on the DMA ring keeping the queue shallow; if the device side
  ever reverts to manual FIFO, the empty-queue gate becomes necessary
  again.
- **macOS `close()` on a tty waits for in-flight write URBs.** The
  device must always drain bulk OUT when nothing consumes it (the main
  loop does), or host processes hang in `close()` holding the port.
- **A DMA transfer in flight when its endpoint is rebuilt is dead**, and
  stopping the channel is not enough: a stopped IN DMA leaves a bank
  partially filled and never validated, so the next transfer stalls the
  same way. `EPRST` the endpoint too. This presented as an intermittent
  one-transfer stall, about one run in two.
- **Read `DEVDMASTATUS` once and decode it, never twice.** Byte count
  and channel-enabled share the register, so two reads ask two
  different instants whether the transfer finished and how far it got.
  They disagree exactly when it finishes between them, and the playback
  ring then resumed its next span behind data already in SRAM and
  overwrote it: samples lost, always forward, always less than one
  slot, with every counter on both sides clean. It cost a fortnight and
  was blamed on macOS. `play_partial` counts the impossible case and
  the suite asserts it is zero.
- **Two transliterations of one algorithm are not two implementations.**
  Track A's `play.cpp` is deliberately identical to Track B's `play.c`,
  so "both tracks fail the same way, and they share no source" argued
  for a host fault when it was evidence of a design fault. Before
  reasoning from a cross-track agreement, check what the tracks
  actually share.
- **Never arm bulk OUT with `END_TR_EN` for streaming.** It ends the
  transfer on any short packet, host pacing produces those constantly,
  and a 2048-byte buffer then absorbs ~347 bytes per arm. It cost ~30%
  of OUT throughput on both tracks and looked like a Track A problem.
- **Measure loop rate with no traffic.** Under load the arming path is
  skipped whenever a channel is busy, so the loop counter reads up to
  17x faster than the loop really is, and points at the wrong culprit.
- **UOTGHS DMA needs AUTOSW**; a `DEVEPTCFG` write while EPEN is clear
  is silently ignored on this part; endpoint config is rebuilt on
  every bus reset and SET_CONFIGURATION so the driver must reapply the
  mode. Each of these alone recreates the one-transfer stall. All three
  apply to Track A's DMA layer too, where the core does the rebuilding
  and there is no hook to catch it - hence the polled keepalive.
- **Judge loop purity per window, never per run.** The whole-run
  Goertzel at 453,488 sps reads 232 codes against a theoretical 1370.5
  while nearly every 50 ms window reads above 1360: a phase
  discontinuity cancels the average. A per-run number is the wrong
  instrument and will report a collapse that is not happening.
- **The board resets whenever the programming port is opened** (NRSTB),
  which also re-enumerates the native port under a possibly new name:
  open control first, keep it open, re-glob and retry the native open.
  The device cannot time its own benchmarks; the host keeps the clock.
- **Discover ports, never hardcode them** (`host/ports.py`); a stale
  path once aimed the 1200-baud erase at the wrong port. On Track B
  there are **three** nodes, two of them on the native cable, and they
  are told apart by USB interface number rather than by name order -
  `find_all_ports()`, not `sorted(glob(...))[0]`.
- **Give the board time to re-enumerate before opening the native
  port.** `measure.Board(settle=3.0)` is what the suite uses and it is
  not decoration: opening the control port resets the board, and a
  native node opened too soon after that belongs to the instance going
  away. It opens successfully and then every write fails ENXIO, which
  reads as a dead device rather than a race.
- **The single-channel trigger floor is RC 44, not 43.** One channel
  reaches 886,363 conversions per second, two reach 906,976: a
  two-channel trigger converts its pair back to back and amortises the
  per-trigger overhead a lone conversion pays in full. Halving the
  two-channel compare value is the obvious move and it is wrong - RC 43
  measures ratio 0.500 with every status bit clear. `ACQ_MIN_RC_FOR()`
  is a table of measured values for that reason.
- **Trigger overrun is silent** (`ACQ_MIN_RC` 86, valid at any MCK).
  **`A0` is AD7, not AD0** (labels map descending). **The DAC is not
  rail to rail** (546-2760 mV), and a DACC channel that never converted
  since `SWRST` sits at its code-0 level - normal, not a fault.
- **Exact divisors matter**: rates that do not divide 39 MHz truncate
  in RC and shift every derived frequency; pick rates like 195000
  (RC 200), 453488 (RC 86), 906976 (RC 43), 1392857 (RC 28).
- **Periodic diagnostics alias periodic signals** (150 ms snapshots
  strobe a 1 kHz tone); pick intervals coprime to the signal.
- **Instrument the suspect region before attributing anything to it**,
  and prefer per-window analysis against device timestamps over
  whole-run averages - a handful of glitches per second hides in an
  average and shows instantly in windows.

## Starting on a different machine, or a different board

Nothing in the repository is machine-specific, but three things are not
in it and one of them is easy to mistake for a regression.

**The venvs are not committed and never travel.** A venv holds absolute
paths and platform wheels. Rebuild all three from the pinned
requirements; `CLAUDE.md` has the interpreters and what each one holds.
`.venv-ft` is the free-threaded 3.14 the daemon wants.

**The toolchain is the xPack ARM build, not ARM's own.** ARM's macOS
build links `cc1` against a Homebrew zstd at an absolute path and
cannot run here; the driver still reports a version, so the failure
only appears when something is actually compiled. See
`docs/toolchain.md`.

**`tests/baseline.json` is calibrated against one specific board**, and
says so in its own header: "Measured on THIS board at MCK 78 MHz. A
record of one board, not a datasheet." On a second Due, expect the
timing-sensitive thresholds to need re-measuring - amplitude floors,
the slew margin, the per-channel rate floors. A failure there on a new
board is a recalibration, not a regression, and the two must not be
confused: re-measure and record, do not widen a tolerance to make a
test pass.

Port paths are enumeration-dependent everywhere; discover them with
`python3 host/ports.py` rather than copying any path out of the docs.

And before a long unattended run, read objective 0c: a wedge leaves an
unkillable process holding the ports, and the only recovery is
unplugging the board.

## Environment

- macOS 12.7.6, Intel x86_64, no Homebrew - but **MacPorts is
  installed** at `/opt/local`. `/usr/bin/python3` is the Xcode CLT
  3.9.6 and nothing is built on it any more. `~/.local/bin` on `PATH`
  (holds `arduino-cli`, `cmake`, `gh`).
- **Three venvs, none committed.** A venv holds absolute paths and
  platform-specific wheels and does not travel; the pinned declaration
  is what is committed.

  | Venv | Interpreter | Holds |
  |---|---|---|
  | `.venv` | `/opt/local/bin/python3.14` (3.14.6) | pytest, pyserial |
  | `.venv-gui` | `/opt/local/bin/python3.13` (3.13.14) | PySide6 6.9.3, pyqtgraph, numpy, scipy |
  | `.venv-ft` | `/opt/local/bin/python3.14t` (free-threaded) | pytest; run the daemon here |

  PySide6 declares `>=3.9,<3.14`, which is why the GUI has its own
  interpreter. The daemon imports nothing outside the standard library,
  which is why it can run on the free-threaded build at all.

  `pyserial` arrived on 2026-08-25 for `tools/soak0c_portable.py`, the
  one host-side thing here that has to run off macOS. `host/` itself is
  still stdlib-only - which `CLAUDE.md` is careful to call a fact about
  the code rather than a rule new code inherits.
- Track B: `cmake --build build -j`, flash with
  `tools/flash.sh build/baremetal_bringup.bin` (discovers the port; an
  interrupted flash leaves SAM-BA enumerated and the banner silent -
  just flash again with the port given explicitly).
- Track A: `tools/sketch.sh compile` / `tools/sketch.sh upload`. Never
  a bare `arduino-cli compile` - it needs `build.f_cpu=78000000L`
  (MCK is 78) and `build.ldscript` (the capture ring in bank 1), and
  both are silent when missing.
- Use the **xPack** ARM toolchain; ARM's own macOS build cannot run
  here.
- Wiring: **DAC0 -> A0**, DAC1 -> A1.
- Remote: `origin` = https://github.com/jerryrt/due_oscilloscope.git,
  push via `gh` credential helper (already configured).
- LEDs: amber = heartbeat; TXL (PA21) flickers with USB IN traffic, RXL
  (PC30) with OUT. Both tracks, same pins, same 50 ms sampling. Track
  A's `u` prints the pin state and `B` prints the activity counters, so
  a dark indicator can be told apart from a pin nothing ever drove.
  **Heartbeat alive with both activity LEDs dark, while a host tool
  sits there making no progress, means the host is stuck in `close()`
  waiting for write URBs the device is not draining** - that is how
  objective 0c was spotted. Confirm with
  `sample <pid> 2 -mayDie | grep close`, then kill the process; the
  board itself is fine.
- Scratch scripts written this session are under the session scratchpad
  and are not part of the repo. Anything worth keeping was folded into
  `host/measure.py` or `tests/`.

## Daemon and front end

```sh
# the daemon: no hardware
python3 -m daemon --fake            # from host/, or PYTHONPATH=host
.venv-ft/bin/python -m daemon       # the real board, free-threaded

# the front end
.venv-gui/bin/python -m gui --spawn-fake    # starts its own fake daemon
.venv-gui/bin/python -m gui                 # a daemon already running

# their tests
.venv/bin/python -m pytest tests/test_daemon_protocol.py \
                          tests/test_daemon_api.py tests/test_jitter.py -q
.venv-gui/bin/python -m pytest tests/test_gui.py -q
```

`docs/daemon-api.md` is the socket reference: framing, the command
catalogue, ownership, backpressure, recording, and what `status`
carries. Two things about it are load-bearing rather than incidental -
`status` never touches the device, and a client that stops reading
loses frames that are counted and reported rather than slowing anyone
down.

## Track A command reference

Same letters, same output. Track A adds `d` (DAC update-rate sweep) and
`j`/`k` (independent-DAC cross-check), which Track B has never had.

Its bulk endpoints run on UOTGHS DMA under the core's enumeration
(`sketches/bringup/usbdma.cpp`). Measured: OUT 19.72 MB/s, IN 31.10,
duplex 15.58 - bytes offered, and the "byte-perfect" that used to
qualify the OUT figure is withdrawn for the same reason it was on
Track B (objective 0h); Track A has never been drained-measured at
all; full loop at 200,000 sps each way with under=0
and the tone at the theoretical maximum; full-rate pair (DAC 906,976 +
capture 453,488) with under=0.

`B` reports `spans` and `partial` on both tracks: OUT DMA transfers
armed, and the ones that ended anywhere but on a slot edge. `partial`
must be zero - a stream span is armed to land exactly on a slot
boundary and nothing may end it early, so a non-zero count is the
lost-sample defect or its next relative, and the suite asserts it.
`spans` is also the handle on the starvation in objective 0a: a
starving run arms few large spans, a healthy one many small ones.

Track A's `B` additionally reports `rebuilds`, the number of times the
core rebuilt endpoint configuration out from under the DMA mode. Zero
through a normal run.
Climbing means the link is resetting, which otherwise reads as data
corruption.

```sh
tools/sketch.sh compile      # both build properties, ldscript path computed
tools/sketch.sh upload       # discovers the control port itself
```

Do not call `arduino-cli compile` by hand. Track A needs two build
properties and each is silent when it is missing: a wrong `build.f_cpu`
makes `micros()` lie by 7.7%, and a missing `build.ldscript` leaves the
capture ring in bank 0, which links, runs, and costs 35-44 ADC overruns
per 4 s at the full rate. The ldscript path has to be relative to the
installed variant directory, which is why it is computed rather than
written down.

The host tools below work against either track unchanged; the wire
format is byte-identical. `loopback.py`'s clock-paced feed is tuned for
the DMA-fed device, so against Track A it simply overruns the plateau -
which is what the underrun counter is for.

## Track B command reference

| Key | Action |
|---|---|
| `h` | banner |
| `r` `s` `x` | read A0/A1, DAC sweep, crosstalk |
| `t` | TC/ADC/PDC trigger-rate sweep |
| `1`..`5` | capture streaming presets, `5` = max in-spec (derived from clock) |
| `=<dac>[,<adc>]` | rate arguments for the next `L` or `P` |
| `L` | full loop: playback + capture (defaults 200 k/200 k) |
| `P` | playback only |
| `0` | stop everything |
| `?` `B` | stream stats; bench + playback counters |
| `F` `R` `X` | transport benchmarks via CPU FIFO: flood IN, sink OUT, duplex |
| `G` `T` `Y` | same three via endpoint DMA (**working**) |
| `V` | dump playback ring + DACC registers |
| `D` | loop diagnostic: 12 snapshots at 150 ms, printed afterwards |
| `M` | mimic loop without USB: gen sine on TIOA1 + capture |
| `u` | dump USB + endpoint + DMA registers, both CDC functions |
| `l` / `=1l` | main-loop load: passes, worst pass, log2 histogram / and clear |
| `=<ms>S` | stall the main loop for `<ms>` - validates `l`, dev only |
| `=<ms>Z` | **detach the native port and re-attach it**: a software unplug, and what releases a host wedged in `close()` (objective 0c). Not `z` - that is a processor reset and leaves the USB pull-up attached |
| `z` | software reset (processor only; no USB disconnect) |

### The native port's control channel

Framed binary, not console text, and the supported way to read state
while the board is working - a console poll blocks the main loop for
13-20 ms and `u` for 113. Six opcodes are implemented:

| op | name | what it carries |
|---|---|---|
| `0x0001` | `PING` | device clock, sequence |
| `0x0002` | `IDENTITY` | track, versions, frame geometry, MCK |
| `0x0020` | `COUNTERS` | the `play:` counters, loop passes, drain polls |
| `0x0021` | `OCCUPANCY` | ring histogram and its trace |
| `0x0022` | `RATE_TRACE` | the consumed-buffer timestamps, paged |
| `0x0024` | `LOAD` | main-loop passes, worst pass, log2 histogram |

`host/control.py` is the client; `docs/control-protocol.md` is the wire
format and the design for what is not built yet.

## Host tools

```sh
python3 host/ports.py                             # discover all three ports
python3 host/loopback.py --seconds 5              # loop test, 200 k defaults
python3 host/loopback.py --dac-sps 906976 --adc-hz 453488   # full-rate pair
python3 host/loopback.py --diag                   # with mid-run firmware snapshots
python3 host/usbbench.py in-dma --seconds 4       # DMA transport benchmarks
python3 host/receive.py --send 5 --seconds 5 --expect-hz 885.72

# added 2026-08-25
python3 tools/loadwatch.py <command-port> log stop   # poll GET_LOAD at 10 Hz
python3 tools/soak0c.py 40 play-nodrain              # reproduce 0c, ~30 s
python3 tools/soak0c_portable.py --cycles 40         # same, pyserial, any OS
```

`tools/soak0c_portable.py` is the only host-side thing here that runs
off macOS, and the only one with a dependency (`pyserial`, pinned in
`requirements-dev.txt`). It exists to answer whether 0c reproduces on
Windows or Linux.

`receive.py --expect-hz` is the gen tone: trigger rate / 512, i.e.
885.72 Hz at the 453,488 Hz max in-spec preset.

### Measuring the byte loss

Everything the 0-series above rests on comes from these, and none of
it is reachable from the command line yet - it is library API, used
from a scratch script or a test.

```python
import measure
from ports import find_ports
ctl, nat = find_ports()
board = measure.Board(control=ctl, native=nat, settle=3.0)

# Did the device receive what the host sent? drain_s is not optional:
# without it the 55-450 KB still in the CDC driver reads as loss.
r = measure.run_play(board, dac_sps=600000, seconds=3.0, drain_s=1.5)
r.host_deficit            # bytes write() counted that never arrived
r.drained                 # False means host_deficit is meaningless

# Ring occupancy, from a run made WITHOUT a drain - the device
# accumulates the histogram until playback stops.
r = measure.run_play(board, dac_sps=600000, seconds=3.0)
r.occ.quantile(0.10)      # slots, from the device's own `O` histogram
r.occ.below(3)            # fraction of ENDTX events that found too few
r.occ.trace               # decimated, every 16th ENDTX: shape over time

# The two diagnostic knobs on the feed.
measure.run_play(board, dac_sps=600000, seconds=3.0, write_size=0)
                          # 0 = the old due-sized policy, the control arm
measure.run_play(board, dac_sps=600000, seconds=3.0, scale=1.02)
                          # deliberate feed-rate offset; sweeping it
                          # finds where the ring neither fills nor drains
```

`run_bench(..., drain_s=..., tx_rate=..., block=...)` is the same idea
for the transport benches, plus `BenchResult.out_deficit`. Remember
that the benches free-run into saturation and behave oppositely to the
paced feed.
