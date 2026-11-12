# AFE version 2: part selection (dual op-amps, precision ADC, negative rail)

**Decided (owner, 2026-11-12):** the fitted dual is the **3PEAK TPH2502** (C118223),
in version 1 and version 2, in every role section 0 gives the COS2353: its
datasheet is complete, its output short is rated infinite with thermal shutdown,
and it clears SC-12's 5 MHz full-scale sine with margin, for about 0.47 CNY more
per dual. COS2353 is the fallback if no other pin-compatible source is found.
Version 1's mid-rail followers stay TLV9062. Section 0 is the study that led
there and is kept as it was written. Still to show for the TPH2502: SC-6 noise at
its wider bandwidth, AN-1 stability into the ADC pin and the Vmid load, and JLC
domestic stock *(check)*.

## 0. Re-choice at the 10 MHz ceiling (2026-11-12)

Against `docs/afe-v2.md` and `docs/afe.md` at origin/main 3f1a606: V2-9 / D13
("cost down is the main purpose ... I never need it work over 10 MHz"), the
two-dual board of SC-9 (one shared scope dual, one AWG dual), and AW-3 as
restated. The TPH2502 below (sections 1-4) was sized to version 1's speeds and
is kept as history. Read-only: no simulation was run. JLC figures were read on
**2026-11-12, 13:30 UTC**, from JLC's own servers by the method of
`jlc-basic.md`: the op-amp category was enumerated through
`selectSmtComponentList` (`firstSortName` "Amplifiers/Comparators",
`secondSortName` "Operational Amplifier": **17,157 listings**, of which 3 are
Basic, NE5532, LM358 and LM324, none usable on 3.3 V), filtered on JLC's own
attributes, then each shortlisted part's domestic page
(`jlc-smt.com/lcsc/detail/<C>.html`) read for `orderLibraryType` and its CNY
`priceList`. **Every part below is Extended on both services.** Prices are
**domestic CNY** (V2-4's basis); international USD is given where it is the
comparison with `bom.md`. Stock is the international API's `stockCount` (the
domestic record reads 0 for every part, as `jlc-basic.md` found).

### 0.1 What the two duals need (*derived* unless sourced)

| Need | Scope dual (both channels, V2-9/SC-9) | AWG dual (DAC0 buffer + output stage) |
|---|---|---|
| Supply | +3.3 V single (PW-1, section 1.5) | +3.3 V and −2.07 V: 5.37 V nominal, **5.445 V** at the LM27762 maxima, inside the *recommended* rating (V2-2) |
| Input | 0.1 to 3.1 V: rail-to-rail input, or no crossover inside it | DAC0 0.55 to 2.75 V (CLAUDE.md), inside the split rails |
| Bandwidth | ≥ 8 MHz closed-loop at G = 1 (SM-3) | ≥ 8 MHz at gain 2.2-2.4 (AW-3): GBW ≥ 8 MHz × the **noise** gain, ≥ 19 MHz if noise gain = signal gain. Version 1's simulation read the 50 Ω row at **0.66** of the hi-Z row (OPA365: 15.1 vs 10.0 MHz, `sim/awg/report.md`), so the 50 Ω row wants **about 29 MHz** *(check by simulation once the stage is drawn)* |
| Slew | none written (see 0.5) | ≥ 13-15 V/µs (AW-3 as restated) |
| Load | 22 Ω into about 12 pF plus trace; AN-1 45° | 50 Ω back-termination, +3.0 V at 30 mA for +1.5 V into 50 Ω (AW-1, D-V2-8: the top end is what the swing allows) |
| Noise (SC-6) | 0.2 mV rms at the pin over the band; at unity noise gain a part of en over ENBW ≈ 1.57 × f−3dB uses en·√ENBW of it | AW-6, unchanged |
| Settling (SC-10) | 0.5 LSB of 12 bits is ln(8192) = 9.0 τ; at 8 MHz τ = 20 ns, so 180 ns against SC-10's 667 ns window | — |
| Short | — | indefinite short to ground survived (D-V2-7); 50 Ω bounds it at ≤ 66.8 mA and ≤ 56 mW in the op-amp (section 1.3) |

### 0.2 Candidates

25 °C typicals. "Intl" is JLC's international API, "dom" the domestic page,
both read 2026-11-12. The CNY column is the tier holding 20 / 100 pieces;
per-board costs in 0.3 use the tier the order actually buys.

| Part (LCSC, package) | GBW / slew | en | Input | Supply rec / abs | Output, short | Stock | CNY @20 / @100 (dom) | USD @20 / @100 (intl) |
|---|---|---|---|---|---|---|---|---|
| **TI TLV9062IDR** (C398355, SOIC-8) | 10 MHz, PM 55° / 6.5 V/µs (SBOS839N 6.x); G=+1 closed loop: **+2.3 dB peak near 5 MHz, −3 dB about 8.4 MHz** (Fig 6-8, read by eye at VS 5.5 V *(check at 3.3 V)*) | 10 nV/√Hz @10 kHz | RRIO, (V−)−0.1 to (V+)+0.1; **transition (V+)−1.2 to −1.0 V, ±0.2 V process**, i.e. about 1.9-2.5 V on 3.3 V, offset steps up to about ±1.5 mV across it (Sec 7.3, Fig 6-4) | 1.8-5.5 / 6 V | ISC ±50 mA, "Continuous" (one amp per package); PM 57° at 20 pF, 45° at about 80 pF (Fig 6-33) | 181,253 | 0.726 / 0.576 | 0.1188 / 0.0943 |
| HGSEMI TLV9062M/TR (C44606410, SOP-8) | 11 MHz, PM 51° (CL 100 pF) / 9 V/µs | 11.5 nV @1 kHz | "complementary input stage", transition not given | 2.1-5.5 / 7.5 V | IOUT 70 mA min, no short rating | 1,400 | **0.412** / 0.325 | 0.0709 / 0.0560 |
| **Gainsil GS8626-SR** (C5179660, SOP-8) | 20 MHz, PM 60° (CL 100 pF) / 17 V/µs | 7 nV @10 kHz, 14 @1 kHz | RRIO, complementary stage (VSS−0.1 to VDD+0.1), transition not given | 2.5-5.5 / 7.5 V | IOUT **70 mA min**; **no short-circuit rating, no thermal shutdown stated**; θJA 125 °C/W; swing at 30 mA sourcing, 25 °C, VS 5 V: **about 0.5 V below V+** (Output Voltage Swing vs Output Current, p. 6, read by eye *(check)*) | 1,915 | 1.199 / 1.055 | 0.2065 / 0.1818 |
| **COSINE COS2353SR** (C2685365, SOP-8) | 50 MHz (G=+1) / 38 V/µs | 10 nV @1 kHz | RRIO, VCM −0.1 to 5.6 V at 5 V; crossover not described | 2.5-5.5 / 6 V | ISC 100 source / 120 sink mA, **no duration, no thermal shutdown stated**; swing 200 mV from rail at RL 150 Ω (about 15 mA), no swing-vs-current curve; θJA 155 °C/W | 4,195 | 1.875 / 1.454 | 0.3067 / 0.2379 |
| 3PEAK TPH2502-SR (C118223, SOP-8), the previous pick | 120 MHz / 180 V/µs | 6.5 nV @1 MHz | section 1.2 | 2.5-5.5 / 7.0 V | "Infinite", thermal shutdown; supply-pin ±60 mA (section 1.3); its text cites a swing-vs-current curve the document does not contain *(check)* | 3,263 | 2.69 / 1.91 | 0.44 / 0.3125 |

Screened out (JLC attributes and section 1's datasheets): **TLV9052** (5 MHz:
SM-3 at G=1 and AW-3), **TLV9002** (1 MHz), **TLV9152** (4.5 MHz),
**TLV9162** (11 MHz: AW-3 at gain 2.4; 7.05 CNY @100 for the scope),
**OPA2322AIDR** (20 MHz but 10 V/µs: AW-3's slew; 5.79 CNY), **OPA2323IDR**
(20 MHz, 33 V/µs, 3.97 CNY @100, 294 stock), **OPA2328DR** (40 MHz, 11.39 CNY),
OPA2365AIDR (6.20 CNY @100), TLV3542 (272 stock), **SGM8262-2 / SGM8272**
(4.5-36 V parts, minimum supply over 3.3 V, 1.4 MHz for the 8272; JLC stock 0
and 1,633), **RS8762** (1.20 / 0.948 CNY, the cheapest fast part, but its
**±50 mA output abs max** is below the 50 Ω short, section 1.3), **SL2122C**
(25 MHz, 12 V/µs: slew), SL620D (RRO only, input range unread *(check)*),
OPA2322M/TR-HG (20 MHz, 2.14 CNY: GS8626's speed at twice its price), GS8592
(not found under that number on JLC). Cheaper 10-11 MHz RRIO clones exist
(GS1002-SR C52211844 0.514 CNY, LMV722-DW C47355687 0.469 CNY, both @20);
their datasheets were not read *(check)* and they save under 0.1 CNY per board
against the HGSEMI part.

### 0.3 Cost per board, both duals (domestic CNY; loading 20 CNY per Extended type per order)

At 20 boards a single type buys 40 pieces and two types 20 each; at 100
boards, 200 and 100. Loading adds 1.00 CNY per type per board at 20, 0.20
at 100 (`bom.md`: 20 CNY per Extended type per order).

| Option | Scope dual | AWG dual | 20 boards | 100 boards | Meets |
|---|---|---|---|---|---|
| E | TLV9062IDR | GS8626-SR | 3.93 | 2.03 | AWG's 50 Ω bandwidth unlikely: 20 MHz at gain 2.4 is 8.3 MHz hi-Z typical, about 5.5 MHz at version 1's 0.66 *(check)* |
| D, one type | GS8626-SR | GS8626-SR | 3.40 | 2.19 | as E |
| **C** | HGSEMI TLV9062M | COS2353SR | **4.29** | **2.18** | scope bandwidth: 11 MHz, PM 51°, no closed-loop curve *(check)* |
| **B** | TLV9062IDR | COS2353SR | 4.60 | 2.43 | scope bandwidth: 8.4 MHz by eye at 5.5 V, marginal *(check at 3.3 V with the ADC load)* |
| **A, one type** | COS2353SR | COS2353SR | 4.75 | 2.75 | yes on every sourced figure; gaps in 0.4 |
| TPH2502, two duals | TPH2502-SR | TPH2502-SR | 5.68 | 4.02 | section 1.6's open items |
| TPH2502, three duals (section 1's plan) | | | 8.02 | 5.93 | |

International USD for comparison with `bom.md` (loading $3.07 per type per
order): A **$0.77 / $0.45**, B $0.73 / $0.39, two TPH2502 $0.92 / $0.66 per
board at 20 / 100.

**Recommendation.** **AWG dual: COS2353SR**, the cheapest part found that
clears AW-3 at gain 2.4 with the 50 Ω row's loss counted (50 MHz, 38 V/µs),
holds 5.445 V inside its recommended 5.5 V, and sinks the short on dissipation.
**Scope dual: the cheapest combination is C or B**, a 10-11 MHz RRIO part
beside it, *if* simulation shows ≥ 8 MHz at G = 1 on +3.3 V with the 22 Ω /
12 pF load (TI publishes a model for the TLV9062; the HGSEMI part's model was
not looked for *(check)*). **The cheapest single-type option is A**, COS2353SR
for both, 0.15 CNY per board above B at 20 boards and 0.32 at 100, and it
removes the scope's bandwidth question. Against two TPH2502 it saves 0.93 CNY
per board at 20 and 1.27 at 100; against section 1's three TPH2502, 3.27 and
3.18.

### 0.4 What is not settled (*check*)

- **COS2353's datasheet is thin** (Rev1.2, 2018): its CMRR and AOL rows cite
  11.9 V conditions on a 5.5 V part, it rates no short duration and states no
  thermal shutdown, gives no crosstalk, no phase margin and no swing-versus-
  current curve, and no maximum IQ. *Derived* for the short: ≤ 66.8 mA and
  ≤ 56 mW plus 2 × 2.5 mA × 5.37 V of quiescent, 83 mW × 155 °C/W = **13 K
  rise**, so it survives on dissipation; that it survives on metal is not
  stated. Swing at 30 mA: 0.2 V at about 15 mA scaled linearly is about
  0.4 V, so the 50 Ω top end is about **+1.45 V** at the load (*derived*;
  D-V2-8 accepts it). GS8626 reads about 0.5 V (+1.4 V at the load) from a
  curve; TPH2502 has no curve. **No candidate shows +3.0 V at 30 mA.**
- **Crossover.** TLV9062 documents its transition at about 1.9-2.5 V on
  +3.3 V, inside the scope's 0.1-3.1 V, with offset steps up to about ±1.5 mV
  (about two codes at 0.8 mV per code) that a linear calibration cannot fit
  out (Fig 6-4). GS8626, COS2353 and the HGSEMI part have complementary or
  undescribed stages. The zero-crossover dual already in this file is TI's OPA2365
  (6.20 CNY @100); no cheap one was found, and JLC's attributes do not tag
  the property, so the search was not exhaustive.
- **SC-9 with the scope channels sharing.** The 0.30 LSB at 10 MHz of the
  what-if used the OPA2354's crosstalk curve. TLV9062's is about −72 dB at
  10 MHz (Fig 6-32), about one code at the pin for a full-scale aggressor
  before the ADC model; GS8626, COS2353 and HGSEMI publish none. The sharing
  condition has to be re-shown on the chosen part.
- **Noise (SC-6).** At G = 1 a wider part folds more: TLV9062 at about 13 MHz
  ENBW is 36 µV rms, COS2353 at an unknown G = 1 bandwidth (50 MHz GBW, so
  ENBW plausibly 50-80 MHz) about 70-90 µV, each against 200 µV with the
  divider's own noise still to add (*derived*, flat en assumed).
- **PW-1** at typical IQ (no maximum given for COS2353): scope dual 5 mA on
  +3.3 V, AWG dual 2 × 2 × 2.5 = 10 mA at the 5 V pin, about 48 mA with the
  30 mA load and 3.4 mA for the rest, against 100 mA.

### 0.5 Scope slew, for the owner

No requirement sets the scope stage's slew, so V2-9 asks for none. For the
record, a full-scale 2.3 V swing at the pin (5 V × 0.462, `notes.md`) has a
full-power bandwidth of SR / (π × 2.3 V): **0.9 MHz on TLV9062** (6.5 V/µs),
2.3 MHz on GS8626, 5.2 MHz on COS2353 (*derived*). Above that, a large signal
is slew-distorted while small-signal bandwidth still reads 8 MHz; a
full-scale step takes about 0.35 µs to cross on the TLV9062. If equivalent-
time captures of full-scale edges matter, that is a requirement to write.

### 0.6 Version 1 roles (D13)

Version 1 has seven op-amp halves (`whatif/bom.md`; circuits in
`sim/scope/netlib.py` and `sim/awg/report.md`):

| Role | Today | Supply | Need under D13 (*derived*) |
|---|---|---|---|
| Scope stage, ×2 | OPA354 | +3.3 V single (`netlib.py`, `vccl` to 0) | non-inverting, gain about 1 (±5 V) and 1.10-1.16 (±1.25 V, TMUX1119 in the feedback); ≥ 8 / ≥ 7 MHz (SM-3) |
| AWG op-amp | OPA365 | +3.3 V and −2.07 V behind Schottkys (5.445 V bare) | signal gain 1.151, but **noise gain 2.15** (Rf 1,099.5 Ω over Rg 953 Ω, with the Ra/Rb attenuator at V+) and Cf 12 pF; slew 6 × 1.15 ≈ 7 V/µs; OPA365's 50 MHz gives 15.1 MHz hi-Z and 10.0 MHz into 50 Ω, so a 20 MHz part would read about 4 MHz there: it needs the 50 MHz class |
| DAC0 buffer | OPA365 | +3.3 V single | follower, 0.55-2.75 V in, 2.05 kΩ load, slew ≥ the DAC's 6 V/µs |
| AWG Vmid follower | OPA365 | +3.3 V single | DC, bare output into Rg, but must follow within a few µs at start-up (AW-8; `sim/awg` "Why it has to be fast and bare") |
| Scope Vmid followers, ×2 | TLV9062 | +3.3 V single | DC, 6 × 10 µF through 4 × 1R with its loop (`whatif/lowcost-scope`): unchanged |

**Cheapest packing, two types (COS2353SR, TLV9062IDR), four duals:**
COS2353 #1 = AWG op-amp + DAC0 buffer (the buffer moves onto the split rails,
as version 2 does: AW-8 and PR-2 at the DAC pin to re-run *(check)*);
COS2353 #2 = both scope stages, shared under D13 (subject to the SC-9 point in
0.4); TLV9062 #1 = both scope Vmids, as today; TLV9062 #2 = AWG Vmid plus a
tied-off spare (TLV9062 in place of OPA365 there needs `sim/awg`'s Vmid sweep
re-run *(check)*). Op-amps per board at 20 boards: 2 × $0.3067 + 2 × $0.1188
= **$0.85 against $10.51** (international, `bom.md`'s basis), and at 100
boards $0.58 against $9.26 (`bom.md` rows at their 100-board tiers); domestic
5.20 / 3.54 CNY. Extended op-amp types fall from three (OPA354, OPA365,
TLV9062) to two: **one fewer loading fee, $3.07 / 20 CNY per order.** If the
TLV9062 also passes the scope stage's bandwidth by simulation, one COS2353
(AWG + DAC0 buffer) and three TLV9062 (scope stages, scope Vmids, AWG Vmid and
a spare) cost **$0.59** at 20 boards and $0.48 at 100.

### 0.7 Sources added for this section

| File (`~/.local/share/afe-datasheets/`) | Document | Fetched from | sha256 |
|---|---|---|---|
| gs8626.pdf | Gainsil GS8626/8628, September 2021 REV_V0 | JLC datasheet link for C5179660, 2026-11-12 | cbafd5e1df45e7b40d750d0de2011885d7095e4756ba56305fd1f9088f7748c9 |
| cos2353.pdf | COSINE COS1353/COS2353, Rev1.2 | JLC datasheet link for C2685365, 2026-11-12 | 0a66107b0275a8b04ff80f288bc26dcaf69373e58d9aa9b51d7311ddf1a5dcb4 |
| hgsemi-tlv9062m.pdf | HGSEMI TLV906x | JLC datasheet link for C44606410, 2026-11-12 | e36addb3ac129cbb84f970be56e8884751b7ae1840503f45c5f790c43055b3d6 |
| tlv9062.pdf, tph2502.pdf | as in the table at the end | | unchanged |

---

The sections below are the study at version 1's speeds, kept as history.

Part study for `docs/afe-v2.md` (origin/main 82096d0), against `docs/afe.md`
and version 1's `whatif/bom.md`. Read-only: no simulation was run for this
file. Every datasheet figure gives its document and section or table; every
JLC figure was read from JLC's parts-search service on **2026-11-12**
(13:05 UTC); figures marked *derived* are arithmetic on those, and anything
not verified is *(check)*. Datasheets are kept outside the repository in
`~/.local/share/afe-datasheets/` (MC-6), hashes at the end.

**Prices are JLC's international USD tiers** (the same source as `bom.txt`'s
"unit@20/unit@100" columns), the tier that holds 20 and 100 pieces. The
domestic CNY ladders that `bom.md` totals with were not read *(check before
pricing V2-4)*. Every part below is **Extended** on JLC (none Basic, none
Preferred), so each type also costs one loading fee per order (20 CNY
domestic, `bom.md`).

## Verdicts

| Question | Verdict |
|---|---|
| Op-amp, preferred | **3PEAK TPH2502-SR** (C118223), all three duals: RRIO, 120 MHz GBW, 180 V/µs, 6.5 nV/√Hz, 7.0 V abs max, short "Infinite" with thermal shutdown, 3,263 in stock, $0.38 at 60 pieces. Two conditions open (section 1.6) |
| Op-amp, second type | **TI OPA2365AIDR** (C130011) for the two scope followers only, on +3.3 V single supply, if the preferred part's input-stage crossover fails the scope's linearity: zero-crossover input, but 5.5 V abs max rules it out of the AWG |
| Channel sharing | Keep **one dual per scope channel**. Version 1's what-if of both channels in one OPA2354 reached 1.99 LSB against SC-9's 2 LSB on the stress ADC model |
| ADS1115 vs SGM58031 | **ADS1115IDGSR** (C37593, $1.13 at 20, 17,442 stock). The SGM58031 is pin-compatible but **4.7x the price** on JLC ($5.34) with 1,143 stock and a looser INL, so it is not worth carrying as the second source |
| Direct-sense input at −1.68 V | **Not allowed through a series resistor alone.** Both parts rate the analog input to GND − 0.3 V; TI adds that overdriving one input "can affect conversions taking place on other inputs" and asks for external Schottky clamps. With a Schottky to GND holding the pin above −0.3 V it is inside both ratings; whether the other inputs are then undisturbed is stated by neither datasheet, so VT-20 decides |
| LM27762 for both loads | **Yes on current**: ±250 mA per output against at most about 95 mA estimated on OUT−. The binding limit is **PW-1's 100 mA at the 5 V input**, because the input carries both rails' current |

## 1. Dual op-amps (V2-2)

### 1.1 What the roles need

| Role | Need | Source |
|---|---|---|
| Scope, per channel | Unity-gain follower in the working proposal, input about 0.1 to 3.1 V, so **rail-to-rail input on +3.3 V** and no input crossover inside that range for linearity | `v2/notes.md` (proposal, not accepted) |
| | Small-signal bandwidth ≥ 8 MHz | SM-3 |
| | Noise ≤ 63 nV/√Hz at the ADC pin over the whole band | SC-6 (0.2 mV over 10 MHz, derived there) |
| | ≤ 2 LSB crosstalk between channels at any frequency the path passes | SC-9 |
| AWG, one dual | DAC0 buffer (input 0.55 to 2.75 V, CLAUDE.md) and output stage, −1.5 to +3.0 V hi-Z, −0.75 to +1.5 V into 50 Ω | AW-1 (afe-v2 3.2) |
| | Bandwidth ≥ the scope path's, unshaped 1.6 Msym/s patterns | AW-3 |
| | Supply +3.3 V and −2.07 V = 5.37 V nominal, **5.445 V at the LM27762's datasheet maxima** | `docs/architecture.md` (AFE), "The rails" |
| | Start-up peaks in the TI model: OUT+ 3.414 V, OUT− −2.100 V, **5.51 V if coincident** *(check)* | `whatif/lm27762/results.json`, case `fly_100n` |
| | Survives an indefinite BNC short, at most 64 mA through 50 Ω | afe-v2 3.2, D-V2-7 |
| All | Phase margin ≥ 45° with parasitics | AN-1 (the design's; every part below is unity-gain stable per its datasheet) |

*Derived:* at +1.5 V into 50 Ω the output stage sits at +3.0 V sourcing
30 mA, **0.235 to 0.34 V under the +3.3 V rail** (3.235 to 3.342 V,
`architecture.md` Power). No candidate tabulates its swing at 30 mA. TI's
OPA354/TLV354x text and 3PEAK's TPH250x text both say "±100 mA ... and
approximately 2.7 V of output swing on a 5 V supply", about 1.15 V per rail
at 100 mA; scaled linearly that is about 0.35 V at 30 mA, which **does not
fit the 0.235 V of headroom.** Read the swing-versus-current figures before
AW-1's 50 Ω row is believed *(check: TPH2502 "Output Voltage Swing vs
Output Current"; SBOS756A Fig 5-12)*. A supply-pin filter resistor (version 1
had 22 Ω ∥ 22 Ω) takes its drop off the same headroom.

### 1.2 Electrical candidates

25 °C typicals unless marked; "abs" = absolute maximum supply.

| Part (datasheet) | GBW | Slew | en | Input / output | Supply op / abs | IQ per amp typ / max |
|---|---|---|---|---|---|---|
| **TPH2502** (3PEAK Rev. A) | 120 MHz (G=10); f−3dB 250 MHz G=1 | 180 V/µs | 6.5 nV/√Hz @1 MHz | VCM V− −0.1 to V+ −0.1; RRO, 2/30 mV at 100 kΩ | 2.5–5.5 / **7.0 V** (abs-max table; its text says 7.5 V) | 6.5 / 7.5 mA |
| **TLV3542** (SBOS756A) | 100 MHz (G=10); 200 MHz G=1 | 150 V/µs (4 V step) | 7.5 nV/√Hz @1 MHz | RRIO, V− −0.1 to V+ +0.1; **transition region V+ −2.0 to V+ −0.4 V** (Sec 7.3) | 2.5–5.5 / 7.5 V (5.1) | 5.2 / 6.5 mA |
| **OPA2354** (SBOS233H) | 100 MHz (G=10); 250 MHz G=1 | 130 V/µs (2 V step) | 6.5 nV/√Hz @1 MHz | RRIO, V− −0.1 to V+ +0.1 | 2.5–5.5 / 7.5 V (6.1) | 4.9 / 6.0 mA (7.5 over temp) |
| **OPA2365** (SBOS365G) | 50 MHz | 25 V/µs | 4.5 nV/√Hz @100 kHz | RRIO, **no crossover** (100 dB CMRR over full range) | 2.2–5.5 / **5.5 V** (7.1) | 4.6 / 5.0 mA |
| RS8762 (Runic Rev A.1) | 120 MHz (G=10); 250 MHz G=1 | 180 V/µs | 6 nV/√Hz @1 MHz | RRIO; offset-calibration switch point "near VDD −1.5 V" (8.2) | 2.7–5.5 / 7 V (7.1) | 8.3 / 10 mA at 5 V (13 over temp) |
| RS8752 (Runic Rev B.1) | "250 MHz" GBP (G=2 table) | 180 V/µs | 8 nV/√Hz @1 MHz | **VCM −0.2 to +3.9 V at 5 V** (V+ −1.1 V); RRO | 2.5–5.5 / 7.0 V | 2.9 / 3.5 mA |
| SGM8052 (SG Micro Rev E.1) | 90–120 MHz (G=10) | 93/−118 V/µs | 8.1 nV/√Hz @1 MHz | **VCM −0.2 to +3.8 V at 5 V**; RRO | 2.5–5.5 / 6 V | 2.3 / 3.2 mA |
| OPA2350 (SBOS099D) | 38 MHz | 22 V/µs | 7 nV/√Hz @10 kHz | RRIO | 2.7–5.5 / 7 V (6.1) | 5.2 / 7.5 mA |
| TLV9062 (SBOS839N) | 10 MHz | 6.5 V/µs | 10 nV/√Hz @10 kHz | RRIO | 1.8–5.5 / 6 V | 0.54 / 0.75 mA |
| TLV9052 (SBOS942J) | 5 MHz | 15 V/µs | 15 nV/√Hz @10 kHz | RRIO | 1.8–6.0 / 7 V | 0.33 / 0.45 mA |

Screen against section 1.1 (*derived*):

- **AWG supply** (5.445 V, 5.51 V transient *(check)*): OPA2365 fails (5.5 V abs);
  version 1 kept it inside only with a Schottky per supply pin, which costs the
  headroom the +3.0 V row needs. Every other part has 6 V or more.
- **Rail-to-rail input on +3.3 V** (scope follower to 3.1 V, DAC0 buffer to
  2.75 V): RS8752 and SGM8052 stop at about V+ −1.1 to −1.2 V = 2.1 to 2.2 V
  and fail as followers. TLV3542's transition region is 1.3 to 2.9 V on
  +3.3 V, inside both ranges: an offset step the linear calibration fit cannot
  remove, of a size the datasheet does not give *(check; the same applies to
  the OPA2354 and to TPH2502, whose datasheet does not describe its input stage)*.
- **Bandwidth**: TLV9062/TLV9052 fail AW-3 (an AWG gain of about 2 needs
  ≥ 16 MHz GBW, *derived*) and are excluded from the signal path; OPA2350 at
  38 MHz is short for the AWG at gain 2 with margin.
- **SC-6** at unity noise gain: every fast part is 4.5 to 8.1 nV/√Hz against
  63, but each figure is a single-frequency typical *(check flatness to 10 MHz)*.

### 1.3 Output current, short circuit and package (afe-v2 3.2)

*Derived:* with the BNC shorted, the 50 Ω back-termination bounds the
current at V+/50 Ω = 66.8 mA at the rail's maximum, and the op-amp's
dissipation in the short at (V+)²/(4 × 50 Ω) = **56 mW**, whatever its own
limit. With the ~11.5 Ω effective output resistance read from the
"2.7 V swing at 100 mA" sentence, the short settles near 3.29/61.5 =
**about 53 mA** *(check against the swing figure)*.

| Part | Output current | Short-circuit rating | Limits that bind on a 53 to 67 mA short | θJA (8-pin) |
|---|---|---|---|---|
| **TPH2502** | ISC sink 100 min / 160 typ, source 100 min / 290 typ mA; abs ±160 mA | "Output Short-Circuit Duration ... Infinite"; thermal shutdown 160 °C | **"Current at Supply Pins ±60 mA" (abs max)**: 53 mA + 7.5 mA IQ = 60.5 mA, at the limit *(check)* | SOP-8 158 °C/W |
| TLV3542 | IO 100 mA min at 5 V, 50 mA typ at 3 V | "Output short-circuit ... Continuous" (one amp per package, 5.1); shutdown 160 °C | none found | *(check, Sec 5.4)* |
| OPA2354 | IO 100 mA min at 5 V, 50 mA typ at 3 V | Continuous (6.1); shutdown 160 °C | none found | HSOIC-8 *(check, Sec 6.5)* |
| OPA2365 | ISC ±65 mA typ | Continuous (7.1) | 5.5 V supply | *(check)* |
| RS8762 | ISC 200/250 mA typ ("momentary test") | Continuous (7.1) | **"Signal output pin ... −50 to 50 mA" (abs max)** | SOP-8 110 °C/W |
| SGM8052 | 100 mA min at 25 °C | not rated *(check)* | — | SOIC-8 125 °C/W |
| OPA2350 | IOUT ±40 mA, ISC ±80 mA | Continuous | IOUT 40 mA < 53 mA | — |

At 56 mW plus 2 × IQ × 5.37 V, a TPH2502 in SOP-8 rises about
158 × (0.056 + 0.081) = **22 K** in the short (*derived*): inside its 150 °C
junction, so the indefinite short holds on dissipation; the 60 mA supply-pin
rating is the open item (VT-6).

### 1.4 Board house (JLC, read 2026-11-12, USD)

| Part, package | LCSC | Class | Stock | @20 pcs | @100 pcs |
|---|---|---|---|---|---|
| **TPH2502-SR**, SOP-8 | C118223 | Extended | 3,263 | 0.4400 | 0.3125 |
| TPH2502-VR, MSOP-8 | C248593 | Extended | **58** | 0.5055 | 0.3599 |
| TLV3542IDR, SOIC-8 | C2863957 | Extended | **272** | 1.8123 | 1.4803 |
| OPA2354AIDDAR, HSOIC-8 | C962993 | Extended | **209** | 2.9785 | 2.4944 |
| OPA2354AIDGKR, VSSOP-8 | C95502 | Extended | 4,393 | 11.209 | 9.4049 |
| **OPA2365AIDR**, SOIC-8 | C130011 | Extended | 6,134 | 1.6520 | 1.1924 |
| RS8762PXK-G, SOP-8 | C42459682 | Extended | 7,694 | 0.1963 | 0.1551 |
| RS8752XK, SOIC-8 | C236994 | Extended | 2,187 | 0.3910 | 0.2928 |
| SGM8052XS/TR, SOIC-8 | C91288 | Extended | 2,367 | 1.2071 | 0.8489 |
| OPA2350EA/2K5, VSSOP-8 | C115876 | Extended | 2,905 | 1.7273 | 1.2399 |
| TLV9062IDR, SOIC-8 | C398355 | Extended | 181,253 | 0.1188 | 0.0943 |
| TLV9052IDR, SOIC-8 | C2058013 | Extended | 8,581 | 0.3455 | 0.2681 |

Stock in **bold** cannot cover 100 boards at three duals each (300 pieces).
Version 1's op-amps cost $10.51 per board at 20 (`bom.md`); three TPH2502 at
the 60-piece tier are **$1.15** and at the 150-piece tier **$0.94** per board,
before loading fees (*derived*). OPA2365 for the two scope duals plus one
TPH2502: $3.41 / $2.77.

### 1.5 Supply current against PW-1 (100 mA at the 5 V input)

The LM27762 draws from its input the sum of both outputs' currents: TI's
transient model gave 200 mA in at ±100 mA out (`whatif/lm27762/results.json`,
`ds_fig51_100mA`). So an amplifier across +3.3 V and −2.07 V costs **2 × IQ**
at the 5 V pin, and one on +3.3 V alone costs 1 × IQ. *Derived*, at IQ max
(25 °C, 5 V), with the AWG at +1.5 V into 50 Ω (30 mA) and 3.4 mA for the rest
(ladder 2.26, bleed 0.71, LM27762 0.39; `architecture.md`):

| Part | 3 duals, all split | 3 duals, scope on +3.3 V only | Verdict |
|---|---|---|---|
| TPH2502 | 123 mA | **93 mA** | Scope stages on +3.3 V only |
| TLV3542 | 111 mA | 85 mA | as above |
| OPA2354 | 105 mA | 81 mA | as above |
| OPA2365 scope + TPH2502 AWG | — | **83 mA** | fits |
| RS8762 | 153 mA | 113 mA | **fails PW-1 either way** |
| RS8752 | 75 mA | 61 mA | fits, but not a follower on +3.3 V |

This agrees with the scope proposal in `notes.md` (the follower needs no
negative rail). Spare halves draw IQ whether used or not.

### 1.6 Recommendation

**Preferred: TPH2502-SR, all six halves.** Reasons: AW-1 and the AWG supply
(7.0 V abs max over 5.445 V, the only cheap RRIO part with margin); AW-3 and
SM-3 (120 MHz, 180 V/µs, ahead of the OPA354 version 1 used); SC-6 (6.5 nV/√Hz);
afe-v2 3.2 and D-V2-7 (infinite short, thermal shutdown, ±160 mA output
rating); SC-9's internal term (−100 dB at 5 MHz, the same figure the OPA2354
quotes); V2-4 (about $9.4 per board under version 1); and stock for 100 boards.
Its text is evidently derived from TI's OPA354 datasheet, and it carries one
internal contradiction (7.0 V table, 7.5 V text); the table value is used.

Open conditions, both *(check)*:
1. The **60 mA supply-pin rating** against the indefinite short (1.3); if the
   swing figure puts the short above about 52 mA, the AWG needs a current limit
   (V2-3 Basic parts) or the TLV3542 there.
2. Its **input stage** is not described: a crossover inside 0.1 to 3.1 V, as
   TLV3542 documents, would be a scope nonlinearity. No vendor SPICE model was
   looked for *(check)*.

**Second type, only if condition 2 fails: OPA2365AIDR** for the two scope
duals, on +3.3 V single supply (5.5 V abs max is then 2.2 V clear), for its
zero-crossover input. **TLV3542IDR** is the TI fallback for the AWG if
condition 1 fails, at 272 stock *(check stock before ordering)*.

Rejected: RS8762 (PW-1, 50 mA output abs max, a 1 ms power-on and 0.4 to 1 V
glitch rule for its calibration block, Sec 8.2); RS8752, SGM8052 (input range);
OPA2350 (bandwidth, 40 mA); TLV9062, TLV9052 (AW-3); OPA2356 (input range to
V+ −1.5 V, `models/datasheet-facts.md`; JLC stock 0 to 90); ADA4891-2 ($4.71,
datasheet not read).

**Package sharing (V2-2):** version 1's what-if put both scope channels in one
OPA2354 with SBOS233H Fig 6-28's crosstalk: 9.1 LSB at the pin at 89 MHz,
**0.71 LSB on the derived ADC model and 1.99 LSB on the stress model**
(`whatif/lowcost-scope/results/xt.json`, case `D|5`, xt1), against SC-9's 2. So
the default holds: one dual per channel, the spare half for that channel's own
use or tied off, as V2-2 requires the design to state.

## 2. ADS1115 vs SGM58031 (V2-8, D-V2-6)

| | ADS1115 (SBAS444E) | SGM58031 (SG Micro Rev A.3) |
|---|---|---|
| Pins | VSSOP-10: 1 ADDR, 2 ALERT/RDY, 3 GND, 4–7 AIN0–3, 8 VDD, 9 SDA, 10 SCL (Table 4-1) | MSOP-10, **same order**; pin 7 is AIN3/VREFIN (Pin Description) |
| Footprint | VSSOP-10 (DGS) | MSOP-10: same 0.5 mm pitch class *(check the land patterns)* |
| Register map | — | Same pointer scheme; DR codes give 6.25–800 SPS (DR_SEL = 0) against 8–860; a 16-bit Chip_ID (Table 15) tells them apart |
| FSR covering 0–3.3 V | ±4.096 V, LSB 125 µV (Table 7-1) | ±4.096 V (Table 2) |
| Noise at ±4.096 V | 125 µV rms at every rate, 8–860 SPS (Table 6-1) | 125 µV rms at every rate (Table 6) |
| INL | 1 LSB max at 8 SPS, ±2.048 V, best fit over 99% of FS (5.5) | 1 typ, **4 max** LSB, same conditions, −40 to 125 °C |
| INL at ±4.096 V | not tabulated *(check)* | not tabulated *(check)* |
| Gain match between inputs | not specified *(check)* | 0.01% typ, **0.08% max** |
| Input impedance at ±4.096 V | CM 6 MΩ, differential 15 MΩ typ (5.5) | differential 25 MΩ (Table 1); CM not given |
| Absolute input | GND to VDD (5.3) | GND to VDD |
| Abs max, analog input | GND − 0.3 V to VDD + 0.3 V; 10 mA continuous, any pin (5.1) | −0.3 V to 5.5 V; 10 mA continuous, 100 mA momentary |
| Crosstalk | not specified | 90 dB at DC, adjacent channels, in range |
| I²C address | ADDR to GND/VDD/SDA/SCL: 1001000b to 1001011b (Table 7-2) | same four (Table 8) |
| JLC (2026-11-12) | **C37593** ADS1115IDGSR, Extended, **17,442**, $1.1303 @20, $0.8817 @100 | **C700177** SGM58031XMS10G/TR, Extended, 1,143, **$5.3387 @20, $4.2429 @100** |

*Derived:* the 0.08% input-to-input gain match is most of SC-7's 0.1% fit
share for a ratio of two inputs; the ADS1115 does not specify the term at all,
so the ratio of input 1 to inputs 2 to 4 needs the design's own figure or a
measurement either way. Both converters' noise equals one LSB at ±4.096 V, so
averaging below one code needs noise or dither the datasheets do not promise
*(check)*.

**Below ground (afe-v2 3.3).** The ADS1115 clause, Sec 7.3.1, quoted:

> "Electrostatic discharge (ESD) diodes connected to VDD and GND protect the
> ADS111x analog inputs. Keep the absolute voltage of any input within the
> range shown in Equation 3 to prevent the ESD diodes from turning on.
> GND – 0.3V < V(AINX) < VDD + 0.3V. If the voltages on the input pins can
> potentially violate these conditions, use external Schottky diodes and series
> resistors to limit the input current to safe values (see the Absolute Maximum
> Ratings table). Overdriving an input on the ADS1115 can affect conversions
> taking place on other inputs. If overdriving an input is possible, clamp the
> signal with external Schottky diodes."

The SGM58031 datasheet rates the input −0.3 V and 10 mA continuous, and says
"the absolute voltage on any inputs pin must be in the range from GND to
VDD"; it says nothing about overdrive or other inputs.

So: a series resistor alone puts the pin at the ESD diode's drop, beyond
−0.3 V, and TI names exactly that as disturbing other conversions; **not
allowed**. A Schottky to GND at the pin (the BOM's BAT54S, C7420333) holding
it above −0.3 V is TI's own remedy and inside both ratings, but it leaves the
pin outside the recommended GND-to-VDD range, and neither datasheet states the
other inputs are unaffected there: **VT-20 is the evidence**, as afe-v2 already
plans. *Derived* design constraints on that resistor R: the ADC's typical 6 MΩ
loads the direct reading by R/6 MΩ (0.17% at 10 kΩ, against the 0.1% fit
share), the clamp carries (1.68 V − Vf)/R, and the clamp's leakage at 0 to 3 V
reverse, which its datasheet gives only at 25 V (2 µA), adds R × I_leak
*(check)*. The jumper fallback (D-V2-5) avoids all three.

## 3. The shared negative rail (V2-1)

| Item | Value | Source |
|---|---|---|
| Output current, each of OUT+ and OUT− | 0 to **250 mA** operating; 300 mA continuous abs max | SNVSAF7C 5.3, 5.1 |
| Load regulation | OUT− 34 µV/mA (0–250 mA, −1.8 V); OUT+ 11 µV/mA | SNVSAF7C 5.5 |
| Input current | ≈ I(OUT+) + I(OUT−) | TI model, `whatif/lm27762/results.json` |
| Start-up, 90% | OUT+ 0.30 ms, OUT− 0.45 ms (TI model, ±100 mA case) | same file |

Estimated OUT− load (*derived*, IQ max, three TPH2502 with the scope on
+3.3 V only): AWG dual 2 × 7.5 = 15 mA, plus the AWG sinking 15 mA at
−0.75 V into 50 Ω or 33.6 mA into a short at the −1.68 V end: **about 49 mA
worst**; with every amplifier on the negative rail, about 79 mA (RS8762: 94).
All are under a third of the 250 mA rating, so **one LM27762 carries both
loads on current.** The limit that binds is PW-1 at the input (section 1.5).

Coupling through the rail (V2-1, SC-9), *derived* at DC from the typical load
regulation: the AWG moving from +1.5 V to −0.75 V into 50 Ω changes OUT− by
15 mA (0.51 mV) and OUT+ by 30 mA (0.33 mV), each under SC-9's 2 LSB
(1.61 mV at AREF 3.3 V) even if the whole step reached the ADC pin. The rails'
transient response and impedance at frequency are not given *(check, VT-19)*.

## 4. Open items

- TPH2502: supply-pin current in the short; input-stage crossover; SPICE model.
- Every candidate: swing at 30 mA for AW-1's +1.5 V into 50 Ω with 0.235 V of
  headroom (1.1).
- Coincident LM27762 start-up peaks (5.51 V) against each part's abs max.
- ADS1115: INL at ±4.096 V; input-to-input gain match; other inputs' readings
  with one input clamped below ground (VT-20).
- SGM58031 and ADS1115 footprint match; domestic CNY prices for all parts.

## Sources

JLC parts search (`jlcpcb.com`, `selectSmtComponentList`), queried by part
number, 2026-11-12, for class, stock and tiers. Datasheets in
`~/.local/share/afe-datasheets/`; the seven marked "local" are copies of the
project's `hardware/afe-proto/models/` files (`models/SOURCES.md`, retrieved
2026-11-10/11) and hash-identical to them; the rest were fetched 2026-11-12.

| File | Document | URL | sha256 |
|---|---|---|---|
| tph2502.pdf | 3PEAK TPH2501/2/3/4 Rev. A | JLC datasheet link for C118223 (aliyuncs, signed) | 774114f825b87a644b59f33c3ee4bcaae6c4b72f3dd757dd556f5a6a4bc8d40c |
| tlv3542.pdf | TI SBOS756A | https://www.ti.com/lit/ds/symlink/tlv3542.pdf | 2d16670b33561c28267b79d52acc6f58b31d3ceecdc0a2bd4887198bd487a76a |
| opa354.pdf (local) | TI SBOS233H, OPA354/2354/4354 | https://www.ti.com/lit/ds/symlink/opa354.pdf | 21c2d9f67869aa7723163e7bf08cf6c9c4563e4cc0379ca41146225d2a41859a |
| opa365.pdf (local) | TI SBOS365G, OPA365/2365 | https://www.ti.com/lit/ds/symlink/opa365.pdf | 9a87d0790f4b118c78f8c2d81c1cd12298d5872fea272db93a419cd7b0084efa |
| opa356.pdf (local) | TI SBOS212A | https://www.ti.com/lit/ds/symlink/opa356.pdf | 6d474fd4f44aabc1aa87aa3bf77ff53d9140fcd21132cf50ba46944f42fb6b4e |
| rs8762.pdf | Runic RS8761/2/4 Rev A.1 | https://run-ic.com/upload/goods/20240912/202409121526199053.pdf | 723011b8f959c38ed5eb3fbfc89ebc8b44b0476e517f5e78013ed0eb15471dd8 |
| rs8752.pdf | Runic RS8751/2/4 Rev B.1 | JLC datasheet link for C236994 | 172c25f6fd9af54634c6e0a56e3d68473526c163d48a9c63b77f6b2def5995da |
| sgm8052.pdf | SG Micro SGM8051-5 Rev E.1 | JLC datasheet link for C91288 | adbb7276096e7cab3d415f01029bbedfc9c84101147b3ba53cfd39edebaa9a40 |
| opa2350.pdf | TI SBOS099D | https://www.ti.com/lit/ds/symlink/opa2350.pdf | 185293ca6674dd181d9934b5806d5a36e99e03caa1fe140b0bf24cccdc07c24d |
| tlv9062.pdf (local) | TI SBOS839N | https://www.ti.com/lit/ds/symlink/tlv9062.pdf | a77c6dbdedda34c1ecf26e4a5abd38a98903054b49fff9cd24d005897eabedaa |
| tlv9052.pdf | TI SBOS942J | https://www.ti.com/lit/ds/symlink/tlv9052.pdf | 71be455ef4b8fc05101c5c8770c041ac07575ea74bfb89dbd190e76ec7dc9a17 |
| ads1115.pdf (local) | TI SBAS444E | https://www.ti.com/lit/ds/symlink/ads1115.pdf | eefff4d412ce2dcd7e659f47238edc9b2fa02e5971f2625af730502033701834 |
| sgm58031.pdf (local) | SG Micro SGM58031 Rev A.3 | LCSC datasheet for C700177 (`models/manifest.json`) | 295f1806da6fe469b67d941888e43bc89266dfe5888f61b17b9f791a2cdc989a |
| lm27762.pdf (local) | TI SNVSAF7C | https://www.ti.com/lit/ds/symlink/lm27762.pdf | 465db259d11b3b2fe202661b21e1e664065ff8873056a984aa9f967a9fbdc6e0 |
