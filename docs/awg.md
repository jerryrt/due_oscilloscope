# The signal generator

Two generators, two reasons. Everything below is measured on this bench
unless it says otherwise.

| | source | path | reached by |
|---|---|---|---|
| **streamed** | host | `HOST -> USB -> play.c ring -> PDC -> DACC` | `measure.build_selected`, `run_play`, `run_loop` |
| **internal** | device | `gen table -> PDC -> DACC`, no USB at all | `=<shape>,<pts>W` on the console |

The streamed one is arbitrary: the host authors every sample, so any
shape it can compute is a shape the board can emit. The internal one
keeps running when no host is attached, which is what a deployed board
needs, and it costs nothing on the wire.

Both exist on both tracks. Track B is `drivers/gen.c` and `drivers/play.c`;
Track A is `sketches/bringup/gen.cpp` and `sketches/bringup/play.cpp`.
Independent source, identical feature and identical printed format.
Invariant 3 shares the wire contract and keeps register programming
apart, naming `gen` among the internals that stay independent, so these
two files are on the right side of that line: Track A's sine comes from
libm and Track B's from a fixed-point Bhaskara approximation, and the
two agreeing on the analog output is then evidence rather than a
tautology.

## Shapes

| code | name | streamed | internal |
|---|---|---|---|
| 0 | sine | yes | yes |
| 1 | square | yes | yes |
| 2 | ramp (rising sawtooth) | yes | yes |
| 3 | triangle | **no** | yes |
| 4 | DC | yes | yes |

Triangle is internal-only today. That is debt with a date on it, not a
property of the path: `measure.build_selected` is one chain and a
`build_triangle` alongside `build_square` closes it.

The ramp divides by `period`, not by `period - 1`, so the last point sits
one step below full scale and the wrap is the same step as every other.
Ending at 4095 would make the wrap a step of zero and put a one-sample
flat spot in the only waveform that has none.

## Resolution, and what it costs

This is the trade a bench AWG makes, and it is not hidden. The trigger
fixes the *update* rate; resolution decides how many updates one cycle
spends:

```
f = trigger_hz / (2 * points)
```

The 2 is DACC TAG mode - every other update belongs to DAC1. Points must
divide the 256-point table, so powers of two from 2 to 256 and nothing
else: a count that does not divide it leaves a partial cycle at the PDC
wrap, which is a phase step in the analog output once per reload, and
invariant 5 exists to refuse exactly that. A request that is not a legal
count **rounds down** and the device reports what it adopted, rather than
refusing and making the caller guess which values exist.

Measured, trigger 200 kHz, square (`tools/dso_sweep.py --internal`):

| points asked | adopted | expected | measured | Vpp |
|---|---|---|---|---|
| 300 | 256 | 390.6 Hz | 391.0 Hz | 2.44 V |
| 256 | 256 | 390.6 Hz | 391.0 Hz | 2.44 V |
| 128 | 128 | 781.2 Hz | 781.0 Hz | 2.46 V |
| 100 | 64 | 1,562.5 Hz | 1,560.0 Hz | 2.46 V |
| 64 | 64 | 1,562.5 Hz | 1,560.0 Hz | 2.48 V |
| 16 | 16 | 6,250 Hz | 6,250 Hz | 2.44 V |
| 4 | 4 | 25,000 Hz | 25,300 Hz | 2.44 V |
| 2 | 2 | 50,000 Hz | 50,000 Hz | 2.44 V |

Full amplitude at every resolution including the top: the DAC is not the
limit here, the table is.

**A 2-point sine is flat, and that is Nyquist rather than a fault.** Both
of its samples land on a zero crossing, so the table holds mid-scale
twice and the output is a line - measured at 0.16 V, which is the noise
floor. A square at the same resolution makes a clean 50 kHz at full
amplitude, which is what proves the converter innocent. `dso_sweep
--internal` skips that one combination and says why.

**The scope's frequency counter is not reliable below about 16 points
per cycle.** At 8 points it read 11,200 Hz for a sine and 13,800 Hz for a
triangle against a true 12,500 Hz, while reading the square and the ramp
correctly. It is counting staircase edges. Judge a coarse waveform by
its period on screen, not by `:MEAS:FREQ?`.

### The trap resolution introduces

The host's issue-#5 instruments - `fold_profile()` and `pair_fold()` in
`host/measure.py` - fold the capture at `GEN_TABLE_LEN` because 256
points has been the generator's only resolution in every build. That
stops being the right period the moment the resolution moves: it becomes
`2 * points`. `measure.gen_fold_len()` is the honest form. **Do not read
an issue-#5 sweep taken at a resolution other than 256 without saying
so.**

### Shape and layout are different axes

`gen_layout` (`=<n>N`, Track B only) is not a shape selector, however
much it reads like one. NORMAL / SWAPPED / TWOCYCLE / DC answer *which
pin* and *where the PDC wrap falls relative to the period*, and every arm
of it is an issue-#5 experiment with results recorded against it. Shape
and resolution are orthogonal to it on purpose, so those diagnostics keep
working and now work against something other than a sine.

TWOCYCLE composes with resolution rather than replacing it: at the
default 256 it builds byte-for-byte the table it has always built, so its
recorded results still describe the thing they were taken on. Resolution
128 in the NORMAL layout builds the same *waveform* by the other route,
and the two differ only in where the fold lands - which is exactly the
distinction the arm exists to make.

## The gap

**The internal generator has no control-channel command.** `=<shape>,<pts>W`
is console-only, and the console is the programming port, which is
development-only. A deployed board is native-port-only, so today it can
be told what to capture and not what to generate.

The control channel is all queries - PING, IDENTITY, COUNTERS,
OCCUPANCY, RATE_TRACE, LOAD, STREAM_STATS, BENCH - so this would be its
first write. There is a place waiting for it:
`lib/due_shared/src/ctl_wire.h` reserves **0x001x for "state the host
both reads and writes"** and that range is empty, so shape and
resolution belong at 0x0010 rather than appended to the counter range.

It is cheaper than it was. The wire format and the whole parser are
shared source now, and both tracks compile them, so a new opcode is one
implementation reaching both boards rather than two hand-copies that
drift - which is the argument invariant 3 was rescoped on. What it still
costs is a `CTL_VERSION` bump, the device-side handler on each track,
and host plus daemon support. It is not done.

## The sync output, and the bench wiring it is for

`=<n>J` puts a trigger on whichever DAC pin is not carrying the
waveform - DAC1 in the normal layout. 0 off, 1 one square per waveform
cycle, 2 one per table wrap.

**Why it is worth a pin.** Triggering a scope on the signal it is also
measuring converts the pin's amplitude noise into time jitter, divided
by the slew rate at the trigger level - the whole of the section below.
A sync edge is a full-scale step every time, so the same noise buys
almost none, and the signal channel is then measured rather than being
asked to trigger as well. It cannot drift against the waveform, either:
one PDC stream and one trigger feed both channels, so the sync lags the
waveform by exactly one trigger period - the TAG interleave - and by
nothing else.

**It is also a better demultiplexing check than what it replaces.** DAC1
used to hold mid scale, and A1 reading flat was the evidence that the
channel tags were being read right. But a flat line is also what a
channel nobody writes looks like, so DC could never tell "correctly
holding 2048" from "not driven at all". A square can. Verified through
the ADC, which is the instrument that can still see DAC1 once its probe
has moved to EXT:

| sync | A1 span | samples in the middle third | verdict |
|---|---|---|---|
| OFF | 40 codes (2041-2081) | 47.6% | flat, as before |
| CYCLE | 2780 codes | **0.0%** | a clean two-level square |
| WRAP | 2785 codes | **0.0%** | a clean two-level square |

A0 stayed the sine (22% in the middle third) throughout.

### Wiring it to a DS1102E, and the two traps

**The EXT trigger level clamps at ±1.2 V, silently.** The DAC sits at
0.52-2.82 V, so the obvious threshold is its 1.67 V midpoint - and the
instrument accepts `:TRIG:EDGE:LEV 1.67` and holds **1.20**, with the
readback agreeing and nothing reporting an error. DC-coupled at x1 the
sync therefore sits entirely above the highest reachable threshold and
**never triggers**.

**The probe ratio moves the whole window, and the window is 100 mV
wide.** Measured on this bench with a x10 probe on EXT, sweeping 25
levels x 2 slopes x 2 couplings:

| coupling | levels that trigger |
|---|---|
| DC | 0.1, 0.2 V |
| AC | 0.0, 0.1 V |

Nothing else in -1.2..+1.2 V fires, on either slope. A sweep at
0.0 / 0.3 / 0.6 / 1.0 / 1.2 steps straight over it and concludes that
EXT does not work - which it did here, for three runs.

So **the level is discovered, not assumed**:
`scope.Oscilloscope.ext_trigger_autoset()` sweeps coupling and level
until the instrument actually triggers and returns what worked. `None`
from it means no signal is reaching the input, which is a cable fault
and not a level to guess harder at.

### What the sync actually buys, measured

Internal generator, trigger 200 kHz, 20 acquisitions each, jitter as the
circular standard deviation of the waveform's phase at the trigger
point. Only the trigger source changes:

| shape | pts | trigger on the signal | trigger on the sync | |
|---|---|---|---|---|
| sine | 32 | 90.720 us | **0.408 us** | **222x better** |
| ramp | 64 | 5.633 us | **2.614 us** | 2.2x better |
| square | 32 | **0.007 us** | 1.471 us | 210x *worse* |

**The square row is not a defect in the idea, it is the x10 probe.** A
square's own edge is already a full-scale step into a 1 MOhm channel at
full amplitude, so triggering on it is as good as triggering gets. The
sync reaches EXT through a x10 divider as 230 mV against the DS1102E's
own 200 mV EXT sensitivity floor, so the sync edge is the noisiest thing
in that setup. Backed out at full scale: `sd x amplitude` = 197 mV-us,
the same form as the signal-triggered case.

**Fit a x1 probe to EXT.** 2.3 V instead of 230 mV predicts sd ~0.086 us
for the square, ~0.04 us for the sine and ~0.26 us for the ramp - the
sync then wins everywhere except against a square's own edge, which
nothing beats. AC coupling is then mandatory, not optional, because
1.67 V is past the clamp.

**Done, 2026-08-27.** With x1 fitted the autoset finds `AC coupled,
level +0.00 V` on its first candidate, and every shape triggers -
including DC, which has no edge of its own and previously needed AUTO
sweep and therefore proved nothing. The x10 numbers above are kept
because they are what made the amplitude limit visible.

### Arm the trigger once, and after the output is running

Two ordering mistakes, both of which read as a hardware fault:

- **Searching a stopped converter.** The autoset looks for an edge, so
  it must run with the output going. Called before the trigger started,
  it reported "no signal is reaching EXT" on a perfectly good cable.
- **Searching inside each measurement window.** A full-range sweep is
  ~44 s of instrument time, which is longer than the window it was
  called inside - it kept driving the instrument after the output had
  stopped and collided with the next acquisition, surfacing as
  `USBTimeoutError` rather than as the ordering bug it was. The probe
  and the sync do not change between combinations, so arm once per run
  and re-assert the found setting after that.

The level ladder searches outward from zero for the same reason: AC
coupling centres the sync on 0 V, so the first candidate is the answer
on a correctly-fitted probe.

### Measuring jitter: fold to phase first

"The crossing nearest screen centre" is not a stable ruler once the
trigger's phase differs from the crossing's. The sync rises at table
index 0 and a ramp crosses mid half a cycle later, so the nearest
crossing flips between two that are a whole period apart and the spread
reads as **96% of a period on a trace that is perfectly still** - which
is what the first run of the table above reported. Fold each crossing to
a phase and take circular statistics; the ambiguity the measurement
created goes away and the one it is trying to measure does not.

---

# Why the trace shakes horizontally on the bench scope

Reported from the bench: the trace moves sideways, "sine and ramp on some
frequency is very profound", ramp worse than sine. Reproduced, and the
cause is the instrument's trigger, not the board.

## What it is

**Amplitude noise at the trigger level, divided by how fast the waveform
crosses it.**

```
t_jitter = V_noise / (dV/dt at the trigger point)
```

## The measurement that shows it

One waveform, one rate, one framing, streamed playback at 200 ksps. Only
the ramp's step changes, and with it the slew rate at the 1.67 V trigger
level. The staircase geometry, the DAC, the USB feed and the ring are
identical throughout. 30 acquisitions each, jitter is the standard
deviation of the crossing nearest the trigger point:

| ramp step | V/div | period | slew rate | jitter sd | **sd x slew** |
|---|---|---|---|---|---|
| 2 | 0.50 | 10,240 us | 0.234 mV/us | 74.82 us | **17.53 mV** |
| 8 | 0.50 | 2,560 us | 0.937 mV/us | 27.57 us | **25.85 mV** |
| 32 | 0.50 | 640 us | 3.750 mV/us | 6.01 us | **22.52 mV** |
| 8 | 1.00 | 2,560 us | 0.937 mV/us | 23.49 us | **22.02 mV** |
| 8 | 0.30 | 2,560 us | 0.937 mV/us | 18.64 us | **17.47 mV** |

The jitter spans **12x**. The product is constant at about **20 mV**.
Underruns were 0 on every one of those rows.

Measured independently, DAC0 held at code 2048, AC coupled at 0.05 V/div:

| | Vpp | Vrms |
|---|---|---|
| board idle, DAC not driven | 118.0 mV | **15.1 mV** |
| DAC0 held at code 2048, streaming | 104.0 mV | **20.2 mV** |

20.2 mV, against the 17.5-25.9 mV the slope experiment backed out without
knowing it. Predicted ramp jitter at step 8 from the noise alone:
20.2 / 0.937 = 21.6 us; measured 27.6 us.

**Most of the noise is there with the DAC not driven at all.** It is a
probe and board floor, not something the stream creates - streaming adds
about 5 mV to a 15 mV floor.

## Why the shapes rank the way they do

Where each waveform crosses the 1.67 V trigger level:

| shape | slew at the trigger point | jitter, as a fraction of one period |
|---|---|---|
| square | full-scale step, effectively infinite | **0.0 - 0.2 %** |
| sine, 32 pts/cycle | ~45 mV/us | 0.3 - 2.7 % |
| ramp, step 8 | **0.94 mV/us** | 3.3 %, sd 27 us |

That is the whole of the reported observation, in order. Ramp is 30-60x
worse than sine because its staircase rises **4.5 mV per sample**, and
square does not shake at all because a full-scale step gives noise
nothing to work with.

Across the AWG ladder the fraction stays roughly flat - sine 0.3-2.7%,
square 0.0-0.2% - because slew rate and period both scale with the sample
rate and the ratio does not.

## What to do about it

Nothing in the firmware. This is a measurement setup property:

- **Trigger on a steep part of the waveform.** For a ramp that means a
  bigger step, which is a resolution choice - `--ramp 32` shook 12x less
  than `--ramp 2`.
- **Shorten the probe ground lead.** 15 mV of the 20 is present with the
  DAC idle.
- **The DAC has no output buffer.** Phase 3's front end is where this
  actually improves; see `docs/hardware-next.md`.
- **`DACC_ACR` is at reset, not at the datasheet's characterisation
  condition.** `=2,1I` is the Arduino core's value. Untested against this
  measurement.

## What it is not

- Not underruns. 0 on every shaky row, and `PLAY_PRIME_BUFS = 24` took
  the ladder to zero.
- Not the host feed, the ring, or the transport. The internal generator,
  with no USB in the path at all, shakes the same way for the same
  shapes.
- Not the frame or sequence path. Nothing was discontinuous.

## The GUI shakes too, and for a completely different reason

Worth writing down so the two are never confused. `gui/app.py` draws
`ring.window(n)` on a 33 ms timer: **the most recent N samples, with no
trigger and no phase alignment of any kind.** The trace's horizontal
position is therefore `(samples arrived since the last redraw) mod
(samples per cycle)`, and nothing pins it.

Board-free, 200 ksps, 2 channels, so frames deliver 1024 samples per
channel:

| tone | samples/cycle | phase step per redraw | on screen |
|---|---|---|---|
| 390.6 Hz | 512 | 0.000 | still |
| 977 Hz | 204.71 | 0.013, 0.016 | slow crawl |
| 1,000 Hz | 200 | 0.720, 0.840 | blur |
| 3,125 Hz | 64 | 0.000 | still |
| 6,250 Hz | 32 | 0.000 | still |

A still trace needs `rate/tone` to divide 1024. Every other frequency
moves on every redraw. **This is a missing feature - the front end has no
software trigger - and it is unrelated to the bench-scope finding above.**
