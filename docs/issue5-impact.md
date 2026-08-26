# Issue #5: what it means for the instrument

`docs/HANDOFF.md` carries the investigation - how the artifact was found,
what was ruled out, and how to reproduce it. This file answers a
different question, and the one a user of the instrument actually asks:
**which half of this thing does the defect affect, how big is it, and
what does it look like in a spectrum.**

The short version: **it is an AWG defect, not a scope defect**, it is
**not noise** but a phase-locked impulse, and at a typical draw it sits
at the noise floor the DAC is specified to.

## What it is, in one paragraph

Once per DAC table wrap - the DACC's PDC reload, `GEN_TABLE_LEN` samples
apart - one ADC sample taken from a **DAC output pin** reads displaced by
somewhere between a fraction of a code and about 80. It is analog and it
is made at the DAC pin rather than in the ADC. It does **not** need a
moving output: the reload alone produces it, measured on two boards and
two hosts. See `docs/HANDOFF.md` for the evidence behind each of those
clauses, and for why the earlier "a changing output is needed" was an
artifact of one image.

## Which half of the instrument is affected

| Configuration | Affected? | Evidence |
|---|---|---|
| **Scope on an ordinary input** | **No** | A2, a 3.3 V divider with no DAC attached, folds to z *below its own control* in every arm while DAC pins carry the artifact in the same frames |
| **Scope on an ordinary input, AWG running at the same time** | **No** | same measurement - the arms above were taken with the generator running |
| **AWG output** | **Yes** | the artifact appears only on DAC pins, and on whichever pin is DC while the other moves |
| **Loopback / self-test / calibration** | **Yes** | there the scope input *is* a DAC pin |
| **AWG idle, or holding DC** | **Yes, on some builds** | the `all-DC` arm was null on the image that first measured it - z 5-6 against a control of 3.1 - and on `main` at `a30b646` the same board with the same wiring gives 8.0-8.2 codes on A0 at z 61-148 and 10.3-10.5 on A1, with no sine anywhere. Assume it is present |

Two consequences worth stating explicitly, because both are easy to get
backwards:

- **It is both DAC pins, whenever either one is moving.** In the normal
  build the sine is on DAC0 and the artifact appears on A1 - the
  *static* DAC1 pin. A moving output disturbs its neighbour.
- **A shared-node explanation is excluded.** If the reload disturbed
  ADVREF, or the ADC's own conversion, every channel would show it. A2
  is on the same 3.3 V rail and shows nothing.

## What it looks like: an impulse, not noise

Deterministic in every respect but one:

| Property | Value |
|---|---|
| Period | exactly one event per table wrap, `GEN_TABLE_LEN` |
| Width | one sample |
| Phase | locked - constant across runs on a given binary |
| Amplitude and sign | **the only unpredictable part**, redrawn by any rebuild, ~0.2 to ~80 codes |

That the period is the *wrap* and not the *waveform* was settled by
running two sine periods inside one table: the events never split into
two per wrap in twelve runs.

**The practical consequence is worse than noise would be.** In the
ordinary build the table wrap and the output sine period are the same
event, so the impulse is synchronous with the tone. It lands on the
tone's own harmonics and reads as **harmonic distortion of the generated
waveform**, not as a separable spur that could be notched out.

## How big, against the part's own specification

One sample in `GEN_TABLE_LEN` displaced by `A` codes gives an RMS error
of `A / sqrt(512)`, against 971 codes RMS for a full-span sine. The model
checks out: measured `sd` on the sine channel is 968.9 against the 971
predicted.

| Displacement | Error vs full scale |
|---|---|
| 12 codes, typical | **-65 dB** |
| 48 codes, the build of 2026-08-26 | -53 dB |
| 80 codes, worst observed | **-49 dB** |

The SAM3X's DAC is specified at SNR 64-74 dB and THD -64 to -80 dB
(datasheet Tables 46-40 and 46-41). **So even a typical draw sits at the
noise floor the part is specified to, and a bad draw is 15 to 30 dB
worse than spec.** That is the strongest argument that this is worth
fixing rather than documenting and living with.

**Caveat on those figures, and it matters.** They assume the excursion at
the pin equals what the ADC reported. If the transient is faster than the
ADC's aperture - and the fact that the sampling instant changes the
reading by a factor of forty says it may well be - the real excursion is
larger and briefer, and these are a lower bound rather than a
measurement.

## Measured, inferred, and open

**Measured.** That the artifact appears only on DAC pins; that ordinary
ADC inputs are unaffected across 50 ohms to 5.5k; that it is once per
wrap and not once per waveform; that it needs a moving output; that the
sampling instant sets its amplitude and sign.

**Inferred, not observed.** That the voltage at the DAC pin actually
moves. Everything points there - the jumper test, the impedance sweep,
the conversion-slot control - but **no independent instrument has ever
looked at the pin.** The ADC is a poor witness for a fast transient: it
reports where its sample landed, not the excursion's height or width.

**The experiment that would close it: put a real oscilloscope on DAC1 and
trigger on the wrap.** That converts the central claim of this file from
inference to observation and gives the transient's actual shape and
duration, which no amount of ADC work can. Nothing else on the open list
is worth as much per minute spent.

**Deferred as of 2026-08-26**, with a different instrument to be built
for it rather than an oscilloscope borrowed. So the central claim of
this file stays marked as inference, and every amplitude quoted here
stays a lower bound, until that exists. Nothing downstream should be
written as though the transient's height were known.

## What this does not bound

The AWG's *underrun* behaviour, byte conservation and rate accuracy are
separate matters and are covered in `docs/status.md` and the 0-series in
`docs/HANDOFF.md`. This file is only about the once-per-wrap artifact.
