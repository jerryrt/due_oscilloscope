# Low-cost Stage A prototype: preparation, assembly and validation

**Candidate recipe P2: simulate first, socketed, stock Due, JP101 open.**
This guide describes the proposed Stage A parts, connections and later
bring-up on the existing carrier. Finish A1 in SPICE using the
[AFE plan](afe-plan.md) before assembling this circuit. The current
[corrected carrier KiCad project](../hardware/mega-proto-carrier/README.md)
is the physical baseline; the old `hardware/afe-shield/` project was
removed. Create the working assembly under
[hardware/afe-proto](../hardware/afe-proto/README.md).

Use the [Due V03 KiCad PCB](../hardware/reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb)
for the Due interface. The owner's DUE R3 board has a reported six-pin
IC2, separate inductor and AMS1117 regulator; the supply layout supports
V03, with AMS1117 substituted for source IC4's NCP1117. The
[observation record](../hardware/reference/arduino-due/hardware-observations.json)
does not establish full-board continuity. V02g is an alternate archived
reference, not the default for this assembly.

The candidate circuit comes from historical commit
`c78201b9bcafd529f013002c875e084f28dd1875`, with a socketed PDIP package.
Its known bandwidth/settling findings remain unresolved. A1 may change
the amplifier or network; update this recipe and its limits to match the
passed schematic before buying or fitting the final circuit.

Stage A uses **100-series references** to avoid the carrier's existing
R1–R3 and D1/D2. Historical U1/D1/R1–R16/C1–C7/JP1 correspond to
U101/D101/R101–R116/C101–C107/JP101 here. Pin numbers and candidate values
are unchanged. Carrier grid/land IDs identify locations, not AFE IC pins.

## Start here

0. Complete the [Stage A simulation gate](../hardware/afe-proto/sim/README.md).
   Freeze the passed schematic/BOM, model versions and numerical report.
   Plan the assembly in the working KiCad copy using real pad IDs, existing
   copper and marked added wires. This recipe is pending that handoff.
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

**Inspection and layout planning can proceed now; assembly follows the
SPICE gate. Stop before first power if the specified supply is unavailable.**
Borrow equipment rather than buying a bench supply or scope solely for
this experiment. A USB current display or USB short-circuit protection
is not a replacement for the first-power current limit.

## Fixed choices and remaining questions

| Review ID | Meaning for this build |
|---|---|
| AFE-01 | Stage A candidate only; resolve required simulation failures before assembly, then measure hardware limitations |
| AFE-02 | Reuse the existing Mega Proto Shield V3 and Due; inspect the actual boards, not just their model names |
| AFE-03 | Multimeter, USB power and soldering tools are available; scope access is intermittent |
| AFE-04 | U101 is socketed; use the PDIP variant below rather than a premium SOIC test socket |
| AFE-05 | No Due modifications. Leave JR1/BR1 untouched and shield JP101 open |
| AFE-06 | Electrical purchasing specification is below; check seller stock, exact markings, mechanical fit and any substitutions before ordering |
| AFE-07 | Use the passed working KiCad assembly and connection tables; record grid/header pad IDs and added wires before soldering |
| AFE-08 | First-power procedure and stop conditions are below; equipment and physical inspection still gate execution |
| AFE-09 | Evaluate amplifier/network changes during A1 if required tests fail; update the schematic, models, BOM and recipe together |
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
| R101, D101, C101 | Produce a nominal 3.0 V shunt reference from 3.3 V |
| R102, C102, U101A | Filter and buffer that reference |
| R103, R104, C103, U101B | Produce a buffered nominal 1.5 V midpoint |
| U101C, R105, C105 | Buffer DAC0 into ADC input A0 |
| U101D, R106, C106 | Buffer DAC1 into ADC input A1 |
| R107, C107 | Connect the 1.5 V midpoint to A2 |
| R108-R116 | Hold unused A3-A11 inputs to ground through resistors |
| C104 | Local IC supply decoupling |
| JP101 | Optional connection from buffered 3.0 V to AREF; **not fitted/closed here** |

U101A, U101B, U101C and U101D are the four amplifiers in one IC; U101E is its
shared supply symbol, not a fifth amplifier.

With JP101 open, the reference still works and can be measured. It does
**not** set the Due's ADC or DAC reference. The stock DAC window is roughly
0.55-2.75 V, not the 0.50-2.50 V window associated with a 3.0 V ADVREF.
A2 receives approximately 1.5 V, not 3.0 V. Reading A2 demonstrates the
measurement path; it does not by itself constitute full ADC calibration.
This circuit provides no external-input attenuation or protection:
**no unknown signals, negative voltages, 5 V logic or mains connections.**

## Parts for one prototype

These are candidate prototype selections. The passed working KiCad schematic
and BOM must agree with them before assembly; revise both if A1 changes a part.
All listed resistors and capacitors are 0805 surface-mount parts. Check
that your chosen isolated pads can support them; use inexpensive small
carrier pads if necessary. Do not stretch unsupported leads across the
board or build the signal path with long solderless-breadboard jumpers.

| Reference | Fit quantity | Exact example part | Required specification |
|---|---:|---|---|
| U101 | 1 | Microchip MCP6024-E/P | Quad op-amp, PDIP-14, 7.62 mm row spacing; prototype-only package choice |
| U101 socket | 1 | ASSMANN A 14-LC-TT | DIP-14, 2.54 mm pitch, 7.62 mm row spacing; ordinary low-profile socket |
| D101 | 1 | TI LM4040AIM3-3.0/NOPB | 3.0 V, A grade, SOT-23; keep this exact reference/grade |
| R101 | 1 | Yageo RC0805FR-0756RL | 56 ohm, 1%, 0.125 W |
| R102, R108-R116 | 10 | Yageo RC0805FR-0710KL | 10 kohm, 1%, 0.125 W |
| R103, R104 | 2 | Yageo RT0805BRD0710KL | 10 kohm, 0.1%, 25 ppm/C, 0.125 W |
| R105, R106, R107 | 3 | Yageo RC0805FR-0768RL | 68 ohm, 1%, 0.125 W |
| C101 | 1 | Murata GRM21BR71A106KE51L | 10 uF, 10 V, X7R, 10% |
| C102, C103 | 2 | Murata GRM21BR71H105KA12L | 1 uF, 50 V, X7R, 10% |
| C104 | 1 | Murata GRM21BR71H104KA01L | 100 nF, 50 V, X7R, 10% |
| C105, C106, C107 | 3 | Yageo CC0805JRNPO9BN471 | 470 pF, 50 V, C0G/NP0, 5% |
| JP101 | 0 closed links | No component purchase | Leave an isolated, labelled open connection; no bridge to AREF |

There are **16 resistors, 7 capacitors, one reference and one quad IC**.
Do not buy five MCP6024s because the schematic draws five units.
Use genuine parts from a traceable distributor; apparent savings on
unidentified reference/op-amp modules can invalidate the experiment.

| Other item | Low-cost choice / quantity |
|---|---|
| Proto shield and stacking headers | Reuse the existing assembly; replace only damaged or mechanically unsuitable pieces |
| D101 carrier | One plain SOT-23-3 breakout if needed; no regulator/reference module with extra circuitry. Check its copper mapping before use |
| Passive mounting | Existing isolated pads if suitable; otherwise small inexpensive 0805 carriers/copper islands, sufficient for 23 passives |
| Wire | Short insulated hookup wire; distinguish 3.3 V, ground and signals by colour/labels |
| Disconnectable connections | Short removable links for power, DAC0/1 and A0/1/2 during testing; not switches operated while powered |
| Test access | Small labelled wire loops/pads for ground, supply, D101 cathode, VREF3V0, VREF1V5 and A0/A1/A2 |
| Mechanical support | Reuse suitable insulating spacers; choose height from the actual underside clearance, not a guessed dimension |
| First-power supply / scope | Borrow for the relevant test session; not part of the default shopping list |

Equivalent resistor/capacitor brands are acceptable **after** matching
value, tolerance, dielectric, voltage/power rating and mounting size.
Do not replace C0G with X7R, or the 0.1% divider with ordinary 1% parts.
The 50 V ratings above identify commonplace parts; this circuit does not
need a 50 V operating rail. X7R capacitance changes with DC bias: these
nominal selections do not establish worst-case filtering or startup.
Record substitutions and their datasheets. Do not change U101's amplifier
type as a purchasing substitution.

The removed schematic used **MCP6024-E/SL (SOIC-14)**. The proposed working
assembly uses socketed **MCP6024-E/P (PDIP-14)** with the same functional pin numbering,
but does not fit the SOIC footprint. Mount its socket in a suitable free
through-hole area. Package, socket and wiring parasitics differ from the
SPICE model and from a future PCB; successful DC operation does not erase
those differences. Never force the SOIC device into a DIP socket.

## Inspect and plan the physical build

The reconstructed carrier has existing 5 V and ground distribution and
an SMD-to-grid breakout. Use its actual pad map and traced copper, rather
than assigning connections from the generic official shield drawing. That breakout
does not automatically supply an op-amp. Create a separate **3.3 V** AFE
feed from the Due's labelled 3.3 V header; do not use the shield's 5 V bus.
Clones and existing hand wiring must be checked with continuity measurements.

| Preparation | Record / acceptance |
|---|---|
| Existing wires | Photograph and label both ends; identify direct DAC0-A0 and DAC1-A1 loopbacks so they are not left in parallel with buffer outputs |
| Socket placement | Pin-1 notch marked; correct hole pitch and row spacing; room for decoupling and local feedback |
| Header labels | Use **Due signal names**, not Mega A12-A15 labels or connector reference numbers copied from another drawing |
| Ground routing | Compact local return joining a verified Due GND; signal wires have nearby returns; avoid shared long loops with unrelated loads |
| C104 | At the socket supply connections, with a short loop from pin 4 through C104 to pin 11 |
| Feedback | Short local connections 1-2, 6-7, 8-9 and 13-14 |
| ADC RC networks | C105/C106/C107 and the ADC side of R105/R106/R107 close to the appropriate analog header connections |
| Reference placement | D101/filter/divider away from clock and USB wiring; no long reference test leads left attached |
| Underside | Trimmed joints/leads cannot touch Due components, USB shells or other copper; inspect when mated unpowered |

The [baseline KiCad carrier model](../hardware/mega-proto-carrier/README.md)
now records all eleven supplied photographs and the measured **103 x 55 mm**
outline. It provides grid coordinates for planning this hand build;
header/grid registration, pad sizes and hidden copper still need physical
checks. It contains no installed Stage A circuitry. Confirm its pad map
against the board. The backlit photos reveal **28 existing SMD-to-grid
links**, recorded in the carrier model; those grid holes are not independent
islands. Their visual mapping still needs continuity confirmation. Then
use the [both-face trace audit](../hardware/mega-proto-carrier/TRACE-AUDIT.md)
for the existing header links, perimeter routes and reset/LED-area copper.
The outer bare digital field is **2x20**, including two ground rows. The
stripped-board photos resolve the switch's upper RESET/lower GND pad pairs,
the LED returns and corner SPI routes. Components were removed only from
the specimen used for routing photographs; the default carrier model keeps
the switch and headers fitted. Remaining unknowns are visible on **User.5**.
Create the working assembly from this carrier baseline. Keep fixed geometry
and existing copper intact; place the passed AFE circuit and record added
wires separately. Annotate the assembly drawing and photographs with the
100-series component references and connections below. Retain the photographs and continuity readings with
the assembly drawing. A layer of tape is not a substitute for adequate
mechanical clearance.

## Complete connection schedule

All pin numbers here are **component pins**, not a carrier board's labels.
For U101, viewed from the top with the notch at the top, pin 1 is upper left;
pins 1-7 run down the left and 8-14 run up the right. Underside views are
mirrored. Check socket notch and IC notch independently.

### U101: all 14 pins

| U101 pin | Function | Final stock-Due configuration |
|---:|---|---|
| 1 | A output | VREF3V0; join pin 2 and R103 upper end; no AREF connection |
| 2 | A inverting input | Short local link to pin 1 |
| 3 | A non-inverting input | R102/C102 filtered-reference junction |
| 4 | Positive supply | AFE +3V3; C104 to GND |
| 5 | B non-inverting input | R103/R104/C103 midpoint |
| 6 | B inverting input | Short local link to pin 7 |
| 7 | B output | VREF1V5; join pin 6 and R107 input |
| 8 | C output | Join pin 9 and R105 input |
| 9 | C inverting input | Short local link to pin 8 |
| 10 | C non-inverting input | Due DAC0 |
| 11 | Negative supply | GND, not a negative-voltage rail |
| 12 | D non-inverting input | Due DAC1 |
| 13 | D inverting input | Short local link to pin 14 |
| 14 | D output | Join pin 13 and R106 input |

### Reference, filters and unused-input resistors

The resistors and specified ceramic capacitors are nonpolar. The D101
reference is polar: **SOT-23 pin 1 = cathode, pin 2 = anode/GND,
pin 3 left floating**. Do not apply a TO-92 pinout to this part.

| Component | End 1 / node | End 2 / node |
|---|---|---|
| R101, 56 ohm | AFE +3V3 | D101 cathode |
| C101, 10 uF | D101 cathode | GND |
| R102, 10 kohm | D101 cathode | U101 pin 3 |
| C102, 1 uF | U101 pin 3 | GND |
| R103, 10 kohm, 0.1% | U101 pin 1 | U101 pin 5 |
| R104, 10 kohm, 0.1% | U101 pin 5 | GND |
| C103, 1 uF | U101 pin 5 | GND |
| C104, 100 nF | U101 pin 4 | U101 pin 11 / GND |
| R105, 68 ohm | U101 pin 8 | A0 node |
| C105, 470 pF | A0 node | GND |
| R106, 68 ohm | U101 pin 14 | A1 node |
| C106, 470 pF | A1 node | GND |
| R107, 68 ohm | U101 pin 7 | A2 node |
| C107, 470 pF | A2 node | GND |
| R108 / R109 / R110 | Due A3 / A4 / A5 respectively | Each to GND |
| R111 / R112 / R113 | Due A6 / A7 / A8 respectively | Each to GND |
| R114 / R115 / R116 | Due A9 / A10 / A11 respectively | Each to GND |

R108-R116 are nine separate 10 kohm resistors, not shorts. Reserve these pins
for this experiment: do not attach another shield circuit or configure
them as outputs while using this wiring.

### Due interface and temporary test configuration

| Connection | Standalone shield test | Final stacked test |
|---|---|---|
| Shield mechanically | Removed from Due | Mated only while all power is disconnected |
| AFE +3V3 | Borrowed supply, regulated 3.30 V with 20 mA limit | Due 3.3 V header only; external supply physically removed |
| GND | Supply negative and multimeter common | Due GND and multimeter common |
| U101 pins 10 and 12 | Temporary links to VREF1V5; keeps both followers at a defined input | Remove both temporary links; connect DAC0 and DAC1 respectively |
| A0/A1/A2 filter nodes | No connection to Due; retain their filter capacitors | Connect to Due A0/A1/A2 respectively |
| A3-A11 | Resistors installed on shield, no Due attached | Each connected to its assigned 10 kohm pull-down |
| JP101 / AREF | Open; reference output isolated from AREF | Still open; no wire to AREF |

Never power an unpowered Due through an analog signal or the 3.3 V header.
Never leave the standalone supply connected when stacking or USB powering.
Never operate links or insert/remove the IC while powered.

## Assembly and unpowered gate

| Step | Action | Check before proceeding |
|---:|---|---|
| 1 | Measure loose resistors; separate 0.1% divider parts from other 10 kohm parts | Values/labels match the BOM; a basic meter cannot certify 0.1% accuracy |
| 2 | Solder the empty socket and supply/ground wiring | Every contact goes only to its intended net; no 5 V connection |
| 3 | Fit D101 and its reference/filter/divider passives | Identify D101 pins from package orientation, not a guessed adapter numbering |
| 4 | Fit feedback links, C104, driver RC networks and unused-input resistors | Check the connection schedule one row at a time |
| 5 | Fit labelled test pads and standalone input links | No floating driver input; no Due or AREF connection |
| 6 | Inspect with magnification; remove solder debris and clean flux as appropriate | No bridges, cracked MLCCs or unsupported joints |
| 7 | Measure continuity with power disconnected and U101 still out | Intended wire links read near lead resistance; no unintended adjacent-pin shorts |
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

1. Leave U101 out. With the supply output off and disconnected, set 3.30 V
   and a 20 mA limit using that supply's manual. Verify output voltage
   independently, turn it off, then connect shield ground and supply.
2. Apply power. If current limiting persists beyond one second, voltage
   fails to rise, or anything heats/smells abnormal, turn off immediately.
   A brief capacitive charging event is not a reason to raise the limit.
3. Measure the supply and D101 cathode. Expected reference-only current is
   about 5.4 mA: (3.30 - 3.00) / 56. With no U101 fitted, do not expect a
   functioning buffered 3.0 V or 1.5 V output.
4. Turn off, disconnect and verify the rail has discharged. Insert U101,
   checking its notch, every leg and the temporary links to pins 10/12.
5. Reapply power with the same limit. Wait one second, then fill in every
   row below; repeat after 30 seconds and five minutes. Stop on any failed
   check, unstable display, unexpected current increase or abnormal heat.

| Measurement, black lead at GND | Coarse check after U101 is fitted |
|---|---|
| U101 pin 4 supply | 3.25-3.35 V at the IC |
| Total standalone supply current | Investigate outside 6-15 mA; about 10 mA is a nominal expectation, not a guaranteed specification |
| D101 cathode | 2.97-3.03 V |
| U101 pin 3, filtered reference | Within 5 mV of D101 cathode after settling, if the meter can resolve this comparison |
| U101 pin 1, VREF3V0 | 2.97-3.03 V; within 5 mV of pin 3, subject to meter uncertainty |
| U101 pin 5, divider midpoint | 1.47-1.53 V |
| U101 pin 7, VREF1V5 | 1.47-1.53 V; within 5 mV of pin 5, subject to meter uncertainty |
| U101 pins 8 and 14 | Within 5 mV of VREF1V5 with their inputs temporarily tied there |
| A0/A1/A2 filter nodes | Approximately VREF1V5; within 5 mV of their respective driver outputs at DC |

If the meter's resolution/accuracy cannot support a 5 mV comparison,
record **not resolved**, not pass or fail. The broad voltage checks can
still expose gross wiring faults. At 3.30 V, R101 normally dissipates only
about 1.6 mW and D101 about 16 mW; these are calculated nominal values,
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
2. Check the final interface table, JP101 open, polarity, clearance and no
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
| 1 | 3.3 V at U101, VREF3V0 and VREF1V5 at idle and during DAC/ADC activity | Oscillation, excursions and repeatable ripple; investigate sustained oscillation before further tests |
| 2 | Power-up and power-down reference/rail traces | Overshoot, settling, rail collapse or undesired interaction; JP101 stays open |
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

The removed circuit was checked using KiCad 10.0.6 and ngspice 47. These
are historical simulation findings to reproduce or explain during A1,
not new passes or measurements of this socketed assembly:

| Check | Baseline evidence / limit |
|---|---|
| Schematic | Zero ERC errors; 61 isolated unused-header-label warnings; critical nets and selected BOM fields checked |
| DC reference | VREF3V0 about 2.9984 V, VREF1V5 about 1.4996 V |
| Baseline driver | About -5.86 dB before R105 at 5.012 MHz; full path about -8.90 dB |
| Baseline 2 V step | About 1.218 us to stay within 0.732 mV of the final plateau, exceeding the 1.129 us single-channel target interval |
| Open-JP101 loaded screen | About 1.232 us settling; selected supply/temperature/RC cases did not establish the full-step deadline |
| Fitted ADC sampling load | Small charge-recovery error in the assumed 769 ns case; not a transistor-level ADC or firmware-sequence qualification |
| Assumed severe wire inductance | A 1 uH stress case did not establish a quiet final plateau; actual shield inductance is unknown |
| Closed-link AREF stress | Unqualified; not a reason to close JP101 in this build |
| Physical implementation | Old template removed; corrected carrier available, with no Stage A assembly or simulation pass yet |

AFE-09 is now resolved through simulation before assembly. Recreate the
candidate circuit and resolve required performance failures in A1; do not
carry them into hardware as accepted results. Later hardware discrepancies
still need diagnosis of construction, probes, source and circuit.

The former `hardware/afe-shield/check.py`, batch simulations and workbook
are absent. Follow the [new simulation plan](../hardware/afe-proto/sim/README.md)
to create reproducible tests from the working KiCad circuit. No new runner
or passed report exists yet. Use KiCad **10.x** with matching libraries,
record the ngspice version, and retain numerical pass/fail evidence.
Simulation does not test the physical socket or solder joints.

## Build and measurement worksheet

Copy this section into your measurement notes; keep photographs and raw
captures beside it. Record actual readings, not ticks copied from this guide.

| Identification | Fill in |
|---|---|
| Recipe / circuit | P2 candidate from c78201b; replace with passed working schematic revision before build |
| A1 simulation report / models / acceptance limits | |
| Working KiCad assembly / carrier revision / added-wire drawing | |
| Due identity / board revision / firmware | |
| Shield identification / photographs | |
| U101 and D101 markings / supplier | |
| Passive substitutions / socket / carrier | |
| Meter model, range, resolution, accuracy specification | |
| First-power supply / measured setting / current limit | |
| Scope / probe / bandwidth / ground connection, if used | |
| Ambient conditions / warm-up duration | |
| JP101 open / Due unchanged / temporary links removed before stacking | |

| Measurement | Standalone 1 s | Standalone 30 s | Standalone 5 min | Stacked idle | Stacked active |
|---|---|---|---|---|---|
| Supply at U101 pin 4 | | | | | |
| Shield current (standalone only) | | | | n/a | n/a |
| D101 cathode | | | | | |
| Filtered reference, U101 pin 3 | | | | | |
| VREF3V0, U101 pin 1 | | | | | |
| Divider midpoint, U101 pin 5 | | | | | |
| VREF1V5, U101 pin 7 | | | | | |
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
