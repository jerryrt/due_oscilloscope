# AFE version 2 requirements (cost-down)

Version 2 is the version 1 AFE made cheaper and simpler: **one scope range of
−1.5 to +3.5 V, an AWG of −1.5 to +3.0 V, no analog switch, dual op-amps,
one negative rail, free-loading passives, and one 16-bit four-input
converter in place of the 24-bit precision ADC.** Every requirement in
[afe.md](afe.md) holds for version 2 except where this file amends it, so this
file states only the differences, by requirement ID. Version 1 is the design
reviewed at `db85f57`; its bill of materials is
`hardware/afe-proto/whatif/bom.md` ($37.0 to $37.4 per board at 20 boards,
$31.5 to $31.7 at 100, domestic order, PCB included).

The owner's rules for version 2 (2026-11-11):

| ID | Rule |
|---|---|
| V2-1 | **One negative rail, shared by the scope and the AWG** |
| V2-2 | **Every op-amp is a dual package**, the single-channel AWG included |
| V2-3 | **Every resistor and capacitor is a board-house library part with no loading fee** (JLC Basic; the domestic service has no Preferred tier) |
| V2-4 | **Cost down** against version 1, reported per block |
| V2-5 | **Calibration may use jumper wires on the Due's pass-through pins**, never the normal signal path |
| V2-6 | **One scope range, −1.5 to +3.5 V, and an AWG of −1.5 to +3.0 V** |
| V2-7 | **No TMUX1119, and no analog switch on the board** |
| V2-8 | **The precision ADC only measures DC, and is chosen for cost**: the REF3030E sets the accuracy, and the converter reads it on its own inputs |

Figures marked *derived* below are arithmetic on `afe.md`'s numbers, not
simulation; the design replaces each with its own. Where this file and the
design disagree, the owner decides (section 6), and until then this file's
value stands.

## 1. What version 1 spends, and where the rules act

Per board at 20 boards, from the version 1 bill of materials (derived; prices
read 2026-11-11, *(check)* before ordering):

| Block | Version 1 | $ per board | Version 2 |
|---|---|---|---|
| Op-amps | 2 OPA354, 3 OPA365, 1 TLV9062 | 10.51 | Duals only (V2-2) |
| Precision resistors | six Extended types at 0.1% (100k, 330k, 174k, 953R, 249R, 49.9R) | 4.79, plus 120 CNY of loading fees per order (about $0.90 per board) | Basic 1% (V2-3) |
| Switches | 3 TMUX1119: two range switches and the sense divider's ratio switch | 5.70, plus their decouplers and pull-downs | None (V2-6, V2-7) |
| Precision ADC and reference | ADS124S08 ($7.45), REF3030E ($0.81) | 8.26 | One ADS1115-class converter (about $0.74 to $1.85 in LCSC snapshots *(check)*) and the REF3030E (V2-8) |
| Calibration ladder | eight 249R 0.1% | 0.97 | Kept, Basic 1% (V2-3) |
| Rails | LM27762: +3.3 V analog, and −2.07 V used by the AWG only | 0.79 | One negative rail for both (V2-1) |
| Scope mid-rail network | per channel 4 × 1R, 4.7k, 1 µF, 6 × 10 µF, 100 nF | about 0.4 | The design's (V2-1) |

## 2. The rules as requirements

| ID | Requirement |
|---|---|
| V2-1 | **One negative rail.** The AFE makes one positive analog rail and **exactly one negative rail**, and both the scope and the AWG stages may draw on it. The value is the design's; version 1's −2.07 V is the starting point and leaves the AWG about 0.4 V of headroom at the bottom of its window (derived). The intent is that the scope's level shift no longer needs a dedicated buffered mid-rail per channel; the design shows what the shared rail removes. **PR-2 still holds at A0, A1 and the DAC pin in every supply and power-off state**, including a scope stage driven to the negative rail, and the design shows how (clamp or supply arrangement). **Coupling through the shared rail counts against SC-9**: the AWG stepping full scale into 50 Ω moves a scope reading by at most SC-9's 2 LSB, and the scope's load on the rail keeps the AWG within AW-6. PW-1's 100 mA, PW-2's ripple and switching-frequency rule and PW-7's start-up apply to the shared rail with both loads on it |
| V2-2 | **Dual op-amps only.** Every op-amp on the board is a dual package; no single-amplifier package is fitted, including in the AWG. **At most two op-amp part types, one preferred.** A package's spare half is allowed only where the circuit has no use for it, and the design says where. **SC-9 is not relaxed.** Version 1 kept the two scope amplifiers in separate packages for SC-9, so the two channels' signal amplifiers share a package only if SC-9 is shown met with them sharing; otherwise each channel's dual carries that channel's own stages, and no package is shared between channels. The AWG is **one dual package**, both halves on the AWG (for example the DAC0 buffer and the output stage); AW-8 and AW-7's offset reference are met with those halves and passives. SM-3's bandwidth, SC-6, AW-6 and AN-1 hold for the parts chosen. The supply across any op-amp stays inside its rating, which for version 1's parts is 5.5 V *(check)*: the +3.3 V and −2.07 V rails are 5.37 V |
| V2-3 | **Free-loading passives only.** Every resistor and capacitor is a JLC **Basic** part, with no loading fee, and **no Extended passive is fitted**. A value is built first from one Basic value, then from series and parallel combinations of Basic values (MC-12's rule); a requirement that cannot be met that way is listed for the owner (section 4), never met with an Extended part. The design lists every passive with its LCSC number and its Basic status read from the board house's own part page, with the date; a third-party list is not evidence. Basic resistors are expected to be 1% thick film at about ±100 ppm/K *(check per part)*, and every requirement that assumed 0.1% at 10 to 25 ppm/K is recomputed with the chosen part's datasheet figures. ICs, diodes and the hand-fitted parts are not passives under this rule; MC-12 still asks that they be few in type |
| V2-4 | **Cost.** The design reports the per-board cost at 20 and at 100 boards on the domestic service, PCB included, in the version 1 format, with the change against version 1 per block of section 1. The target is the owner's (D-V2-1) |
| V2-5 | **Calibration connections by jumper wire.** The shield passes every Due pin through and leaves it reachable from the top of the stack (MC-9), so the Due's DAC and ADC pins and the AFE's own calibration nodes can be joined by a jumper wire for a calibration and removed afterwards. A connection used **only during calibration** may be made this way instead of by a permanent trace or a part, where that removes a part or frees a pin. The AFE brings each such node to a labelled header pin or pad beside the Due pin it joins, and the calibration procedure names each wire. **The host verifies every jumper by measurement before using a reading**: each position gives a reading that cannot be mistaken for another, and a missing or misplaced wire stops the calibration with a message, never a wrong fit. A jumper carries only the AFE's own signals (the reference, the ladder, the sense divider, DAC0 or DAC1), all inside 0 V to AREF, so PR-2 holds with any wire in any position the procedure names or with the wire left off. **Nothing in normal use depends on a jumper**: the scope inputs, the AWG output and the wide path are wired permanently |
| V2-8 | **A cheap DC precision ADC.** The precision channel reads only DC, during calibration and as a slow DC measurement, so it need not be a 24-bit part and need not take an external reference. **The REF3030E (PA-2) is read on the converter's own inputs, and every precision reading is taken as a ratio to it in the same session**, so the converter's internal reference cancels and only its linearity, noise and short-term drift remain; the design shows those inside SC-7's fit share from the datasheet. The candidate is **one ADS1115** (TI, 16-bit, four inputs, I²C), with the SG Micro SGM58031 as a possible second source *(check: pin compatibility, JLC stock and price)*. The bus is the Due's hardware TWI on the edge headers or a software bus on two edge-header pins, which frees the version 1 bus pins D33 to D37. PA-1's "16 bits noise-free" becomes **a 16-bit converter whose averaged reading meets SC-7's fit share**; the design states the averaging. The converter is supplied from the +3.3 V analog rail, and every input stays between 0 V and that rail in normal use (PR-4's rule for the unpowered and forced cases, from the chosen part's datasheet). The four inputs are allocated in section 3.4 |

## 3. Ranges and the switch-free design

### 3.1 Scope: one range, −1.5 to +3.5 V (V2-6)

One range makes the range switch unnecessary, and its offset centre of +1.0 V
lets the inputs read 3.3 V logic and 0 to 3.3 V signals with a ×1 probe. 5 V
logic needs a ×10 probe, which gives −15 to +35 V.

| Version 1 | Version 2 |
|---|---|
| **SC-2**: each input ±5 V, usable to ±6 V | Each input **−1.5 to +3.5 V, usable from about −2.0 to +4.0 V** (derived), with the ADC pin inside 0 to AREF and at least 80 mV of margin per side at AREF 3.20 V, over AREF 3.20 to 3.30 V, component tolerance and a centring error of ±30 mV recomputed for 1% parts. The +1.0 V centre is set by the AFE's own reference arrangement and calibrated (SC-7); it need not be exact |
| **SC-4**: at most 4 mV per code; ±5 V occupies 70 to 75% of full scale | **At most 1.8 mV per code at the input** (derived: 1.63 to 1.74 mV at 70 to 75% of full scale). The 5 V span occupies 70 to 75% of full scale at nominal AREF |
| **SC-11**: a second range of ±1.25 V, selected by a Due pin through a solid-state switch | **Removed.** No range selection, so D38 and D39 are free |
| **SC-8**: gain within 3%, with the range switch's resistance in the gain | Held at 3% with no switch in the gain; relaxed to the design's worst case only if 1% parts cannot meet it (it only catches a mis-assembled part) |
| **DF-2**: ±5 V and ±10 V of difference | **Two difference ranges from the PGA gains 1 and 0.5, about ±3.4 V and ±6.9 V** (derived); the design states the exact values. Each input stays within −2.0 to +4.0 V, so the common mode left at a large difference is small, and the documentation states it |
| **DF-4**: a separate figure for the ±1.25 V range | One figure, ±0.5% of reading ±1 code |
| **PR-1**: ±12 V on both inputs, powered or unpowered | Held. The divider attenuates less than version 1's (a 5 V span into about 2.3 V at the pin, against 10 V), so ±12 V puts more voltage inside the divider; the design shows where it is clamped and that the clamp's leakage and capacitance stay inside SC-7 and the divider's compensation (SC-3) |
| **SC-3**: 1 MΩ, compensated, ×1 and ×10 probes; capacitance at most 30 pF | Held, rebuilt from Basic values within 1% |
| **Section 5's PAM table** (on ±5 V and ±1.25 V) | On the one range: about 2,700 codes for a full AWG loopback, PAM128 passes and PAM256 is on the limit; a 1 V signal spans about 590 codes and fits PAM32 (derived, from the 8.6 to 11.4-code level band at 1.68 mV per code) |
| **VT-15**: PAM16 through the AFE on the ±1.25 V range | On the one range |

### 3.2 AWG: −1.5 to +3.0 V (V2-6)

| Version 1 | Version 2 |
|---|---|
| **AW-1**: ±1.0 V into a high-impedance load, ±0.5 V into 50 Ω | **−1.5 to +3.0 V into a high-impedance load, −0.75 to +1.5 V into 50 Ω**, using at most 92% of the board's DAC window as built, over AW-7's tolerances and AREF 3.20 to 3.30 V. The window's ends reach about −1.68 and +3.18 V (derived). +3.0 V sits under the +3.3 V rail, so no new rail is needed |
| **AW-2**: step at most 1 mV (0.62 mV per code) | **At most 1.5 mV per code** (derived: about 1.4 mV) |
| **PW-3**: a short to ground indefinitely, at most 30 mA | **A short to ground indefinitely, survived.** Through 50 Ω the current at the window's top end is about 64 mA (derived), at or past what the op-amp sources, so the op-amp's own current limit sets it. The design states the current, shows the package and the rails within their ratings for an indefinite short, and adds a current limit from Basic parts only if they are not. The short is exempt from PW-1's 100 mA but not from its 450 mA total (D-V2-7) |
| **AW-8**: within ±2.1 V through a Due reset or boot | **Within the AFE's rails, about −2.1 to +3.3 V** (derived), returning to the commanded value once the firmware drives DAC0. The documentation states that anything connected to the AWG may see this during a reset or boot |
| **PR-4**: forced voltage up to ±1.8 V survived with no damage | The design restates the level from the new swing and the op-amp's rating, by PR-4's rule |
| **AW-7**: the offset reference is the AWG's own | Held; its centre is about +0.75 V instead of 0 V |

### 3.3 Calibration with no switch (V2-7)

The tee calibration of PA-3 stands, now on one range per channel, and with
the AWG's span close to the scope's.

| Version 1 | Version 2 |
|---|---|
| **PA-3**: the AWG covers about 23% of the ±5 V range, so the fit extrapolates; 256 points on ±1.25 V and 1024 on ±5 V | **The AWG covers about 90 to 93% of the range** (derived); only the top 0.3 to 0.5 V is extrapolated. The design states the points that meet SC-7's fit share, at least 256 per channel |
| **PA-4**: one switch moves the sense divider's bottom end, so the ratio is measured at every calibration | **No switch. The ratio is measured through a direct sense input**: a second precision-ADC input on the AWG's BNC node through a series resistor. During calibration the AWG steps through levels the precision ADC can read directly (0 V to about 3.0 V), the host reads each one directly and through the divider, and their ratio is the divider ratio; the negative and top levels then use the divider. Whenever the AWG goes below 0 V the direct input is driven below the precision ADC's supply, so the design shows from the datasheet that the resulting current is allowed and **that it does not disturb the readings of the other inputs while it flows** *(check)*, or clamps the node (the BOM's BAT54S) with a leakage that stays inside SC-7's fit share. If neither holds, the ratio is measured by moving one jumper wire (V2-5) between two readings, which the host verifies |
| **PA-3, PA-4**: the ratio switch's Due pin D40 | Free |
| **The sense divider**: two 100k 0.1%, k = 1/2 | Basic 1%. Its ratio is measured at every calibration, so its tolerance does not reach SC-7; the design confirms its drift over one calibration session is inside SC-7's fit share, and sets k and its bottom end so −1.68 to +3.18 V stays inside the precision ADC's input range |
| **PA-9, D11**: the ladder is eight 249 Ω 0.1% resistors on A2 to A9, up to 8 taps | **Kept, Basic 1%, six taps** (the top tap and five below it), **two of them measured**. The top tap is the reference itself, so AREF tracking (PA-8) is not affected. One mid tap is read by the precision ADC at every calibration, so the Due ADC has two measured points plus ground, its gain and offset, which the host can re-read at any time without the tee or the AWG. The other four taps are not measured: they are known to about 1% from the resistor values, and serve as a fault check of the Due ADC pins and as quiet DC sources for its noise floor across the range, never as calibration points. **PA-9's minimum becomes two measured taps (the top and one mid tap) plus ground.** The mid tap's ratio drifts with its 1% resistors between calibrations, and the design shows that drift inside the recalibration threshold (EN-1, D-V2-3). Tap impedance stays under PA-9's leakage limit. The rule that the Due does not read the taps while the precision ADC converts stays (PA-3), since the ladder still runs straight off the reference |
| **PA-3**: one precision-ADC IC with its own multiplexer, no external multiplexer | **One converter** (V2-8), still with no external multiplexer |

### 3.4 The precision ADC's four inputs (V2-8)

| Input | Node | Use |
|---|---|---|
| 1 | REF3030E output, the ladder's top tap | The accuracy anchor: every other reading is a ratio to it |
| 2 | The AWG-sense divider's tap | The AWG at the BNC during the tee calibration (PA-3) |
| 3 | The direct sense input | The divider ratio (section 3.3) |
| 4 | One ladder tap near mid-scale | The Due ADC's second measured point (PA-9) |

There is no spare input. If the direct sense input cannot be used (section
3.3), the ratio falls back to the jumper and input 3 is free for a second
measured ladder tap.

## 4. Requirements the 1% passives move (V2-3)

| Version 1 | What moves it | Version 2 |
|---|---|---|
| **DF-3** names 0.1% at 25 ppm/K for the input network, and asks 30 dB at DC and 18 dB at 10 kHz **before** calibration (version 1's design: 32.1 dB) | 1% resistors put up to about ten times the version 1 mismatch into the two channels' dividers | The resistor clause goes. **After** calibration stays at 44 dB at DC: the tee calibration fits each channel's gain, so tolerance is removed and only drift since calibration is left. The before-calibration figure, and with it the hardware differential mode (SM-6), is relaxed to the design's computed worst case (D-V2-2) |
| **EN-1**: gain drift at most 0.2% over 15 to 35 °C, before calibration | Two 1% thick-film resistors forming one ratio may drift in opposite directions: up to 200 ppm/K, 0.4% over EN-1's 20 K (derived, from the expected ±100 ppm/K *(check)*) | Relaxed to the design's computed worst case for the parts chosen (D-V2-3) |
| **SC-7**: ±0.5% of reading ±5 mV after calibration; version 1's worst case 0.29 to 0.39% | Calibration removes tolerance but not the drift since calibration, and the resistors' share of that drift grows with their tempco | **Held at ±0.5%.** If the design's worst case exceeds it, the recalibration threshold (PA-3, EN-1: 10 K since calibration) is lowered to the change that keeps it, rather than SC-7 being widened (D-V2-3) |
| **AW-4**: 50 Ω ±1% back-termination (version 1: 49.9 Ω 0.1%, 1206) | 49.9 Ω may not be Basic | A Basic value or combination within 1% of 50 Ω, rated for the short circuit of section 3.2; a single 51 Ω part (2% high) only with the owner's acceptance (D-V2-4) |
| **MC-12**: precision input-network resistors are exceptions to the basic library | V2-3 allows no exception for passives | MC-12 holds with no passive excepted; precision ICs (reference, converters) remain exceptions chosen for accuracy first |
| **MC-12**: the two scope amplifiers in separate packages, the AWG stage in its own | V2-2 | Replaced by V2-2's package rule |
| **MC-10**: nothing is wired to the Due's headers while the AFE is installed; **MC-11**: an undecided choice is never a jumper | V2-5 | Both hold in normal use. During a calibration, the wires the procedure names are allowed, and are removed afterwards |

## 5. Verification added

| ID | Test | Covers |
|---|---|---|
| VT-19 | Coupling through the shared negative rail: the AWG stepping full scale into 50 Ω while each scope channel holds a DC input, and the reverse, each reading's change against SC-9 and AW-6 | V2-1, SC-9, AW-6 |
| VT-20 | The direct sense input: the ratio it measures against a jumper-measured ratio on the same board, and the other inputs' readings with the AWG held at −1.68 V against the same readings at 0 V | PA-4, SC-7 |
| VT-21 | Any calibration jumper the procedure names: left off, in each wrong position the headers allow, and in the right one; the host stops on each wrong case and the pins stay inside PR-2 | V2-5, PR-2 |
| VT-6 | As version 1, plus the indefinite short of section 3.2 with the package temperature logged | PW-3 |
| VT-12 | As version 1, now also setting the recalibration threshold of section 4's SC-7 row | EN-1, SC-7 |

## 6. Decisions for the owner

| ID | Decision | Recommendation |
|---|---|---|
| D-V2-1 | The per-board cost target | Set it once the design has priced version 2, against version 1's $37.0 to $37.4 at 20 boards. The switches (about $5.70), V2-3 (about $5.70) and the converter (about $5.60 to $6.70) together remove roughly $17 to $18 per board at 20 before the op-amp change (derived) |
| D-V2-2 | DF-3 before calibration and the hardware differential mode, at the design's 1% worst case | Accept: after calibration stays at 44 dB, and SM-6 already holds the hardware mode only to the before-calibration figure |
| D-V2-3 | EN-1's uncalibrated drift, and SC-7 held by a tighter recalibration threshold rather than a wider limit | Accept both, with the threshold set by VT-12 |
| D-V2-4 | AW-4 at 51 Ω if no Basic combination reaches 50 Ω ±1% | Decide only if the design finds no combination |
| D-V2-5 | The ratio measurement: the direct sense input, or the jumper | The direct sense input, if VT-20 and the datasheet check pass; the jumper otherwise |
| D-V2-6 | The precision ADC: one ADS1115-class converter reading the REF3030E ratiometrically (V2-8), in place of the ADS124S08, with two of the ladder's taps measured (PA-9) | Accept, if the design shows SC-7's fit share from the ADS1115's datasheet linearity and noise, and JLC stock is adequate. It stays on every board, as in version 1 |
| D-V2-7 | The AWG's short-circuit current set by the op-amp's limit (about 64 mA) instead of PW-3's 30 mA | Accept, if the design shows the package and rails within their ratings for an indefinite short |
