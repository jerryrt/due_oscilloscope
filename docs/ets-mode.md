# ETS mode: capturing a repeating PRBS at the DAC's top rate

`docs/ets.md` holds the sampling model and its limits, and `host/eqtime.py`
the reconstruction. This document is the plan for turning them into a
capture mode, starting on Track B, and the claim the plan has to prove first.

Figures marked *(check)* are unmeasured: derived, or read from another
document. Nothing here has been run on a board yet.

## The claim

> ETS can capture the DAC at its maximum rate, with a 1 V peak-to-peak NRZ
> PRBS, in high resolution.

Read as three separate claims, each of which can fail on its own:

| part | what has to be true | evidence today | status |
|---|---|---|---|
| **A. The DAC can emit it** | a 1 V NRZ PRBS at the DAC's top rate comes out repeatable, level by level | The conversion ceiling is `PLAY_MIN_RC` = 28 timer ticks: 1,607,143 updates/s at 90 MHz by arithmetic *(check; `docs/awg.md`'s 1,392,857 is the 39 MHz figure)*. Toggling pins near 750 kHz. At the ceiling a full-swing square reaches 64-68% of its amplitude and the peak height varies cycle to cycle. A 1.1 V step rises in 166 ns, slew-limited, against a symbol of about 622 ns | **Plausible, unproven.** Nothing is measured for a 1 V swing or a PRBS at the ceiling, and cycle-to-cycle variation breaks the repetition ETS needs |
| **B. A PRBS can be played** | the device or the host supplies the pattern with no gaps | The device generator holds fixed shapes (sine, square, ramp, triangle, DC) in a power-of-two table; it has no PRBS. Host-fed playback carries any data, runs on TIOA1 independent of the ADC's TIOA0, and is byte-exact up to the same ceiling. At the ceiling it needs about 3.2 MB/s of USB OUT with 16-bit samples, while an ETS capture on one channel brings about 2 MB/s in | **Open.** A duplex load of about 5 MB/s is above the 1.71 MB/s where loss started in the one measured duplex arm (`CLAUDE.md`, Windows). Linux at this load is unmeasured |
| **C. ETS resolves it** | the fold shows the edges and levels at a resolution finer than the edge | Folds sample every 44.4 ns (22.2 ns with interleave), the track-and-hold is estimated at 50-54 ns, and a fold has already resolved a 277-300 ns full-step edge and a 166 ns edge for a 1.1 V step. The fold floor measured was about 60 ns | **Supported** for a square at 750 kHz and below. For a PRBS at the ceiling, unmeasured. The 50-54 ns track-and-hold figure is an interpretation of a datasheet formula, not a measurement *(check)* |

So the claim is **plausible and partly supported, and two parts decide it**:
whether the DAC's output repeats identically at its top rate (A), and
whether the USB can feed that rate while capturing (B). Phase 0 measures
both before anything is built.

"Maximum rate" has to be defined by measurement. The candidates are the
conversion ceiling (1.6 M symbols per second, arithmetic) and the highest
rate at which the folded PRBS stays periodic; phase 0 reports the second.

## Why PRBS

A PRBS repeats with a known period, so the fold needs no clock recovery
and no trigger: both timers divide MCK, and `eqtime.period_ticks` gives the
period exactly. It exercises every transition and run length, which an
alternating square does not, and an eye diagram folds out of the same data.
PRBS7 (127 symbols) is the first pattern: the shortest period gives the most
repeats and the quickest fold. Longer patterns are a later step.

The pattern length `L` and the samples per symbol `S` set the fold period
`P = L * S * RC_dac` ticks. The ADC trigger period `R` must be coprime with
`P` for the fold to reach every tick position (`docs/ets.md`). For example
`L` = 127, `S` = 1, RC 28 gives `P` = 3,556 ticks, and `R` = 45 is coprime
with it.

## Phases

Each phase ends at a gate. A phase starts only after the gate before it
passes. Gate values marked TBC are fixed after phase 0 measures a reference.

| phase | what | board | firmware change | gate |
|---|---|---|---|---|
| **0. Validate** | On Track B, with the Rigol as the reference: (a) 1 V PRBS7 on DAC0 at rates up to the ceiling, read the repeatability of each level and edge cycle to cycle; (b) the same pattern folded through the loop, compared with the Rigol's trace; (c) the highest rate at which the fold stays periodic; (d) a duplex run of host-fed playback at that rate with a one-channel capture, byte conservation and underruns | yes | none | A table of rate against periodicity, rise time against the Rigol's, and duplex loss. **Passes** when the fold matches the Rigol edge within TBC at a stated rate, and the duplex run loses nothing |
| **1. Host library** | A PRBS generator, a planner that picks `R` and refuses non-coprime pairs, a fold on `eqtime`, and an eye builder. Board-free tests, each broken on purpose before trusted: a wrong period must smear the eye, and a non-coprime `R` must refuse | no | none | Tests pass in the container, and each new check fails when the thing it guards is broken |
| **2. Track B mode** | The daemon exposes an ETS capture on one channel, running until stopped, with a progressive fold. The front end shows the folded waveform and the eye | yes | only if phase 0(d) fails | Matches phase 0's fold on the same wiring, with no lost frames |
| **3. Device PRBS** | Only if the duplex run in phase 0(d) fails: a PRBS shape in the generator table, on all three tracks with the same console surface (`CLAUDE.md`, invariant 3) | yes | yes, all three tracks | Host and device PRBS give the same fold |
| **4. Tracks A and C** | The same fold on Tracks A and C, which should need no host change | yes | none | Same fold, same periodicity |
| **5. AFE wide path** | The wide path of `docs/afe_requirement_*.md` section 3, measured against the same signals | yes | none | Set when the AFE exists |

Phase 3 is the one design decision: the host feeds the pattern (no firmware
change, USB-bound) or the device holds it (a firmware change on three tracks,
no USB load). Phase 0(d) decides it. The tracks are peers, so the change
would have to land on all three.

## Conditions on the signal

ETS works only for a signal that repeats exactly and whose period is known
or can be found. Here the DAC and the ADC share MCK, so the period is exact.
Random data, single events and a source with its own drifting clock are
outside this document (`docs/afe_requirement_*.md` covers a host-side period
search for an external source).

The loop is DAC0 to A0. With probes fitted the line at a quarter of the
sample rate appears on Track C and is absent on Tracks A and B, so Track B
is the clean start. The DAC's window is about 0.55 to 2.75 V, which holds a
1 V swing, and the ADC range is 0 to 3.3 V.

## Not established

- The ADC's input bandwidth beyond the datasheet-derived estimate, and
  whether the start delay is deterministic (`docs/ets.md`).
- Whether a 1 V PRBS survives the DAC's conversion ceiling with a repeating
  output, and what the highest rate that does is.
- Duplex USB loss at 5 MB/s on Linux.
- The DAC's behaviour above 1.6 M updates/s, which is outside the plan.
