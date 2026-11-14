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

### Goal

Add five LEDs to the COPPIA AFE-2 shield for the Arduino Due:

- one **power LED**, lit while the shield's supplies are up;
- four **status LEDs**, each driven by its own Due GPIO pin. What each
  one means is decided later, in firmware.

The status LEDs must be **free to change at any time, including in the
middle of a capture**, with no measurable effect on any scope or AWG
reading.

### What you are given

- The AFE-2 KiCad 10 project: schematic, board, libraries and 3D
  models, plus the Arduino Due model for rendering the shield stacked
  on it.
- The SPICE netlists of the scope channel and the power section, with
  the part models they use.
- Datasheets for the parts on the board, and the SAM3X8E (the Due's
  processor).
- The Due's header pin table, and the list of pins already in use.
- The shield's requirements and layout rules.
- The board house's list of Basic parts.

Some vendor models are licensed to us, not published: keep them to
yourself.

### Constraints

- Lowest cost. On this board the number of distinct part types costs
  more than the number of placements.
- Board-house Basic parts only. No new ICs, no transistors, no driver
  chips.
- Follow the layout rules you are given. Change nothing else on the
  board.

### Step 1: the impact note, before you draw anything

Write a one-page note and get it reviewed before any schematic work. It
answers:

1. Where does each LED's current come from, and where does it return?
2. What else does each rail you touch feed, and what happens to it when
   an LED switches?
3. Which Due pins do you use, and why those? What is on each one
   already?
4. What voltage does each pin see in every state: running, reset,
   being flashed, Due unpowered, a ±12 V signal on a scope input with
   the Due off?
5. What can the switching edge couple into, and how will your routing
   prevent it?
6. How would you show on the bench that the LEDs change nothing? How do
   you know your test could have seen an effect if there were one?

Every "negligible" comes with a number and where it came from: a
datasheet page, a calculation, or "(check)" if it is a guess.

### Step 2: the design and its validation

Do the whole flow yourself:

1. **Schematic**: the five LEDs and their resistors, added to the given
   schematic.
2. **Simulation**: show with the given SPICE netlists what one status
   LED switching does at the scope's ADC pin. Compare it with one ADC
   code and with the channel's noise budget.
3. **Layout**: place and route the new parts on the given board. Design
   rule check clean.
4. **Manufacturing files**: Gerbers and drill files, BOM and placement
   file, in the board house's format.
5. **3D renders**: the shield alone, and stacked on the Due, with the
   LEDs and their labels readable.
6. **Bench test plan**: the test from question 6, written so that
   someone else could run it.

### Deliverables

- The impact note (reviewed before step 2).
- The modified KiCad project.
- The simulation files and their results.
- The manufacturing files and the renders.
- A short report: what you changed, what the simulation shows, the
  bench test, and the cost (placements and part types added).

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
| 3 | +3V3A step at the ADC pin | One LED's step × the rail's output impedance, through the TPH2502's supply rejection and the REF3030E's line regulation; well below one code (about 0.8 mV) and SC-6's 0.2 mV. **Our own reference figure is not yet computed: run it on `v2/sim/scope/scope_v2.cir` before marking (check)** |
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

| Item | From |
|---|---|
| KiCad project | `v2/kicad/afe-v2.kicad_sch`, `.kicad_pro`, `fp-lib-table`, `sym-lib-table`, `lib/`; the board `v2/layout/integrated/afe-v2-integrated.kicad_pcb` with its `.kicad_pro` and tables |
| Shared libraries and 3D models | `kicad/lib/` (`afe.kicad_sym`, `afe.pretty`, `afe.3dshapes`) |
| Due model for the stacked render | The Due STEP used for the project's renders (not in the repository; from the render scratch area) |
| SPICE | `v2/sim/scope/scope_v2.cir` and its `models/`; the power section's study in `v2/sim/powercal/` |
| Vendor models | From `models/` (not published; hand over privately) |
| Datasheets | TPH2502, LM27762, REF3030E, ADS1115, BAV99, SAM3X8E, and the chosen LED's |
| Pin table | `docs/due-header-table.md` |
| Requirements and rules | `docs/afe.md` sections PW, PR, SC and LR, and `docs/afe-v2.md` |
| Basic parts | `v2/jlc-basic.csv` |

Paths are relative to `hardware/afe-proto/` except the two `docs/afe*`
files, which are at the repository root. If the intern's design is later
taken into the repository, it is re-entered through the project's own
tools and checks; their files are not merged as they are.
