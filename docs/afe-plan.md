# Building the AFE shield: the plan

**Status: Stage A in design; nothing built.** `docs/afe.md` is the
requirement this plan builds; this file says in what order, with what
tools, and what proves each step. The design is also the review of the
requirement: every estimate in its table is checked as the stage that
sets it is drawn, and a line that the arithmetic or the simulation
moves is corrected in `docs/afe.md`, not carried here.

For an explanation of the engineering process behind these phases, see
[AFE design with KiCad: workflow and quality gates](afe-workflow.md).
The [self-contained prototype recipe](afe-prototype.md) defines the
low-cost, socketed Stage A experiment on a stock Due: parts, connections,
unpowered checks, staged bring-up and measurements. It does not authorize
an AREF modification or custom PCB fabrication.

## The phases

In the order the measurement asks for them, one per issue on the
tracker, each closed by the check in its last column.

| phase | what is made | what proves it | lands in |
|---|---|---|---|
| **A1** reference and pin driver, drawn | the reference sheet and the pin-driver sheet under `hardware/afe-shield/`, the AREF path on the Due settled, the BOM | ngspice: DC operating points of the reference and the mid-rail buffer; the follower's AC response flat past 5 MHz; the pin driver settling within one conversion at 886 ksps; the loopback DAC swing inside the follower's input range | `hardware/afe-shield/` |
| **A2** reference and pin driver, built | Stage A on a Mega Proto Shield Rev3, wired from the sheets, on the board with the most residual | a meter: AREF at 3.000 V, VREF1V5 at half of it; `tools/gen_sweep.py` read within holds, against that board's shielded rows | `records/`, a capture note naming the shield revision |
| **C1** DAC output stage, drawn | the output sheet: reconstruction filter, the summer, the output pins; the charge-pump inverter as an option on the same sheet | ngspice: a DC sweep across the DAC's span for centring and endpoints on each rail choice; an AC sweep for the filter corner | `hardware/afe-shield/` |
| **C2** DAC output stage, built | Stage C on the proto shield, pump off then on | the sweep through the loopback, one arm per rail choice | `records/` |
| **B1** attenuation, ranges, offset, drawn | the input sheet with the divider, its compensation, the clamps, the range switch and the offset filter; the PWM channel on all three tracks | ngspice: DC transfer per range against the requirement's rows; AC flatness with the compensation capacitor and with it removed; the PWM ripple after two RC sections | `hardware/afe-shield/`, the firmware for the PWM |
| **B2** attenuation, built | Stage B on the proto shield | a meter across ±20 V on the DC rows; the sweep | `records/` |
| **P** the PCB | the board from the same schematic on the Mega outline | the sweep on the PCB against the proto build, same board | `hardware/afe-shield/` |

Stage A goes first because it is the stage the within-hold measurement
points at, Stage C before Stage B because the loopback bench needs an
output before it needs an attenuator, and the PCB last because the
proto build is what the PCB is compared with.

## Proposed Stage A PCB development pass

**Scope proposed for approval: Stage A only, not fabrication release.**
The development layout covers the reference, mid-rail, DAC-to-ADC drivers
and Due headers. Stages B and C are outside this pass. Layout development
can precede the prototype, but electrical validation, prototype measurements
and a physical Due fit check remain release gates. The current findings
and model limitations are in
[`hardware/afe-shield/REVIEW.md`](../hardware/afe-shield/REVIEW.md).

| step | work | acceptance gate |
|---|---|---|
| 1. Baseline | Preserve the existing design; rerun ERC, PCB DRC, net connectivity checks and manufacturer-model simulations | Reproducible reports distinguishing existing defects from regressions |
| 2. Electrical validation | Audit model pin mapping and measurement methods; investigate driver settling and reference-buffer loading; check the ADC acquisition window, not just its conversion interval; evaluate component/network changes | Explicit performance targets and relevant supply, tolerance and temperature cases; no silently relaxed requirements; review any op-amp/package change before committing to placement |
| 3. Mechanics and footprints | Compare header and mounting-hole geometry with the official Due design; check exact package pinouts, connector orientation, heights, clearances and library differences | Verified schematic-to-footprint mapping and dimensioned mechanical review; physical mating still required before release |
| 4. Populate and place | Synchronize Stage A footprints, place decoupling and feedback networks, plan ADC drive paths, add useful test points and reference/jumper markings | Placement review before routing; D1 and each physical IC identifiable on the board |
| 5. Route | Define manufacturing rules and stackup; route analog signals and supply returns; add ground copper and inspect coupling to digital headers; retain JP1 open by default | No unrouted required connections or unexplained ERC, DRC or schematic-parity errors; any intentional exceptions individually justified |
| 6. Review package | Inspect copper, mask, silkscreen, drills and 3D assembly; prepare BOM, assembly views, bring-up procedures and reference provenance | Engineering-review outputs clearly separated from release files; remaining risks and required bench measurements listed |

The manufacturer and stackup must be selected before fabrication rules are
final. A clean DRC or successful simulation does not qualify noise, crosstalk,
ADC acquisition accuracy, power sequencing or reference stability on hardware.
The full AFE scope, target changes, board ordering and fabrication submission
require separate owner decisions.

Deliverables are the KiCad project, reproducible checks, review findings,
assembly/BOM information and a bring-up checklist. Official specifications,
manuals, application guides and vendor models stay version-managed with
their source URLs, checksums and original license text.

## The review, done by the design

The requirement's table is a list of estimates. The design replaces
each with a derivation, a simulation or a reading, and the row moves to
the measured column when the last of those is in.

| requirement row | what the design checks it with | phase |
|---|---|---|
| input range, resolution referred to input | the divider's transfer, `Vb·(1−k) + k·Vin`, evaluated per range in the schematic's notes and swept in ngspice | B1 |
| input impedance | the divider, read off the sheet | B1 |
| resolution at the pin, effective bits, noise | the converter's; the AFE is judged by the cleanliness row alone | A2 |
| DC accuracy, drift | the reference's grade on the BOM, then a meter | A1, A2 |
| analog bandwidth, rise time | the divider's compensation and the pin driver's corner in an AC sweep, then a sine sweep through the loopback | B1, B2 |
| channel crosstalk | two channels driven in antiphase through the loopback | A2 |
| offset | the offset buffer's reach per range on the sheet, the PWM ripple in simulation, a meter on the built stage | B1, B2 |
| protection | the clamp current at ±20 V and at the transient rating in simulation; the series resistor's voltage rating on the BOM | B1 |
| output range, resolution, offset | the DC sweep of the summer at the reference the design sets | C1 |
| output impedance and coupling | read off the sheet | C1 |
| generator rate, drive, frequency accuracy | `docs/awg.md`'s figures, unchanged by the shield | C2 |
| cleanliness | the sweep, every built phase | A2, C2, B2 |

## Tooling

**KiCad 10.x is the default and required CAD major version across all teams
and benches**, with matching 10.x symbol and footprint libraries. Do not use
KiCad 9 or older for active edits or validation. The AFE check scripts enforce
this major version and print the exact CLI version used; set `KICAD_CLI` when
an older installation is also on PATH.

The checked macOS project uses KiCad 10.0.6 and ngspice 47. The
manufacturer models and offline KiCad manuals are indexed in
[`docs/reference`](reference/README.md); the reproducible design review
is in [`hardware/afe-shield/REVIEW.md`](../hardware/afe-shield/REVIEW.md).
The A1 performance checks remain open. KiCad 9.0.8/ngspice 45 identify the
original Debian design provenance, not the active CAD baseline.

| tool | version and source | used for |
|---|---|---|
| KiCad | 10.x required; validated with 10.0.6 and its matching libraries | the schematic, the PCB, the BOM |
| ngspice | 47 validated for the batch runner; record the bundled engine version separately when using the GUI | the checks in the phase table |
| the `Arduino_Mega` project template | ships with KiCad | the root sheet, board edge, headers and mounting holes of a Mega-format shield. On the Due the positions the template labels A12 to A15 carry DAC0, DAC1, CANRX0 and CANTX0, and the AREF pin is pin 8 of the PWM-high row |
| the Due's V03 reference design | `docs/datasheets/arduino/arduino-Due-Reference-design.zip`, EAGLE 6.3, published by Arduino under CC BY-SA | what is between the AREF header pin and ADVREF: BR1 and JR1, read from the netlist rather than from a meter |
| the Mega Proto Shield Rev3 reference design | `docs/datasheets/arduino/arduino-mega-proto-Shield-reference-design.zip`, EAGLE 6.4 | the proto build's pad rows and the SOIC-14 footprint; importable into KiCad if the proto layout is ever drawn |
| vendor SPICE models | Microchip and Texas Instruments downloads, kept beside the sheets that use them with their licence text | the op-amps and the reference in simulation |

Symbols the library carries under the names the requirement uses:
`LM4040DBZ-3`, `BAT54S`, `TS3A5017RSV`, `TLV2372`, `TPS6040x`. The
MCP6024 has no symbol of its own and the MCP6004 is pin-identical in
the same SOIC-14, so the sheet places that symbol with the MCP6024 as
its value; the model is the MCP6024's.

## Decisions the plan carries open

| decision | the options | who, and when |
|---|---|---|
| drive AREF, or measure the scale | drive it: JR1 removed and BR1 bridged 1 to C on the Due, the shield's 3.0 V buffer on AREF, the reference is the scale and the three benches' boards stop being identical. Measure it: the Due untouched, the same buffer on a spare ADC pin, the scale read as two points per board. The shield carries both: the AREF link is a solder jumper, open by default, so one shield serves a stock Due and a modified one | the owner, before A2 is wired |
| ranges | one fixed ±20 V range, or ±20, ±5 and about ±3 V with the switched shunt and a bottom end that follows the range | the owner, before B1 |
| the bipolar output | the single rail, unipolar, or the charge-pump inverter on the output stage alone | the owner, after C2's two arms |

## Bookkeeping

The tracker holds one issue per phase, each naming this plan and closed
by its own proof column. A bench's standing page carries which phase it
is on. A capture taken through the shield names the shield revision in
its note, and a record row taken through it carries the phase, the way
the shield-on rows already do. Findings go to `docs/afe.md`, the
reasoning to the commit, and nothing to the issue that is not being
argued.
