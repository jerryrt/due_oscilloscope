# AFE: owner plan

Not for the contractor. The contractor's side is
[the contractor brief](afe/contractor/brief.md). This plan covers what you do: supply the
inputs, review each revision, build, measure, and decide what goes back.

## The loop

    send Rev A inputs -> contractor designs, simulates, lays out
         -> you review and re-simulate -> comments -> contractor Rev B ...
         -> design accepted -> you build block by block -> you measure VT-1..14
         -> measurement data -> next design round (if anything fails)

## O0: before the first send

| To do | Why |
|---|---|
| Write the **client data sheet**: ADC input model (sample-and-hold capacitance, series resistance), DAC output impedance, noise and window per board, AREF and 3.3 V values and noise, ADC acquisition settings. Give each value its source | The contractor cannot simulate the ADC driver or the AWG output without it |
| Take the measurements the data sheet needs (DAC noise DC to 1 MHz, per-board AREF and DAC window for all three Dues, ADC noise at 90 MHz, channel memory and crosstalk, DAC output during reset and boot) | They need a Due. Only you can |
| Close or freeze every TBC in `afe.md` at the stated value | The contractor treats TBC as binding. `MC-8` (connector, ×1 or ×10 probe) has no default, so choose |
| Verify the `(check)` items: which pin is IN+, the 0.054 ns per ohm plus 205 ns track time, the differential-mode common-mode window, the pin absolute maximum | The design is based on them |
| Measure the real pin positions and hole grid with calipers. Send a dimensioned drawing, or a physical carrier | `MC-4` is a photo estimate |
| Add a BOM cost target and an availability rule | The contractor does not know the budget |
| Remove or inline references to files you are not sending (`docs/noise.md`, `docs/hardware.md`, `docs/datasheets/`, `records/`, `tools/phase0.py`, `calibration.json`) and explain the 22.5 MHz out-of-spec ADC clock | The documents cite them |
| Decide the review turnaround you promise | The loop runs at your speed |

Known thin margins to tell them about: `AW-2` (0.86 to 0.97 mV per step
against 1 mV) and `DF-3` (46 dB from 0.1% parts gives about 48 dB worst
case). `SC-9` and `SC-10` interact (5 kohm may allow more than 2 LSB of
crosstalk), so ask them for the ADC-model simulation.

## O1: review each revision

1. Rerun their command. Do the numbers match the report?
2. Run your own checks in ngspice: the headline cases, at the worst
   corners, and at least one case they did not choose.
3. Check the pass/fail table: every ID present, margin shown, worst case
   not nominal. Hard ones (noise, crosstalk, CMRR, parasitics) should have
   headroom, because the board will be worse than the simulation. Pick your
   margin policy and tell them.
4. Check the protection cases yourself: ±30 V on an input, powered and
   unpowered, and the AWG output with an external ±5 V.
5. Check the BOM: part numbers exist, stock and price are current, no
   single-source or obsolete parts, within cost target.
6. Check the pin-to-hole map against the carrier: MC-2 holes unused, unused
   Due pins untouched, nothing covering a header socket.
7. Read the model-gap list. Each item should name a test in their
   validation plan.
8. Send numbered comments. For each: requirement ID, what is wrong or
   missing, what evidence would fix it. Do not tell them to relax a limit.

Accept a design only when every row passes, and the validation plan can be
run by you. Record the revision letter you accepted.

## O2: firmware and host work you owe

| Item | Needed for |
|---|---|
| Firmware reads JP-DIFF on a spare pin and selects differential mode and PGA gain | VT-2, VT-11 |
| Firmware limits the DAC to the per-board range | VT-6 |
| Host calibration of gain, offset, response and common mode | VT-1, VT-2, VT-4, VT-6 |

Land firmware changes on all three tracks and keep the invariants (nothing
in the sample path, no printf in an ISR).

## O3: build and measure

Assemble one block at a time on the prototype board, with the loopback
jumpers removed, from a current-limited supply first. Order: power, AWG
output, scope channel 1, scope channel 2, differential. Run VT-1 to VT-14
from their validation plan. Record the revision, the Due identity, the
firmware `build=`, the instruments and every probe. A probe on a measured
pin perturbs it. Discard the first run of any repeated measurement by
index, and break each new check on purpose before trusting it.

The tests that need only a bench (VT-3, VT-4, VT-5, VT-8, VT-12, much of
VT-10) can start before the firmware work. The tests that use the Due's
ADC (VT-1, VT-2, VT-6, VT-7, VT-11) cannot.

## O4: send results back

For anything that fails or surprises, send: the requirement ID, the
measured value, the setup, the Due and firmware, and the model gap it
relates to. The contractor then reruns the affected simulations with the
measured value. Same revision protocol as O1. When all VT pass, write the
calibration note for the host software and the design review.

## Phase 2

The optional differential amplifier assembly is a separate order, after the
Phase 1 design is accepted and measured. Phase 1 only has to define the
interface (P2-6).
