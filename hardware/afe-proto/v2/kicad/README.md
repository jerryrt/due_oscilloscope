# AFE version 2: the KiCad schematic

KiCad 10.x only (`kicad-cli` 10.0.8 is what generated and checked it). Schematic only: no PCB yet.
Pattern and code are version 1's (`../../kicad`), copied, not imported.

| file | what |
|---|---|
| `design.py` | the design as data: every part, value, LCSC number, footprint and pin's net; the Due header allocation |
| `build_sch.py` | writes `afe-v2.kicad_sch`, the project file, `sym-lib-table`, `fp-lib-table`, `lib/afe.kicad_sym` (TPH2502, ADS1115) |
| `check.py`, `spicecmp.py` | the checks and the SPICE netlist comparison, with mutation arms |
| `lib/afe.pretty/` | the BNC and Due XIO socket footprints, copied from version 1 |
| `sexpr.py` | S-expression reader/writer |

```sh
python3 -I hardware/afe-proto/v2/kicad/build_sch.py     # writes afe-v2.kicad_sch (then kicad-cli sch upgrade)
python3 -I hardware/afe-proto/v2/kicad/check.py         # all checks, then 19 mutation arms (about 70 s)
python3 -I hardware/afe-proto/v2/kicad/check.py --fast  # checks only
```

The schematic is flat, one sheet, a net label on every pin, laid out by block (power, scope, AWG, calibration,
Due headers). It is a connection list for the netlist and the checks, not a drawing to read for signal flow.
Footprints come from KiCad's standard libraries (0603, 0805, 1206, SOT-23, SOIC-8 3.9 mm for the SOP-8 dual,
MSOP-10, WSON-12) plus `afe.pretty`.

## What it holds

97 parts (77 fitted by the board house, 35 LCSC types, 48 nets). Designators: `U1 C1 C2` and `1xx`/`2xx` the scope
(channel 1, 2), `3xx U2` the AWG, `4xx U3 U4 U5` the rails, reference and ADS1115, `5xx` the ladder and sense
divider, `J1 J2 J3` the BNCs, `J4..J10` the Due headers, `J11` the CAL jumper header, `MH1 MH2` standoffs. Each part's `Sim`
field gives its name in the studies (`scope.R1a`, `awg.R3`, `pc.R_FB1`).

Due header allocation (V03, `docs/due-header-table.md`): POWER0 5 V and ground; ADCL0 A0 (CH2), A1 (CH1), the ladder
taps on A2..A7 with the reference on A7's pin; ADCH0 DAC0; PWMH0 ground, AREF (through an unfitted 0R, PA-7),
**SDA1 and SCL1 (pins 9, 10: the SAM3X's TWI0; TWI1 is D20/D21, which have the Due's 1.5k pull-ups) for the ADS1115's I2C**; XIO0 ground. Every other pin is declared NC and passes through.
No Due 3.3 V pin is used (the scope centre is the REF3030E now). D5..D9, D16, D39 are free.

## Checks

`S1` ERC (one exclusion, the LM27762 PGOOD tied to ground). `S2` netlist equals `design.py`. `S3` fields equal
`design.py`. `E1` every pin connected or declared NC. `E2` no single-pin net. `E3` value, footprint (exists in a
library), LCSC on every fitted part. `E4` TPH2502, ADS1115, LM27762 pin names against datasheet tables. `B1` value,
LCSC and quantity against the three `parts.csv`, and every row placed. `N1`, `N2` the scope and AWG blocks against
`sim/scope/scope_v2.cir` and `sim/awg/awg.cir`. `C1` rails computed from the netlist (+3.318 V, -2.003 V). `C2`
ladder. `C3` sense divider and ADS1115 pair. `C4` the CAL header and the shunt on the hand-fitted list. `C5` no scope part on the negative rail.
`H1` Due headers equal the header-pin table.

### The netlist comparison (`spicecmp.py`)

It compares topology and values, not names. The SPICE side drops the elements listed in `RULES` (sources, rail and
reference models, strays, loads, each with its reason), shorts the 0 V ammeters, collapses a capacitor with its
ESR, and every SPICE element not listed stays in the graph (so a new element fails; a rule naming a vanished element
fails too). The schematic side takes the block's parts from KiCad's exported netlist, expands the BAV99 into two
diodes and the dual into two amplifiers (from pin names), and both sides fold parallel resistors and capacitors.
Then a colour refinement over the element/net graph must give identical colours; ground, +3.3 V_A, the negative
rail, the reference and the DAC pin are anchored by name.

**Covers:** values and connectivity of 29 scope elements and 14 AWG elements. **Does not cover:** the sources and
strays (by design); the power/calibration block, which has no netlist (checked by `C1..C4` arithmetic instead);
channel-for-channel swaps between the identical scope channels (electrically identical, so not a difference);
pin-to-pin crossings that preserve the graph's symmetry; the models' internals; the AWG capacitor derating (see below).

Recorded differences between the studies and the schematic: the AWG study carries the two 10 uF filter capacitors
as 14 uF effective (0.7 derating, a rule in `RULES`); the scope study has 1.1 uF at the reference output where the
powercal parts put 1 uF there and the 100 nF at the input (both treated as the reference model, not compared).

## Decisions to confirm

1. **ADS1115 allocation (final, from the coordinator).** AIN0 reference, AIN1 the 2/3 ladder tap, AIN2 the sense tap
   through R510 (3.9k), AIN3 the divider's bottom node B through R511 (10k); the differential pair is AIN2 - AIN3.
   My first reading (inputs 1..4 in order) put the pair on AIN1/AIN2, which the multiplexer cannot select; `C3`
   now derives the pair from the netlist and checks it against the multiplexer table.
2. **I2C** is the SAM3X's TWI0 on PWMH0.9/.10 (labelled SDA1/SCL1 on the Due header; no pull-ups there), with two
   4.7k Basic pull-ups (C23162) to +3.3 V_A on the shield.
3. **Calibration jumper `J11`**: a 1x3 male header, silkscreen "CAL" (layout), pins TAP_low | B | TAP_on, one 2.54 mm
   shunt across B and TAP_on (the "on" position, marked). TAP_on is the 1/3 ladder tap (TAP2). **TAP_low is
   a placeholder**: the power study has not named it, so `design.TAP_LOW` is TAP1 (a ladder tap) in one constant. I
   did not use a separate net named TAP_LOW_TBD because a single-pin net fails the no-single-pin check. The shunt is
   a loose hand-fitted part (`design.HAND_FITTED`, checked by `C4`); the other hand-fitted parts are the BNCs, the
   stacking headers, the J11 header and the two standoffs with screws. Every Due pin stays reachable from the top.
4. **Part numbers I added** (not in any study): 2 x 4.7k pull-up C23162, 0R C21189 for PA-7 (unfitted), six test
   points, two mounting holes; all Basic per `../jlc-basic.csv`. The BAV99 is drawn with KiCad's
   BAT54S series-pair symbol (pins 1 A1, 2 K2, 3 common), as version 1 did.
5. **TPH2502 pinout** is the datasheet's pin figure (OUTA, -INA, +INA, V- | +INB, -INB, OUTB, V+, standard dual);
   the symbol is one unit, one package. Footprint `SOIC-8_3.9x4.9mm_P1.27mm`; ADS1115 footprint `MSOP-10_3x3mm`
   (KiCad's own ADS1115 symbol names a TSSOP-10 footprint, which is wrong for the DGS package).
6. **The AWG study moved while this was built** (11:03 on 2026-11-12: Rf = Rg2 = 3k, Rbin 2.7k, offset filter
   100R + 2 x 10 uF back, 330 pF output pole gone). The schematic follows the files as read at 11:07, and so did the
   powercal bleed (1.8k, C4177). `check.py` fails the moment a `parts.csv` or `.cir` moves again, which is its job.
   The AWG's `design.md` still describes the earlier circuit.
7. The BNC footprint's 3D model is a stand-in (as in version 1).
8. **Second standoff `MH2` at Due hole (90.17, 50.8)**, added. It is inside the 100 x 53.34 outline (2.54 mm from the
   top edge, 0.94 mm of copper-free edge beyond the 3.2 mm hole) and clear of every header except XIO0 pin 1
   (93.98, 50.8): 3.81 mm away, so a 5.6 mm screw head leaves about 0.2 mm to the pad and the ISO7380 courtyard
   (r 3.1) overlaps the socket's. Fits if the layout shifts the courtyard rule; flagged for the PCB round.
   MH1 (96.52, 2.54) is unchanged.
9. The bleed follows `powercal/parts.csv` as it stands (1.8k, C4177); `B1` fails when it moves.
