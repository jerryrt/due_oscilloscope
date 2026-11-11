# Building the AFE

The plan that meets [the AFE requirements](afe.md): the build, step by step,
and the owner's side of it. **Every circuit is simulated and passes review
before anything is placed, ordered or soldered.** A failed simulation changes the
circuit and is rerun; it never relaxes a limit. Requirement IDs (SC-, SM-, DF-,
AW-, PA-, PR-, PW-, VT-) are those of `afe.md`, whose "Requirement IDs" table gives
each prefix's meaning.

## The sequence

| Step | Work | Gate: what must be true to leave it |
|---|---|---|
| **0** Inputs and tooling | Take the measurements the requirements lean on, close the TBC values, set up KiCad 10.x, ngspice and validated models | **G0**: every input in the table below has a value and a source; every TBC is closed or frozen with an owner; models are validated and hashed |
| **1** Architecture and budgets | Choose the topology and parts on paper; allocate gain, error, noise, current and impedance | **G1**: every requirement has a block and a numeric allocation, and no budget is negative at worst case |
| **2** Simulation | Simulate each block, then the whole, against the requirement numbers: 2a power, 2b scope channel, 2c AWG output, 2d differential mode, 2e integration | **G2**: an accepted report per block, and an integrated report that passes every case at the stated corners. **Nothing is built before G2** |
| **3** Layout of the shield PCB | Lay out the passed circuit as a custom shield PCB for all phases in one design, with optional parts as unfitted footprints (MC-11); run KiCad 10.x's electrical and design rule checks | **G3**: header-pin table reviewed against the Due V03 reference, rule checks clean, parasitics from the real layout added as sensitivity cases and the affected simulations rerun |
| **4** Build and bench | Assemble and bring up block by block; run VT-1 to VT-17 | **G4**: every test passes on the board, with its record |
| **5** Calibration and review | Write the calibration note for the host software, the test report and the version 1 design review | **G5**: review accepted |

Steps 0 to 5 deliver version 1: Phase 1 and Phase 3 (3a and 3b).

## Step 0: inputs and tooling

Measurements that decide whether a requirement can be met, taken before
the circuit exists, on the Due alone with no AFE circuit fitted
(loopback jumpers allowed). Each result is recorded in `records/` with the bench,
Due identity, firmware `build=` and instrument.

| Input | Why it matters | How |
|---|---|---|
| DAC noise over DC to 1 MHz, DAC0 driving and idle | AW-6 premise: records disagree by 15x (20 mV against 1.3 mV) | External instrument with a floor of at most 0.15 mV; `docs/noise.md` has the loopback figure |
| Per-board AREF and DAC window for all three Dues | SC-2, AW-1 and AW-7 margins | `calibration.json` and a scope on the pin; AREF at the 3.3 V pin and ADC |
| ADC noise baseline at 90 MHz | SC-6 and SC-10 are judged against it | `tools/phase0.py noise-fast` |
| Channel memory and crosstalk at 90 MHz, with a low-impedance source | SC-9, SC-10 | `docs/noise.md` method; `docs/hardware.md` lists this as unmeasured at 90 MHz |
| The ADC's own noise floor, with a quiet DC source: one alkaline AA cell (1.5 V) through a series resistor into one ADC pin | Decides whether the DAC or the ADC holds the level band, and the AFE noise targets that follow. No rework. Not a Li-ion cell, which reaches 4.2 V | One cell and one resistor on the Due; `tools/phase0.py noise-fast` |
| Differential mode: VIN+ pin, common-mode window, PGA gain codes | DF-1, DF-2 | SAM3X datasheet in `docs/datasheets/` |
| DAC output while the Due resets and boots | AW-8 | Scope on DAC0 through a reset and a flash |
| ADC acquisition settings the firmware will use | SC-9, SC-10, AN-2 | Client decision |

The TBC values of the requirement are frozen ([afe.md](afe.md), section 18); what
is left to decide is its section 16, decisions D1 to D11. All are decided except D7, which needs one
measurement, the Due's own supply current, before step 1 closes PW-1.

Tooling: KiCad 10.x with matching symbol and footprint libraries, and
ngspice, with the exact versions recorded in every report. Models live in
the models subfolder with their source and hash (MC-6); each gets a
smoke test before it is trusted. The working KiCad project is a new one under `hardware/afe-proto/`, a shield PCB mated to the [Due V03 reference](../hardware/reference/arduino-due/README.md). Models, simulation benches and accepted reports each get
a subfolder of `hardware/afe-proto/`, created in this step.

## Step 1: architecture and budgets

A written budget, reproducible from a script rather than a spreadsheet,
for each of these:

| Budget | Requirements it must close |
|---|---|
| Scope gain window: attenuation 0.2290 to 0.2453 at nominal AREF, tolerances, centring | SC-2, SC-4, SC-8 |
| Matching: parts of 0.1% for the CMRR chain; mismatch against 46 dB | DF-3 |
| ADC pin: source impedance, settling, channel memory | SC-9, SC-10 |
| Noise at the ADC pin and at the AWG output | SC-6, AW-6 |
| AWG: gain 1.10 to 1.20, window use at most 92%, step | AW-1, AW-2, AW-7 |
| Current: normal, AWG short, external ±5 V | PW-1, PW-3, PR-4 |
| Rails: derived rails, ripple, and noise fed back to 3.3 V and AREF | PW-2, PW-4, PR-2 |

The step ends with the topology and the part list with alternates.

## Step 2: simulation

Run in this order, because each block uses the one before it. A block
passes only when every case meets the requirement number itself.

| Block | Cases | Requirements |
|---|---|---|
| **2a** Power | Rail startup and ramp, load steps, ripple at the amplifier pins, current, noise reaching 3.3 V and AREF | PW-1, PW-2, PW-3, PW-4 |
| **2b** Scope channel | DC transfer over AREF 3.20 to 3.30 V and tolerance Monte Carlo; headroom to ±6 V; AC corner and peaking; noise; switched ADC-load settling; channel crosstalk surrogate; clamp currents at ±30 V and in the unpowered case; the Due's pin voltages and the parts that fail for inputs above ±30 V | SC-2 to SC-10, PR-1 to PR-3 |
| **2c** AWG output | Span and centring against the DAC window; step; corner; load, short and external ±5 V; reset and boot state; noise with a quiet source | AW-1 to AW-8, PR-4 |
| **2d** Differential | CMRR with tolerance Monte Carlo at DC and 10 kHz; both ranges and their step; common-mode window | DF-1 to DF-4 |
| **2e** Integration | Everything together with the quad or multi-device packages, local decoupling and the ADC-load surrogate; wiring parasitics as sensitivity cases; phase margin; reference drift; temperature corners; every unpowered case | AN-1 to AN-4, EN-1, PR-2 |

A report states the KiCad and ngspice versions, model hashes, exported
netlist, stimuli and loads, and a numeric result against its limit for
every case. Effects the models cannot show (measured noise, crosstalk,
physical fit) are listed as model gaps with the bench test that closes
them.

## Step 3: layout of the shield PCB

| Work | Evidence |
|---|---|
| A new KiCad 10.x project under `hardware/afe-proto`, a shield in the Mega/Due form factor stacked on the Due through stacking headers | The project, with the Due V03 reference as its mating model |
| Header pin positions taken from the Due V03 reference and checked by continuity on the owner's boards (MC-4) | Written confirmation, before a round is ordered |
| Every net's header pin in a table, and the unused Due pins left through unchanged (MC-5, MC-9); AREF listed as used (PA-7) | The table, and KiCad's electrical and design rule checks clean |
| Optional parts as unfitted footprints, and choices as Due-pin switches (MC-11) | The BOM marks each as fitted or unfitted for the round |
| Parasitics extracted from the layout, not estimated, added as sensitivity cases | The affected step 2 blocks rerun and passing |
| Unpowered continuity and insulation checks defined | Checklist the build step runs |

## Step 4: build and bench

Assemble one block at a time on the round's board, with the loopback
jumpers removed (MC-10), and power it from a current-limited supply first.
Tests that used those jumpers use an external cable between the AWG
connector and a scope input, and the wiring is declared as AFE fitted. Order: power, AWG output, scope channel one, scope channel two,
differential. Record the assembly revision, the Due identity, the
firmware, the instruments and every probe with each measurement; a probe
on a measured pin perturbs it, so declare it.

Bench tests are VT-1 to VT-17 in `afe.md`. Run every repeated measurement
one time more than needed and discard the first by index, and break each
new check on purpose to see it fail before trusting it. A test that was
skipped has not passed.

The firmware and host work the tests depend on is the owner's, in the table under "The owner's side" below.

The tests that need only a bench (VT-3, VT-4, VT-5, VT-8, VT-12, much of VT-10,
and VT-16) can start before the firmware work. The tests that use the Due's ADC
(VT-1, VT-2, VT-6, VT-7, VT-11, VT-15, VT-17) cannot.

## Step 5

Step 5 produces the written calibration note (what the host must correct,
and how), the test report and the design review.

## Rounds

All phases are one PCB design, built over several rounds. A round is: simulate what
changed, lay it out, order it, bring it up, measure it. Every gate of this plan
applies to each round, and a failed round changes the circuit and is rerun. It
never relaxes a limit.

**Round 1 is for learning what the document cannot decide.** It carries the whole
design, with every open choice as a Due-pin switch or an unfitted
footprint, never a jumper (MC-11):

| Open choice | How round 1 carries it |
|---|---|
| Input ranges (D1) | the ±1.25 V stage and its Due-pin switch, fitted; ±5 V selected at reset |
| The reference at an ADC input, and at AREF (PA-7, PA-8) | the ladder's top tap on a spare ADC pin, and an unfitted series 0 ohm resistor to AREF |
| The AFE's own supply current (D7) | a sense resistor in the 5 V feed with a test point either side, so a meter reads it with no jumper |
| 3b, the slow ADC and DAC | fitted in version 1 (D5) |
| Test points | on every rail, the reference, and each stage's output |

Round 1 is considered done when it has answered: which converter holds the level
band (VT-3), how wide the equivalent-time path is and how noisy (VT-16), and
whether a narrow range fills the ADC without losing the noise margin (VT-15).
Later rounds fix what those answers and the layout show.

## The owner's side

The plan above is the build. This is what the owner does around it, as a loop
with the contractor.

    send Rev A inputs -> contractor designs, simulates, lays out
         -> owner reviews and re-simulates -> numbered comments -> Rev B ...
         -> design accepted -> owner builds block by block -> measures VT-1..17
         -> measurement data -> next design round (if anything fails)

### Before the first send

| To do | Why |
|---|---|
| Write the **client data sheet**: ADC input model (sample-and-hold capacitance, series resistance), DAC output impedance, noise and window per board, AREF and 3.3 V values and noise, ADC acquisition settings. Give each value its source | The contractor cannot simulate the ADC driver or the AWG output without it |
| Take the measurements the data sheet needs (DAC noise DC to 1 MHz, per-board AREF and DAC window for all three Dues, ADC noise at 90 MHz, channel memory and crosstalk, DAC output during reset and boot) | They need a Due. Only you can |
| Close or freeze every TBC in `afe.md` at the stated value | The contractor treats TBC as binding. `MC-8` (connector, ×1 or ×10 probe) has no default, so choose |
| Verify the `(check)` items: which pin is IN+, the 0.054 ns per ohm plus 205 ns track time, the differential-mode common-mode window, the pin absolute maximum | The design is based on them |
| Check the Due's header pin positions by continuity on each of the owner's boards | `MC-4` takes them from the Due V03 reference, a converted board file |
| Add a BOM cost target and an availability rule | The contractor does not know the budget |
| Remove or inline references to files you are not sending (`docs/noise.md`, `docs/hardware.md`, `docs/datasheets/`, `records/`, `tools/phase0.py`, `calibration.json`) and explain the 22.5 MHz out-of-spec ADC clock | The documents cite them |
| Decide the review turnaround you promise | The loop runs at your speed |

Known thin margins to tell them about: `AW-2` (about 0.59 to 0.65 mV per step
against 1 mV at ±1 V: the DAC's step is 0.54 mV, so the margin is 35 to 40%, and it was
written as 0.86 to 0.97 by dividing by AREF where the DAC's span is two thirds of it) and `DF-3` (46 dB from 0.1% parts gives about 48 dB worst
case). `SC-9` and `SC-10` interact (5 kohm may allow more than 2 LSB of
crosstalk), so ask them for the ADC-model simulation.

Done since this was written: every TBC but MC-8 is frozen at its stated value
and the decisions are one list ([afe.md](afe.md), section 16). What the owner
sends is the contractor package ([afe/contractor-inventory.txt](afe/contractor-inventory.txt)),
which is the rounded wording **as sent**, already out of date on construction, until the package is revised to the decisions of section 16.

### Reviewing each revision

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
6. Check the header-pin table against the Due V03 reference: AREF listed as used, unused
   Due pins untouched, nothing covering a header socket.
7. Read the model-gap list. Each item should name a test in their
   validation plan.
8. Send numbered comments. For each: requirement ID, what is wrong or
   missing, what evidence would fix it. Do not tell them to relax a limit.

Accept a design only when every row passes, and the validation plan can be
run by you. Record the revision letter you accepted.

### Firmware and host work the owner owes

| Item | Needed for |
|---|---|
| Firmware reads JP-DIFF on a spare pin and selects differential mode and PGA gain | VT-2, VT-11 |
| Firmware limits the DAC to the per-board range | VT-6 |
| Host calibration of gain, offset, response and common mode | VT-1, VT-2, VT-4, VT-6 |

These dependencies are the owner's, and not the contractor's. Land firmware changes on all three tracks and keep the invariants (nothing
in the sample path, no printf in an ISR).

### Sending results back

For anything that fails or surprises, send: the requirement ID, the
measured value, the setup, the Due and firmware, and the model gap it
relates to. The contractor then reruns the affected simulations with the
measured value. Same revision protocol as O1. When all VT pass, write the
calibration note for the host software and the design review.

### Phase 3

Phase 3, the precision reference and converter pair (3a and 3b), is in version
1 (D5) and goes through steps 1 to 4 with Phase 1.

## Traceability

| Requirements | Simulated in | Tested in |
|---|---|---|
| SC-1 to SC-10 | 2b, 2e | VT-1, VT-3, VT-4, VT-10, VT-13 |
| DF-1 to DF-4 | 2d | VT-2, VT-11 |
| AW-1 to AW-8 | 2c | VT-3, VT-4, VT-5, VT-6 |
| PR-1 to PR-4 | 2b, 2c, 2e | VT-5 |
| PW-1 to PW-4 | 2a | VT-8, VT-6 |
| AN-1 to AN-4, EN-1 | 2e | VT-12, VT-13 |
| PW-5, CA-1, MC-1 to MC-12 | review | VT-14 |
| SM-3 to SM-8, SC-11 | 2b, 2c, 2e | VT-4, VT-15, VT-16, VT-17 |
| PA-1 to PA-9 (Phase 3, D5) | 2a, 2e | PA-6's meter and reference check |
