# AFE shield BOM and cost, per board and per order (2026-11-11, owner's cost cuts, domestic order)

**Approved design, reconciled against `docs/afe.md` at e510edd** (read, not
taken from a summary; mismatches are listed under "Reconciliation with
afe.md" at the end). The ADS124S08IPBSR replaces the MCP3564, calibration
is by BNC tee with the sense at the AWG's BNC (PA-3) and a ratio switch on
the sense divider (PA-4), the reference is the REF3030 **E grade** (PA-2),
and C2 stays provisional, built from Basic 12 / 20 pF only.

**Owner decisions, 2026-11-11 (evening; `docs/afe.md` 24b642b "trim the AFE
towards a $35 board"), all in the tables below:**
- **B:** the OPA365 reference buffer and its 100 nF are removed. The ladder
  stays eight 249R 0.1 % with six taps and runs directly off the REF3030E
  (PA-8). That is 2.26 mA, inside the REF30E's 10 mA source rating (load
  regulation, SBVS032K 6.5).
- **C:** both scope Vmid buffers become one TLV9062IDR (C398355, Extended,
  SOIC-8). Per channel the loop is 4 x 1R in parallel, 4.7k, 1 uF C15849, and
  6 x 10 uF C15850 + 100 nF. It replaces 5 x 1R, 4.7k, 2 x 1.5 nF, 2 x 10 uF,
  100 nF and an OPA365 per channel. **The 1.5 nF C1595 leaves the BOM** (its
  only placements were the four HF-feedback parts).
- **k = 1/2 sense divider:** 2 x 100k (one fewer).
- **100k C394537 from the AWG's Vmid node to S1** (the ratio switch's
  Vmid-side throw), in place of a 4.7k. This BOM never carried a 4.7k there,
  so the 100k is added and the ratio switch's 4.7k control pull-down stays.
  If the 4.7k meant was that pull-down, the 4.7k count is one less (-$0.003
  per board) *(check)*.
- **REFP0 = 2 x 100 nF**: the 10 uF and its 1R || 1R || 1R are removed.
- **ADC-pin clamps:** one BAT54S C7420333 per scope ADC pin, after Riso:
  pin 1 to GND, pin 3 to the ADC pin, pin 2 to +3.3 V_A. Two placements, no
  new type.
- **Ratio-switch clamps (D7, D8):** one BAT54S C7420333 on each of the
  TMUX1119 ratio switch's (U12) D and S1 pins, wired the same way: pin 1 to
  GND, pin 3 to the node, pin 2 to +3.3 V_A (`kicad/design.py`;
  `sim/powercal` C1-q). Two placements, six joints, no new type.
- **C2 = 20 || 12 || (12 s 20) pF per channel**, from `sim/scope/netlib.py`
  `P_HZ` (39.5 pF, Basic types only): 2 x 12 pF and 2 x 20 pF per channel.
  No 39 pF part is in the BOM, nor is any other type C2 needs.
- **Ordering is domestic** (JLC China), with the fee rules and prices of the
  domestic section, at 6.6912 CNY per USD *(check)*, PCB included. The
  international figures stay alongside for reference.

Before that: the design
after SM-5 was dropped. Earlier the same day: the early
BOM (`bom-2026-11-11-early.md`); the low-impedance (route (c)) BOM this
replaces is not kept. The plain-text list with provisional reference
designators is `bom.txt`, generated from the same counts. Read-only pass:
no simulation was run for this file.

**Sources.** Coordinator's design statement of 2026-11-11 (afternoon);
`sim/scope/netlib.py` `P_HZ` (1 Mohm: R1 = R3 = 330k + 330k + 100k, R2 330k,
C1 12 pF, Rnp 680, shared 249R + 10 uF sense filter; its T-switch injection
is replaced by the tee);
`sim/awg/run.py` (buffered DAC0, the AWG's own Vmid, 249R injection
isolation); `sim/powercal` (stiffened per-channel Vmid, ladder 8 x 249R
with 6 taps, two 10 uF per LM27762 output, 5 V bulk, 1R branches, no
ferrite, negative divider 330k || 100k over 3 x 330k, bleed 4.7k);
`docs/jlcpcb-parts.md` for class, stock and the one-day price reading
(USD *(check)*); LM27762 capacitors from SNVSAF7C 7.2.2.4.

**Precision ADC: ADS124S08IPBSR** (C2870171, TQFP-32, 12 analog inputs;
AIN6/AIN7 are shared with REFP1/REFN1 and AIN8-AIN11 with GPIO0-3), on
external reference REFP0/REFN0 from the REF3030E. Per PA-3 it reads the
AWG output through the sense divider, that divider's ratio (PA-4) and every
ladder tap (PA-9); it no longer reads the DAC0 buffer. The channel
assignment is the design's, not this file's. The ladder is three 249R in parallel plus
five in series (6 taps), unchanged in parts.

**Tee calibration:** the four injection TMUX1119, the 249R injection
isolation resistor, their four decouplers and the D40/D41 pull-downs are
removed. Added: one TMUX1119 ratio switch with a 4.7k pull-down, a 100 nF
decoupler and a BAT54S clamp on each of its D and S1 pins. The AWG-sense divider is **two 100k 0.1 % (k = 1/2)**: 100k from
the AWG's BNC node, after the 49.9 ohm back-termination, to the tap, and
100k from the tap to the far end. The ratio switch (S1) moves the far end
between the AWG's mid-rail reference, through a 100k, and the reference top
tap (PA-4).

**Excluded:** BNCs and headers (owner hand-solders them; priced separately
under "Owner-soldered parts" below), test points, shipping, PCB fabrication (*(check)*, below). BAV99 x 3: unfitted
footprints, no part, no fee. AREF series 0 ohm (PA-7): one 0603 footprint,
unfitted by default (MC-11), no part, no fee. Test point (D5's 3a): not
listed. The ADC-pin BAT54S clamps are carried again (owner, 2026-11-11), one
per scope ADC pin.

## Part types

`n` = placements per board. "@20" = JLC tier for 20 x n pieces; "@100" =
tier for 50 x n pieces, because **100 boards are two Economic orders of 50**
(Economic PCBA takes 2-50 boards per order, JLC capabilities page, read
2026-11-11). **Every tier is now read** (JLC parts search, 2026-11-11,
cross-checked on the raw part page for C14663), and each unit price is the
tier that actually holds 20 x n or 50 x n pieces. The earlier rule, which
used only the qty-20 and qty-100 tiers as an upper bound, is retired. The
100 nF C14663 re-reads at 0.0164 (1-499) and 0.0130 (500-1499), against the
0.0062 recorded earlier in `jlcpcb-parts.md`, so a price can move by that
much between readings *(check before ordering)*. Bold flags: (a), (b), (c) are the provisional items below;
"placeholder" and "assumed" are pending.

| type | value | pkg | LCSC | class | n | function: placements | joints | unit @20 | unit @100 | $/board @20 | $/board @100 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 100k | 100k 0.1 % 10 ppm/K | 0603 | C394537 | Extended | 9 | scope R1 = 330k+330k+100k, 100k part (1/ch) 2; scope R3 = 330k+330k+100k, 100k part (1/ch) 2; +3.3 V_A FB bottom (LM27762 R2) 1; OUT- FB R3 = 330k || 100k, 100k part 1; AWG-sense divider, k = 1/2: BNC node to tap 1, tap to S1 common 1; AWG Vmid node to S1 1 | 18 | 0.1223 | 0.1223 | 1.1007 | 1.1007 |
| 330k | 330k 0.1 % 25 ppm/K | 0603 | C351655 | Extended | 19 | scope R1, 330k parts (2/ch) 4; scope R3, 330k parts (2/ch) 4; scope R2 (1/ch) 2; scope Vmid divider 2; AWG Rbpl (DAC0 buffer input to GND) 1; AWG Vmid divider 2; OUT- FB R3 = 330k || 100k, 330k part 1; OUT- FB R4 = 3 x 330k || 3 | 38 | 0.0805 | 0.0716 | 1.5295 | 1.3604 |
| 174k | 174k 0.1 % 25 ppm/K | 0603 | C861163 | Extended | 1 | +3.3 V_A FB top (LM27762 R1) 1 | 2 | 0.0421 | 0.0421 | 0.0421 | 0.0421 |
| 953R | 953R 0.1 % 25 ppm/K | 0603 | C2984375 | Extended | 6 | scope RF (1/ch) 2; AWG Ra 1; AWG Rg 1; AWG Rb, 953 part 1; AWG Rf, 953 part 1 | 12 | 0.0290 | 0.0226 | 0.1740 | 0.1356 |
| 249R | 249R 0.1 % 10 ppm/K | 0603 | C2692731 | Extended | 15 | scope RG (1/ch) 2; 3.3 V sense filter (shared) 1; AWG Rb, 249 || 249 2; AWG Rf, 249 || 249 2; calibration ladder, 6 taps 8 | 30 | 0.1217 | 0.1025 | 1.8255 | 1.5375 |
| 49.9R | 49.9R 0.1 % 10 ppm/K 250 mW | 1206 | C869759 | Extended | 1 | AWG output series Rs 1 | 2 | 0.1238 | 0.1079 | 0.1238 | 0.1079 |
| 680R | 680R 1 % | 0603 | C23228 | Basic | 3 | scope Rnp (1/ch) 2; AWG DAC0 buffer Rbin 1 | 6 | 0.0021 | 0.0021 | 0.0063 | 0.0063 |
| 22R | 22R 1 % (page; code J = 5 %) | 0603 | C23345 | Basic | 8 | scope Riso (1/ch) 2; AWG Rb, 22 part 1; AWG Rf, 22 part 1; AWG supply filter 22 || 22 per pin 4 | 16 | 0.0017 | 0.0017 | 0.0136 | 0.0136 |
| 4.7k | 4.7k 1 % | 0603 | C23162 | Basic | 7 | scope Vmid DC feedback (1/ch) 2; +3.3 V_A bleed 1; D38-D39 range pull-downs 2; ratio-switch control pull-down 1; ADS124S08 CS (D36) pull-up 1 (all three computed under "Control-pin pull resistors") | 14 | 0.0028 | 0.0028 | 0.0196 | 0.0196 |
| 1R | 1R 1 % 400 ppm/K | 0603 | C22936 | Basic | 11 | 5 V feed sense 1; scope op-amp supply branch (1/ch) 2; scope Vmid isolation 4 x 1R || (4/ch) 8 | 22 | 0.0031 | 0.0031 | 0.0341 | 0.0341 |
| 12 pF | 12 pF C0G 5 % 50 V | 0603 | C38523 | Basic | 8 | scope C1 across R1 (1/ch) 2 (**(c)**); scope C2 = 20 \|\| 12 \|\| (12 s 20), 12 pF parts (2/ch) 4 (**(c)**); AWG Cf 1; AWG Vmid tap 1 | 16 | 0.0068 | 0.0068 | 0.0544 | 0.0544 |
| 20 pF | 20 pF C0G 5 % 50 V | 0603 | C1648 | Basic | 4 | scope C2 = 20 \|\| 12 \|\| (12 s 20), 20 pF parts (2/ch) 4 (**(c)**) | 8 | 0.0088 | 0.0088 | 0.0352 | 0.0352 |
| 100 nF | 100 nF X7R 10 % 50 V | 0603 | C14663 | Basic | 18 | OPA354 supply pin, scope branch (1/ch) 2; 3.3 V sense node 1; scope Vmid node (1/ch) 2; TLV9062 supply 1 (**assumed**); AWG DAC0 buffer supply 1; AWG Vmid buffer supply 1; AWG op-amp V+ and V- pins 2; LM27762 VIN 1 (**assumed**); REF3030 VIN 1 (SBVS032K); ADS124S08 DVDD, IOVDD tied 1 (SBAS660); ADS124S08 REFP0 to REFN0, 2 x 100 nF 2; TMUX1119 range (1/ch) 2 (**assumed**); TMUX1119 ratio switch 1 (**assumed**) | 36 | 0.0164 | 0.0130 | 0.2952 | 0.2340 |
| 1 uF | 1 uF X5R 10 % 50 V | 0603 | C15849 | Basic | 5 | LM27762 flying capacitor C1 1; REF3030 VIN bulk 1 (SBVS032K); ADS124S08 AVDD, at least 330 nF 1 (SBAS660); scope Vmid loop (1/ch) 2 | 10 | 0.0112 | 0.0112 | 0.0560 | 0.0560 |
| 10 uF | 10 uF X5R 10 % 25 V | 0805 | C15850 | Basic | 24 | 5 V bulk = LM27762 CIN 2; LM27762 CPOUT 2; LM27762 OUT+ 2; LM27762 OUT- 2; scope op-amp supply branch (1/ch) 2; 3.3 V sense filter (shared) 1; scope Vmid tap 1; scope Vmid node (6/ch) 12 | 48 | 0.0236 | 0.0202 | 0.5664 | 0.4848 |
| OPA354 | 250 MHz RRIO op-amp | SOT-23-5 | C36384 | Extended | 2 | scope op-amp (1/ch) 2 | 10 | 1.6919 | 1.3519 | 3.3838 | 2.7038 |
| OPA365 | 50 MHz RRIO op-amp | SOT-23-5 | C96626 | Extended | 3 | AWG op-amp 1; AWG DAC0 buffer 1; AWG Vmid buffer 1 | 15 | 2.3375 | 2.1528 | 7.0125 | 6.4584 |
| TLV9062 | dual 10 MHz RRIO op-amp, TLV9062IDR | SOIC-8 | C398355 | Extended | 1 | both scope Vmid buffers (one amplifier per channel) 1 | 8 | 0.1187 | 0.0942 | 0.1187 | 0.0942 |
| LM27762 | +3.3 V_A / -2.07 V | WSON-12+EP | C473398 | Extended | 1 | AFE rails (leadless: X-ray) 1 | 13 | 0.7912 | 0.6833 | 0.7912 | 0.6833 |
| REF3030E | 3.0 V ref, **E grade** REF3030EAIDBZR, 0.1 %, 15 ppm/K max (0-70 C and -40-125 C), 20 (-40-85 C) (PA-2) | SOT-23 | C54120492 | Extended | 1 | calibration reference 1 | 3 | 0.8075 | 0.7078 | 0.8075 | 0.7078 |
| ADS124S08 | 24-bit ADC, 12 inputs, ADS124S08IPBSR | TQFP-32 | C2870171 | Extended | 1 | precision ADC 1 | 32 | 7.4489 | 6.7150 | 7.4489 | 6.7150 |
| TMUX1119 | SPDT switch | SC-70-6 | C2673327 | Extended | 3 | scope range switch (1/ch) 2 (**(b)**); tee ratio switch 1 | 18 | 1.8995 | 1.6739 | 5.6985 | 5.0217 |
| BAT54S | series Schottky pair 30 V | SOT-23 | C7420333 | Preferred | 8 | AWG op-amp V+ and V- (one die each) 2; AWG DAC0 buffer supply 1; AWG Vmid buffer supply 1; scope ADC-pin clamp after Riso, pin 1 GND / 3 ADC pin / 2 +3.3 V_A (1/ch) 2; ratio-switch clamp on D and S1 (D7, D8), same pins 2 | 24 | 0.0129 | 0.0129 | 0.1032 | 0.1032 |

The 22R's page says 1 %, its code reads 5 % *(check)*. LM27762 joints count
the exposed pad *(check)*. Tiers re-read 2026-11-11 for the changed rows:
ADS124S08IPBSR C2870171 is Extended with 1,257 in stock, at 8.652 (1-9),
7.4489 (10-29), 6.715 (30-99) and 6.1004 (100+). TMUX1119DCKR is at 2.4683
(1-9), 2.1185 (10-29), 1.8995 (30-99) and 1.6739 (100-499), with 7,216 in
stock. The full tier tables used are in the batch-cost section below.

**REF3030 grade: E, per PA-2 and SC-7.** Read 2026-11-11 (raw part pages and
the JLC parts search). Drift figures are from SBVS032K 6.5 and 6.6.

| grade | part | LCSC | class | JLC stock | 1-9 / 10-29 / 30-99 / 100-499 | accuracy, drift (max) |
|---|---|---|---|---|---|---|
| **E (the design)** | **REF3030EAIDBZR** | **C54120492** | Extended | **996** | 0.9122 / **0.8075** / 0.7078 / 0.6326 | 0.1 %; 15 ppm/K (0-70 C), 20 (-40-85 C), 15 (-40-125 C) |
| A (not used) | REF3030AIDBZR | C38423 | Extended | 82,588 | 0.5019 / 0.3809 / 0.3221 / 0.2698 | 0.2 %; 50 ppm/K (0-70 C), 75 ppm/K (-40-125 C) |

The E grade costs **$0.4266 per board more** than the A grade at 10 and 20
boards, $0.4103 at 5, and $0.3857 at 100 (orders of 50, the 30-99 tier). That agrees with PA-2's "+$0.43". It is
the same footprint, with no fee change. SC-7 says the A grade fails without
a meter calibration of every board (0.56 %), so it is not an option for the
design. Stock: 996, against 100 needed for 100 boards. The only E-grade
3.0 V REF30xx found is REF3030EAIDBZR: the search lists no REF3030EAIDBZT and
no second source. The REF30E's capacitive-load table (0.1-22 uF, ESR
10-500 mohm) is the one the REFP0 network below is built to meet.

**LM27762 capacitor set** (SNVSAF7C 7.2.2.4, "5 external capacitors"): CIN
= the 5 V bulk 2 x 10 uF (2 uF effective minimum, 4.7 uF typical); flying
C1 = 1 x 1 uF C15849 (0.47-1 uF recommended); CPOUT 2 x 10 uF (4.7 uF
typical, 2 uF effective minimum; a C15850 at -5 V keeps about 4.5 uF);
OUT+ and OUT- 2 x 10 uF each (powercal). EN+/EN- to VIN, PG to ground: no
parts.

## Counts

| | |
|---|---|
| part types fitted | **23**: 13 Extended, 1 Preferred, 9 Basic (international); 14 Extended, 9 Basic (domestic: the BAT54S is Extended there) |
| Extended ($3.07 international, 20 CNY domestic, per order each) | 100k, 330k, 174k, 953R, 249R, 49.9R, OPA354, OPA365, TLV9062, LM27762, REF3030E, ADS124S08, TMUX1119DCKR |
| Preferred (no fee, international only) | BAT54S C7420333 |
| Basic | 680R, 22R, 4.7k, 1R, 12 pF, 20 pF, 100 nF, 1 uF, 10 uF |
| placements / SMT joints per board | **159 / 401** (157 / 395 before D7 and D8; 154 / 390 before the owner's cuts; 151 / 381 before the clamps and C2) |
| leadless pieces (X-ray) | 1 per board (LM27762) |

Against the previous pass: OPA365 6 -> 3, TLV9062 new (one type in, the 1.5
nF out), 1R 16 -> 11, 1.5 nF 4 -> 0, 10 uF 17 -> 24, 1 uF 3 -> 5, 100 nF
19 -> 18, 100k unchanged at 9 (one out of the divider, one in to S1).

## Cost summary

Economic PCBA (price page, "Last updated on Oct 22, 2026", read
2026-11-11): setup $8.18, stencil $1.53, $3.07 per Extended type, $0.0016
per joint, packing free, X-ray per leadless piece (1-10 $1.64, 11-50 $0.82,
51-200 $0.49). Whether an X-ray quantity is priced wholly at its tier or
tier by tier is not stated; both are given as "whole / graduated"
*(check)*.

| per order, international (reference) | 20 boards (1 order) | 100 boards: each of 2 orders of 50 |
|---|---|---|
| parts | $624.81 | $1,385.48 |
| setup + stencil | $9.71 | $9.71 |
| loading, 13 Extended | $39.91 | $39.91 |
| SMT, 401 joints | $12.83 | $32.08 |
| X-ray, whole / graduated | $16.40 / $24.60 | $41.00 / $49.20 |
| **fees** | **$78.85 / $87.05** | **$122.70 / $130.90** |
| **order total** (PCB excluded) | **$703.67 / $711.87** | **$1,508.18 / $1,516.38** (both: $3,016.36 / $3,032.76) |

| per board, international, PCB excluded | 20 boards | 100 boards (2 x 50) |
|---|---|---|
| parts | $31.24 | $27.71 |
| fees | $3.94 / $4.35 | $2.45 / $2.62 |
| **total** | **$35.18 / $35.59** | **$30.16 / $30.33** |

**The order is domestic; its totals are in "JLC China (domestic)" at the
end**: $32.80 / $33.18 per board at 20 boards and $27.57 / $27.72 at 100,
JLC with PCB; $37.11 / $37.49 and $31.64 / $31.79 with the owner-fitted
parts.

For reference: one order of 100 at Economic rates (not offered) would be
$41.19 / $41.44 per board; one Standard PCBA order of 100 (setup $25.56,
stencil $8.21, $1.53 per type x 23, fixture 5 x $8.21 *(check that it
applies)*, fiducials and rails required) $41.83 / $42.07. Both reference
figures are from the MCP3564 / T-switch design and were not recomputed.


**Not in the totals:** PCB fabrication, 2-layer 100.0 x 53.34 mm (outline below) at qty 20
and 100, **not read** *(check)*: JLC's quote is computed in the browser and
the pages fetched carry no price. Hand-soldering labour $3.58 per order
(owner solders). "Confirm parts placement" $0.45 (optional), the
Economic/Standard handling fee, shipping.

## Top 10 cost lines, per board

| rank | line | @20 | @100 (2 x 50) | share @20 |
|---|---|---|---|---|
| 1 | ADS124S08 x 1 | 7.45 | 6.72 | 21 % |
| 2 | OPA365 x 3 | 7.01 | 6.46 | 20 % |
| 3 | TMUX1119DCKR x 3 | 5.70 | 5.02 | 16 % |
| 4 | OPA354 x 2 | 3.38 | 2.70 | 10 % |
| 5 | Extended loading fee | 2.00 | 0.80 | 6 % |
| 6 | 249R 0.1 % x 15 | 1.83 | 1.54 | 5 % |
| 7 | 330k 0.1 % x 19 | 1.53 | 1.36 | 4 % |
| 8 | 100k 0.1 % x 9 | 1.10 | 1.10 | 3 % |
| 9 | X-ray, LM27762 (whole tier) | 0.82 | 0.82 | 2 % |
| 10 | REF3030E x 1 | 0.81 | 0.71 | 2 % |

International prices; share of the $35.18 total. The ADS124S08, LM27762 and REF3030E are one
placement each, so an order of 50 takes their 30-99 tier.

## Provisional items and their deltas

The tee ((a) in the earlier pass) is adopted and is in the tables.

| item | in the tables | delta, $/board @20 / @100 | fees |
|---|---|---|---|
| **(b) cut 4**: 3157-class parts replace the 2 range TMUX1119 (evaluation pending; placeholder $0.10-0.30 each *(check)*) | 2 x TMUX1119 | parts **-3.38..-2.98 / -2.92..-2.52**. The ratio switch's one TMUX1119 then falls to the 10-29 / 30-99 tiers. -12 joints plus the 3157's | +1 Extended type, +$3.07 per order: the TMUX1119 stays for the ratio switch, and every 3157-class part searched is Extended (`jlcpcb-parts.md`) |
| **(c) C2** | C1 12 pF; C2 = 20 \|\| 12 \|\| (12 s 20) = 39.5 pF per channel (`P_HZ`; the 100 kHz-step null is 38.96 pF) | in the tables: 2 x 12 pF + 2 x 20 pF per channel, Basic only; no 39 pF | none |

## Control-pin pull resistors

All four stay **4.7k 1 % C23162**, now on computed figures rather than
assumed ones. Sources: SAM3X datasheet 11057C (`docs/datasheets/microchip/`)
31.5.1 and Table 45-2; TMUX1119 SCDS401C 5.6 (VDD = 3.3 V +/-10 %);
ADS124S08 SBAS660C 7.5.

- **The Due's side.** After reset every PIO line is an input with its
  pull-up on (31.5.1, `PIO_PUSR` resets to 0). RPULLUP is 50 / 100 / 150
  kohm min / typ / max; VDDIO 3.0-3.6 V. PC1-PC9 are group 1: IOH 15 mA
  at VOH = VDDIO - 0.4 V, IOL 9 mA at VOL = 0.4 V (Table 45-2, note 2).
- **R66-R68, the range and ratio-switch pull-downs (D38-D40).** Worst low
  level with the internal pull-up on: 3.6 V x 4.747k / (50k + 4.747k) =
  0.312 V, plus the TMUX1119's 0.05 uA SEL leakage x 4.747k = 0.2 mV, so
  **0.31 V against SEL's VIL of 0.8 V**: 0.49 V of margin, and SEL reads
  low (S1: +/-5 V, and the AWG's Vmid on the ratio switch) at reset and
  with the pin unconfigured. The largest pull-down that still holds 0.8 V
  is 14.3k; the "about 10k" once proposed would leave 0.2 V of margin.
  Driving the line high costs the Due 3.3 V / 4.7k = 0.70 mA (0.77 mA at
  3.6 V and -1 %) per line, against 15 mA; VOH >= 2.6 V against SEL's VIH
  of 1.35 V. 4.7k stands: the margin is in the low state, which is the
  safe one.
- **R69, the ADS124S08 CS pull-up (D36), to +3.3 V_A.** CS input current
  is +/-1 uA, so the pull-up holds CS within 4.7 mV of IOVDD against VIH =
  0.7 IOVDD whatever the Due's pull-up is doing (the internal one alone
  could drop 0.15 V, and firmware may disable it). Selecting costs the Due
  IOVDD / 4.653k = 0.71 mA at 3.3 V, 0.77 mA at 3.6 V, against IOL 9 mA at
  VOL 0.4 V; VIL is 0.3 IOVDD, 0.97 V at +3.3 V_A's 3.235 V low end
  (`docs/architecture.md`, Power). 4.7k stands: it keeps the ADC deselected through reset
  and costs current only while CS is low.

## Pending, with placeholders

- ADS124S08 control pins need no parts (SBAS660 10.1.5): CLK to DGND
  (internal oscillator), START/SYNC to DGND (conversions by command), RESET
  to IOVDD (or a Due pin), DRDY unconnected (or D37), REFN0 to AVSS, REFOUT
  open with the internal reference off, REFCOM to AVSS.
- IC decoupling: one 100 nF per IC supply pin; 5 are assumed (LM27762 VIN,
  three TMUX1119, the TLV9062). The REF3030 and ADS124S08 capacitors
  are from their datasheets ("Reference and converter capacitors" below).

## Flags

- **ADS124S08IPBSR: 1,257 in stock** (C2870171): covers 20 and 100 boards.
  The MCP3564-E/ST's stock problem (42) is gone with it.
- Stock at 100 boards: 249R 1,500 of 3,875; OPA354 200 of 1,927; REF3030E
  100 of 996; others well covered. One day's reading *(check)*.
- Every tier was read once, on 2026-11-11; the 100 nF moved from 0.0062 to 0.0164 between two readings *(check before ordering)*.
- `sim/awg/run.py` still computes the negative rail from (330k + 330k +
  100k) \|\| 330k / 330k; this BOM carries powercal's approved 330k \|\| 100k
  over 3 x 330k (same types, same five placements).
- The X-ray line disappears with the leaded LM27762 replacements in
  `jlcpcb-parts.md` ("X-ray and leaded negative-rail options").

## Owner-soldered parts (not in the JLC totals)

The BNCs and the stacking headers are hand-soldered by the owner (MC-8,
MC-12, D8), so they carry no JLC fee and are bought as loose parts. Read
2026-11-11 the same way as the JLC parts: class, JLC stock
(`overseasStockCount`) and price tiers from the raw
`jlcpcb.com/partdetail/<C-number>` page, candidates found through the JLC
parts search API. LCSC's own pages were not reachable this time (its search
returned "Access Denied"), so LCSC stock is *(check)*; JLC's tiers agree
with LCSC's to within a few percent (`docs/jlcpcb-parts.md`). "@20" is the
tier for 20 x n pieces and "@100" for 100 x n, one purchase per batch.

**BNC: right-angle.** `docs/afe.md` does not say straight or right-angle;
MC-8 puts all three on one board edge, which a right-angle (edge-launch)
jack does and a straight one does not, so right-angle is the choice and a
straight part is listed as the alternative. Owner to confirm.

**Headers: from the V03 board file** (`docs/due-header-table.md`): five
1x8 (POWER0, ADCL0, ADCH0, PWML0, COMMUNICATION0), one 1x10 (PWMH0) and one
2x18 (XIO0), 86 pins, every one passed through (MC-9). The 6-pin `SPI0`
header is needed only if the precision ADC uses hardware SPI (MC-1); this
design bit-bangs SPI on D33-D36 (ADS124S08 CS on D36), so it is not counted.
The Due carries female sockets, so the shield needs long-tail
(stacking) female headers.

**Headers: a generic Arduino Mega stacking set, bought by the owner
anywhere.** The usual Mega/Due set is five 1x8, one 1x10 and one 2x18
long-pin female headers, 2.54 mm pitch, often with a 1x6 (older Mega) and
a 2x3 (ICSP) as spares. Prices read on the web 2026-11-11, single-unit
retail, no quantity pricing read:

| seller | contents | price | stock |
|---|---|---|---|
| Gogo:Tronics (NZ), "Stackable Arduino Mega Header Set For Both R2 and R3" | 5 x 1x8, 1 x 1x10, 1 x 2x18, 1 x 1x6, 1 x 2x3 (an exact match) | NZ$4.70 incl. GST | out of stock |
| RobotPark, "Arduino Mega Shield Stacking Headers" | 5 x 1x8, 1 x 2x18, 1 x 1x6 (**no 1x10**; the page says new Megas need one) | US$2.50 | sold out |
| Desertcart (AE), "shield stacking header set compatible with Arduino Mega 2560", pack of 2 | per set 5 x 1x8, 1 x 1x10, 1 x 2x18, 1 x 2x3 | AED 76 per 2 sets | not read |

Tail length: none of these pages states it *(check)*. The common Uno R3
set (Adafruit 85: 1x10, 2 x 1x8, 2 x 1x6, 2x3; no 2x18) states legs of
"all 10.5 mm" and 8.8 mm below a 1.7 mm PCB; take 10.5 mm as the typical
tail *(check on the set bought)*. Every pin in one set has the same tail, so
the shield sits level, which a mixed catalogue set does not do.

Pages: <https://sparks.gogo.co.nz/catalog/Wire-and-Connectors-37/PCB-Headers-60/2.54mm-0.1-in-100-mil-61/Stackable-Arduino-Mega-Header-Set-For-Both-R2-and-R3-917.html>,
<https://www.robotpark.com/Arduino-Mega-Shield-Stacking-Headers>,
<https://www.desertcart.ae/products/47682905-shield-stacking-header-set-compatible-with-arduino-mega-2560-pack.md>
(from a search snippet, not opened), <https://www.adafruit.com/products/85>.

**Price used for the subtotal: US$2.50 per board *(check)***, the lowest
Mega-set price read (RobotPark, sold out, single unit), plus nothing for its
missing 1x10. It is a placeholder for a set the owner buys at retail: no
seller's 20- or 100-set price was read, and two of the three listings are out
of stock.

| line | part | LCSC | n/board | unit @20 | unit @100 | $/board @20 | $/board @100 |
|---|---|---|---|---|---|---|---|
| BNC 50 ohm, right-angle THT ("Board Side Elbow", 3 GHz) | Kinghelm KH-BNC50-3511 | C2837587 (JLC stock 12,646) | 3 | 0.6506 (50-99) | 0.5640 (100-499) | 1.9518 | 1.6920 |
| Mega stacking-header set: 5 x 1x8, 1 x 1x10, 1 x 2x18, about 10.5 mm tails *(check)* | generic | none | 1 set | 2.50 *(check)* | 2.50 *(check)* | 2.50 | 2.50 |
| Standoff, M3 x 8 mm hex, female-female (material not on the page *(check)*), XHHD | M3*8MM | C66568 (JLC stock 1,211) | 1 | 0.0236 (1-99) | 0.0218 (100-1999) | 0.0236 | 0.0218 |
| Screw, M3 x 5 mm pan head, cross slot (Shuntian PM3X5) | PM3X5 | C357542 (JLC stock 10,763) | 2 | 0.0024 (1-999) | 0.0024 | 0.0048 | 0.0048 |
| Shim washer, M3 flat, 0.5 mm, only if the measured gap needs it | generic | none found at JLC | 0-1 | *(check)* | *(check)* | 0 | 0 |
| **subtotal, owner-fitted** | | | | | | **4.48 *(check)*** | **4.22 *(check)*** |

Alternatives read the same day: BNC right-angle HanElectricity
BNC-Q9-50KWE C49352232, 107 in stock (enough for 20 boards, not 100),
0.4888 (50-99) / 0.4250 (100-599); BNC straight *(mounting not stated
explicitly on the page, check)* HenryTech HL-BNC-KHDA C19712152, 1,541 in
stock, 2.0466 (30-99) / 1.8324 (100-499).

**Headers from the JLC/LCSC catalogue (not used).** No stocked, matching
stacking set exists there. The candidates were Samtec SSQ-108-03-F-S
C3323459 (1x8, 10 mm tail, 31 in stock, 1.3649 / 1.2750), SSQ-110-03-T-S
C3322872 (1x10, 57 in stock, 2.0809 / 1.6150), SSQ-118-04-G-D C6496612
(2x18, 14.83 mm tail, 4 in stock, 9.3777), and a 2x20 PC104 cut to 2x18
(ZHOURI C5307344, 12.2 mm tail, 926 in stock, 0.8141 / 0.5722; BOOMELE C35165,
6,758, 0.8582 / 0.6375). That set cost $9.72 / $8.56 per board, has too
little stock even for 20 boards (100 x 1x8 needed), and mixes 10 and 12.2 mm
tails. Optional `SPI0` pass-through, if hardware SPI is ever used: Samtec
SSQ-103-03-T-D C3323194 (2x3), 78 in stock, 0.9890 / 0.9563; the generic Mega
sets often include a 2x3. Whether a socket fits over the Due's 7.55 mm
`SPI0` pins under the shield is *(check)*.

**Standoff (MC-1, MC-12).** It goes on the Due mounting hole nearest the
overhang, (96.52, 2.54), which is 5.08 mm inboard of the Due's x = 101.6
edge. The hole is a 3.2 mm NPTH (drill and pad 3.2 mm, V03 board file), so
M3 clearance. The other candidate, (90.17, 50.8), is 11.4 mm inboard.

**Length.** The shield's underside rests on the Due's sockets, 8.47 mm above
the Due's top (STEP model); with 10.5 mm tails, 8.9 mm of pin goes into the
socket and may hold the shield slightly higher *(check: measure the mated gap
on the set bought)*. The nearest standard M3 standoff is **8 mm**: 10 mm
would jack the shield about 1.5 mm off its sockets. A gap of about 0.5 mm is
shimmed with one M3 flat washer on the Due side. The standoff should never
force the shield up. The fit is F-F with one M3 x 5 screw from below the Due
and one from above the shield: 5 - 1.6 mm board = 3.4 mm of thread at each
end, 6.8 mm in total, which clears an 8 mm through-threaded standoff (M3 x 6
would meet in the middle). The shield's hole is an NPTH at the same
coordinates; a metal standoff then bonds nothing.

**Clearance.** From the hole centre, XIO0's body starts 3.81 mm away (Y 6.35)
and ADCH0's ends 3.81 mm away (x 92.71). A hex up to about 6.4 mm across
corners and the 5 mm screw head fit; the standoff's across-flats size is not
on its page *(check)*. Parts on the Due's top around the hole were not
checked *(check)*.

**No variant (owner, 2026-11-11):** the owner keeps both scope channels and
the differential mode on every board, so one BOM covers every build and no
reduced-fit variant is priced.

**Grand total per board** (JLC total + owner-fitted, PCB fabrication and
shipping excluded; X-ray whole tier / graduated):

| | 20 boards | 100 boards (2 x 50 JLC orders) |
|---|---|---|
| JLC assembly, international, PCB excluded | $35.18 / $35.59 | $30.16 / $30.33 |
| owner-fitted (BNCs, headers, standoff), international prices | $4.48 *(check)* | $4.22 *(check)* |
| grand total, international, PCB excluded | $39.66 / $40.07 | $34.38 / $34.55 |
| **grand total, domestic, PCB included (the order)** | **$37.11 / $37.49** | **$31.64 / $31.79** |

The 5- and 10-board batches are in "Batch cost at 5, 10, 20 and 100 boards"
at the end.

## Pin check: the AFE's control pins on the Due

Sources: the V03 EAGLE schematic (`source/Arduino-DUE-V03.sch`, every
`<pinref>` on each net), `docs/due-header-table.md`, and a grep of
`drivers/`, `lib/`, `sketches/` and `apps/`. The D-to-port map is read from
the schematic (the net's U1 pin name), not from the Arduino variant table.

| Due pin | port | header.pin (x, Y) | AFE use | other connections on V03 | firmware use | alternate functions (CMSIS header) |
|---|---|---|---|---|---|---|
| D33 | PC1 | XIO0.14 (96.52, 35.56) | ADS124S08 SCLK, bit-banged | none: U1 and XIO only | none | none listed |
| D34 | PC2 | XIO0.15 (93.98, 33.02) | ADS124S08 DIN (MOSI) | none | none | A: EBI D0, B: PWML0 |
| D35 | PC3 | XIO0.16 (96.52, 33.02) | ADS124S08 DOUT/DRDY (MISO), input to the Due | none | none | A: D1, B: PWMH0 |
| D36 | PC4 | XIO0.17 (93.98, 30.48) | ADS124S08 CS, 4.7k pull-up | none | none | A: D2, B: PWML1 |
| D37 | PC5 | XIO0.18 (96.52, 30.48) | **unassigned** (was the precision DAC's CS; the DAC is gone, D5). Free for the ADS124S08 DRDY if wanted | none | none | A: D3, B: PWMH1 |
| D38 | PC6 | XIO0.19 (93.98, 27.94) | range select CH1, 4.7k pull-down | none | none | A: D4, B: PWML2 |
| D39 | PC7 | XIO0.20 (96.52, 27.94) | range select CH2, 4.7k pull-down | none | none | A: D5, B: PWMH2 |
| D40 | PC8 | XIO0.21 (93.98, 25.40) | tee ratio switch, 4.7k pull-down (pin provisional: the design statement names none) | none | none | A: D6, B: PWML3 |
| D41 | PC9 | XIO0.22 (96.52, 25.40) | **free** (the second injection switch is gone with the tee) | none | none | A: D7, B: PWMH3 |

**No clash.** Each net PIN33..PIN41 has exactly two pins in the schematic,
U1's PCn and the XIO header, so the Due has no load, pull-up, LED or other
function on any of them. The firmware never touches port C: the grep finds
no `PIOC`, no `PIO_PC*` and no `PWM->`. Its only PIO accesses are PIOA
and PIOB: `drivers/adc.c` disables the pull-ups on PA2/3/4/6 and PB15-18
(the analog inputs), the LED is PB27 (D13), and `console_port` reads PIOA
status registers. The EBI and PWM functions on PC2-PC9 are not enabled
anywhere. One SODR/CODR write on PIOC can set SCK/MOSI/CS and the three
control lines together, and none of the other AFE pins (A0-A9, DAC0, AREF,
5 V, GND, 3.3 V sense) is on port C.

Not established: Track A's Arduino core `init()` / `variant.cpp` is not in
the repository and was not read, so whether it drives PC1-PC9 at start-up is
*(check)*. After reset the PIO lines are inputs with the internal pull-up on
(SAM3X 11057C 31.5.1). The 4.7k pull-downs hold D38-D40 at 0.31 V or less
against its 50 kohm minimum ("Control-pin pull resistors"). MISO
(D35) floats onto the pull-up while CS is high, which is harmless.

## Mechanical check: BNCs on the left edge (x = 17)

Heights and footprints of the Due's left-side parts are from the STEP bodies
in `hardware/reference/arduino-due/models/components/`, placed through their
V03 footprints (body extents in X/Y above the board; z from the Due's top
surface). The models are the owner-supplied assembly's, "unqualified" by
their own README.

| Due part | body X | body Y | height | cable enters |
|---|---|---|---|---|
| X2 barrel jack (Kycon KLDHCX-0202-A model) | -1.88 to 12.32 | 3.2 to 12.8 | 11.0 | from x < 0 |
| J3 programming USB, micro-B | -1.18 to 4.55 | 18.2 to 26.3 | 2.75 | from x < 0 |
| USB1 native USB, micro-AB | -1.20 to 4.73 | 34.0 to 42.2 | 2.81 | from x < 0 |
| RESET0 button | 1.49 to 9.45 | 45.4 to 52.1 | 3.15 | from the top |
| Due female headers (POWER0 etc.) | | | 8.47 | |

**Stacking height.** The shield's underside sits on top of the Due's
sockets, 8.47 mm above the Due's top surface (model), and its top surface is
about 10.1 mm up with a 1.6 mm board. With 10.5 mm tails, 8.9 mm of pin
projects below the shield into the 8.47 mm socket. If the pin bottoms out
before the shield touches the socket top, the shield rides a little higher
*(check on the set bought)*.

**BNC body: not read.** The KH-BNC50-3511 drawing (C2837587) could not be
fetched: JLC's datasheet link is a signed storage URL that returned 403, and
LCSC's copy returned an error page. JLC lists a 9.5 mm interface and nothing
else. So its body size, its overhang past the edge and its pin length below
the board are *(check)* and the check below is conditional.

**Result, conditional on that drawing:**
- **The pins cannot reach the jack.** The jack ends at x 12.32 and the
  shield, with every BNC pin, starts at x 17.0: 4.7 mm clear laterally, at any
  pin length.
- **The barrel can.** A right-angle BNC mounted on the shield's top has its
  barrel at or above the shield's top surface, about 10.1 mm up, against
  the jack's 11.0 mm top. If a barrel sits over the jack's Y band (3.2-12.8)
  and projects more than 4.7 mm past the edge (to x <= 12.3), it hits the
  jack by up to about 0.9 mm. Edge-launch BNCs normally project well past the
  board edge *(check)*.
- **Cable access.** The DC plug, both USB plugs and the BNC plugs would all
  leave the stack to the left. The USB connectors are 2.8 mm tall and sit
  under the BNC level, but the micro-B plug bodies' height against the
  underside of a mated BNC plug is *(check)*. The DC plug enters at the jack,
  under any BNC placed in its band.
- **Room on the left edge:** after keeping clear of the jack band and of
  PWMH0 (body from Y 48.3), the edge has about Y 14 to 47, roughly 33 mm.
  Whether three BNCs fit there depends on the body width *(check)*; at the
  usual BNC flange of about 14-15 mm *(check)* only two fit.

**Proposal: put the BNCs on the right instead,** on a shield extended past
the Due: **x 17.0 to 117.0, Y 0 to 53.34 (100.0 x 53.34 mm)**, with the three
BNCs on the x = 117 edge. XIO0's body ends at x 97.79, which leaves 19.2 mm
of board for the BNC footprints. The full 53 mm of edge is available, and
the cables leave away from the USB and power plugs, with nothing of the
Due's under them. The extension overhangs the Due by 15.4 mm past its right
edge (x 101.6). It is supported only by the headers, so a standoff at the
Due's mounting hole (96.52, 2.54) or (90.17, 50.8) should carry the force of
plugging a BNC. The outline stays inside 100 x 100 mm.

If the left edge is kept, use at most two BNCs there, centred in Y 14-47
(for example about Y 22 and Y 39 *(check against the body width)*), and put
the third elsewhere. That breaks MC-8's "one board edge".

## Board outline from the V03 board

Read by parsing `hardware/reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb`
(footprint positions resolved through their rotations; `Edge.Cuts`), in
agreement with `docs/due-header-table.md`. Origin = the outline's lower-left
corner; Y up (= -y in the file).

**Due outline:** 101.6 x 53.34 mm bounding box. Straight right edge at
x = 99.06 except a nose to x = 101.6 between Y 5.08 and 37.85 (chamfered),
r = 1 mm corners. Mounting holes (3.2 mm, NPTH): (13.97, 2.54),
(15.24, 50.8), (66.04, 7.62), (66.04, 35.56), (90.17, 50.8), (96.52, 2.54).

| header | pins | pad centres x | Y |
|---|---|---|---|
| POWER0 | 1x8 | 27.94 (pin 1) .. 45.72 | 2.54 |
| ADCL0 | 1x8 | 50.80 (pin 1) .. 68.58 | 2.54 |
| ADCH0 | 1x8 | 73.66 (pin 1) .. 91.44 | 2.54 |
| PWMH0 | 1x10 | 41.656 (pin 1) .. 18.796 (pin 10) | 50.80 |
| PWML0 | 1x8 | 63.50 (pin 1) .. 45.72 | 50.80 |
| COMMUNICATION0 | 1x8 | 68.58 (pin 1) .. 86.36 | 50.80 |
| XIO0 | 2x18 | 93.98 (odd) / 96.52 (even) | 50.80 (pins 1, 2) .. 7.62 (35, 36) |
| SPI0 (only with hardware SPI) | 2x3 | 63.627 / 66.167 | 25.40 .. 30.48 |

All 2.54 mm pitch. Pad centres span x 18.796 to 96.52 and Y 2.54 to 50.80;
with the 2.54 mm header bodies, x 17.53 to 97.79 and Y 1.27 to 52.07.

**A shield of 100 mm or less in X and Y reaches every header: yes.** The
farthest header (XIO0, even row) is at x = 96.52, its body ends at 97.79,
and Y needs only 53.34. The Due is 101.6 mm wide only because of its
right-side nose, which carries no header.

**Outline: x 17.0 to 117.0, Y 0 to 53.34, 100.0 x 53.34 mm (the one carried),
with the BNCs on the overhanging right edge; see the mechanical check.**
The first trim, x 17.0 to 99.06 (82.06 x 53.34 mm, r = 1 mm corners), holds
only with the BNCs on the left. Either outline cuts:
- **the left 17 mm**, where there is no header. That removes the clash with
  the Due's barrel jack X2 (11.0 mm tall against a shield underside about
  8.5 mm up, pads x 5.69-11.68), and leaves the native USB (x 0-4.55), the
  programming USB (x 1.14-4.09) and the reset button (x 2.0-10.4)
  uncovered. It drops the Due's two left mounting holes (their edges end at
  x 15.57 and 16.84, outside the cut); the other four stay available for
  standoffs. PWMH0's body is 0.53 mm and its pad copper about 1 mm from the
  new left edge (JLC: copper at least 0.2 mm from the edge).
- **the right nose** (x 99.06-101.6, Y 5.08-37.85) and its chamfers:
  nothing is there, and XIO0's body ends 1.27 mm inside the new edge.
- Nothing in Y: the header bodies reach Y 1.27 and 52.07.

Header-free edge: after the cut only the left edge (x = 17.0) is free of
headers along its whole length, and it is crowded by the Due's jack and USB
plugs. **The mechanical check above therefore proposes x 17.0 to 117.0
(100.0 x 53.34 mm), with the BNCs on the right edge**, past XIO0 and over
nothing of the Due's. The 82.06 mm outline stands only if the BNCs go on the
left.

**JLC 2-layer price break at 100 x 100 mm: not read** *(check)*. The JLC
home page read 2026-11-11 says "PCB prototypes starting at just $2 for 5
PCBs" with no size stated, and the capabilities page names 100 x 100 mm
only as the size limit for 0.6 mm boards. Prices at 20 and 100 boards come
from the quote tool, computed in the browser, so neither the 101.6 x 53.34
nor the 82.06 x 53.34 price was read; both outlines are inside 100 x 100.

## Reference and converter capacitors (datasheets read 2026-11-11)

Sources: `models/ref3030/ref30.pdf` (SBVS032K, REF30 and REF30E) and
`models/ads124s08/ads124s08.pdf` (SBAS660C). Only existing types are used.

**What the datasheets ask:**
- **REF30E** (6.5): stable input capacitor at least 0.1 uF, stable output
  capacitor 0.1 to 22 uF with ESR 10 mohm to 500 mohm, -40 to 125 C; turn-on
  settling (2 ms to 0.1 %) is given with CL = 1 uF.
- **REF30** (6.6, the A grade, not used): no capacitive-load range in the table. 8.1:
  no output capacitor is required; with one, "take special care" with low-ESR
  and high capacitance; a 0.1 uF supply bypass is always recommended. 8.3: a
  supply bypass "greater than 0.47 uF". 8.4: low-ESR 0.1 uF ceramic at VIN.
- **ADS124S08** (pin table, 9.3.3.2, 11.4): AVDD at least 330 nF to AVSS;
  DVDD at least 100 nF to DGND, and IOVDD 100 nF only if not tied to DVDD
  (Figure 118 ties them at 3.3 V with one 0.1 uF); "connect a 100-nF bypass
  capacitor across the external reference input pins"; REFOUT needs 1-47 uF
  to REFCOM only if the internal reference is enabled (it is not here).
  Unused or command-driven pins per 10.1.5 (see Pending). AVDD 2.7-5.25 V,
  so the +3.3 V_A rail serves.

**Chosen:**

| node | parts | types | why |
|---|---|---|---|
| REF3030 VIN | 100 nF + 1 uF | C14663 + C15849 | 0.1 uF low-ESR at the pin (8.1, 8.4) and more than 0.47 uF (8.3) |
| REF3030 output = REFP0, which also feeds the ladder directly (B) | 2 x 100 nF from REFP0 to REFN0 | 2 x C14663 | SBAS660C 9.3.3.2 asks for 100 nF; the owner's network is two (decision of 2026-11-11). The 10 uF and its 1R \|\| 1R \|\| 1R are gone |
| REFN0 | tied to AVSS, no part | | SBAS660C 10.1.5 |
| ADS124S08 AVDD | 1 uF | C15849 | at least 330 nF (11.4); 100 nF is not enough and 1 uF is the smallest existing type above it |
| ADS124S08 DVDD + IOVDD (tied) | 100 nF | C14663 | 11.4, Figure 118 |

The tables above include this.

**Range checks.**
- REFP0 load: 2 x 100 nF = 0.2 uF, inside the REF30E's 0.1-22 uF, but the
  -10 % tolerance and DC bias leave little above the 0.1 uF floor, and two
  ceramics' ESR is likely below the 10 mohm floor of the REF30E's ESR
  window. Neither was read *(check: the reference's stability is the owner's
  simulated cut; the datasheet window is not obviously met)*. The ladder,
  1328 ohm, sits on the same node, and it damps as a resistive load does not
  count in the datasheet's capacitor window.
- DC-bias loss of the 10 uF X5R at 3 V was not read *(check)*; it only
  matters against the 0.1 uF floor, which it clears by far.

## Reconciliation with afe.md (e510edd)

Read against `docs/afe.md`: PA-1 to PA-9, SC-2, SC-3, SC-7 to SC-11,
AW-1 to AW-8, PW-1 to PW-7, CA-1, MC-1, MC-8, MC-9, MC-11, MC-12, D5, D8,
D11.

**Fixed in this BOM:**
1. **PA-2 / SC-7: the reference is the E grade.** The A grade was in the
   totals; it is now REF3030EAIDBZR C54120492, +$0.4266 per board, which
   matches PA-2's "+$0.43".
2. **PA-3: the precision ADC no longer reads the DAC0 buffer.** It reads the
   AWG sense, the divider's ratio and the ladder taps. The ADC description
   said "the DAC0 buffer"; corrected. The AWG's DAC0-buffer op-amp stays, as
   part of the AWG.
3. **PA-3 / PA-4: the sense divider and the ratio switch.** The designator
   notes now read 100k + 100k from the BNC node (after AW-4's
   back-termination) to the tap, and 100k from the tap to the far end, which
   the one TMUX1119 moves between the mid-rail reference and the reference
   top tap. Still 3 x 100k.
4. **PA-7: the AREF series 0 ohm** was missing; it is now listed as an
   unfitted 0603 footprint (MC-11), at no cost.

**Agree (no change):**
- **SC-3:** the 1 Mohm compensated input (R1 = R3 = 330k + 330k + 100k, R2
  330k, C1, C2).
- **MC-1:** edge headers only, no SPI0. The outline covers every header but
  not the USB / jack end, and overhangs the other end by about 15 mm; the
  BOM's x 17.0-117.0 overhangs by 15.4.
- **MC-8:** three right-angle 50 ohm BNCs, one part number, on the
  overhanging edge, owner-soldered.
- **MC-12:** a generic Mega stacking set, owner-bought.
- **PA-8:** the top tap is the reference itself, with the ladder straight off
  the REF3030E and no buffer (afe.md 24b642b; owner decision B).
- **PA-9 / D11:** eight 249R, 3 in parallel + 5 in series, six taps. More
  than six taps would need a different arrangement, not more ADC inputs,
  since the ADS124S08 has 12.
- **AW-4:** 50 ohm +/-1 %; the BOM's 49.9 ohm 0.1 % is the value PR-4 names.
- **AW-7:** the AWG's own offset reference, from +3.3 V_A.
- **PW-1:** power from 5 V only, with no load on the Due's 3.3 V pin beyond
  the sense.

**Flagged: the text looks wrong, or the BOM cannot comply:**
- **MC-1's outline, "at most 100 x 53.3 mm".** The Due is 53.34 mm in Y,
  so 53.3 is presumably 53.34 rounded. The BOM keeps 100.0 x 53.34 mm. If
  53.3 is a hard limit, the outline must shrink by 0.04 mm; the header
  bodies (Y 1.27 to 52.07) still fit.
- **MC-1's standoff "on a Due mounting hole under the overhang".** No Due
  mounting hole lies under the overhang: the Due ends at x 101.6, and its
  nearest hole, (96.52, 2.54), is 5.08 mm inboard, under the shield. The
  standoff is now an owner-fitted line on that hole (M3 x 8 F-F C66568 + 2 x
  M3 x 5 C357542). MC-12 names only BNCs and headers as hand-fitted, so the
  text should add the standoff.
- **D5 is stale.** It says "DAC0 measured by the precision ADC does its job
  (PA-3)", but PA-3 now calibrates by BNC tee, with the precision ADC
  sensing at the AWG's BNC. D5 also lists a test point in 3a, which no BOM
  line carries (test points are excluded).
- **AW-4 against PW-3.** AW-4 says the series resistor limits a short to
  "about +/-20 mA"; PW-3 says at most 30 mA (relaxed 2026-11-11). A text
  inconsistency; no part changes.
- **MC-12's design review also asks for the cost with Phase 3 fitted on only
  some boards (MC-11).** The owner keeps both channels and the differential
  mode on every board, so no variant is needed; MC-12's partial-fit cost
  sentence is then moot and could be removed.
- PA-3's warm-up uses "the precision ADC's own temperature sensor". The
  ADS124S08 has one (SBAS660C, features), so no part is needed.

## Batch cost at 5, 10, 20 and 100 boards

The owner asked for 5 and 10 as well as 20 and 100. Parts are priced at the
tier holding B x n pieces for each type, read in full 2026-11-11 from the
JLC parts search (the same record the raw part page carries). No tier was
estimated. 100 boards are two Economic orders of 50, so their tier is the
one for 50 x n.

International, for reference (the order is domestic, below). **Fees per
order:** setup $8.18, stencil $1.53, 13 Extended x $3.07 = $39.91, 401
joints x $0.0016 per board, and X-ray on the LM27762: 1-10
pieces at $1.64 (5 boards $8.20, 10 boards $16.40); 20 and 50 as before,
priced wholly at the tier / tier by tier.

**Owner-fitted per board, bought once per batch:** 3 BNC C2837587 (15 or 30
pieces: 0.7879; 60: 0.6506; 300: 0.564), the generic header set at $2.50
*(check)*, standoff C66568 (0.0236 below 100 pieces, 0.0218 at 100+), and
2 x M3 x 5 screws C357542 (0.0024).

| per board, international | 5 boards | 10 boards | 20 boards | 100 boards (2 x 50) |
|---|---|---|---|---|
| JLC parts | $35.51 | $31.81 | $31.24 | $27.71 |
| JLC fees (per order) | $61.03 | $72.44 | $78.85 / $87.05 | $122.70 / $130.90 |
| **JLC per board** | **$47.71** | **$39.05** | **$35.18 / $35.59** | **$30.16 / $30.33** |
| owner-fitted per board | $4.89 *(check)* | $4.89 *(check)* | $4.48 *(check)* | $4.22 *(check)* |
| **total per board, PCB excluded** | **$52.60** | **$43.94** | **$39.66 / $40.07** | **$34.38 / $34.55** |
| **batch total, PCB excluded** | **$262.99** | **$439.44** | **$793.27 / $801.47** | **$3,438.36 / $3,454.76** |

Where two figures are given, the X-ray is priced wholly at its tier / tier
by tier; at 5 and 10 boards both readings give the same figure.

**Excluded, and why:** PCB fabrication (2-layer, 100 x 53.34 mm) and
shipping. They were tried again 2026-11-11 and are still not read
*(check)*. The quote page's scripts call
`/shoppingCart/calculationGoodsCostsNew` and
`/shoppingCart/calculateGoodsFreight`, but under the
`/api/overseas-pcb-order/v1` prefix that serves the parts search, both
return 404 on jlcpcb.com and cart.jlcpcb.com. The real prefix, and any
login they need, were not found. The home page says only "$2 for 5 PCBs"
with no size or quantity terms. So the 5- and 10-board totals above lack
the PCB and the freight, which are a larger share of a small batch.

## JLC China (domestic) comparison

Read 2026-11-11 with curl from public pages only: no login, no account,
no quote API, no order. The question is whether ordering the same build
from JLC's domestic service (嘉立创 SMT, jlc-smt.com; PCB, jlc.com) with
a Chinese address and paying in CNY saves money.

**Exchange rate: 6.6912 CNY per USD**, Bank of China spot selling rate
(现汇卖出价 669.12 per 100 USD; 中行折算价 671.91), published 2026-11-12
05:30 Beijing time, <https://www.boc.cn/sourcedb/whpj/>. It moves daily
*(check)*.

**Short answer: about 8 % cheaper per board, and all of it is the
exchange rate.** Every domestic part price read is the international
USD price times 6.118, line for line (ratio 0.91 on 22 of 23 types at
6.6912), so the parts saving disappears if the yuan weakens to about
6.12 per USD. The assembly fees come out nearly level: a lower setup fee
and a free stencil, against more Extended types (14, not 12) at a
slightly higher loading fee.

### Domestic SMT (嘉立创 SMT) fees

Sources: the fee table in "嘉立创SMT贴片:可贴工艺\数量\交期\收费介绍"
(an image, article dated 2022-10-18),
<https://www.jlc-smt.com/help_document/id/4025.html>; the
Economic/Standard comparison image in the same article; "SMT产品类型
分类说明", <https://www.jlc-smt.com/help_document/id/30669.html>. The
jlc.com home page (read the same day) still states "SMT贴片服务 50元起贴,
1分钱1个焊点", which agrees. The live calculator
(<https://www.jlc-smt.com/calc-online>) computes in the browser and was
not read, so the figures are the published table *(check in the
calculator before ordering)*.

| item | Economic (经济型, one side) | Standard (标准型) | international Economic |
|---|---|---|---|
| setup / engineering (工程费) | 50 CNY ($7.47) per design | 150 CNY per side | $8.18 |
| stencil | free (shared, 不收费) | 50 CNY per side | $1.53 |
| loading, Extended (扩展库) | 20 CNY ($2.99) per type, capped at 800 CNY per order | 8 CNY per type, Basic or Extended, cap 800 | $3.07 per type, no cap stated |
| loading, Basic (基础库) | none (only Extended is charged) | 8 CNY per type | none |
| loading, a type bought as a pre-booked full reel | 5 CNY per type (table header) | 5 CNY | |
| SMT joint | 0.01 CNY ($0.0015) | 0.01 (0-50k), 0.008 (50k-100k), 0.007 (100k+) | $0.0016 |
| X-ray (按个数, by piece count) | 0-10: 10 CNY; 11-50: 5; 51-200: 3; 201-500: 2; 501-1000: 1.5; 1001-3000: 1; 3001+: 0.5 | same | 1-10 $1.64, 11-50 $0.82, 51-200 $0.49 |
| large-board fee | 350 CNY per order above 650 cm² | same | |
| packing / AOI | free / free | 3 CNY + 0.0002 per cm² / free | packing free |
| THT (hand) | 20 CNY setup; 0.1 CNY per joint to 10k | same | $3.58 per order + $0.0164 per joint |
| boards per order | Economic: at most 50 for a 2-layer 1.6 mm green HASL (leaded or lead-free) board, 30 for OSP (capability image in 4025); minimum not stated *(check)* | no limit; 70 x 70 mm minimum, rails and fiducials required | 2-50 |

Whether the X-ray tier price is per piece is read from "按个数" and the
table layout, not stated in words *(check)*; the international figure is
read the same way. The 650 cm² large-board fee is taken to mean one
board's area (ours is 53.3 cm²); if it meant the order's total area,
every order of 13 boards or more would pay 350 CNY more *(check)*.

**Attrition (损耗), a domestic charge the international figures above do
not carry.** <https://www.jlc-smt.com/help_document/id/42767.html>
(2024-02-21): Basic parts carry no attrition (JLC absorbs it). Extended
parts are bought with extra pieces by CNY unit price: 1-2 pins 10 / 8 /
4 / 2 / 0 extra below 0.1 / 0.2 / 0.5 / 1.0 / from 1.0 CNY; 3-8 pins 5 /
4 / 2 / 0 below 0.2 / 0.5 / 1.0 / from 1.0; more than 8 pins none; plus
0.2 % (0.4 % below 1 CNY) above one reel or 1,000 pieces. For this BOM
that was **7.34, 9.68, 9.49 and 8.34 CNY per order** at 5, 10, 20 and 50
boards before the owner's cuts (mostly the cheap resistors and the 1.5 nF);
the cuts remove the 1.5 nF's share and add about 1.5 CNY for the TLV9062
(two extra pieces), not recomputed exactly, under $0.30 per board
at 5 and less above. The same page requires every tape to be at least
8 cm long to load a feeder; at 5 boards that can force a few extra
pieces of the one-per-board ICs, but the tape pitches were not read and
it is not priced *(check)*. Whether the international service charges
attrition was not checked here; the international totals above do not
include it.

**The domestic library differs from the international one for this
BOM:** the two parts JLCPCB marks Preferred (1.5 nF C1595, BAT54S
C7420333) are plain Extended (`orderLibraryType` `expand`) on the
domestic pages, and no Preferred tier appears there, so the domestic
order has **14 Extended types** (after the owner's cuts: the 1.5 nF gone,
the TLV9062 in), 280 CNY of loading. The nine Basic
types are Basic on both. The domestic Basic library's size was not read;
an older jlc.com page (`/portal/newV2/smt.jsp`) says 689 Basic and more
than 6,000 Extended types, which is stale.

**Coupons and offers for a first, small order** (read 2026-11-11):
- **Free PCB coupons** (领券中心, <https://www.jlc.com/coupons>; rules
  <https://www.jlc.com/portal/server_guide_37595.html>, updated
  2026-09-29; <https://www.jlc.com/portal/t7i37578.html>): two coupons a
  month, 10 x 10 cm or smaller, 5 pieces, single-piece delivery, standard
  process, green mask for 1-, 4- and 6-layer, claimed by WeChat scan. The
  general coupon (通用券, any CAD tool) needs a PCB order of at least
  20 CNY paid and shipped in the previous month; without one, only the
  嘉立创EDA coupon (EDA专用券) is offered, which needs a design drawn
  natively in 嘉立创EDA. **A first order of this KiCad board qualifies
  for neither.** Free boards are now OSP, not HASL (jlc.com news
  "省钱10%:品质更好,OSP工艺替换无铅喷锡", 2026-08-24, listed in the news
  column of the pages above). A "PCB+SMT 盲盒免费券" (a few blind-box coupons in the same
  monthly draw) makes the SMT fees free and leaves only the parts to pay,
  under the same eligibility.
- **Double-11 SMT offer** (<https://www.jlc.com/portal/q7i64931.html>):
  a 300 CNY SMT processing coupon for a "new SMT customer", defined as
  one with **at least one paid and shipped PCB order** and no paid SMT
  order in the year to 3 November; usable 11-13 November 2026 only, not on
  components. A 30 %-off joint-fee coupon (焊点费七折) for any customer
  with a paid and shipped PCB order, claimable to 13 November, valid to
  31 December 2026. A brand-new account meets neither.
- **Change-material coupon** (换料费减免券,
  <https://www.jlc-smt.com/help_document/id/36630.html>): 300 CNY per
  full-reel purchase of a part, used at 15 CNY per type per Economic order
  while that reel lasts. Only worth it for a part bought by the reel.
- **Joint fee at 0.005 CNY** (<https://www.jlc-smt.com/help_document/id/42886.html>):
  only for 嘉立创EDA designs above 1 m² per order. Not this board.

So the comparison below uses **no coupon**. If the owner first places a
small paid PCB order and waits for it to ship, the joint-fee coupon
(-0.0030 CNY per joint) and next month's general free-PCB coupon (the
5-board PCB) become available; neither moves the per-board total by more
than about 1 % (the free PCB at 5 boards, 4 CNY a board).

### Domestic PCB price (2-layer, 100 x 53.34 mm, 1.6 mm, green)

No quote was read: the jlc.com order page computes in the browser
through an account API, which was not called. What is published:
- jlc.com home page: "FR-4 免费打样 ... ¥20.00 / 5片起" (from 20 CNY for
  5 pieces).
- "0元特价爆款，福利专享规则"
  (<https://www.jlc.com/portal/server_guide_4114.html>, updated
  2026-09-29): a special-price order of up to 10 boards within 10 cm is
  **20 CNY**; a non-special prototype is **20 CNY engineering fee plus
  board area at 330-350 CNY/m²** (by thickness).
- Price cut of 2026-09-14 (<https://www.jlc.com/portal/q33i63612.html>,
  its image): **double-sided 420 -> 370 CNY/m²**, prototypes and small
  batches.
- Lead-free HASL costs 30 CNY/m² beyond an engineering fee whose amount
  is not given (the same OSP news item, 2026-08-24). Leaded HASL's
  surcharge, if any, was not read.

Used here *(check every figure in the live quote)*: 5 and 10 boards
**20 CNY** (the special order; whether it holds alongside an SMT order is
not stated); 20 boards 20 + 370 x 0.10668 m² = **59.47 CNY**; each order
of 50, 20 + 370 x 0.2667 m² = **118.68 CNY**. No HASL surcharge, drill,
or small-board fee applies on the published rules (board 53.3 cm², no
side under 3 cm; `server_guide_53841`, updated 2026-09-15).

**Shipping in China** (`server_guide_4105`, updated 2026-09-16): free
inside Guangdong (SF 电商标快 up to 3 kg, JD 特惠, 优速). Outside
Guangdong, free only for a 5-piece single-board prototype ordered through
the PC assistant; otherwise charged first-weight plus extra weight
(`server_guide_4011`, `server_guide_4040`), at rates not published on the
pages read. A typical courier fee was not read *(check)* and is not in the
totals.

### Domestic part prices

Read from each part's domestic SMT page,
`https://www.jlc-smt.com/lcsc/detail/<C-number>.html`, whose embedded
record carries the library type and the CNY ladder (`priceList`); the
domestic help page above says its rules use 立创商城 (szlcsc) prices.
**szlcsc itself was not read:** `so.szlcsc.com` search and
`item.szlcsc.com` product pages answer curl with a JavaScript anti-bot
challenge, which was not worked around, so whether szlcsc's own ladder
equals the SMT library's is *(check)*. One unanswered user question on
jlc.com (2021, `q6i27817`) claims a 3x gap for a different part; it is
old and was not tested.

**Stock: not read.** The server-rendered record shows `stockNum` 0 for
every part, Basic ones included (100 nF C14663 among them), so the field
is not populated in the page and says nothing *(check stock in the BOM
matcher, ADS124S08 first)*. Every C-number resolved to the same
manufacturer part as the international BOM; **no part is missing**.

"@20" is the tier for 20 x n pieces, "@100" for 50 x n (two orders of 50),
as in the international table; USD at 6.6912.

| type | LCSC | n | domestic class | CNY ladder (from qty: price) | CNY @20 | CNY @100 | USD @20 / @100 | intl USD @20 / @100 | dom./intl @20 |
|---|---|---|---|---|---|---|---|---|---|
| 100k | C394537 | 9 | Extended | 1: 1.0605; 50: 0.842; 150: 0.748; 500: 0.587; 2500: 0.521; 5000: 0.492 | 0.748 | 0.748 | 0.1118 / 0.1118 | 0.1223 / 0.1223 | 0.91 |
| 330k | C351655 | 19 | Extended | 1: 0.712; 50: 0.565; 150: 0.492; 500: 0.407; 2500: 0.366; 5000: 0.346 | 0.492 | 0.407 | 0.0735 / 0.0608 | 0.0805 / 0.0716 | 0.91 |
| 174k | C861163 | 1 | Extended | 1: 0.257; 200: 0.219; 600: 0.198; 5000: 0.185 | 0.257 | 0.257 | 0.0384 / 0.0384 | 0.0421 / 0.0421 | 0.91 |
| 953R | C2984375 | 6 | Extended | 1: 0.166; 200: 0.13; 600: 0.109; 5000: 0.0969 | 0.166 | 0.13 | 0.0248 / 0.0194 | 0.0290 / 0.0226 | 0.86 |
| 249R | C2692731 | 15 | Extended | 1: 1.0564; 50: 0.838; 150: 0.744; 500: 0.583; 2500: 0.525; 5000: 0.496 | 0.744 | 0.583 | 0.1112 / 0.0871 | 0.1217 / 0.1025 | 0.91 |
| 49.9R | C869759 | 1 | Extended | 1: 0.757; 50: 0.66; 150: 0.612; 500: 0.575 | 0.757 | 0.66 | 0.1131 / 0.0986 | 0.1238 / 0.1079 | 0.91 |
| 680R | C23228 | 3 | Basic | 1: 0.0126; 1000: 0.0098; 5000: 0.0083 | 0.0126 | 0.0126 | 0.0019 / 0.0019 | 0.0021 / 0.0021 | 0.90 |
| 22R | C23345 | 8 | Basic | 1: 0.0101; 1000: 0.0079; 5000: 0.0068 | 0.0101 | 0.0101 | 0.0015 / 0.0015 | 0.0017 / 0.0017 | 0.89 |
| 4.7k | C23162 | 7 | Basic | 1: 0.0169; 1000: 0.0134; 5000: 0.0116 | 0.0169 | 0.0169 | 0.0025 / 0.0025 | 0.0028 / 0.0028 | 0.90 |
| 1R | C22936 | 11 | Basic | 1: 0.0186; 1000: 0.0144; 5000: 0.0122 | 0.0186 | 0.0186 | 0.0028 / 0.0028 | 0.0031 / 0.0031 | 0.90 |
| 12 pF | C38523 | 8 | Basic | 1: 0.0416; 1000: 0.0327; 4000: 0.0266 | 0.0416 | 0.0416 | 0.0062 / 0.0062 | 0.0068 / 0.0068 | 0.91 |
| 20 pF | C1648 | 4 | Basic | 1: 0.0538; 500: 0.041; 1500: 0.0353 | 0.0538 | 0.0538 | 0.0080 / 0.0080 | 0.0088 / 0.0088 | 0.91 |
| 1.5 nF | C1595 | 0 (removed, C) | Extended (intl Preferred) | 1: 0.0274; 1000: 0.0209; 4000: 0.0174 | | | | | 0.91 |
| 100 nF | C14663 | 18 | Basic | 1: 0.1; 500: 0.0793; 1500: 0.0676; 4000: 0.0605 | 0.1 | 0.0793 | 0.0149 / 0.0119 | 0.0164 / 0.0130 | 0.91 |
| 1 uF | C15849 | 5 | Basic | 1: 0.0685; 500: 0.0532; 1500: 0.0464 | 0.0685 | 0.0685 | 0.0102 / 0.0102 | 0.0112 / 0.0112 | 0.91 |
| 10 uF | C15850 | 24 | Basic | 1: 0.192; 200: 0.144; 600: 0.123; 2000: 0.107 | 0.144 | 0.123 | 0.0215 / 0.0184 | 0.0236 / 0.0202 | 0.91 |
| OPA354 | C36384 | 2 | Extended | 1: 14.08; 10: 11.67; 30: 10.35; 100: 8.187; 500: 7.534 | 10.35 | 8.187 | 1.5468 / 1.2235 | 1.6919 / 1.3519 | 0.91 |
| OPA365 | C96626 | 3 | Extended | 1: 17.29; 10: 15.54; 30: 14.3; 100: 13.17; 500: 12.65 | 14.3 | 13.17 | 2.1371 / 1.9683 | 2.3375 / 2.1528 | 0.91 |
| TLV9062 | C398355 | 1 | Extended *(check)* | **not read** (the domestic page now answers curl with an anti-bot challenge); derived as the international ladder x 6.118: 1: 0.726; 50: 0.576; 150: 0.499; 500: 0.436 | 0.726 | 0.576 | 0.1085 / 0.0861 | 0.1187 / 0.0942 | 0.91 (assumed) |
| LM27762 | C473398 | 1 | Extended | 1: 5.78; 10: 4.84; 30: 4.18; 100: 3.63 | 4.84 | 4.18 | 0.7233 / 0.6247 | 0.7912 / 0.6833 | 0.91 |
| REF3030E | C54120492 | 1 | Extended | 1: 5.58; 10: 4.94; 30: 4.33; 100: 3.831 | 4.94 | 4.33 | 0.7383 / 0.6471 | 0.8075 / 0.7078 | 0.91 |
| ADS124S08 | C2870171 | 1 | Extended | 1: 52.93; 10: 45.57; 30: 41.08; 100: 36.2 | 45.57 | 41.08 | 6.8104 / 6.1394 | 7.4489 / 6.7150 | 0.91 |
| TMUX1119 | C2673327 | 3 | Extended | 1: 15.1; 10: 12.96; 30: 11.62; 100: 9.728; 500: 9.139 | 11.62 | 9.728 | 1.7366 / 1.4538 | 1.8995 / 1.6739 | 0.91 |
| BAT54S | C7420333 | 8 | **Extended** (intl Preferred) | 1: 0.0786; 500: 0.0628; 3000: 0.0558 | 0.0786 | 0.0786 | 0.0117 / 0.0117 | 0.0129 / 0.0129 | 0.91 |

No part is dearer in USD at today's rate; the 953R is cheaper still
because the domestic ladder's first break is at 200 rather than the
international one's. Ladders are truncated above the quantities this
BOM reaches. The REF3030 A grade (C38423, not used) reads 1: 3.07; 10:
2.33; 30: 1.97; 100: 1.65 CNY, so the E grade's premium is 2.61 CNY
($0.39) per board at 10-29.

**Owner-fitted parts from the domestic pages** (same source; the header
set has no C-number and stays at the $2.50 placeholder *(check)*: a
domestic retail price was not read):

| line | LCSC | n | CNY ladder | CNY/board @5-10 / @20 / @100 | intl $/board @20 / @100 |
|---|---|---|---|---|---|
| BNC KH-BNC50-3511 | C2837587 | 3 | 1: 5.73; 10: 4.82; 50: 3.98; 100: 3.45; 500: 3.29 | 14.46 / 11.94 / 10.35 | 1.9518 / 1.6920 |
| Standoff M3 x 8 F-F | C66568 | 1 | 1: 0.141; 100: 0.13 | 0.141 / 0.141 / 0.130 | 0.0236 / 0.0218 |
| Screw M3 x 5 | C357542 | 2 | 1: 0.0134; 1000: 0.0126 | 0.0268 | 0.0048 |
| **subtotal without headers** | | | | **14.63 / 12.11 / 10.51 CNY = $2.19 / $1.81 / $1.57** | $1.98 / $1.72 |

The BNC is dearer domestically at 5-10 boards (the 15- and 30-piece buys
fall in the 10-49 tier, 4.82 CNY = $0.72, against JLC's 0.7879) and
cheaper from 20 boards up. Owner-fitted with the $2.50 header set:
**$4.69 / $4.69 / $4.31 / $4.07** per board at 5 / 10 / 20 / 100 boards,
against $4.89 / $4.89 / $4.48 / $4.22.

### Batch cost, domestic against international

Domestic Economic SMT with the fees above; parts at the tier for B x n
(50 x n per order at 100 boards, two orders of 50 as before); X-ray on
the LM27762 at 10 CNY a piece for 1-10 and 5 for 11-50, priced wholly at
the tier / tier by tier; no coupon; attrition and shipping excluded
(attrition is given below the table). International figures are this
file's batch-cost section, which excludes PCB and shipping.

**After the owner's cuts (2026-11-11 evening), with the ADC-pin clamps, the ratio-switch clamps (D7, D8) and the C2 network, the order:**

| per board | 5 boards | 10 boards | 20 boards | 100 boards (2 x 50) |
|---|---|---|---|---|
| domestic parts | 217.08 CNY = $32.44 | 194.49 CNY = $29.07 | 191.00 CNY = $28.55 | 166.48 CNY = $24.88 |
| domestic fees per order | 400.05 CNY = $59.79 | 470.10 CNY = $70.26 | 510.20 / 560.20 CNY = $76.25 / $83.72 | 780.50 / 830.50 CNY = $116.65 / $124.12 |
| domestic JLC per board | 297.09 CNY = $44.40 | 241.50 CNY = $36.09 | 216.51 / 219.01 CNY = $32.36 / $32.73 | 182.09 / 183.09 CNY = $27.21 / $27.36 |
| domestic PCB per order *(check)* | 20 CNY = $2.99 | 20 CNY = $2.99 | 59.47 CNY = $8.89 | 118.68 CNY = $17.74 |
| **domestic JLC + PCB per board** | **$45.00** | **$36.39** | **$32.80 / $33.18** | **$27.57 / $27.72** |
| owner-fitted per board (domestic BNC, standoff, screws; $2.50 headers *(check)*) | $4.69 | $4.69 | $4.31 | $4.07 |
| **total per board, PCB and owner-fitted included** | **$49.69** | **$41.08** | **$37.11 / $37.49** | **$31.64 / $31.79** |
| **total per batch** | 1,662.4 CNY = **$248.44** | 2,748.8 CNY = **$410.81** | 4,966.5 / 5,016.5 CNY = **$742.24 / $749.72** | 21,169.8 / 21,269.8 CNY = **$3,163.83 / $3,178.77** |
| international for reference: total per board, PCB excluded | $52.60 | $43.94 | $39.66 / $40.07 | $34.38 / $34.55 |
| international batch, PCB excluded | $262.99 | $439.44 | $793.27 / $801.47 | $3,438.36 / $3,454.76 |
| saving per board, both PCB excluded | $3.51 (6.7 %) | $3.16 (7.2 %) | $3.00 / $3.03 (7.6 %) | $3.10 / $3.11 (9.0 %) |

Against the owner's target of about $35 per board for the first batch,
domestic with the PCB: the 20-board batch is $37.11 / $37.49 per board,
$2.1-2.5 over. Of that, $4.31 is the owner-fitted parts, including the
$2.50 header placeholder *(check)*. The JLC order plus PCB alone is
$32.80 / $33.18. Domestic shipping outside Guangdong and attrition (about
1-2 CNY per board at 20) are still excluded.

The rows below are the comparison before the owner's cuts, kept for the
record:

| per board, before the cuts | 5 boards | 10 boards | 20 boards | 100 boards (2 x 50) |
|---|---|---|---|---|
| domestic parts | 253.85 CNY = **$37.94** | 236.13 CNY = **$35.29** | 225.05 CNY = **$33.63** | 204.19 CNY = **$30.52** |
| international parts | $41.51 | $38.62 | $36.81 | $33.87 |
| domestic fees per order | 399.50 CNY = $59.71 | 469.00 CNY = $70.09 | 508.00 / 558.00 CNY = $75.92 / $83.39 | 775.00 / 825.00 CNY = $115.82 / $123.30 |
| international fees per order | $57.87 | $69.19 | $75.43 / $83.63 | $118.75 / $126.95 |
| **domestic JLC per board** | 333.75 CNY = **$49.88** | 283.03 CNY = **$42.30** | 250.45 / 252.95 CNY = **$37.43 / $37.80** | 219.69 / 220.69 CNY = **$32.83 / $32.98** |
| international JLC per board | $53.09 | $45.54 | $40.58 / $40.99 | $36.25 / $36.41 |
| owner-fitted per board, domestic / intl | $4.69 / $4.89 | $4.69 / $4.89 | $4.31 / $4.48 | $4.07 / $4.22 |
| **total per board, PCB excluded: domestic** | **$54.57** | **$46.99** | **$41.74 / $42.11** | **$36.90 / $37.05** |
| total per board, PCB excluded: international | $57.98 | $50.43 | $45.06 / $45.47 | $40.47 / $40.63 |
| saving per board | $3.41 (5.9 %) | $3.44 (6.8 %) | $3.32 / $3.36 (7.4 %) | $3.57 / $3.58 (8.8 %) |
| domestic PCB per order *(check)* | 20 CNY = $2.99 | 20 CNY = $2.99 | 59.47 CNY = $8.89 | 118.68 CNY = $17.74 |
| **domestic total per board, PCB included** | **$55.16** | **$47.28** | **$42.18 / $42.56** | **$37.26 / $37.41** |
| **domestic total per batch, PCB included** | 1,845.6 CNY = **$275.82** | 3,163.9 CNY = **$472.84** | 5,645.2 / 5,695.2 CNY = **$843.67 / $851.14** | 24,930 / 25,030 CNY = **$3,725.82 / $3,740.77** |
| international total per batch, PCB excluded | $289.89 | $504.28 | $901.15 / $909.35 | $4,046.73 / $4,063.13 |

Before the cuts, CNY batch totals include the header set converted at 6.6912 (16.73 CNY a
set). Domestic attrition adds 7.34 / 9.68 / 9.49 / 16.69 CNY per batch
($1.10 / $1.45 / $1.42 / $2.49). Where two figures are given, the X-ray is
priced wholly at its tier / tier by tier.

**What differs, line by line:**
- **Parts: lower by the exchange rate only.** The domestic CNY ladder is
  the international USD ladder times 6.118 on every type; at 6.6912 that
  is 8.6 % off. Break-even is about 6.12 CNY per USD.
- **Setup lower** (50 CNY = $7.47 against $8.18 + $1.53 stencil):
  -$2.24 per order.
- **Loading higher**: 14 Extended types x 20 CNY = 280 CNY = $41.85
  against 13 x $3.07 = $39.91, because the BAT54S loses its Preferred
  status (the 1.5 nF, the other one, has left the BOM). A domestic Basic
  BAT54S would save 20 CNY ($2.99) per order *(not searched)*.
- **Joints** 0.01 CNY = $0.0015 against $0.0016; **X-ray** 10 / 5 CNY =
  $1.49 / $0.75 against $1.64 / $0.82: both slightly lower.
- **Attrition**: a published domestic rule, about 7-10 CNY per order for
  this BOM; not in the international figures.
- **PCB**: domestically about 20-119 CNY per order on published rules;
  the international PCB price was never read, so no comparison.
- **Shipping**: free inside Guangdong; elsewhere in China not published
  *(check)*. International freight was never read either.
- **Not compared**: import duty, VAT and customs clearance on an
  international shipment to a Chinese address, and whether domestic prices
  include VAT (an unanswered jlc.com question, `q6i24839`, asks why a tax
  line appeared) *(check)*.
