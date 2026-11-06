# AFE requirements

Figures are targets in general terms. We check your results against our own
detailed limits, so do not read a rounded number here as a tolerance.

## What it is

Two scope inputs, one generator output, and a jumper that selects a
differential mode (channel 1 minus channel 2). It is built on the proto
board that stacks on the Arduino Due. The Due is not modified.

## Scope inputs

- DC coupled, about ±5 V, and still reading correctly to ±6 V. At ±6 V the
  converter pin must stay inside 0 V to its reference (about 3.3 V) with
  some margin on both sides.
- Step size about 4 mV or better at the input. ±5 V should use roughly
  70 to 75% of the converter's range.
- Input resistance 1 megohm; input capacitance about 30 pF or less
  including wiring.
- One low-pass pole at about 270 kHz, no peaking. It is not an anti-alias
  filter.
- Noise at the converter pin about 0.5 mV rms or less to 1 MHz.
- The two channels match closely (gain a few tenths of a percent, offset a
  few mV). We correct the rest in software.
- The converter shares one sample-and-hold between the two channels, so the
  driver must be low-impedance and settle fast: one channel must not disturb
  the other by more than a couple of converter steps.

## Differential mode

- A jumper on the AFE tells the firmware the mode. It must not change the
  analog signal path.
- About ±5 V difference, at about 4 mV and 7.5 mV per
  step.
- Common-mode rejection, show that every converter pin stays inside the converter's differential
  common-mode window, and state any limit.

## Generator output

- ±1 V, DC coupled, from the Due's DAC0 output.
- Step about 1 mV or finer. Low-pass about 360 kHz.
- Drives 10 kilohms or more, output impedance about 50 ohms or less. A
  short to ground must be safe indefinitely.
- Draws very little from the DAC pin (about 0.1 mA or less).
- Adds about 1 mV rms noise or less.
- While the Due resets or boots the output stays within about ±1.5 V.
- Use the reference rail for the offset, not the 5 V rail.

## Protection and power

- Each scope input survives ±30 V continuously, powered or unpowered.
  Above that only parts we can replace on the board may fail, never the Due.
- The converter pins and the DAC pin always stay between about −0.2 V and
  3.45 V, in every supply state, powered or not.

## Construction

- Low-cost build, assembled and soldered by hand on the proto board.
  Prefer common, widely stocked parts over premium ones: no evaluation
  boards, sockets or lab-grade parts as the default. 
- Keep the number of ICs low.
- Everything must be hand-solderable: through-hole parts, or surface-mount
  on adapters.
- Every Due pin you do not use passes through unchanged. No wire or part may
  cover a header socket.
- All connections to the outside are on the AFE board. Do not wire anything
  to the Due's own headers, and do not add a loopback between DAC0 and an
  input.
- The connector type is open: propose one.
- KiCad 10.x.

## What to check in the public specifications

We have not copied these. Read them and tell us what you used:

- The converter's input model (sample-and-hold capacitance, series
  resistance, required source impedance, track time) and its clock limits.
- The DAC's output impedance, drive limit and output range.
- The absolute maximum voltage on the converter and DAC pins.
- The differential mode: which pin is the positive input, the available
  gains, and the common-mode window.

## What we measured on our own boards

These are measurements, not datasheet values; the boards vary.

- The converter reference is the 3.3 V rail, about 3.27 V on the board we
  measured. Design for 3.20 to 3.30 V.
- The converter clock is 22.5 MHz, above the 20 MHz in the datasheet, by
  choice. One channel samples at about 1.02 Msps. Two channels share about
  1.05 Msps, so about 523 ksps each.
- Converter noise on a held input is about 0.8 step rms, and about 1.65 step
  rms when the DAC drives the same pin.
- The DAC output reaches about 0.58 V to 2.77 V on a scope, not the full
  rail range; theory says 1/6 to 5/6 of the reference.
- DAC noise is not settled. Treat it as unknown. Design the
  output stage to keep the AFE's own contribution small.

Not measured: converter input capacitance and resistance, DAC output
impedance, noise on the reference. Take them from the datasheet.
