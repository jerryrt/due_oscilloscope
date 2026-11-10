# ETS mode: capturing a repeating PRBS at the DAC's top rate

`docs/ets.md` holds the sampling model and its limits, and `host/eqtime.py`
the reconstruction. This document is the plan for turning them into a
capture mode, starting on Track B, and what the first measurements say about
the claim the plan rests on.

Figures marked *(check)* are unmeasured: derived, or read from another
document.

## The claim, and where it stands

> ETS can capture the DAC at its maximum rate, with a 1 V peak-to-peak NRZ
> PRBS, in high resolution.

Phase 0 measured it on one bench: `montreal5`, Track B (image `8d3f2b2`
plus a tree delta), probes fitted, DAC0 wired to A0, a Rigol DS1102E on
DAC0. `tools/ets_phase0.py` is the instrument; `records/ets-phase0-montreal5-b.jsonl`
holds the seven-rate sweep and `records/ets-phase0-montreal5-b-scope.jsonl` the
three runs with the Rigol. **Supported on this bench, at one run per rate.**

| part | what had to be true | measured |
|---|---|---|
| **A. The DAC emits it** | a 1 V PRBS7 at the top playback rate repeats identically | Every rate from 200 kHz to RC 28 (1,607,142 symbols per second, the playback floor `PLAY_MIN_RC`) folds to a PRBS7 with the eye 99.8-99.9% open. The residual against the fold is 1.27-1.31 codes rms, the same as a held level read the same way, so the output is periodic to the noise floor. The swing is 1,238 codes, 998 mV |
| **B. It can be fed** | host-fed playback and a one-channel capture run together without loss | 0 underruns and every byte played at every rate, at the top rate with 3.2 MB/s out and 2 MB/s in, with no frame gaps. A device-held pattern is not needed on this host. Windows is not measured, and it is where a duplex loss was seen at 1.7 MB/s combined |
| **C. ETS resolves it** | the fold shows the edges, and agrees with an independent instrument | Isolated transitions read 137-139 ns rise and 139-140 ns fall through the fold, and 134-135 ns rise and 138-141 ns fall on the Rigol (10 ns per point), a gap of 2-3%. The Rigol's isolated-transition counts are small (2 to 17 per record), and its swing reads 984-991 mV against the fold's 998 mV |

Two things the claim does not get from this. A 138 ns edge is 2.5 times the
track-and-hold's estimated 50-54 ns, so the fold cannot say how much the ADC
adds: the answer would sit inside a 3 ns difference and the Rigol's counting
error. And "maximum rate" is the firmware's playback floor, which is where the
measurement stopped, not a rate at which the output failed.

The `docs/awg.md` ceiling of about 1.5 M updates per second, and the 64-68%
amplitude it records for a full-swing square at 700 kHz, were not seen: a 1 V
step needs about 140 ns to cross and fits inside a 622 ns symbol, where the
2.2 V step of that table did not.

## Why PRBS

A PRBS repeats with a known period, so the fold needs no clock recovery and
no trigger: both timers divide MCK, and `eqtime.period_ticks` gives the
period exactly. It exercises every transition and run length, which an
alternating square does not, and an eye diagram folds out of the same data.
PRBS7 (127 symbols) is the first pattern: the shortest period gives the most
repeats and the quickest fold.

With `L` symbols, `S` samples per symbol and the DAC's `RC_dac`, the fold
period is `P = L * S * RC_dac` ticks. The ADC trigger period `R` must be
coprime with `P` for the fold to reach every tick position (`docs/ets.md`).
At RC 28, `P` is 3,556 ticks and `R` = 45 is coprime with it.

## How the tool reads a capture

Four points that decide whether the numbers mean anything:

* **The capture starts before the feed.** The DAC sits at its idle level for
  2 to 12 ms first. Left in, those samples read as 600 codes of noise against
  the fold. `steady_range` keeps the longest run of 1,024-sample blocks whose
  residual is within 3 times the median, and the row records what it dropped.
* **Run 0 is thrown away.** The first run after a board or daemon start is an
  outlier.
* **Each check was broken on purpose first.** A fold on the wrong clock
  relation must collapse the eye (it reads 1.4% open), a start-up transient
  must be trimmed, and a slower edge must read slower on both the fold and
  the scope reader (`selftest`).
* **Rise and fall are read on isolated transitions only**, where both
  neighbouring symbols have settled, and averaged. A single-pole edge of a
  known rise reads 5% low through the fold on synthetic data.

## Phases

Each phase ends at a gate and starts after the one before it passes.

| phase | what | board | firmware change | gate |
|---|---|---|---|---|
| **0. Validate** | Done on `montreal5` as above | yes | none | The numbers above. Proposed pass: fold and Rigol rise within 5%, duplex loses nothing. These thresholds were chosen after the data was seen |
| **1. Host library** | A PRBS generator, a planner that picks `R` and refuses non-coprime pairs, a fold on `eqtime`, an eye builder. Board-free tests, each broken on purpose before trusted | no | none | Tests pass in the container, and each new check fails when what it guards is broken |
| **2. External source** | A second Due's DAC0 into the capturing Due's A0, so the source has a clock of its own. `host/etsperiod.py` finds the clock ratio from the samples and the fold runs on it. Needs `linux-x1`'s two Dues, cross-wired | yes, two boards | none | The recovered ratio folds to the eye phase 0 shows, and a period 20 ppm off does not. Edge rise within 5% of phase 0's and the Rigol's |
| **3. Track B mode** | The daemon exposes an ETS capture on one channel, running until stopped, with a progressive fold. The front end shows the folded waveform and the eye | yes | none | Matches phase 0's fold on the same wiring, with no lost frames |
| **4. Other hosts** | `tools/ets_phase0.py loop` on the Windows and macOS benches, for the duplex load | yes | none | No underruns and no byte loss, or a device-held pattern (below) |
| **5. Device PRBS** | Only if phase 3 fails | yes | all three tracks | Host and device PRBS give the same fold |
| **6. Tracks A and C** | The same fold on Tracks A and C, which should need no host change | yes | none | Same fold, same periodicity |
| **7. AFE wide path** | The wide path of the AFE requirement draft, measured against the same signals | yes | none | Set when the AFE exists |

## A device-held pattern: the RAM

If a host cannot feed the pattern, it can live on the device and play from RAM
with no USB in the path, as the generator's table does.

| item | figure |
|---|---|
| Bank 0 (64 KiB) after `.data` and `.bss` | 8,712 B free, stack and heap included *(Track B map; where the stack sits is unchecked)* |
| Bank 1 (32 KiB) | 16,384 B free; the capture ring takes the other 16,384 B *(check that nothing else is placed there)* |
| Today's generator table | 512 entries, 1,024 B |
| A pattern at 1 sample per symbol, 2 B each | PRBS7 254 B, PRBS9 1,022 B, PRBS10 2,046 B, PRBS11 4,094 B, PRBS13 16,382 B |

PRBS7 to PRBS10 fit in bank 0 with room to spare. PRBS11 leaves about 4.6 KB
for stack and heap, so it belongs in bank 1, whose use by the DMA masters is
unchecked.

What it needs from the firmware: a table whose length is the pattern's
period (today the wrap is fixed at the table length and points must divide
256, so a 127-symbol period does not fit), and a PRBS shape built from an
LFSR when the generator is configured, which is setup work and not on the
sample path. That is a new shape value in the shared wire contract and the
same console surface on all three tracks.

## A source with a clock of its own

A second board's DAC has its own crystal, so the pattern's period in the
capturing board's ticks is not an integer and is off the nominal one by tens
of ppm. The pattern is known, so the one unknown is that ratio. `host/etsperiod.py`
matches short blocks of samples against the pattern's ideal waveform and
fits a line through the block phases over the whole capture: the phase moves
at a rate equal to the ratio's error. `tools/ets_cross.py` runs the source in
one process and the capture in another, each pinned to a board by `DUE_DUT`,
and analyses the raw capture.

What has been measured, on the `montreal5` capture of 3 M samples, whose true
ratio is 0, with an offset emulated by assuming a wrong ADC period:

| emulated offset | recovered | error |
|---|---|---|
| +150 ppm | +150.0000 ppm | 0.0000 ppm |
| -150 ppm | -149.9999 ppm | 0.0001 ppm |
| +40 ppm | +39.9999 ppm | -0.0001 ppm |
| -250 ppm | -250.0000 ppm | 0.0000 ppm |

A fold on the recovered period reproduces phase 0's eye (99.8% open, rise
138.5 ns, fall 139.5 ns). A fold on a period 20 ppm out reads 1.5% open, and
on the nominal period 0.2%. The unmodified capture returns a ratio of
-1.3e-11. Emulation shows the algorithm and not a real crystal: wander,
temperature drift and the source's own jitter are not in it.

A search that scores whole-capture folds on candidate periods does not work
for a known pattern: a fold on bins as wide as a symbol cannot tell a period
that is 8 ticks out by the end of its window from the right one, so each
stage's pick is noise.

Measured on `linux-x1`, Track B on both Dues (image `8ffc8ed`), DUT1 DAC0
into DUT2 A0, RC 28 and RC 56, 8 M samples each
(`records/ets-cross-linux-x1.jsonl`):

| | same board (`montreal5`) | two boards (`linux-x1`) |
|---|---|---|
| Clock ratio | exactly 1 | -2.52 and -2.49 ppm |
| Where samples land in a tick | all on whole ticks | flat, min over max 0.999 |
| 2.2 ns bins filled | 10% | 100%, at least 111 samples each |
| Edge 50% crossing scatter, fold repeatability | n/a | 0.05-0.11 ns |
| Odd minus even samples, edge position | n/a | +22.20 to +22.24 ns, rising and falling |

The first four rows say what an independent clock buys: the fold's time axis
is no longer a lattice of ticks, and an edge can be placed to about a tenth
of a nanosecond in repeatability. That is the fold's scatter and not an
accuracy: it does not contain the last row.

The last row is the ADC start snapping to the ADC's own clock. The odd and
even samples of a run differ by exactly one 45 MHz tick on every edge of both
kinds, so it is a pure time shift and not an amplitude or bandwidth effect,
and the odd samples are taken one tick earlier. Pooling them blurs every edge
by that tick, and `ets_cross.py resolution` moves the odd samples back by the
offset it measures and folds again. An even ADC RC puts every trigger at the
same phase of the ADC clock, which should leave nothing to correct; that is a
control still to be run (`ets_cross.py both --rc-adc 46`, where the odd-minus-even
figure must read zero).

The resolution is still bounded by the track-and-hold's rise, which is
estimated and not measured *(check)*, by the source's edge jitter, and by how
well the ratio holds over a capture. The block-phase scatter is 0.6 to 0.7
ticks against 0.22 on one board, and its cause is open.

## Conditions on the signal

ETS works only for a signal that repeats exactly and whose period is known or
can be found. Here the DAC and the ADC share MCK, so the period is exact.
Random data, single events and a source with its own drifting clock are
outside this document.

With probes fitted the line at a quarter of the sample rate appears on
Track C and is absent on Tracks A and B, so Track B is the clean start. The
DAC's window is about 0.55 to 2.75 V, which holds a 1 V swing, and the ADC
range is 0 to 3.3 V.

## Not established

* The ADC's input bandwidth, beyond the datasheet-derived estimate, and
  whether the start delay is deterministic (`docs/ets.md`). Both need an edge
  faster than 138 ns; the DAC's smallest steps reach about 60 ns.
* The Rigol's probe: its software ratio reads x1 and the physical switch is
  unknown, which bounds its own rise time near 58 ns if it is x1.
* Duplex USB loss on Windows and macOS, and more than one run per rate.
* The DAC's behaviour above the playback floor, which is outside the plan.
