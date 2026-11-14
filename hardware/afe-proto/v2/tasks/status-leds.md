# Task: five status LEDs on AFE-2

One task, written at two levels. Hand out **version 1** first. Hand out
**version 2** only after the intern's impact note has been reviewed: it
is the specification to build against and the answer key for the note.

The skill being trained is **predicting what a new part does to the
analog side before drawing it**. An LED looks like the most harmless
part on a board. On this one it is not, because the rail the LEDs draw
from, the pins they hang on and the copper they cross all reach the
scope's readings. The intern should find that out on paper, before the
layout, not on the bench after it.

The reviewer notes at the end say what a strong note finds and where
interns usually go wrong.

---

## Version 1: the goal and the questions

### Goal

Add five LEDs to COPPIA AFE-2 (`hardware/afe-proto/v2`):

- one **power LED**, lit while the AFE's supplies are up;
- four **status LEDs**, each driven by its own Due GPIO pin. What each
  one means is decided later, in firmware.

The status LEDs must be **free to change at any time, including in the
middle of a capture**, with no measurable effect on any scope or AWG
reading.

### Constraints

- Lowest cost. On this board the number of distinct part types costs
  more than the number of placements (`docs/afe.md`, MC-12).
- Board-house Basic parts only. No new ICs, no transistors, no driver
  chips.
- Follow the layout rules in `docs/afe.md`, section LR. Change nothing
  else on the board.

### Before you draw anything

Write a one-page **impact note** and get it reviewed. It answers:

1. Where does each LED's current come from, and where does it return?
2. What else does each rail you touch feed, and what happens to it when
   an LED switches?
3. Which Due pins do you use, and why those? What is on each one
   already?
4. What voltage does each pin see in every state: running, reset,
   being flashed, Due unpowered, a ±12 V signal on a scope input with
   the Due off?
5. What can the switching edge couple into, and how does your routing
   prevent it?
6. How would you show on the bench that the LEDs change nothing? How do
   you know your test could have seen an effect if there were one?

Every "negligible" in the note comes with a number and where it came
from (a datasheet page, a calculation, or *(check)* if it is a guess).

### Deliverables

1. The impact note, reviewed before any layout.
2. The design change and the regenerated outputs.
3. One proposed bench-test row for `docs/afe-v2.md`, from question 6.

### Done when

The note is accepted, DRC is clean, the quick test tier passes in the
container, and the full gate passes on montreal5.

---

## Version 2: the detailed requirement

### The circuit

| LED | Circuit | Lit when |
|---|---|---|
| Power, D401 | +3V3A → R408 4.7 kΩ → D401 → GND | the AFE's +3.3 V rail is up |
| Status 0..3, D601..D604 | +3V3A → R601..R604 4.7 kΩ → LED → Due pin (active-low) | the pin drives low |

**Pins: D34, D35, D36, D37** (PC2..PC5, XIO0 pins 15..18, J605 pins
15..18). They are free in version 2 (`hardware/afe-proto/docs/due-header-table.md`
lists D33..D41 as unassigned), and they share one port, so one register
write sets all four. Confirm against `v2/kicad/design.py` that nothing
else uses them.

**Why +3V3A and active-low**, which is the heart of the task:

- The Due's 3.3 V rail is also its ADC reference (AREF). Current drawn
  from it moves every reading's gain, and `docs/afe.md` PW-1 forbids the
  AFE to load it. An LED driven high by a GPIO draws its current from
  that rail. So does the GPIO's own drive, on every switch.
- Active-low from +3V3A, the LED's current comes from the AFE's own rail
  generator and sinks through the pin to the Due's ground. The Due's
  3.3 V supplies none of it.
- At reset the Due's pins are inputs with pull-ups, so an active-low LED
  stays off until firmware drives it.

### Parts

| Part | Choice | Notes |
|---|---|---|
| LED, ×5 | One type, 0603, red or yellow, JLC Basic | Forward voltage about 1.8 to 2.2 V at 0.3 mA *(check, from its datasheet)*. Green and blue LEDs need about 3 V and will not light properly from 3.3 V through 4.7 kΩ. Add the LED's row to `v2/jlc-basic.csv`, read from the board house's site, with the date |
| Resistor, ×5 | 4.7 kΩ 1% 0603, C23162 | Already in the BOM (`T['4.7k']` in `design.py`), so no new type |

That is +10 placements and +1 part type. With a 1.9 V LED each one
draws about 0.3 mA, and all five about 1.5 mA (derived; recompute with
your LED's forward voltage).

### Designators and blocks (LR-11)

- D401 and R408 in **POWER**. No D4xx exists yet; R408 is the next free
  resistor.
- D601..D604 and R601..R604 in **EDGE**, with the GPIO traces.
- Silk labels: `PWR` and `S0` to `S3`, beside each LED, legible with the
  shield on the Due.

### Files you edit by hand

| File | Change |
|---|---|
| `docs/afe-v2.md` | One requirement row (the five LEDs, the pins, active-low from +3V3A, **states may change at any time including during capture**), one decision row, one bench-test row |
| `hardware/afe-proto/v2/kicad/design.py` | The 10 parts and their nets, the LED in `T` |
| `hardware/afe-proto/v2/jlc-basic.csv` | The LED's row |
| `hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb` | Place and route the 10 parts |

Everything else is **regenerated by the existing tools, never edited**:
the schematic, BOM and placement file, `bom.md`, the order tables, the
fab zip and its manifest, the renders, the gate-3 package and the cap
record. `docs/afe-v2.md` text is quoted into the gate-3 package, so
regenerate it in the same change. If a check wants any other file
changed, ask before editing it.

### Layout rules

- **LR-5**: no LED part or trace within 10 mm of U401 or its flying
  capacitor C409.
- **LR-2, LR-3**: the GPIO traces stay on the digital edge near J605.
  None crosses CH1, CH2 or REF/CAL, and none runs beside a scope
  channel's high-impedance side.
- **LR-11**: each part inside its block's outline; the outline is
  redrawn if the block grows.
- Each LED visible from above with the shield stacked: not under a BNC
  or behind a header.
- The bottom ground plane stays whole under the new traces.

### The impact analysis: what the note must work out

Each row is a question with a number to compute. Take datasheet figures
with page numbers; mark anything read off a graph *(check)*.

| # | Effect | Work out | Compare with |
|---|---|---|---|
| 1 | LED current on the Due's 3.3 V / AREF | Show that it is zero in every LED state with this circuit, and what it would be if the LEDs were driven high instead | PW-1 (none allowed), PW-4 (0.3 mV) |
| 2 | Extra load on +3V3A | Total current with all five on, at your LED's forward voltage | The LM27762's positive-output rating and the rail's existing load |
| 3 | +3V3A step reaching the ADC pin | One status LED's step × the rail's output impedance = ΔV on the rail; then through the TPH2502's supply rejection and the REF3030E's line regulation to the ADC pin | One code (about 0.8 mV at AREF 3.27 V) and SC-6's 0.2 mV noise |
| 4 | Pin voltage in every state | Running, reset (pull-up), flashing, Due unpowered, ±12 V on a scope input with the Due off (+3V3A then stays below 0.5 V, PR-3) | PR-2 and the SAM3X's absolute maximum *(check)* |
| 5 | LED "off" but faintly lit | With the pin high at the Due's 3.3 V and +3V3A slightly above it: the voltage left across the LED and resistor, and the current | The LED's forward voltage at microamps |
| 6 | The switching edge | Rise time of a GPIO edge, and what capacitance couples it into an analog trace at your routing distance | SC-9's 2 LSB crosstalk budget |
| 7 | Return current | The path the sink current takes from the pin back to the rail generator | LR-1 (one plane, no star ground) |

### Bench test (the row to add)

**VT-LED: status LEDs during capture.**

- Both scope inputs grounded at the BNC. Capture both channels at the
  full rate while firmware toggles all four status LEDs at a frequency
  that is not a mains multiple (for example 37 Hz).
- **Pass:** the spectrum of each channel shows no line at the toggle
  frequency or its harmonics above the noise floor. The reference tap,
  read with all LEDs on and then all off, differs by less than its own
  run-to-run spread.
- **Positive control first.** Before trusting a pass, show that the
  test can fail: with a jumper wire, feed one LED's anode from the Due's
  3.3 V instead of +3V3A, and confirm that the line appears. A test that
  cannot fail proves nothing.

### Out of scope

Firmware. What the states mean, and the pin driver in all three tracks'
`main()`, are a separate task. This task leaves the pins as inputs, so
the LEDs are off on firmware that does not know about them.

### Acceptance

1. Impact note reviewed before layout.
2. DRC clean; the quick tier passes in the container.
3. The fab set and BOM show exactly +10 placements and +1 part type,
   and nothing else in them changed.
4. The full gate passes on montreal5, and the merge goes to the owner
   as yes/no.

---

## Reviewer notes

**What a strong note finds**, roughly in order of how much it matters:

1. **The AREF trap.** The Due's 3.3 V rail is its ADC reference.
   GPIO-driven LEDs wired the obvious way (active-high) load it on every
   switch. This is the point of the exercise; a note that misses it
   fails, however tidy the rest is.
2. **Reset behaviour.** Active-low keeps the LEDs off through reset and
   flashing because of the pull-ups. Active-high could glow faintly.
3. **Pin safety across rails.** The pin must never rise above the Due's
   supply when the two 3.3 V rails differ or one is off.
4. **Forward voltage against 3.3 V.** This rules out green and blue.
5. **A number for every "negligible"**, with its source.
6. **A test that can fail**, which means a positive control.

**Common wrong turns:**

- A green LED, or a 1 kΩ resistor chosen for brightness with no thought
  to rail load or current steps.
- Adding a transistor or driver IC to "be safe". It costs part types
  and solves a problem that the circuit choice removes.
- Routing the GPIO traces across the scope channels because it is
  shorter.
- "The current is tiny, so it doesn't matter", with no comparison
  against one code or the noise budget.
- A bench test with no positive control.

**Grading:** the note counts more than the layout. A clean layout over
a note that missed item 1 is a fail; a note that finds items 1 to 4 and
puts numbers on them, with a rough layout, is a pass to be finished
together.
