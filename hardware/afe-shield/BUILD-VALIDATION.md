# Shield construction and physical validation

**A correct circuit can fail because of its construction.** A hand-wired
proto shield, a routed two-layer PCB and the bare Due are different
electrical arrangements. Treat each as a distinct test condition. This
checklist supplements [the workflow](../../docs/afe-workflow.md) and
[the AFE plan](../../docs/afe-plan.md); it does not release this board.

## What can be checked before assembly?

| Risk | Before assembly | Evidence that still needs hardware |
|---|---|---|
| Misaligned or reversed headers | Dimensioned header/hole review, numbering and orientation check, unpowered mating trial | Contact quality, intermittent faults and mechanical strain |
| Long signal and ground loops | Wiring drawing, paired signal/return routing, loop-area review | Actual pickup, ringing and disturbance sensitivity |
| Coupling to the Due beneath the shield | Placement/keep-out review against clocks, supplies and connectors | Noise with the actual stacked geometry and operating modes |
| Poor decoupling | Capacitor selection, pin-to-capacitor loop and ground-return review | Rail excursions at the IC during real activity |
| Excess capacitance/inductance | Estimated parasitic sensitivity cases; representative evaluation board | Measured settling and stability with actual wiring and probes |
| Wrong parts or assembly | Exact BOM, pinout, polarity and assembly drawing review | Inspection, resistance and continuity measurements |
| Shared return impedance | Map reference, signal and load-current return paths | Reference movement and crosstalk under load |

Two copper layers are not inherently inadequate. Prefer a largely
continuous ground reference, compact critical loops and controlled return
paths. Ground copper fragmented by routes on both sides is not equivalent
to a continuous plane. Select more layers if the required geometry cannot
preserve those paths; do not assume a layer count guarantees performance.

A plated-through proto shield with pads on both sides is not necessarily
a routed two-layer signal/ground design. Its electrical topology depends
on the soldered links and wires. Record a wiring diagram and photographs
of both sides before treating its result as reproducible.

## Pre-power gate

| Check | Required outcome |
|---|---|
| Board orientation and fit | Every header mates without bending; no offset-by-one connection; holes and standoffs fit |
| Underside and stack height | No lead, joint or wire contacts the Due, connector shells or other unintended copper |
| Continuity | Critical nets match the schematic, including feedback, supply and reference paths |
| Isolation | No unintended shorts between power, ground, reference or adjacent signal pins |
| Passive selection | R5/R6/R7 are 1%; C5/C6/C7 are 5% C0G/NP0; component ratings are checked separately |
| Configuration | JP1 open by default; Due reference configuration documented before any alternate connection |
| Test plan | Supply limit, safe stimulus range, test points and stop conditions specified before power |

Do not connect unknown external signals directly to ADC pins. Stage A is
not the input-protection/attenuation stage. Reference modifications and
power-up must follow [the design review](REVIEW.md), not this checklist
alone.

## Placement and hand-wiring rules for the prototype

Keep amplifier feedback local to the package. Place decoupling with a
short supply-and-ground loop. Keep the ADC RC network close to the ADC
connection and document the remaining header-to-chip path on the Due.
Pair signal wiring with nearby returns, avoid long parallel runs beside
clocks or switching nodes, and keep reference wiring out of load-current
returns. A long wire does not become harmless because its DC resistance
is low.

Avoid adding a long probe ground lead to a sensitive high-speed node.
Record probe type, capacitance, attenuation, ground connection and
location. A probe can create or suppress the problem being investigated.

## Separate circuit effects from construction effects

| Comparison | Hold constant | What it can establish |
|---|---|---|
| Bare Due versus mechanically fitted, electrically disconnected shield | Board, firmware image, supplies, cable geometry, temperature/rest conditions | Whether stacking alone changes the measured behaviour |
| Short baseline loopback versus Stage A prototype | Board and stimulus/timing; declared probe loading | Effect of the assembled Stage A path, including its wiring |
| Prototype versus routed PCB | Circuit values, configuration and test procedure | Effect of the implementation; both need their own acceptance results |
| Before/after one wiring or grounding change | Everything except the declared change | Whether that physical feature contributes to the failure |

Use repeated, interleaved comparisons when a quantity varies with time.
An A/B difference after moving several wires, changing the board and
warming the device is not attribution. Record the board identity,
shield revision, wiring/probes, reference configuration, firmware image,
sample/channel settings, instruments and conditions with the measurements.

First establish safe rails and bias, then test DC transfer, reference
movement, step response, frequency response, noise and channel interaction.
Measure the final PCB even when the prototype passes. A prototype failure
also needs diagnosis: wiring, fixture and circuit are separate suspects.

## What the automated screen can and cannot say

`sim/screen.py` includes explicit assumed series-wire inductances. They
are sensitivity experiments, not values extracted from this shield. They
do not represent shared-ground impedance, mutual coupling, ferrite loss,
all probe loading or the physical ADC switching sequence. A small change
in this screen cannot clear the physical-build gate. Keep the actual
measurement requirements above even when the screen passes.
