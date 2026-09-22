# Low-cost Stage A prototype: preparation, assembly and validation

**Build recipe P1: experimental, socketed, stock Due, JP1 open.**
This is a self-contained guide for a hand-built Stage A on an existing
Mega Proto Shield V3. It covers shopping, connections, safe first power,
multimeter checks and the later oscilloscope session. It is not a release
of a finished oscilloscope front end or of the KiCad PCB.

The circuit baseline is commit
`c78201b9bcafd529f013002c875e084f28dd1875`. Component references and values
below describe that circuit, with the explicitly declared prototype
package choice for U1. This is a fixed build recipe, not a live team-status
page. Record any departure on your build sheet; do not silently combine
it with a later schematic revision.

## Start here

1. Disconnect all Due power, USB cables and external wires. Photograph the
   existing stacked assembly, then remove the shield and photograph both
   sides. Preserve a record of existing loopback wires before changing them.
2. Inventory the parts below and dry-fit the socket, IC and reference
   carrier. Do not buy another shield or a custom PCB.
3. Mark the proposed placement and every existing copper connection on a
   photograph. Complete the unpowered checks before soldering the circuit.
4. Assemble and test the shield **off the Due first**. Borrow a regulated,
   adjustable current-limited supply for first power. USB power alone does
   not provide the controlled 3.3 V / 20 mA test specified here.
5. After the standalone DC checks, remove the external supply completely,
   configure the stock-Due connections and repeat DC checks using USB power.
   Reserve an oscilloscope session for dynamic validation.

**You can do preparation and unpowered assembly with the tools already
available. Stop before first power if the specified supply is unavailable.**
Borrow equipment rather than buying a bench supply or scope solely for
this experiment. A USB current display or USB short-circuit protection
is not a replacement for the first-power current limit.

## Fixed choices and remaining questions

| Review ID | Meaning for this build |
|---|---|
| AFE-01 | Experimental Stage A only; known performance limitations are accepted as questions to measure |
| AFE-02 | Reuse the existing Mega Proto Shield V3 and Due; inspect the actual boards, not just their model names |
| AFE-03 | Multimeter, USB power and soldering tools are available; scope access is intermittent |
| AFE-04 | U1 is socketed; use the PDIP variant below rather than a premium SOIC test socket |
| AFE-05 | No Due modifications. Leave JR1/BR1 untouched and shield JP1 open |
| AFE-06 | Electrical purchasing specification is below; check seller stock, exact markings, mechanical fit and any substitutions before ordering |
| AFE-07 | Use the complete connection tables below; mark actual pad positions on photographs before soldering |
| AFE-08 | First-power procedure and stop conditions are below; equipment and physical inspection still gate execution |
| AFE-09 | Amplifier/network redesign is deferred until measurement; no relaxed performance requirement is implied |
| AFE-10 | Ability to drive the Due's reference load remains unqualified and is outside this build |
| AFE-11 | ADC timing and channel-sequence effects must be recorded and measured |
| AFE-12 | Noise, settling and channel interaction remain hardware tests, not inferred passes |
| AFE-13 | Custom PCB mechanics/routing/fabrication are outside this recipe |

Budget rule: prefer established, widely distributed commodity parts.
Reuse wire, headers and tools already owned. Buy single ICs and cut-tape
passives, not reels. Spares are optional; a few spare small passives are
usually more useful than a second board. Do not buy candidate amplifiers,
evaluation boards, an attenuator or a charge pump for this Stage A build.
Availability and prices are not guaranteed by the part numbers below.

## What the circuit does

| Block | Function |
|---|---|
| R1, D1, C1 | Produce a nominal 3.0 V shunt reference from 3.3 V |
| R2, C2, U1A | Filter and buffer that reference |
| R3, R4, C3, U1B | Produce a buffered nominal 1.5 V midpoint |
| U1C, R5, C5 | Buffer DAC0 into ADC input A0 |
| U1D, R6, C6 | Buffer DAC1 into ADC input A1 |
| R7, C7 | Connect the 1.5 V midpoint to A2 |
| R8-R16 | Hold unused A3-A11 inputs to ground through resistors |
| C4 | Local IC supply decoupling |
| JP1 | Optional connection from buffered 3.0 V to AREF; **not fitted/closed here** |

U1A, U1B, U1C and U1D are the four amplifiers in one IC; U1E is its
shared supply symbol, not a fifth amplifier.

With JP1 open, the reference still works and can be measured. It does
**not** set the Due's ADC or DAC reference. The stock DAC window is roughly
0.55-2.75 V, not the 0.50-2.50 V window associated with a 3.0 V ADVREF.
A2 receives approximately 1.5 V, not 3.0 V. Reading A2 demonstrates the
measurement path; it does not by itself constitute full ADC calibration.
This circuit provides no external-input attenuation or protection:
**no unknown signals, negative voltages, 5 V logic or mains connections.**

## Parts for one prototype

These are prototype selections, not a change to the KiCad PCB BOM.
All listed resistors and capacitors are 0805 surface-mount parts. Check
that your chosen isolated pads can support them; use inexpensive small
carrier pads if necessary. Do not stretch unsupported leads across the
board or build the signal path with long solderless-breadboard jumpers.

| Reference | Fit quantity | Exact example part | Required specification |
|---|---:|---|---|
| U1 | 1 | Microchip MCP6024-E/P | Quad op-amp, PDIP-14, 7.62 mm row spacing; prototype-only package choice |
| U1 socket | 1 | ASSMANN A 14-LC-TT | DIP-14, 2.54 mm pitch, 7.62 mm row spacing; ordinary low-profile socket |
| D1 | 1 | TI LM4040AIM3-3.0/NOPB | 3.0 V, A grade, SOT-23; keep this exact reference/grade |
| R1 | 1 | Yageo RC0805FR-0756RL | 56 ohm, 1%, 0.125 W |
| R2, R8-R16 | 10 | Yageo RC0805FR-0710KL | 10 kohm, 1%, 0.125 W |
| R3, R4 | 2 | Yageo RT0805BRD0710KL | 10 kohm, 0.1%, 25 ppm/C, 0.125 W |
| R5, R6, R7 | 3 | Yageo RC0805FR-0768RL | 68 ohm, 1%, 0.125 W |
| C1 | 1 | Murata GRM21BR71A106KE51L | 10 uF, 10 V, X7R, 10% |
| C2, C3 | 2 | Murata GRM21BR71H105KA12L | 1 uF, 50 V, X7R, 10% |
| C4 | 1 | Murata GRM21BR71H104KA01L | 100 nF, 50 V, X7R, 10% |
| C5, C6, C7 | 3 | Yageo CC0805JRNPO9BN471 | 470 pF, 50 V, C0G/NP0, 5% |
| JP1 | 0 closed links | No component purchase | Leave an isolated, labelled open connection; no bridge to AREF |

There are **16 resistors, 7 capacitors, one reference and one quad IC**.
Do not buy five MCP6024s because the schematic draws five units.
Use genuine parts from a traceable distributor; apparent savings on
unidentified reference/op-amp modules can invalidate the experiment.

| Other item | Low-cost choice / quantity |
|---|---|
| Proto shield and stacking headers | Reuse the existing assembly; replace only damaged or mechanically unsuitable pieces |
| D1 carrier | One plain SOT-23-3 breakout if needed; no regulator/reference module with extra circuitry. Check its copper mapping before use |
| Passive mounting | Existing isolated pads if suitable; otherwise small inexpensive 0805 carriers/copper islands, sufficient for 23 passives |
| Wire | Short insulated hookup wire; distinguish 3.3 V, ground and signals by colour/labels |
| Disconnectable connections | Short removable links for power, DAC0/1 and A0/1/2 during testing; not switches operated while powered |
| Test access | Small labelled wire loops/pads for ground, supply, D1 cathode, VREF3V0, VREF1V5 and A0/A1/A2 |
| Mechanical support | Reuse suitable insulating spacers; choose height from the actual underside clearance, not a guessed dimension |
| First-power supply / scope | Borrow for the relevant test session; not part of the default shopping list |

Equivalent resistor/capacitor brands are acceptable **after** matching
value, tolerance, dielectric, voltage/power rating and mounting size.
Do not replace C0G with X7R, or the 0.1% divider with ordinary 1% parts.
The 50 V ratings above identify commonplace parts; this circuit does not
need a 50 V operating rail. X7R capacitance changes with DC bias: these
nominal selections do not establish worst-case filtering or startup.
Record substitutions and their datasheets. Do not change U1's amplifier
type as a purchasing substitution.

The active KiCad schematic specifies **MCP6024-E/SL (SOIC-14)**. The
socketed **MCP6024-E/P (PDIP-14)** has the same functional pin numbering,
but does not fit the SOIC footprint. Mount its socket in a suitable free
through-hole area. Package, socket and wiring parasitics differ from the
SPICE model and from a future PCB; successful DC operation does not erase
those differences. Never force the SOIC device into a DIP socket.

## Inspect and plan the physical build

The official Mega Proto Shield V3 has 5 V and ground distribution, plus
an SOIC breakout whose individual pins are brought to pads. That breakout
does not automatically supply an op-amp. Create a separate **3.3 V** AFE
feed from the Due's labelled 3.3 V header; do not use the shield's 5 V bus.
Clones and existing hand wiring must be checked with continuity measurements.

| Preparation | Record / acceptance |
|---|---|
| Existing wires | Photograph and label both ends; identify direct DAC0-A0 and DAC1-A1 loopbacks so they are not left in parallel with buffer outputs |
| Socket placement | Pin-1 notch marked; correct hole pitch and row spacing; room for decoupling and local feedback |
| Header labels | Use **Due signal names**, not Mega A12-A15 labels or connector reference numbers copied from another drawing |
| Ground routing | Compact local return joining a verified Due GND; signal wires have nearby returns; avoid shared long loops with unrelated loads |
| C4 | At the socket supply connections, with a short loop from pin 4 through C4 to pin 11 |
| Feedback | Short local connections 1-2, 6-7, 8-9 and 13-14 |
| ADC RC networks | C5/C6/C7 and the ADC side of R5/R6/R7 close to the appropriate analog header connections |
| Reference placement | D1/filter/divider away from clock and USB wiring; no long reference test leads left attached |
| Underside | Trimmed joints/leads cannot touch Due components, USB shells or other copper; inspect when mated unpowered |

There is deliberately no invented hole-coordinate drawing for a board we
have not physically inspected. Annotate top and bottom photographs with
the component references and connections below. Treat those photographs
as the assembly drawing and retain them with the measurements. A layer
of tape is not a substitute for adequate mechanical clearance.

## Complete connection schedule

All pin numbers here are **component pins**, not a carrier board's labels.
For U1, viewed from the top with the notch at the top, pin 1 is upper left;
pins 1-7 run down the left and 8-14 run up the right. Underside views are
mirrored. Check socket notch and IC notch independently.

### U1: all 14 pins

| U1 pin | Function | Final stock-Due configuration |
|---:|---|---|
| 1 | A output | VREF3V0; join pin 2 and R3 upper end; no AREF connection |
| 2 | A inverting input | Short local link to pin 1 |
| 3 | A non-inverting input | R2/C2 filtered-reference junction |
| 4 | Positive supply | AFE +3V3; C4 to GND |
| 5 | B non-inverting input | R3/R4/C3 midpoint |
| 6 | B inverting input | Short local link to pin 7 |
| 7 | B output | VREF1V5; join pin 6 and R7 input |
| 8 | C output | Join pin 9 and R5 input |
| 9 | C inverting input | Short local link to pin 8 |
| 10 | C non-inverting input | Due DAC0 |
| 11 | Negative supply | GND, not a negative-voltage rail |
| 12 | D non-inverting input | Due DAC1 |
| 13 | D inverting input | Short local link to pin 14 |
| 14 | D output | Join pin 13 and R6 input |

### Reference, filters and unused-input resistors

The resistors and specified ceramic capacitors are nonpolar. The D1
reference is polar: **SOT-23 pin 1 = cathode, pin 2 = anode/GND,
pin 3 left floating**. Do not apply a TO-92 pinout to this part.

| Component | End 1 / node | End 2 / node |
|---|---|---|
| R1, 56 ohm | AFE +3V3 | D1 cathode |
| C1, 10 uF | D1 cathode | GND |
| R2, 10 kohm | D1 cathode | U1 pin 3 |
| C2, 1 uF | U1 pin 3 | GND |
| R3, 10 kohm, 0.1% | U1 pin 1 | U1 pin 5 |
| R4, 10 kohm, 0.1% | U1 pin 5 | GND |
| C3, 1 uF | U1 pin 5 | GND |
| C4, 100 nF | U1 pin 4 | U1 pin 11 / GND |
| R5, 68 ohm | U1 pin 8 | A0 node |
| C5, 470 pF | A0 node | GND |
| R6, 68 ohm | U1 pin 14 | A1 node |
| C6, 470 pF | A1 node | GND |
| R7, 68 ohm | U1 pin 7 | A2 node |
| C7, 470 pF | A2 node | GND |
| R8 / R9 / R10 | Due A3 / A4 / A5 respectively | Each to GND |
| R11 / R12 / R13 | Due A6 / A7 / A8 respectively | Each to GND |
| R14 / R15 / R16 | Due A9 / A10 / A11 respectively | Each to GND |

R8-R16 are nine separate 10 kohm resistors, not shorts. Reserve these pins
for this experiment: do not attach another shield circuit or configure
them as outputs while using this wiring.

### Due interface and temporary test configuration

| Connection | Standalone shield test | Final stacked test |
|---|---|---|
| Shield mechanically | Removed from Due | Mated only while all power is disconnected |
| AFE +3V3 | Borrowed supply, regulated 3.30 V with 20 mA limit | Due 3.3 V header only; external supply physically removed |
| GND | Supply negative and multimeter common | Due GND and multimeter common |
| U1 pins 10 and 12 | Temporary links to VREF1V5; keeps both followers at a defined input | Remove both temporary links; connect DAC0 and DAC1 respectively |
| A0/A1/A2 filter nodes | No connection to Due; retain their filter capacitors | Connect to Due A0/A1/A2 respectively |
| A3-A11 | Resistors installed on shield, no Due attached | Each connected to its assigned 10 kohm pull-down |
| JP1 / AREF | Open; reference output isolated from AREF | Still open; no wire to AREF |

Never power an unpowered Due through an analog signal or the 3.3 V header.
Never leave the standalone supply connected when stacking or USB powering.
Never operate links or insert/remove the IC while powered.

## Assembly and unpowered gate

| Step | Action | Check before proceeding |
|---:|---|---|
| 1 | Measure loose resistors; separate 0.1% divider parts from other 10 kohm parts | Values/labels match the BOM; a basic meter cannot certify 0.1% accuracy |
| 2 | Solder the empty socket and supply/ground wiring | Every contact goes only to its intended net; no 5 V connection |
| 3 | Fit D1 and its reference/filter/divider passives | Identify D1 pins from package orientation, not a guessed adapter numbering |
| 4 | Fit feedback links, C4, driver RC networks and unused-input resistors | Check the connection schedule one row at a time |
| 5 | Fit labelled test pads and standalone input links | No floating driver input; no Due or AREF connection |
| 6 | Inspect with magnification; remove solder debris and clean flux as appropriate | No bridges, cracked MLCCs or unsupported joints |
| 7 | Measure continuity with power disconnected and U1 still out | Intended wire links read near lead resistance; no unintended adjacent-pin shorts |
| 8 | Check power-to-ground and 5 V isolation | Investigate any sustained near-short; capacitor charging and semiconductor paths mean not every reading is infinite |
| 9 | Dry-fit shield on the unpowered Due, inspect underside, then remove it | No contacts/strain; no shifted header row |

A stable supply-to-ground reading below 10 ohm is a **stop/investigate**
condition for this unpowered assembly, not an expected load. A reading
above that does not prove correct wiring. Check both meter polarities
and allow capacitors to charge; do not use a resistance/continuity range
on a powered board. Return the red meter lead to the voltage jack after
any current measurement; never put a meter in current mode across a rail.

## First power: standalone, no Due connected

These are **coarse room-temperature bring-up limits**, not a precision
specification or a stability certificate. They apply only to the unloaded
shield in the standalone configuration above. Do not apply the 20 mA
limit to powering the whole Due.

1. Leave U1 out. With the supply output off and disconnected, set 3.30 V
   and a 20 mA limit using that supply's manual. Verify output voltage
   independently, turn it off, then connect shield ground and supply.
2. Apply power. If current limiting persists beyond one second, voltage
   fails to rise, or anything heats/smells abnormal, turn off immediately.
   A brief capacitive charging event is not a reason to raise the limit.
3. Measure the supply and D1 cathode. Expected reference-only current is
   about 5.4 mA: (3.30 - 3.00) / 56. With no U1 fitted, do not expect a
   functioning buffered 3.0 V or 1.5 V output.
4. Turn off, disconnect and verify the rail has discharged. Insert U1,
   checking its notch, every leg and the temporary links to pins 10/12.
5. Reapply power with the same limit. Wait one second, then fill in every
   row below; repeat after 30 seconds and five minutes. Stop on any failed
   check, unstable display, unexpected current increase or abnormal heat.

| Measurement, black lead at GND | Coarse check after U1 is fitted |
|---|---|
| U1 pin 4 supply | 3.25-3.35 V at the IC |
| Total standalone supply current | Investigate outside 6-15 mA; about 10 mA is a nominal expectation, not a guaranteed specification |
| D1 cathode | 2.97-3.03 V |
| U1 pin 3, filtered reference | Within 5 mV of D1 cathode after settling, if the meter can resolve this comparison |
| U1 pin 1, VREF3V0 | 2.97-3.03 V; within 5 mV of pin 3, subject to meter uncertainty |
| U1 pin 5, divider midpoint | 1.47-1.53 V |
| U1 pin 7, VREF1V5 | 1.47-1.53 V; within 5 mV of pin 5, subject to meter uncertainty |
| U1 pins 8 and 14 | Within 5 mV of VREF1V5 with their inputs temporarily tied there |
| A0/A1/A2 filter nodes | Approximately VREF1V5; within 5 mV of their respective driver outputs at DC |

If the meter's resolution/accuracy cannot support a 5 mV comparison,
record **not resolved**, not pass or fail. The broad voltage checks can
still expose gross wiring faults. At 3.30 V, R1 normally dissipates only
about 1.6 mW and D1 about 16 mW; these are calculated nominal values,
not measured temperatures or permission to ignore a warm component.

The reference need not display exactly 3.000 V. Its A-grade nominal
initial accuracy is 0.1% at the specified datasheet conditions, and
meter uncertainty, temperature, bias current and amplifier offset add
to the observed error. A cheap meter can establish plausible DC operation
without certifying millivolt-level absolute accuracy.

**A steady multimeter reading cannot rule out oscillation.** Passing
these checks permits the controlled low-voltage experiment below, not a
claim that startup, noise or high-speed behaviour is qualified.

## USB-powered stock-Due test

1. Power everything off. Remove the standalone supply and its leads.
   Remove both temporary VREF1V5-to-driver-input links. Remove any old
   direct DAC0-A0 / DAC1-A1 jumpers; otherwise the buffers are bypassed or
   their outputs can contend with the DACs.
2. Check the final interface table, JP1 open, polarity, clearance and no
   accidental 5 V feed. Connect the AFE power to the labelled Due 3.3 V
   header. Mate the boards with no USB/power attached.
3. Use the existing known-working firmware; do not flash a new image just
   for assembly. Record firmware/board identity and configure only known
   low-voltage DAC loopback activity. Confirm A3-A11 are not outputs or
   connected to another circuit.
4. Apply the usual USB power. Repeat the rail/reference/midpoint readings.
   The nominal Due rail is 3.3 V; if it is outside 3.135-3.465 V, stop and
   investigate rather than extending this recipe's operating conditions.
   Those bounds are a conservative experiment condition, not a Due rating.
5. Start with static DAC levels. Measure DAC0 and A0, then DAC1 and A1;
   use the measured DAC voltage, not an assumed volts-per-code scale.
   Check low, middle and high levels within the stock DAC window.
6. A2 should remain near 1.5 V. Capture A2 with the existing acquisition
   tool and compare the mean code with the meter reading. Record channel
   list, rate and reference assumption; do not assume A2 should be half
   scale, because 1.5 V is not half of the stock approximately 3.3 V scale.

For a coarse DC tracking check, investigate a repeatable input/output
difference above 10 mV **after accounting for meter uncertainty and source
drift**. This is a fault screen, not the final ADC error budget. Repeat
measurements in input-output-input order to expose drift. Do not infer
accurate gain or offset from two sequential readings near the meter's
resolution limit.

Start with single-channel, slow/static measurements before the existing
multi-channel/high-rate sweep. Host tool commands depend on the connected
board, firmware and ports; use the established bench configuration rather
than copying guessed serial-port or DAC-setting commands from a recipe.
The project includes `tools/gen_sweep.py`; read its `--help` and select the
actual bench configuration before a capture. Do not run it merely to test
whether hardware is safe to power.

## Make the borrowed oscilloscope session count

Bring the circuit, build photographs, DC results and a saved bare-Due
baseline. Use a compensated x10 probe with a short ground spring where
possible. Connect scope ground only to circuit GND; account for USB/earth
ground paths. Never defeat scope protective earth. Record probe loading
and bandwidth; a long ground clip can manufacture ringing.

| Priority | Measure | What to record / decide |
|---:|---|---|
| 1 | 3.3 V at U1, VREF3V0 and VREF1V5 at idle and during DAC/ADC activity | Oscillation, excursions and repeatable ripple; investigate sustained oscillation before further tests |
| 2 | Power-up and power-down reference/rail traces | Overshoot, settling, rail collapse or undesired interaction; JP1 stays open |
| 3 | DAC0 versus A0, then DAC1 versus A1 | Step amplitude, rise/fall shape, overshoot, ringing and settling; record input edge as well as output |
| 4 | One channel active, other at DC; then both active | Crosstalk and reference/supply movement under load |
| 5 | Matched before/after loopback sweeps and quiet-input captures | Whether Stage A improves or worsens the actual measurement problem |

The Due's DAC is not an ideal fast step or a calibrated 5 MHz generator.
Its loopback can evaluate the intended application but cannot alone prove
the amplifier's 5 MHz flatness or ideal 2 V-step response. Those tests
need a suitable source, controlled amplitudes/offset and adequate scope
bandwidth, agreed for that session. Do not attach an arbitrary generator
to the unprotected ADC path. Likewise, many ordinary scopes cannot resolve
sub-millivolt settling on a 2 V step; record the detection limit instead
of claiming 12-bit settling from a visually flat trace.

No scope access means these rows remain **not measured**. Do not redesign
the amplifier solely because a slow meter looks good, or because an
uncontrolled long-wire build rings. Change one construction feature at a
time and repeat the same test before attributing a result to the IC.

## Known baseline and interpretation

The baseline was checked using KiCad 10.0.6 and ngspice 47. These are
simulation findings, not measurements of this socketed assembly:

| Check | Baseline evidence / limit |
|---|---|
| Schematic | Zero ERC errors; 61 isolated unused-header-label warnings; critical nets and selected BOM fields checked |
| DC reference | VREF3V0 about 2.9984 V, VREF1V5 about 1.4996 V |
| Baseline driver | About -5.86 dB before R5 at 5.012 MHz; full path about -8.90 dB |
| Baseline 2 V step | About 1.218 us to stay within 0.732 mV of the final plateau, exceeding the 1.129 us single-channel target interval |
| Open-JP1 loaded screen | About 1.232 us settling; selected supply/temperature/RC cases did not establish the full-step deadline |
| Fitted ADC sampling load | Small charge-recovery error in the assumed 769 ns case; not a transistor-level ADC or firmware-sequence qualification |
| Assumed severe wire inductance | A 1 uH stress case did not establish a quiet final plateau; actual shield inductance is unknown |
| Closed-link AREF stress | Unqualified; not a reason to close JP1 in this build |
| PCB | Mechanical template only; no Stage A placement/routing to fabricate |

AFE-09 remains a measurement-led decision. A useful DC prototype can
still fail the high-speed goals. A bad hand-wired result may be caused
by construction, probes, source or circuit. Record failures as evidence;
do not silently lower the requirements or declare all gates passed.

For reproducible board-free checks, from the repository root:

```sh
python3 hardware/afe-shield/check.py
hardware/afe-shield/sim/run.sh --strict
python3 hardware/afe-shield/sim/screen.py --model mcp6024
python3 -m unittest discover -s hardware/afe-shield/sim -p test_screen.py -v
```

Use KiCad **10.x**, with matching libraries, and record its exact version.
The strict baseline returns **2** for the known performance findings;
that is not a successful electrical release. The separate screen returning
zero means its cases completed, not that every diagnostic passed. No
simulation or command tests the physical socket or solder joints.

## Build and measurement worksheet

Copy this section into your measurement notes; keep photographs and raw
captures beside it. Record actual readings, not ticks copied from this guide.

| Identification | Fill in |
|---|---|
| Recipe / circuit | P1 / c78201b; list any later changes explicitly |
| Due identity / board revision / firmware | |
| Shield identification / photographs | |
| U1 and D1 markings / supplier | |
| Passive substitutions / socket / carrier | |
| Meter model, range, resolution, accuracy specification | |
| First-power supply / measured setting / current limit | |
| Scope / probe / bandwidth / ground connection, if used | |
| Ambient conditions / warm-up duration | |
| JP1 open / Due unchanged / temporary links removed before stacking | |

| Measurement | Standalone 1 s | Standalone 30 s | Standalone 5 min | Stacked idle | Stacked active |
|---|---|---|---|---|---|
| Supply at U1 pin 4 | | | | | |
| Shield current (standalone only) | | | | n/a | n/a |
| D1 cathode | | | | | |
| Filtered reference, U1 pin 3 | | | | | |
| VREF3V0, U1 pin 1 | | | | | |
| Divider midpoint, U1 pin 5 | | | | | |
| VREF1V5, U1 pin 7 | | | | | |
| A0 / A1 / A2 | | | | | |

| Test result | Fill in: pass, fail, not resolved or not measured; attach evidence |
|---|---|
| Unpowered connection/short/fit checks | |
| Coarse standalone DC checks | |
| Coarse stacked DC checks / DAC tracking | |
| A2 capture conditions and mean/spread | |
| Scope rail/reference/startup checks | |
| Step response / channel interaction / matched sweep | |
| Stop conditions encountered and one-at-a-time rework | |
| Remaining limitations and AFE-09 decision | |

## Retained source material

The instructions above do not require following these links during a
normal build. They are retained primary-source evidence for pinouts,
ratings and mechanical review, not a substitute for the connection tables.

| Source, stored in this repository | What was checked |
|---|---|
| [Microchip MCP6021/2/3/4 DS20001685F](datasheets/microchip/MCP6021-DS20001685F.pdf), page 1 and ordering information | Quad pinout and PDIP/SOIC package choices |
| [TI LM4040-N](datasheets/ti/LM4040-N.pdf), sections 4 and 5 | SOT-23 polarity, unused pin, reference grade and limits |
| [Arduino Mega Proto Shield V3 schematic](datasheets/arduino/arduino-mega-proto-Shield-reference-design.pdf) and [original CAD archive](datasheets/arduino/arduino-mega-proto-Shield-reference-design.zip) | Header pass-through, 5 V/GND distribution and separate SOIC breakout |
| [Due pinout](datasheets/arduino/Arduino-Due-full-pinout.pdf) | Due signal identification rather than Mega analog labels |
| [ASSMANN socket drawing](datasheets/assmann/Axx-LC-TT.pdf) | 14 contacts, 2.54 mm pitch, 7.62 mm row spacing |
| [56 ohm](datasheets/yageo/RC0805FR-0756RL.pdf), [10 kohm 1%](datasheets/yageo/RC0805FR-0710KL.pdf), [10 kohm 0.1%](datasheets/yageo/RT0805BRD0710KL.pdf), [68 ohm](datasheets/yageo/RC0805FR-0768RL.pdf) Yageo sheets | Values, tolerances, sizes and ratings |
| Murata [10 uF](datasheets/murata/GRM21BR71A106KE51.pdf), [1 uF](datasheets/murata/GRM21BR71H105KA12.pdf), [100 nF](datasheets/murata/GRM21BR71H104KA01.pdf), and Yageo [470 pF](datasheets/yageo/CC0805JRNPO9BN471.pdf) sheets | Nominal capacitance, voltage rating, dielectric and package |

Source URLs, retrieval dates and original-file hashes are retained in
[the reference manifest](reference/sources.json). Vendor files are not
edited. These references do not prove present distributor stock or
performance of an assembled prototype.
