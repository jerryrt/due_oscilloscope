# Task: five status LEDs on AFE-2

One task, at two levels, for two readers.

- **Version 1** is the brief the intern works from. It is
  self-contained: the intern does the whole design and validation flow
  on their own, from an input package the owner hands over, and uses
  nothing else in this repository.
- **Version 2** is the owner's answer sheet and checklist, used to mark
  the intern's work. It goes to the intern afterwards, for study.

The skill being trained is **predicting what a new part does to the
analog side before drawing it**. An LED looks like the most harmless
part on a board. On this one it is not: the rail the LEDs draw from,
the pins they hang on and the copper they cross all reach the scope's
readings. The intern should find that out on paper and in simulation,
not on the bench after the boards arrive.

---

## Version 1: the brief

Add five LEDs to the COPPIA AFE-2 shield: one shows that the shield's
power is up, and four are set by Due GPIO pins, their meanings to be
decided later.

- The four status LEDs may change at any time, even during a capture,
  with no measurable effect on the scope or the AWG.
- Lowest cost: Basic parts, as few new part types as possible.
- Before you design anything, write one page on what these LEDs could
  do to the analog side, with numbers, and have it reviewed.
- Then do the whole flow yourself, through simulation, layout,
  manufacturing files, 3D renders and a bench test plan.

### Files you are given

- `afe-v2.kicad_pro`, `afe-v2.kicad_sch`: the schematic project
- `afe-v2-integrated.kicad_pcb` and its project file: the board
- `afe.kicad_sym`, `afe.pretty/`, `afe.3dshapes/`: the libraries and 3D
  models
- the Arduino Due 3D model, for the stacked render
- `scope_v2.cir`: the scope channel's SPICE netlist
- `tph2502.lib`, `lm27762.lib`, `ref3030.lib`, `bav99.lib`,
  `ads1115.lib`: SPICE models of the board's parts
- the datasheets of the board's parts and of the SAM3X8E
- `due-header-table.md`: the Due's pins
- `afe.md`, `afe-v2.md`: the shield's requirements and layout rules
- `jlc-basic.csv`: the board house's Basic parts

---

## Version 2: answer sheet and checklist

### Expected answers

**The circuit.**

| LED | Circuit | Lit when |
|---|---|---|
| Power, D401 | +3V3A → R408 4.7 kΩ → D401 → GND | the shield's +3.3 V rail is up |
| Status 0..3, D601..D604 | +3V3A → R601..R604 4.7 kΩ → LED → Due pin (active-low) | the pin drives low |

**Pins: D34, D35, D36, D37** (PC2..PC5, XIO0 pins 15..18, J605 pins
15..18). Free in version 2 (`hardware/afe-proto/docs/due-header-table.md`
lists D33..D41 as unassigned), and on one port, so one register write
sets all four. Any other free single-net pins are acceptable if the note
argues for them; D0/D1 (console), D13 (on-board LED), D20/D21
(pull-ups) and the analog and DAC pins are not.

**Why +3V3A and active-low**, the heart of the task:

- The Due's 3.3 V rail is also its ADC reference (AREF). Current drawn
  from it moves every reading's gain, and `docs/afe.md` PW-1 forbids the
  shield to load it. An active-high LED on a GPIO draws its current from
  that rail.
- Active-low from +3V3A, the current comes from the shield's own rail
  generator and sinks through the pin to the Due's ground. The Due's
  3.3 V supplies none of it.
- At reset the Due's pins are inputs with pull-ups, so an active-low LED
  stays off until firmware drives it.

**Parts.** One LED type: 0603, red or yellow, Basic, forward voltage
about 1.8 to 2.2 V at 0.3 mA *(check, from the chosen part's
datasheet)*. Green and blue need about 3 V and will not light properly.
Resistor 4.7 kΩ 1% 0603, C23162, already in the BOM. That is +10
placements and +1 part type. With a 1.9 V LED each draws about 0.3 mA,
all five about 1.5 mA (derived).

**Designators and labels.** D401/R408 in POWER; D601..D604/R601..R604
in EDGE; silk `PWR` and `S0` to `S3`. Other numbering is fine if it
follows the block scheme (LR-11).

### The impact table

The intern's note should cover each row with a number. The right-hand
column is what a good answer reaches.

| # | Effect | Good answer |
|---|---|---|
| 1 | LED current on the Due's 3.3 V / AREF | Zero in every state with this circuit; about 0.3 mA per LED, switching, if driven active-high (PW-1, PW-4) |
| 2 | Extra load on +3V3A | About 1.5 mA with all five on, checked against the LM27762's positive-output rating and the rail's existing load |
| 3 | +3V3A step at the ADC pin | **DC, from the datasheets (derived):** one LED's 0.3 mA × the LM27762's 11 µV/mA load regulation (typical, stated at 1.8 V out) ≈ 3.3 µV on +3V3A; through the TPH2502's 80 dB minimum PSRR ≈ 0.3 nV, and through the REF3030E's 240 µV/V maximum line regulation ≈ 0.8 nV. About six orders below one code (0.8 mV) and SC-6's 0.2 mV. **The transient at the edge is not in any datasheet** and is what the simulation is for. Our reference run, a 30 µV step on the amplifier rail (ten times the derived DC figure), gives a peak of 257 nV at the ADC pin on the clean-room TPH2502 and 8.1 nV on the vendor model: under 0.001 of a code on both (`models-open/VALIDATION.md`, section 1) |
| 4 | Pin voltage in every state | Never above the Due's supply; with the Due off and ±12 V on a scope input, +3V3A stays below 0.5 V (PR-3), so the pin stays safe (PR-2) |
| 5 | LED "off" but faintly lit | Pin high at about 3.27 V against +3V3A at about 3.3 V leaves tens of millivolts, far below the forward voltage: no current |
| 6 | The switching edge | A fast GPIO edge; the traces kept on the digital edge, away from the scope's high-impedance side, inside SC-9's 2 LSB |
| 7 | Return current | Pin → Due ground → the one plane → the rail generator; no star ground (LR-1) |

### Bench test the intern should propose

- Both scope inputs grounded at the BNC; capture both channels at the
  full rate while the four status LEDs toggle at a frequency that is not
  a mains multiple, for example 37 Hz.
- **Pass:** no spectral line at the toggle frequency or its harmonics
  above the noise floor; the reference tap differs between all-on and
  all-off by less than its own run-to-run spread.
- **A positive control first:** feed one LED's anode from the Due's
  3.3 V with a jumper wire and confirm that the line appears. Without
  it, a pass proves nothing.

### Checklist for marking

**Impact note**

- [ ] Finds the AREF trap (row 1). Missing it fails the task, however
      good the rest is.
- [ ] Chooses active-low and explains reset behaviour.
- [ ] Shows the pin is safe in every power state (row 4).
- [ ] Rules out green and blue on forward voltage.
- [ ] Puts a number and a source on every "negligible".
- [ ] Proposes a bench test with a positive control.

**Simulation**

- [ ] Models the +3V3A step with a rail impedance taken from the
      LM27762 datasheet or the power netlist, not assumed.
- [ ] Reports the result at the ADC pin and compares it with one code
      and with SC-6.
- [ ] Agrees with our reference run within reason, or explains why not.

**Layout**

- [ ] DRC clean.
- [ ] No new part or trace within 10 mm of U401 or C409 (LR-5).
- [ ] GPIO traces stay on the digital edge, clear of CH1, CH2 and
      REF/CAL (LR-2, LR-3).
- [ ] Bottom ground plane whole under the new traces.
- [ ] Each part inside its block; labels legible; LEDs visible with the
      shield stacked (check the stacked render).
- [ ] Nothing else on the board moved: compare against the original.

**Manufacturing files and cost**

- [ ] Exactly +10 placements and +1 part type in the BOM and placement
      file.
- [ ] The LED is a Basic part, with its LCSC number and stock checked
      on a stated date.
- [ ] Gerbers open cleanly in a viewer; the renders match them.

**Common wrong turns** (each costs marks, none fails alone):

- a green LED, or a 1 kΩ resistor chosen for brightness with no thought
  to rail load or current steps;
- a transistor or driver IC added "to be safe";
- GPIO traces routed across the scope channels because it is shorter;
- "tiny, so it doesn't matter" with no comparison against one code;
- a bench test with no positive control.

**Grading.** The note counts more than the layout. A clean layout over
a note that missed row 1 is a fail; a note that gets rows 1 to 4 right
with numbers, over a rough layout, is a pass to be finished together.

### The input package: what to hand the intern

| Item in version 1's list | Repository path, under `hardware/afe-proto/` unless stated |
|---|---|
| Schematic project | `v2/kicad/afe-v2.kicad_pro`, `afe-v2.kicad_sch`, `fp-lib-table`, `sym-lib-table`, `lib/` |
| Board | `v2/layout/integrated/afe-v2-integrated.kicad_pcb`, its `.kicad_pro` and tables |
| Libraries and 3D models | `kicad/lib/` (`afe.kicad_sym`, `afe.pretty`, `afe.3dshapes`) |
| Due 3D model | The Due STEP used for the project's renders; not in the repository |
| Scope netlist | `v2/sim/scope/scope_v2.cir`, **with its `.include` pointed at the clean-room TPH2502 model**: as committed it includes the vendor model |
| SPICE models | The clean-room models, `models-open/{tph2502,lm27762,ref3030,bav99,ads1115}-open/`; no vendor file goes out |
| Datasheets | TPH2502, LM27762, REF3030E, ADS1115, BAV99, SAM3X8E |
| Pin table | `docs/due-header-table.md` |
| Requirements and rules | `docs/afe.md` and `docs/afe-v2.md`, at the repository root |
| Basic parts | `v2/jlc-basic.csv` |

**Using the clean-room models.** The TPH2502 model carries the
datasheet's DC supply rejection; on 3.3 V circuits pass `VSREF=3.3`,
and `EN=6.5n` when noise matters. Its supply rejection reads 30 to
50 dB worse than the vendor model's, so the intern's row 3 figure
should come out pessimistic, not optimistic. The REF3030E model follows
the datasheet's output impedance, about 80 Ω at 1 kHz with the board's
capacitors, where the project's own board simulations used 0.05 Ω; a
kHz-range answer on the reference that differs from ours for that
reason is right, not wrong. `models-open/VALIDATION.md` has the
comparison. If the intern's design is later
taken into the repository, it is re-entered through the project's own
tools and checks; their files are not merged as they are.
