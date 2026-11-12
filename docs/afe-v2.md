# AFE version 2 requirements (cost-down)

Version 2 is the version 1 AFE made cheaper and simpler: **one scope range of
−1.5 to +3.5 V, an AWG of −1.5 to about +2.05 V, no analog switch, dual op-amps,
one negative rail, free-loading passives, and one 16-bit four-input
converter in place of the 24-bit precision ADC.** Every requirement in
[afe.md](afe.md) holds for version 2 except where this file amends it, so this
file states only the differences, by requirement ID. Version 1 is the design
reviewed at `db85f57`; its bill of materials is
`hardware/afe-proto/whatif/bom.md` ($37.0 to $37.4 per board at 20 boards,
$31.5 to $31.7 at 100, domestic order, PCB included).

The owner's rules for version 2 (2026-11-11, V2-9 2026-11-12):

| ID | Rule |
|---|---|
| V2-1 | **One negative rail, shared by the scope and the AWG** |
| V2-2 | **Every op-amp is a dual package**, the single-channel AWG included |
| V2-3 | **Every resistor and capacitor is a board-house library part with no loading fee** (JLC Basic; the domestic service has no Preferred tier) |
| V2-4 | **Cost down** against version 1, reported per block |
| V2-5 | **Calibration may use jumper wires on the Due's pass-through pins**, never the normal signal path |
| V2-6 | **One scope range, −1.5 to +3.5 V, and an AWG of −1.5 to +3.0 V**, the AWG's top end lowered to about +2.05 V on 2026-11-12 so an indefinite short stays inside the op-amp's supply-pin rating (D-V2-7) |
| V2-7 | **No TMUX1119, and no analog switch on the board** |
| V2-8 | **The precision ADC only measures DC, and is chosen for cost**: the REF3030E sets the accuracy, and the converter reads it on its own inputs |
| V2-9 | **Cost down is the main purpose, and nothing works above 10 MHz** (2026-11-12): no requirement is met beyond what it needs |

Figures marked *derived* below are arithmetic on `afe.md`'s numbers, not
simulation; the design replaces each with its own. Where this file and the
design disagree, the owner decides (section 7), and until then this file's
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
| V2-2 | **Dual op-amps only.** Every op-amp on the board is a dual package; no single-amplifier package is fitted, including in the AWG. **At most two op-amp part types, one preferred.** A package's spare half is allowed only where the circuit has no use for it, and the design says where. **SC-9 is not relaxed.** Version 1 kept the two scope amplifiers in separate packages for SC-9, so the two channels' signal amplifiers share a package only if SC-9 is shown met with them sharing; otherwise each channel's dual carries that channel's own stages, and no package is shared between channels. The AWG is **one dual package**, both halves on the AWG (for example the DAC0 buffer and the output stage); AW-8 and AW-7's offset reference are met with those halves and passives. SM-3's bandwidth, SC-6, AW-6 and AN-1 hold for the parts chosen. The supply across any op-amp stays inside its **recommended operating** rating, not its absolute maximum, shown at both rails' worst-case tolerance; for version 1's parts that rating is 5.5 V *(check)* against the rails' nominal 5.37 V (+3.3 V and −2.07 V) |
| V2-3 | **Free-loading passives only.** Every resistor and capacitor is a JLC **Basic** part, with no loading fee, and **no Extended passive is fitted**. A value is built first from one Basic value, then from series and parallel combinations of Basic values (MC-12's rule); a requirement that cannot be met that way is listed for the owner (section 4), never met with an Extended part. The design lists every passive with its LCSC number and its Basic status read from the board house's own part page, with the date; a third-party list is not evidence. Basic resistors are expected to be 1% thick film at about ±100 ppm/K *(check per part)*, and every requirement that assumed 0.1% at 10 to 25 ppm/K is recomputed with the chosen part's datasheet figures. ICs, diodes and the hand-fitted parts are not passives under this rule; MC-12 still asks that they be few in type |
| V2-4 | **Cost.** The design reports the per-board cost at 20 and at 100 boards on the domestic service, PCB included, in the version 1 format, with the change against version 1 per block of section 1. The target is the owner's (D-V2-1) |
| V2-5 | **Calibration connections by jumper wire.** The shield passes every Due pin through and leaves it reachable from the top of the stack (MC-9), so the Due's DAC and ADC pins and the AFE's own calibration nodes can be joined by a jumper wire for a calibration and removed afterwards. A connection used **only during calibration** may be made this way instead of by a permanent trace or a part, where that removes a part or frees a pin. The AFE brings each such node to a labelled header pin or pad beside the Due pin it joins, and the calibration procedure names each wire. **The host verifies every jumper by measurement before using a reading**: each position gives a reading that cannot be mistaken for another, and a missing or misplaced wire stops the calibration with a message, never a wrong fit. A jumper carries only the AFE's own signals (the reference, the ladder, the sense divider, DAC0 or DAC1), all inside 0 V to AREF, so PR-2 holds with any wire in any position the procedure names or with the wire left off. **Nothing in normal use depends on a jumper**: the scope inputs, the AWG output and the wide path are wired permanently |
| V2-8 | **A cheap DC precision ADC.** The precision channel reads only DC, during calibration and as a slow DC measurement, so it need not be a 24-bit part and need not take an external reference. **The REF3030E (PA-2) is read on the converter's own inputs, and every precision reading is taken as a ratio to it in the same session**, so the converter's internal reference cancels and only its linearity, noise and short-term drift remain; the design shows those inside SC-7's fit share from the datasheet. The candidate is **one ADS1115** (TI, 16-bit, four inputs, I²C), with the SG Micro SGM58031 as a possible second source *(check: pin compatibility, JLC stock and price)*. The bus is the Due's hardware TWI on the edge headers or a software bus on two edge-header pins, which frees the version 1 bus pins D33 to D37. PA-1's "16 bits noise-free" becomes **a 16-bit converter whose averaged reading meets SC-7's fit share**; the design states the averaging. Every input here is at or above ground and the 3.0 V reference needs the ±4.096 V range *(check)*, so the converter works as **15 bits single-ended**, about 125 µV per code (derived), and the budget is sized against that, never 16. The converter is supplied from the +3.3 V analog rail, and every input stays between 0 V and that rail in normal use (PR-4's rule for the unpowered and forced cases, from the chosen part's datasheet). The four inputs are allocated in section 3.4 |
| V2-9 | **A 10 MHz ceiling, and no over-design.** This is afe.md's D13, which applies to version 1 as well; version 2 states its consequences here. The owner's words: "cost down is the main purpose here, and I never need it work over 10 MHz at most". **No frequency requirement extends above 10 MHz**, and a part is chosen as the cheapest that meets the requirement as written, never for margin the requirement does not ask for. SM-3's bandwidth stays at least 8 MHz on the one range (D3) and is not a target to exceed: with no filter (SC-5) the ADC folds in every frequency the stage passes, so bandwidth beyond the need adds noise against SC-6 and buys nothing. Requirements whose wording reached past 10 MHz are capped in section 3: SC-9's "any frequency the wide path passes" and AW-3's stage speed. AN-1's phase margin is not a frequency requirement and holds for whatever parts are chosen |

## 3. Ranges and the switch-free design

### 3.1 Scope: one range, −1.5 to +3.5 V (V2-6)

One range makes the range switch unnecessary, and its offset centre of +1.0 V
lets the inputs read 3.3 V logic and 0 to 3.3 V signals with a ×1 probe. 5 V
logic needs a ×10 probe, which gives −15 to +35 V.

| Version 1 | Version 2 |
|---|---|
| **SC-2**: each input ±5 V, usable to ±6 V | Each input **−1.5 to +3.5 V, usable from about −2.0 to +4.0 V** (derived), with the ADC pin inside 0 to AREF and at least 80 mV of margin per side at AREF 3.20 V, over AREF 3.20 to 3.30 V, component tolerance and a centring error of ±30 mV recomputed for 1% parts. The +1.0 V centre is set by the AFE's own reference arrangement and calibrated (SC-7); it need not be exact |
| **SC-4**: at most 4 mV per code; ±5 V occupies 70 to 75% of full scale | **At most 1.8 mV per code at the input** (derived: 1.63 to 1.74 mV at 70 to 75% of full scale). The 5 V span occupies 70 to 75% of full scale at nominal AREF, taken as 3.25 V, the middle of 3.20 to 3.30 V |
| **SC-11**: a second range of ±1.25 V, selected by a Due pin through a solid-state switch | **Removed.** No range selection, so D38 and D39 are free |
| **SC-8**: gain within 3%, with the range switch's resistance in the gain | Held at 3% with no switch in the gain; relaxed to the design's worst case only if 1% parts cannot meet it (it only catches a mis-assembled part) |
| **DF-2**: ±5 V and ±10 V of difference | **Two difference ranges from the PGA gains 1 and 0.5, about ±3.4 V and ±6.9 V** (derived); the design states the exact values. Each input stays within −2.0 to +4.0 V, so the common mode left at a large difference is small, and the documentation states it |
| **DF-4**: a separate figure for the ±1.25 V range | One figure, ±0.5% of reading ±1 code |
| **PR-1**: ±12 V on both inputs, powered or unpowered | Held. The divider attenuates less than version 1's (a 5 V span into about 2.3 V at the pin, against 10 V), so ±12 V puts more voltage inside the divider; the design shows where it is clamped and that the clamp's leakage and capacitance stay inside SC-7 and the divider's compensation (SC-3) |
| **SC-3**: 1 MΩ, compensated, ×1 and ×10 probes; capacitance at most 30 pF | **Nominal 1 MΩ within 1%, from Basic values, with the 1% parts' spread allowed on top** (about ±2% worst case, derived; owner, 2026-11-12, D-V2-9), since the probe compensation is adjusted per channel. Capacitance as version 1 |
| **The offset centre**: version 1's buffered mid-rail, one TLV9062 half per channel | **Set from the REF3030E through each channel's input resistors** (owner, 2026-11-12, D-V2-10): no buffer and no divider off +3.3 V, whose noise and drift would reach every offset. The reference then has three roles, the precision ADC's anchor, the ladder's top and the scope's centre, and the design shows that its sink rating covers an input clamped past +4 V *(check)*, and that SC-7's budget holds with the scope's signal current flowing in the reference the precision ADC reads |
| **SC-9**: crosstalk at most 2 LSB for a full-scale input at any frequency the wide path passes | **Up to 10 MHz** (V2-9). The two scope channels may share one dual op-amp: the design's data puts the coupling under 1 LSB at 10 MHz even at three times the datasheet's figure, so V2-2's sharing condition is met and the board carries two duals, one for the scope and one for the AWG. The AWG-into-scope limit is unchanged |
| **Section 5's PAM table** (on ±5 V and ±1.25 V) | On the one range: about 2,200 codes for a full AWG loopback at the lowered AWG top end, so PAM128 passes and PAM256 does not (derived); a 1 V signal spans about 590 codes and fits PAM32 (derived, from the 8.6 to 11.4-code level band at 1.68 mV per code) |
| **VT-15**: PAM16 through the AFE on the ±1.25 V range | On the one range |

### 3.2 AWG: −1.5 to about +2.05 V (V2-6)

| Version 1 | Version 2 |
|---|---|
| **AW-1**: ±1.0 V into a high-impedance load, ±0.5 V into 50 Ω | **−1.5 V to the top end PW-3 allows into a high-impedance load, about +2.05 V for the TPH2502** (derived), and half of each into 50 Ω (−0.75 to about +1.03 V), using at most 92% of the board's DAC window as built, over AW-7's tolerances and AREF 3.20 to 3.30 V. **The window's top end is set by the indefinite short** (owner, 2026-11-12, D-V2-7): the short current at the window's top, through the back-termination at its low tolerance, plus the op-amp's maximum quiescent current, stays inside its supply-pin rating; for the TPH2502 that is (60 − 15) mA × 49.5 Ω, a window end of about +2.23 V and a nominal top of about +2.05 V (derived), and the design restates it from its own figures. The window's bottom end stays about −1.68 V (derived). **The short limit is a hardware guarantee and the top end is a per-board figure (D-V2-12):** the window's top at the DAC's highest code stays under the short limit in every corner of AREF, the rails and the parts, with no firmware clamp; and because the DAC window scales with AREF (3.20 to 3.30 V), the top end a given board reaches varies by up to about 0.3 V between boards. AW-1's top is therefore **the worst-corner top end the design guarantees, +1.71 V** (the design's figure; a typical board reaches more, up to a window top of about 2.2 V), the AWG offset is taken from the REF3030E rather than the +3.3 V rail to remove that rail's share of the spread, the 92% window use is judged against this guaranteed range, and the host measures and reports each board's actual top end at calibration. Into 50 Ω the output then sits at most about +2.05 V while sourcing about 21 mA, about 1.25 V from the +3.3 V rail (derived), so D-V2-8's swing limit no longer binds; the design still reports it |
| **AW-2**: step at most 1 mV (0.62 mV per code) | **At most 1.5 mV per code** (derived: about 1.1 mV at the lowered top end) |
| **PW-3**: a short to ground indefinitely, at most 30 mA | **A short to ground indefinitely, survived, inside every rating of the op-amp** (supply-pin current included) **by the choice of AW-1's top end, with no current limiter** (D-V2-7): about 45 mA at the window's top and about 34 mA at its bottom through 50 Ω (derived), plus the quiescent current. VT-6 confirms it on the first board with the package temperature logged. The short is exempt from PW-1's 100 mA but not from its 450 mA total |
| **AW-8**: within ±2.1 V through a Due reset or boot | **Within the AFE's rails, about −2.02 to +3.41 V** (the design's figure, over the 1% rail corners), returning to the commanded value once the firmware drives DAC0. The documentation states that anything connected to the AWG may see this during a reset or boot |
| **PR-4**: forced voltage up to ±1.8 V survived with no damage | **Restated by PR-4's rule (D-V2-12):** the forced voltage the AWG survives is the level that keeps the op-amp's supply-pin current inside its rating, about 0.73 V above the commanded top end and 0.52 V below the commanded bottom end (the design's figures); the documentation states it |
| **AW-7**: the offset reference is the AWG's own | Held; its centre is about +0.75 V instead of 0 V |
| **AW-3**: an unfiltered stage whose bandwidth is at least the scope path's | **Bandwidth at least SM-3's 8 MHz, and slew enough not to slow the DAC's own edge** (V2-9): about 6 V/µs at the DAC pin *(check)* times the stage's gain of about 1.8 to 1.9 at the lowered top end, so roughly 11 to 12 V/µs (derived). The DAC updates at most 1.39 M times a second, so the AWG never carries a full-scale 10 MHz sine, and the slew that would need (about 110 V/µs at 3.5 V peak to peak, derived) is not a requirement |

### 3.3 Calibration with no switch (V2-7)

The tee calibration of PA-3 stands, now on one range per channel, and with
the AWG's span close to the scope's.

| Version 1 | Version 2 |
|---|---|
| **PA-3**: the AWG covers about 23% of the ±5 V range, so the fit extrapolates; 256 points on ±1.25 V and 1024 on ±5 V | **The AWG covers about 71 to 78% of the range** at its lowered top end (derived); the top 1.3 to 1.5 V of the scope's range is extrapolated, so the design shows SC-7's fit share holds there, using the scope's linearity (VT-23). The design states the points that meet SC-7's fit share, at least 256 per channel |
| **PA-4**: one switch moves the sense divider's bottom end, so the ratio is measured at every calibration | **No switch and no direct sense input (owner, 2026-11-12, D-V2-5). The ratio is measured by a jumper wire (V2-5)** at every calibration: the wire moves the divider's bottom end between two nodes, the job version 1's switch did, and the host reads the tap in each position and verifies the wire's position from the readings (VT-22). **It is one manual action per calibration (owner, 2026-11-12):** the wire is fitted together with the tee cable at the start and removed with it at the end, the host prompts for both and takes every reading it needs in that one session (the wire-off readings before it is fitted or after it is removed), and no procedure asks for a second touch of the board. While it is fitted, the ladder tap it loads is not used as a calibration point of the Due ADC. **The sense tap never goes below ground or above the precision ADC's supply in any wire state, by hardware alone (owner, 2026-11-12): no host action is assumed**, since the ADS1115's datasheet forbids the overdrive *(check: SBAS444E 7.3.1)*. Passive parts may be added for it. That means: the bottom end has a **permanent default**, tied to the REF3030E through a resistor, so with the wire off the tap stays in range over the AWG's whole −1.68 to +2.23 V window, which is also its state in normal use; **the wire's second position is a node that keeps the tap in range over the same whole window** (with k = 1/2 as first drawn, any node from 1.68 V up to the +3.3 V rail does, the low end keeping the tap at or above 0 V at −1.68 V, while at the lowered top end (+2.23 V) the tap stays under 3.3 V for any node up to the rail, derived; the design restates the bounds for its k, which is 0.4 in the current design. A measured ladder tap such as the one near +2.25 V serves, read with the wire in place since the divider loads it); and **any wrong position the headers allow is survived passively**, for example by a series resistor and a clamp at the ADC input, with the current inside the datasheet's rating and the other inputs' readings undisturbed *(check)*. The ratio comes from the change in the tap between the two positions at one AWG level, ΔV_tap = (1 − k) × ΔV_bottom, so both bottom nodes are ones the precision ADC reads, or the default resistor's drop is in the equation; the design shows which. Nothing of the AWG's node reaches a precision-ADC input except through the divider |
| **PA-3, PA-4**: the ratio switch's Due pin D40 | Free |
| **The sense divider**: two 100k 0.1%, k = 1/2 | Basic 1%. Its ratio is measured at every calibration, so its tolerance does not reach SC-7; the design confirms its drift over one calibration session is inside SC-7's fit share, and sets k and its bottom end so −1.68 to +2.23 V stays inside the precision ADC's input range |
| **PA-9, D11**: the ladder is eight 249 Ω 0.1% resistors on A2 to A9, up to 8 taps | **Kept, Basic 1%, six taps** (the top tap and five below it), **two of them measured**. The top tap is the reference itself, so AREF tracking (PA-8) is not affected. One tap below it, near two thirds of full scale, is read by the precision ADC at every calibration (the other input goes to the sense divider's bottom node, section 3.4). **They are checks, not calibration anchors (D-V2-13):** the scope's accuracy comes from the tee fit alone, because the precision ADC's channel match and offset on the taps exceed the Due ADC nonlinearity they would correct (the design's study: the fit alone holds the extrapolated top of the range to 0.26 to 2.28 mV, with the taps added 3.1 to 5.7 mV). The measured taps serve the warm-up criterion (PA-3), a between-calibration check of the Due ADC's gain and offset, and the fault check. The other four taps are not measured: they are known to about 1% from the resistor values, and serve as a fault check of the Due ADC pins and as quiet DC sources for its noise floor across the range, never as calibration points. **PA-9's minimum becomes two measured taps (the top and one below it) plus ground.** The measured taps' ratios drift with their 1% resistors between calibrations (about 0.13% over 10 K, the design's figure); since no tap corrects a reading, that drift does not enter SC-7 and sets no recalibration threshold, and a between-calibration check reports a disagreement larger than it as a fault. Tap impedance stays under PA-9's leakage limit. The rule that the Due does not read the taps while the precision ADC converts stays (PA-3), since the ladder still runs straight off the reference |
| **PA-3**: one precision-ADC IC with its own multiplexer, no external multiplexer | **One converter** (V2-8), still with no external multiplexer |

### 3.4 The precision ADC's four inputs (V2-8)

| Input | Node | Use |
|---|---|---|
| 1 | REF3030E output, the ladder's top tap | The accuracy anchor: every other reading is a ratio to it |
| 2 | The AWG-sense divider's tap | The AWG at the BNC during the tee calibration (PA-3) |
| 3 | The sense divider's bottom node, read as a differential pair with input 2 and through a resistor matching input 2's source impedance | The divider ratio (PA-4, D-V2-14): the reference's scale is rebuilt on this input with the wire off, so the ratio rests on one pair rather than on two inputs' gains |
| 4 | A ladder tap near two thirds of full scale | The Due ADC's second measured point, a check (PA-9, D-V2-13) |

There is no spare input.

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

## 5. Layout and routing

The layout rules LR-1 to LR-10 and their check VT-19 (afe.md section 11.1)
hold unchanged. The shared negative rail (V2-1) gives LR-6 scope branches
on that rail as well as the AWG's, and VT-20 measures the coupling left
through it.

## 6. Verification added

| ID | Test | Covers |
|---|---|---|
| VT-20 | Coupling through the shared negative rail: the AWG stepping full scale into 50 Ω while each scope channel holds a DC input, and the reverse, each reading's change against SC-9 and AW-6 | V2-1, SC-9, AW-6 |
| VT-21 | The jumper ratio measurement: the ratio from the jumper's two positions against the same ratio read by an external meter, three times with the wire removed and refitted between them | PA-4, V2-5, SC-7 |
| VT-22 | Any calibration jumper the procedure names: left off, in each wrong position the headers allow, and in the right one, each with the AWG at both ends of its window and the host taking no protective action; the pins stay inside PR-2 and the sense tap inside the precision ADC's input range in every case, and the host then stops on each wrong case | V2-5, PR-2, PA-4 |
| VT-6 | As version 1, plus the indefinite short of section 3.2 with the package temperature logged | PW-3 |
| VT-12 | As version 1, now also setting the recalibration threshold of section 4's SC-7 row | EN-1, SC-7 |

## 7. Decisions for the owner

| ID | Decision | Recommendation |
|---|---|---|
| D-V2-1 | The per-board cost target | Set it once the design has priced version 2, against version 1's $37.0 to $37.4 at 20 boards. The switches (about $5.70), V2-3 (about $5.70) and the converter (about $5.60 to $6.70) together remove roughly $17 to $18 per board at 20 before the op-amp change (derived) |
| D-V2-2 | DF-3 before calibration and the hardware differential mode, at the design's 1% worst case | Accept: after calibration stays at 44 dB, and SM-6 already holds the hardware mode only to the before-calibration figure |
| D-V2-3 | EN-1's uncalibrated drift, and SC-7 held by a tighter recalibration threshold rather than a wider limit | Accept both, with the threshold set by VT-12. On the design's first scope values the uncalibrated gain drift is 0.21% over 20 K (derived), against version 1's 0.2% |
| D-V2-4 | AW-4 at 51 Ω if no Basic combination reaches 50 Ω ±1% | Decide only if the design finds no combination |
| D-V2-5 | The ratio measurement: a direct sense input, or a jumper | **Decided 2026-11-12: the jumper.** No direct sense input; the freed precision-ADC input measures a second ladder tap |
| D-V2-6 | The precision ADC: one ADS1115-class converter reading the REF3030E ratiometrically (V2-8), in place of the ADS124S08, with three of the ladder's taps measured (PA-9) | Accept, if the design shows SC-7's fit share from the ADS1115's datasheet linearity and noise, and JLC stock is adequate. It stays on every board, as in version 1 |
| D-V2-7 | The AWG's indefinite short | **Decided 2026-11-12: the AWG's top end is lowered until the short stays inside the op-amp's supply-pin rating**, about +2.05 V for the TPH2502 (AW-1, PW-3), rather than a current limiter or a short past the rating. At the original +3.0 V the short put 75 to 79 mA through the supply pin against its 60 mA |
| D-V2-8 | The AWG's top end into 50 Ω | **Decided 2026-11-12: set by the chosen op-amp's output swing, no new rail** (AW-1) |
| D-V2-9 | SC-3's 1 MΩ from 1% Basic parts | **Decided 2026-11-12: nominal within 1%, the parts' spread allowed on top** |
| D-V2-10 | The scope's offset centre | **Decided 2026-11-12: from the REF3030E**, on the conditions in section 3.1 |
| D-V2-11 | The frequency ceiling and sharing one dual between the scope channels | **Decided 2026-11-12: nothing above 10 MHz, cost first** (V2-9); the scope channels share one dual (SC-9) |
| D-V2-12 | The AWG's top end against the short limit and the DAC window | **Decided 2026-11-12 by the spec lead under the owner's delegation.** No resistor set meets both the 92% window use and the short limit over AREF 3.20 to 3.30 V, because the DAC window scales with AREF. The short limit stays a hardware guarantee (no firmware clamp, as for PA-4's tap); the AWG offset comes from the REF3030E; AW-1's top becomes the worst-corner top end the design guarantees, +1.71 V, with each board's actual top measured at calibration; and PR-4's forced-voltage level is restated from the supply-pin rating. A short held through a Due reset, while DAC0 falls from its 3.3 V reset level, puts about 75 mA through the supply pin for the 0.2 to 0.3 s the DAC sits above its window top *(check: the recorded reset trace)*; it needs a short and a reset at once, and is accepted as a transient double fault; AW-5 is judged at the DAC's own output codes, where it passes |
| D-V2-13 | The ladder's measured taps as calibration anchors | **Decided 2026-11-12 by the spec lead under the owner's delegation: not anchors.** Adding them to the tee fit made the extrapolated top of the scope's range worse, not better, because the precision ADC's channel match and offset exceed the nonlinearity they would correct; so they stay as checks (warm-up, between calibrations, faults), their drift leaves SC-7's budget, and the 10 K recalibration rule stands rather than tightening to 7.5 K |
| D-V2-14 | The sense ratio's share of SC-7 | **Decided 2026-11-12 by the spec lead under the owner's delegation: the sense ratio keeps its 0.05%, on the tracking case, and the calibration block as a whole about 0.24%, inside SC-7's ±0.5%.** On the datasheet's 0.1% gain channel match, the restructured ratio (input 3 on the divider's bottom node, read differentially with input 2 and impedance-matched) reaches 0.05% only if the two inputs' common-mode impedances track, which the datasheet does not specify. They are one sampling capacitor behind one multiplexer, so tracking is the physical expectation and the case this budget takes: the whole SC-7 stack, worst case and linear at 10 K since calibration, is then 0.351% and 2.13 mV against ±0.5% and 5 mV (the reference 0.129%, the sense ratio 0.050%, the extrapolated tee fit 0.064%, the scope's own drift 0.108%; the design's table). If the inputs spread independently by ±25%, it is 0.526% linear (0.288% RSS), shown as information. VT-21 measures it on the board; if the inputs are found not to track, the lever is a lower source impedance at the converter within the reference's load limit, not an Extended part |
