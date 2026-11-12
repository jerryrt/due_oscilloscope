# Step 2c: AWG output simulation (revision 8, owner 2026-11-11: the buffered AWG with its own fast Vmid is the design; revision 7: BAT54S C7420333 model, AW-8 with a late Vmid; revision 6 and earlier: the unbuffered design, now `--variant=legacy`)

Regenerate everything: `cd hardware/afe-proto/sim/awg && python3 -I run.py --jobs=4` (about 75 s with four ngspice processes; numpy only; reads `../powercal/results.json` for the AFE quiescent total; writes `raw/results.json`, `raw/run.log`, netlists under `netlists/<case>/`). The AWG-Vmid option sweep: `python3 -I run.py vmid` (about 7 min; `raw/results_vmid.json`). The unbuffered design: `python3 -I run.py --variant=legacy` (`raw_legacy/`, `netlists_legacy/`). No vendor model is copied: TI models are read by relative path from `../../models/`.
The resistor tolerance budget is `python3 -I budget/awg_tol.py` from `hardware/afe-proto` (values on the command line, `Ra=.. Rf=..`, to try others).

## Report header

| item | value |
|---|---|
| ngspice | `ngspice -v`: ngspice-47 (KLU), batch mode, TEMP 27 C |
| KiCad | none: no schematic exists yet; the exported netlists are the generated `netlists/*.cir` |
| TI models (local only; sha256 from `models/SOURCES.md`, recomputed by `run.py`) | OPA365 cc95b072...c8; OPA354 48aeb72c...07; OPA356 bd3c0642...9c |
| Own models | `models/awg_behavioural.lib` (sha256 1beaf38e... at this run), CC BY-SA 4.0 (`models/LICENSE`): DAC0 source, Vmid buffer, LM27762 (steady and ramp), protection diodes, switch. Each default carries its source in the file. **The diode figures (BAV99, BAT54S, SMF-class TVS) were recalled, not read: the Nexperia/Diodes downloads are blocked (`SOURCES.md`), so all are *(check)***. LM27762 behaves as in `sim/powercal/models/lm27762_beh.lib` in the points that matter here: the +LDO only sources, the -LDO only sinks |
| Stimuli | DC sweeps; AC at the DAC pin, at V+ or in series with a rail; `.noise` with a quiet DC DAC (ideal + Rout); DAC edges 1.9 V in 375 ns (5 V/us, the measured 300 ns 10-90 %) and 0.5 V in 52 ns (42 ns 10-90 %); ideal 2 ns edge for the cable; 5 mV 2 MHz ripple; four start-up orders; DAC0 reset ramp (3.3 V jump, linear fall to 0 V, rest, return), time scaled 1e4; forced +/-1.8 (stated level), +/-2.0, +/-3 and +/-5 V DC at the BNC, powered and unpowered; **operating points at +/-1.0 V commanded (AW-1 swing, new)** |
| Loads | 1 Mohm &#124;&#124; 15 pF; open; 50 ohm; 1 m lossless 50 ohm line (5 ns) open / 50 ohm / scope input |
| Corners | AREF 3.20-3.30 V (requirement; 3.10 V is margin evidence only); rails +3.23..3.37 V and -1.97..-2.18 V (+/-5 % of the -2.073 V setting) for every row except one; **the AW-1 50 ohm swing row takes its weak corner at the LM27762 datasheet tolerance, +3.235 / -2.041 V** (VFB+ 1.182 V and VFB- -1.202 V, the Sec 5.5 limits over temperature, with the 0.1 % feedback resistors at their worst ratio; owner decision 2026-11-11), its strong corner staying at the blanket +3.37 / -2.18 V; Vmid = AREF/2 +/-30 mV; V+ parasitic 0.5 / 1.5 / 3.5 pF |
| DAC window | A: theory 1/6..5/6 AREF; B: measured 0.578-2.771 V (`docs/hardware.md`, centre +39.5 mV above AREF/2) |
| Parts | **Stocked 0.1 % resistors only** (`docs/jlcpcb-parts.md`), now also the Monte Carlo tolerance (it was 0.05 %); one 49.9 ohm 0.1 % output resistor (AW-4); C0G capacitors 5 %; PCB 1.5 pF at V+ (0.5-3.5 pF corners), 2 pF at the inverting node (assumed) |
| Power ratings assumed | 2010 0.5 W for the output resistor in the PR-4 row (the BOM part is a 1206, `docs/architecture.md`); BAV99 package 250 mW *(check)* |

## The design (revision 8, owner 2026-11-11): buffered DAC0, a low-impedance attenuator, the AWG's own fast Vmid

Approved by the owner on 2026-11-11. AW-7's pre-calibration offset row is information (the MCP3564 calibrates offset), and AW-1's 92 % window is the binding as-built check. AW-1 into 50 ohm is judged at the LM27762's 34 uV/mA load regulation (0.31 mV); the model-rail row (0.76 mV) is information, and VT-8 measures the + rail's load regulation into 50 ohm.

**The circuit** (sim/loop step `buf`, which passes SM-5, plus the isolation resistor, the Schottky and the AWG's own Vmid): DAC0 -> 680 ohm -> OPA365 follower (+IN; 330k from +IN to ground, so an undriven DAC0 commands -1.15 x Vmid), on +3.3 V_A through its own BAT54S die and 100 nF, V- at ground -> Ra 953 -> V+; Rb = 953 + (249 &#124;&#124; 249) + 22 to ground; no Rx; Rf = 953 + (249 &#124;&#124; 249) + 22 with Cf 12 pF; Rg 953 to the AWG's own Vmid (330k / 330k from +3.3 V_A, 12 pF, bare OPA365 follower; below); no Ca/Cb. No injection branch (removed 2026-11-11 for a BNC-tee calibration); the precision ADC's sense divider, 100k + 100k to Vmid or 3.0 V, loads the BNC. As revision 6 otherwise: 49.9 ohm output with the 3-diode stacks on the op-amp side, a Schottky in each AWG op-amp supply pin, 4.7 k bleed; supply filters 22 &#124;&#124; 22; negative rail R3 = 330k &#124;&#124; 100k, R4 = 330k / 3 (three 330k in parallel; sim/powercal's approved divider, 45 kohm at FB-) = **-2.0712 V**; datasheet corners -2.039 / -2.103 V, bare rails 5.445 V, AW-1 50 ohm edge -1.866 V. Slope 1.1513, zero at Vmid by construction. PW-3's limit is afe.md's 30 mA.

**Schottky: BAT54S C7420333** (hongjiacheng, approved 2026-11-11), model `models-open/bat54s-c7420333/bat54s_c7420333.lib` (own, CC BY-SA 4.0), fitted to the vendor datasheet (`models/bat54s-c7420333/`, fetched by `tools/fetch_models.py`, git-ignored). Pinout: series pair, D1 pin 1 -> pin 3, D2 pin 3 -> pin 2; pin 3 is common. `DBAT54S_TYP` fits Fig. 1 at 25 C (0.01-190 mA, worst residual 4.6 mV: 153 / 218 / 278 / 349 mV at 0.01 / 0.1 / 1 / 10 mA, 435 mV at 50 mA); `DBAT54S_MAX` lies at or above the maximum table from 0.1 to 30 mA (240 / 320 / 400 / 500 mV; 11.8 mV over at most). Leakage: 12.5 Mohm across each supply Schottky (2 uA at 25 V, the table maximum). **Which model where:** the AW-1 swing rows (headroom) take MAX; everything else takes TYP, the lower drop, which is the worse side for the pin abs-max, AW-8 and PW-3. The recalled DBAT54 (IS 1e-7, N 1.34, RS 2.5) turns out to sit on the datasheet maximum up to 30 mA (238 / 320 / 421 / 509 mV); the typical part drops 40-110 mV less. Not modelled: the 100 C curve (about 80 mV lower again at 1 mA).

Types: OPA365, 680 (C23228, 1 %, Basic), 330k, BAT54S, 100 nF, 953, 249, 22 (C23345: its page says +/-1 % but the part code's "J" means 5 %, so 5 % in the Monte Carlo *(check)*), 12 pF; no new type. AWG-only types leaving: 13.7k, 15.8k, 20 pF.

### The AWG's own Vmid (2026-11-11; the Vmid section is sim/powercal's, this is the proposal for it)

**Circuit:** the AWG's Vmid buffer (an OPA365 follower on +3.3 V_A behind its own BAT54S die and 100 nF) follows **330k / 330k from +3.3 V_A with 12 pF at the tap**, and drives Rg **with no output capacitor**. Rbpl (330k at the DAC0 buffer's input) now returns to **ground**, not to Vmid. In `run.py`: `vm_div`, `cvm`, `cvm2`, `bpl_to` in the design's parameters; `python3 -I run.py vmid` re-runs the sweep (about 7 min, four processes).

Swept, existing types only: divider 4.7k / 4.7k (1 %), 100k / 100k, 330k / 330k (0.1 %); tap 12 pF, 1.5 nF, 100 nF; output 10 uF + 100 nF (the network sim/awg modelled until now) or none. Each option: AW-8 on the start-up grid (4 orders x DAC0 floating / 0 V / 3.3 V x + rail 3.23 / 3.37 V) and at power-up (soft-start 20 us and 2 ms, DAC0 on the reset trace or 0 V, 60 ms); AW-6 with the LM27762 noise (22 uV rms) and the 5 mV 2 MHz ripple and harmonics through the divider; AW-1 window use and the offset over the 3.3 V_A span; the divider current.

| divider, tap, output | AW-8 grid / power-up | AW-6 total (ripple share) | offset, worst | divider current | verdict |
|---|---|---|---|---|---|
| any, with 10 uF + 100 nF at the output | 2.598-2.605 V | 83.5-103.5 uV | | | fails AW-8 |
| 4.7k, 12 pF, none | 1.724 / 1.721 V | **193.2 (172.0)** uV | 99.1 mV | 355.5 uA | fails AW-6 |
| 4.7k, 1.5 nF, none | 1.749 / 1.721 V | 86.2 (5.6) uV | 99.1 mV | 355.5 uA | holds |
| 100k, 12 pF, none | 1.724 / 1.721 V | 89.5 (16.0) uV | 83.9 mV | 16.7 uA | holds |
| **330k, 12 pF, none** | **1.724 / 1.721 V** | **88.1 (6.3) uV** | **83.9 mV** | **5.1 uA** | **holds (chosen)** |
| 100k or 330k with 1.5 nF; any with 100 nF; 4.7k with 100 nF (tap tau 75 us to 16.5 ms) | 2.601-2.605 V | 83.5-85.8 uV | | | fails AW-8 |

**Why it has to be fast and bare.** The excursion needs only a few microseconds of Vmid behind the DAC path while the rails rise in 10 us: any tap time constant above about 3.5 us fails, and so does any output capacitor the buffer must charge at its 65 mA limit (10 uF takes 250 us). **And the bare output is also the only stable one:** the OPA365 follower driving 10 uF + 100 nF reads **9.8 deg** phase margin, bare 77.6 deg (loop break, 953 ohm load). That applies to any Vmid buffer drawn with 10 uF on its output, the scope's included, and is for sim/powercal to check. The bare buffer's high-frequency output impedance is in the model and is what Rg sees; the bandwidth rows below include it.

**What it costs.**
- **AW-7 offset before calibration: 90.1 mV [A] / 84.2 mV [B] against the 60 mV row (FAIL).** Vmid now follows +3.3 V_A (3.235-3.342 V at the datasheet limits: Vmid 1.6157-1.6721 V) and not AREF (3.20-3.30 V), so the two no longer track. The host calibrates offset through the MCP3564 (AW-7), and the requirement that binds before calibration is AW-1's window: **88.8 % [A], 85.1 % [B], limit 92 % (PASS, 3.2 % spare)**.
- **AW-1 50 ohm swing 0.76 mV against one code, 0.62 mV (FAIL)**, on the positive half, at every rail corner. It is not headroom: 20 mA into 50 ohm sags +3.3 V_A through the model's 0.2 ohm, and the AWG Vmid follows it by half. At the LM27762's 34 uV/mA load regulation (the datasheet's typical, given for the - LDO) the same row reads 0.31 mV. The model is pessimistic by six times there; the row is left at the model's figure.
- AW-6 83.4 -> 89.3 uV (the divider's thermal noise and the rail through it); AW-3 hi-Z 16.2 -> 15.8 MHz, 50 ohm 10.7 -> 10.5 MHz; divider 5.1 uA from +3.3 V_A; three placements of existing types (2 x 330k, 12 pF), against the scope tap's 10 uF.
- Rbpl to ground: an undriven DAC0 now commands -1.15 x Vmid, **-1.52 to -1.72 V** (AW-8 limit 2.1 V), where it commanded 0 V. In exchange PR-2 holds unpowered: with Rbpl to Vmid and the AWG's Vmid buffer dead, the AWG output forced to -5 V drags Vmid to -0.49 V through Rg, and the undriven DAC0 pin follows it through 330k to **-0.488 V** (limit -0.2 V; microamps, and the Due's own pin clamp is not modelled). It was hidden before because sim/awg held an unpowered Vmid at 0 V. **The revision 6 design returns Rg to a Vmid buffer too**, so it has the same exposure through Rx (not simulated).

### Result: 151 rows, 3 FAIL, none of them the design's

| FAIL | value |
|---|---|
| model: macromodel against Fig. 7-15 | 10.4 points low at 300 pF only; within 10 points from 10 to 200 pF |
| AW-6 with an OPA354 / OPA356 in the AWG position (alternatives, not the design) | 129.7 / 100.6 uV (OPA365 89.3 uV) |

The rows the owner's decision moved: AW-7 offset before calibration [A] / [B] **90.1 / 84.2 mV, information**; AW-1 window, position-aware **88.8 % [A] / 85.1 % [B], limit 92 %, PASS** (binding); AW-1 into 50 ohm **0.31 mV at 34 uV/mA, PASS (judged)**, 0.76 mV on the model's 0.2 ohm rails (information). AW-8: start-up grid **1.745 V**, power-up **1.720 V**, DC levels within 1.720 V (margin 0.355 V). 29 guards, all fail broken and pass restored; the new one breaks the 50 ohm row back to the model's rails (0.76 mV FAIL, 0.31 mV PASS).

### BNC-tee calibration (2026-11-11): the injection branch is removed, the precision ADC senses the AWG output

The PA-3 injection is replaced by a BNC-tee calibration, so the DAC0 buffer's injection branch (the 249 ohm and the T-switches, with the AN-1 analysis of it below) is gone: **the buffer's load is the attenuator (2.05 kohm) and its pin trace.** The precision ADC (ADS124S08, sim/powercal's) reads the AWG output on the BNC side through a 0.1 % divider, modelled as **100k + 100k (200k) from the BNC to a tap and 100k from the tap to Vmid or to the 3.0 V reference** (k = 1/3: the tap moves by a third of the BNC swing; powercal switches the far end; approved 2026-11-11), the ADC input as 1 nA/V. The other way round (100k from the BNC, k = 2/3) is reported beside it as a comparison only.

- **AN-1, the buffer: 59.8 deg** with a 5-10 pF trace (limit 45), **55.2 deg at 15 pF** (target 50), 51.4 / 45.3 deg at 20 / 30 pF; 45 deg holds to 30 pF. Pin overshoot 0.2 / 0.6 % at 10 / 15 pF.
- **What the branch had been doing to the AWG:** its isolated capacitance had lifted the bandwidth through the buffer; without it AW-3 reads 15.8 -> **15.1 MHz** into high-Z and 10.5 -> **10.0 MHz** into 50 ohm (8 MHz limit), 16 corners 13.5-16.2 MHz. AW-4 cable overshoot 1.5 -> 1.2 %; AW-6 87.6 uV (circuit), total unchanged within 0.1 uV; AW-1, PR-4 and PW rows unchanged to their printed digits; the 300 kohm of divider on the BNC costs 0.017 % of amplitude into 50 ohm; AW-4, AW-6 (89.9 uV total) and PR-4 move by no more than their last digit.
- **The sense tap, for powercal's input-protection check** (information rows; the divider limits none of these, the ADC input's clamp and series resistance are powercal's):

| tap voltage | far end at Vmid | far end at 3.0 V |
|---|---|---|
| **design, k = 1/3 (200k BNC-tap, 100k tap-far end)**: AW-8's DC excursions, output -1.720..+1.513 V | **+0.544..+1.621 V** | **+1.427..+2.504 V** |
| design: output forced to +/-1.8 and +/-5 V, powered (PR-4) | **-0.579..+2.760 V** | **+0.333..+3.666 V** |
| design: the same, unpowered (Vmid buffer dead, reference 0 V) | -2.131..+3.674 V | -1.667..+1.667 V |
| comparison only, k = 2/3 (100k BNC-tap, 200k tap-far end): AW-8 | -0.588..+1.567 V | -0.147..+2.008 V |
| comparison: forced +/-1.8 / +/-5 V, powered | -2.790..+3.880 V | -2.333..+4.333 V |
| comparison: unpowered | -3.565..+4.337 V | -3.333..+3.333 V |

### PAM step settling (information, 2026-11-11)

AW-3 sets no settling limit and SM-5 was dropped, so these rows are information. A PAM16 step at 1.6 Msym/s (the DAC's 6 V/us ramp, 1.5 V full scale, the stage's own delay taken out, since it only shifts the fold's time axis): the **AFE-added error at the symbol centre is 3.84 / 4.13 / 4.62 codes for a full-scale step and 0.00 codes for one level**, at DAC0 impedance 0 / 100 / 300 ohm (4.68 / 0.00 at 1 kohm), high-Z and a 1 m cable to a scope. For scale, **DAC0 alone into the ADC's input model** (2 pF, 3.8 kohm, 6 pF) is 17.5 / 19.4 / 23.7 codes on the full-scale step at the same impedances (42.8 at 1 kohm) and 0.00 on one level: the full-scale ramp ends 61 ns before the symbol centre, and the converter's own input settles more slowly than the AFE adds. Guard: Cf 100 pF takes the one-level step to 7.57 codes (FAIL against 1 code), 0.00 restored. The rejected lowcost variant reads 48.4 / 2.07 codes.

### The LM27762 ripple, calibrated (2026-11-11, with sim/powercal P4-b)

sim/powercal found sim/awg's ripple source under-calibrated: 5 mV behind 0.2 ohm into the 10 uF reads only **0.93 mV on the datasheet's own condition** (Fig 5-1, the LDO's 2.2 uF alone; the guard below reads it). The source now sits where powercal puts it, behind the LDO's 11 mohm + 0.8 uH (powercal gap G2, assumed), scaled to read **5 mV / n on the 2.2 uF alone** (the guard reads 5.000 mV), with the LDO's 2.2 uF on each rail and fundamentals at 1.7 / 2.0 / 2.3 MHz (the worst taken), harmonics to 10.5 MHz, both rails in phase. The netlists keep their 0.2 ohm DC source (load regulation, start-up): the ripple is applied to the rail impedance each AC run measures at the rail node, and the start-up runs carry a source scaled to the same rail ripple.

**5 mV / n, not the earlier flat 5 mV per harmonic**, as powercal does: the datasheet gives the fundamental only, and a switched-capacitor ripple's harmonics fall with order; the flat weighting assumed each harmonic at the fundamental's level with no source for it. It is reported beside the row (25.47 uV) as the bound if the spectrum is flatter than 1/n.

**The rails' 10 uF parts (powercal, 2026-11-11): two Samsung CL21A106KAYNNNE (C15850) on each LM27762 output**, ahead of the AWG's 22 || 22 ohm filters, modelled from Samsung's characterisation as sim/powercal reads it (`models/cl21a106kaynnne/`, hash-pinned): ESR 4.04 mohm at 2 MHz and 15.2 mohm at its 3-10.5 MHz maximum (the 2 MHz value for lines below 3 MHz, the maximum above, two AC runs stitched by frequency, as powercal does), ESL 0.373 nH (in the small-signal runs only: in a transient it stalls ngspice's first step against the op-amp macromodel), capacitance -30.5 % at 3.3 V and -13.6 % at 2.07 V of DC bias, then -10 % tolerance (6.26 and 7.78 uF each).

**Result: 11.22 uV rms at the AWG output, against powercal's 10.93 uV (+2.6 %)**, at 1.7 MHz, with 0.49 / 0.38 mV on the + / - rail at 2 MHz. The remaining 2.6 % is the rest of +3.3 V_A, which powercal carries and sim/awg does not. Against the earlier rail assumptions (one nominal 10 uF per rail, no ESL): 19.57 uV at 10 mohm, 29.05 uV at 20 mohm; flat 5 mV harmonics 20.99 uV. AW-6 total **89.8 uV** (limit 100); legacy 79.7 uV with 5.50 uV of ripple. Start-up rows: AW-8 grid 1.745 V; op-amp pins 4.783 V, DAC0 buffer pins 3.052 V (limit 5.5 V).

### AN-1 of the buffer, and the isolation resistor (superseded by the BNC-tee calibration above: kept as the record of the injection-branch analysis)

Loop break on the follower; worst over DAC0 0.578 / 1.65 / 2.771 V and + rail 3.23 / 3.37 V. Loads (assumptions *(check)*): trace at the buffer pin 5-10 pF (15 pF for margin); the injection branch carries 10 pF of trace and each switch's 10 pF source side; a switch that is on adds Ron 3.7 ohm (8.8 max lowers the load seen), 10 pF on its drain side, and node N as 4.5 kohm to Vmid + 2 pF.

| isolation (existing types) | normal: pin 5-10 pF, switches off | calibration: one or both on | any, pin 15 pF |
|---|---|---|---|
| none | 40.7 | 33.9 | 32.7 deg |
| 22 ohm feeding both (Rg 953 + 22) | 44.5 | 40.1 | 38.3 |
| 49.9 ohm feeding both (Rg 953 + 49.9) | 48.8 | 46.1 | 43.9 |
| 49.9 ohm in the branch | 47.9 | 45.3 | 43.2 |
| 49.9 + 49.9 ohm in the branch | 53.6 | 53.0 | 50.4 |
| **249 ohm in the branch (chosen)** | **61.4** | **61.2** | **57.8** |

A resistor feeding both sides isolates nothing the attenuator does not already present, costs gain (Ra + Rsh) and needs Rg to grow with it; the branch resistor leaves the AWG path untouched. 249 ohm is one placement of the ladder's 0.1 % type and keeps 7.8 deg over the 50 deg target with a 15 pF pin trace; 45 deg holds to 41 pF at the pin. Pin overshoot for a 100 mV step 2.3-3.5 % (9.4-17.2 % without it).
**What it costs the injection** (a calibration-accuracy term, raised with sim/powercal): node N receives **0.9468 of the buffer's swing with one channel on, 0.8997 with both** (Ron 3.7 ohm; 0.9458 / 0.8988 at 8.8 ohm), from 249 + Ron against 4.5 kohm. Each channel draws (Vbuf - Vmid) / 4.75 kohm, at most 0.26 mA; buffer supply current 6.02 mA worst (quiescent 4.2 mA in the model + 1.35 mA attenuator + the branch).
**What it moves on the AWG** (same diode, branch present, Rinj 0 -> 249): DC gain unchanged (1.15064); bandwidth hi-Z 17.8 -> 16.2 MHz, 50 ohm 11.0 -> 10.7 MHz; AW-6 84.6 -> 83.2 uV; open-cable overshoot 1.5 -> 1.7 %; DAC-edge overshoot 0.02 %, rise 301 ns, settling 396 ns, all unchanged.

Validation of the method: the macromodel in the datasheet's Fig. 7-15 test overshoots as much as the part or more up to 100 pF (7.5 / 14.6 / 17.1 / 22.8 / 26.7 % at 10-100 pF against 6 / 7.5 / 10 / 20 / 28 %, read by eye *(check)*); the loop break agrees with the simulated closed loop to 2.2 %; 1 nF straight on the buffer reads 8.5 deg and fails the check (datasheet: unity-gain stable to about 1 nF). sim/loop's Middlebrook injection reads 77.0 / 77.0 / 77.2 deg at 10 / 52 / 1000 pF where the loop break reads 63.7 / 41.0 / 9.7: it forces the load-side voltage, so the pole between the op-amp's ~30 ohm open-loop output resistance and the load is outside what it measures.

### Unpowered back-feed (AN-3, PR-2, PR-3)

AN-3 reads "The DAC load is within the DAC's drive limits (AW-5)", and AW-5 "Draws at most 0.1 mA from the DAC pin", with no power state named. The AFE takes its power from the Due's 5V pin and the LM27762's EN+ and EN- are tied to VIN (sim/powercal), while DAC0 is powered from the Due's 3.3 V on the same 5 V. So the AFE unpowered with DAC0 driven is **not a steady state of normal use**: it exists in the power-up window if the LM27762 comes up after the Due's 3.3 V (its start-up time is not in its datasheet, powercal gap G1), and in faults (the LM27762 in shutdown or UVLO while the Due's regulator still holds, or the AFE's 5 V feed open).

ESD-only dead buffer: **10.2 uA** from the pin, AFE rails 1.2 mV, 0.25 uA into them (PASS); the buffer's supply pin charges to 2.83 V. A dead CMOS chip on a lifted supply pin can draw current, which no model here has. Pessimistic bound, the dead chip as a short (as 440 ohm, 5 mA at 2.2 V) across its supply, DAC0 at 2.771 / 3.3 V:

| Rbin | back-feed, short (440 ohm) | AW-3 bandwidth hi-Z / 50 ohm, model input only | the same with 4 pF more at the input (about 6 pF in all) | gain, min |
|---|---|---|---|---|
| 680 | 3.76 (2.30) mA | 16.2 / 10.7 MHz | 13.2 / 9.5 MHz | 1.1488 |
| 1k | 2.57 (1.80) mA | 14.1 / 10.0 MHz | 11.0 / 8.5 MHz | 1.1477 |
| 2 x 680 | 1.90 (1.44) mA | 12.3 / 9.1 MHz | 8.9 / **7.4** MHz | 1.1464 |

No series value within the bandwidth reaches 0.1 mA (that would need about 30 kohm); the current is bounded by the resistor and lasts as long as the window. **Keep 680 ohm and make it a bench check (VT-5):** DAC0 driven at 3.3 V into the unpowered AFE, current measured; the bound is 3.8 mA. Whether DAC0 tolerates milliamps for that time is not in the SAM3X datasheet *(check)*.

PR-3/PR-4 unpowered with the AWG output forced to +/-1.8 and +/-5 V, DAC0 held at 0 V or high-Z: DAC pin within +/-1 mV, buffer 0 V, all AFE rails within 1 mV, 0.23 uA into them (8 rows, PASS).

### Rows the BAT54S model moved (TYP unless stated; recalled DBAT54 in brackets)

AW-1 50 ohm swing (MAX) 0.01 mV, the row's rail edge -1.859 V (-1.87); abs max, AWG op-amp pins in start-up **4.753 V** (4.630), buffer pins 3.035 V (2.976), bare rails 5.444 V (no diode); PR-4 pins at +/-5 V **4.12 V** (3.94), resistor 0.287 W (0.279), forced +/-1.8 V 57.1 mA (55.1), normal range 58.5 mA (56.5); AW-8 DAC0 at 0 V -1.723 V (-1.660), at 3.3 V +1.659 V (+1.587), sweep 1.723 V (1.660), reset ramp 1.722 V (1.660); PW-3 window ends 25.87 mA (unchanged), dissipation 36 mW (34); PW-1 fault total 425 mA (423); clamp error 0.049 mV (0.036); unpowered rails 1 mV, 0.23 uA (0 mV, 0.10 uA; the leakage resistors).

### Checks broken on purpose (28 guards, all fail broken and pass restored)

For the AW-1 50 ohm row judged at 34 uV/mA: the model's 0.2 ohm rails break it (0.76 mV FAIL, 0.31 mV PASS). For the AWG's own Vmid: a 100 nF tap instead of 12 pF breaks the start-up check (2.602 V FAIL, design 1.671 V) and the power-up check (2.605 V FAIL, design 1.608 V); "wrong Vmid" now moves the divider ratio (-73.6 mV FAIL, +6.7 mV). The default design carries the two Vmid start-up guards the other way round (it is the broken arm; a Vmid present from t = 0 passes). Buffer and protection: 1 nF on the buffer (8.5 deg FAIL, 61.4 deg), the model read at the wrong load against Fig. 7-16, the loop break on the wrong load, Rbpl 10 k (AW-5 258 uA, AN-3), the buffer's Schottky removed (2289 mV FAIL, 1 mV), output resistor 0.5 ohm (PW-1 121.9 mA), buffer on a 6 V rail, Cf 100 pF with the buffer loaded; and the inherited guards, four re-aimed for this circuit (noise with Cf / 40, the -1.2 V rail, Ca 100 pF, slope x1.4 on AW-8). The AW-1 "blanket corner" guard is dropped for every design: with the BAT54S model the row passes at that corner.

### Every row of the design (`raw/results.json`)

| | ID | case | limit | worst result | margin |
|---|---|---|---|---|---|
| PASS | model | OPA365 model input noise density at 100 kHz vs datasheet | 4.5 nV/rtHz +/-15 % | 4.49 nV/rtHz | +15 % |
| PASS | model | OPA354 model input noise density at 1000 kHz vs datasheet | 6.5 nV/rtHz +/-15 % | 6.69 nV/rtHz | +12 % |
| PASS | model | loop-gain setup: &#124;T/(1+T)/beta&#124; against the simulated closed loop, 10 kHz-30 MHz | agree within 10 % | 4.2 % | +5.8 % |
| PASS | AW-7 | gain 1.10-1.20 [window theory 1/6-5/6 AREF, +/-30 mV centring] | 1.10..1.20 | 1.1486..1.1541 | +0.0459 |
| PASS | AW-7 info | offset at window centre [A] (calibrated by the MCP3564; AW-1 window use is the binding check) | info (was <= 60 mV) | 90.1 mV | -30.1 mV against the old 60 mV |
| PASS | AW-1 | window use, width [A] | <= 92 % | 81.6 % | +10.4 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [A] | <= 92 % | 88.8 % | +3.2 % |
| PASS | AW-5 | DAC pin load at window ends [A] | <= 0.1 mA | 8.3 uA | +91.7 uA |
| PASS | AW-2 | one DAC code at the output [A] (ideal 12-bit) | <= 1 mV | 0.620 mV | +0.380 mV |
| PASS | AW-7 | gain 1.10-1.20 [measured board window 0.578-2.771 V, +39.5 mV centre] | 1.10..1.20 | 1.1486..1.1541 | +0.0459 |
| PASS | AW-7 info | offset at window centre [B] (calibrated by the MCP3564; AW-1 window use is the binding check) | info (was <= 60 mV) | 84.2 mV | -24.2 mV against the old 60 mV |
| PASS | AW-1 | window use, width [B] | <= 92 % | 81.1 % | +10.9 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [B] | <= 92 % | 85.1 % | +6.9 % |
| PASS | AW-5 | DAC pin load at window ends [B] | <= 0.1 mA | 8.5 uA | +91.5 uA |
| PASS | AW-2 | one DAC code at the output [B] (ideal 12-bit) | <= 1 mV | 0.624 mV | +0.376 mV |
| PASS | AW-2 | info: single-code step incl. datasheet DNL +3 LSB (the Due's, not an AFE limit) | nominal step <= 1 mV | 2.48 mV |  |
| PASS | AW-7 info | nominal parts, DAC at Vmid (1.65 V): output (zero-offset pick Rf/Rg = Rb/Ra + Rb/Rx) | info (a few mV) | +6.66 mV |  |
| PASS | AW-1 | circuit swing: output at +/-1.0 V commanded (high-Z level), into hiz, 2 Vmid x 3 rail corners, weak corner +3.230 / -1.968 V (blanket +/-5 % of the setting): error against the linear map | <= 0.62 mV (one DAC code, AW-2) | 0.00 mV (smallest &#124;v(bnc)&#124; 0.9960 V, target 1.0 V) | +0.62 mV |
| PASS | AW-1 info | circuit swing: output at +/-1.0 V commanded (high-Z level), into r50, 2 Vmid x 3 rail corners, weak corner +3.235 / -2.039 V (LM27762 datasheet: VFB+/- limits (Sec 5.5) and 0.1 % feedback resistors): error against the linear map [model rails, 0.2 ohm = 200 uV/mA: information; the row below is judged] | <= 0.62 mV (one DAC code, AW-2) | 0.76 mV (smallest &#124;v(bnc)&#124; 0.4993 V, target 0.5 V) | -0.14 mV |
| PASS | AW-1 | circuit swing into r50, the same corners, rails at the datasheet load regulation 34 uV/mA (judged; VT-8 measures the + rail into 50 ohm) | <= 0.62 mV (one DAC code, AW-2) | 0.31 mV | +0.31 mV |
| PASS | AW-3/SM-3 | stage -3 dB bandwidth, OPA365, nominal, into 1 Mohm &#124;&#124; 15 pF | >= 8 MHz | 15.1 MHz | +7.1 MHz |
| PASS | AW-3 info | gain 10 kHz-8 MHz relative to DC, V+ parasitic 0.5 / 1.5 / 3.5 pF (attenuator compensation Ca, Cb) | info (host calibrates, CA-1) | 0.869..1.000 nominal, 0.860..1.000 over the three |  |
| PASS | AW-3/AW-4 | bandwidth into 50 ohm over capacitor/parasitic corners | >= 8 MHz | 9.5 MHz | +1.5 MHz |
| PASS | AW-3/SM-3 | bandwidth over 16 capacitor/parasitic corners | >= 8 MHz | 13.5..16.2 MHz | +5.5 MHz |
| PASS | AW-3/SM-3 | bandwidth with the buffer output at 5 / 10 / 30 pF, hi-Z and 50 ohm | >= 8 MHz | 10.0 MHz | +2.0 MHz |
| PASS | AW-3/AW-7 | DAC output impedance tolerated (swept 0-3k; datasheet gives none) | gain 1.10-1.20 and BW >= 8 MHz | ok up to 1000 ohm of [0, 100, 300, 1000, 3000] |  |
| PASS | AN-1 | phase margin, OPA365, 4 loads, +2 pF at the inverting node | >= 45 deg | 69.6 deg | +24.6 deg |
| **FAIL** | model | OPA365 follower overshoot against CL, the datasheet test (G = +1, RL 10 k, +/-2.5 V, 200 mV step): model vs Fig 7-15 at 10/30/40/70/100/200/300 pF | within +/-10 points at every CL | 8(6) / 15(8) / 17(10) / 23(20) / 27(28) / 35(42) / 39(50) % sim(datasheet) | -0.4 points |
| PASS | model | OPA365 follower, 200 mV step, model at CL 0 / 10 / 20 pF (a probe) vs Fig 7-16 (about 13 %, no CL stated) | one of them within +/-5 points | 2.8 / 7.5 / 11.4 % (13) | +3.4 points |
| PASS | model info | OPA365 follower alone, 1 nF, loop-break PM (datasheet Sec 8.3.3: stable to about 1 nF in unity gain) | info | 11.7 deg at 12.3 MHz |  |
| PASS | model | buffer loop break: &#124;T/(1+T)&#124; against the simulated closed loop bin -> bo, 52 pF load, 10 kHz-30 MHz (no -IN replica; with a 6 pF replica) | agree within 10 % | 2.2 % (2.3 % with 6 pF) | +7.8 % |
| PASS | AN-1 | DAC0 buffer phase margin [no injection branch]: attenuator + pin trace 5-10 pF, DAC 0.578/1.65/2.771 V, + rail 3.23/3.37 V | >= 45 deg (target 50) | 59.8 deg | +14.8 deg |
| PASS | AN-1 target | DAC0 buffer [no injection branch]: the design target with a 15 pF pin trace (the 5-10 pF assumption + 50 %) | >= 50 deg | 55.2 deg | +5.2 deg |
| PASS | AN-1 info | DAC0 buffer [no injection branch]: 20 / 30 pF at its pin | info (>= 45 deg) | 51.4 / 45.3 deg |  |
| PASS | AN-1 info | DAC0 buffer [no injection branch]: largest trace capacitance at its pin that keeps 45 deg (worst operating point) | info | 30 pF |  |
| PASS | AN-1 info | sim/loop's Middlebrook injection on the same circuit, DAC 1.65 V, 3.3 V: 10 / 52 / 1000 pF (loop break in brackets) | info (why the loop run saw no capacitive-load effect) | 77.0 (63.7) / 77.0 (41.0) / 77.2 (9.7) deg |  |
| PASS | AN-1 info | DAC0 buffer [no injection branch], 100 mV step at 1.6 V: pin overshoot at 10 / 15 pF | info | 0.2 / 0.6 % |  |
| PASS | AW-4 | amplitude into 50 ohm / into high-Z: total series 49.9 ohm (accuracy cost of the protection, host calibrates it) | ideal 0.5005 for the resistors | 0.5005 | +0.00 % from ideal |
| PASS | AW-1 | into 50 ohm: BNC amplitude when the hi-Z amplitude is +/-1.0 V (<= 92 % of the window) | +/-0.5 V (AW-1 second clause) | +/-0.501 V | +0.001 V |
| PASS | AW-3/AW-4 | -3 dB bandwidth into hiz | >= 8 MHz | 15.1 MHz | +7.1 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_open | >= 8 MHz | 14.5 MHz | +6.5 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_r50 | >= 8 MHz | 10.0 MHz | +2.0 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_scope | >= 8 MHz | 13.8 MHz | +5.8 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into r50 | >= 8 MHz | 10.0 MHz | +2.0 MHz |
| PASS | AW-4 info | 1 m (5 ns) open cable, ideal 2 ns edge (stricter than any signal this stage can make): ringing after 60 ns, source 49.9 ohm | info (reflection coefficient (Zs-50)/(Zs+50)) | 0.0 % ring |  |
| PASS | AW-4 | same cable open, real stage, 42 ns DAC-class edge: far-end overshoot, worst of V+ parasitic 0.5 / 1.5 / 3.5 pF | <= 5 % | 1.2 % (1.2 / 1.1 / 1.0) | +3.8 % |
| PASS | AW-4 | same cable terminated in 50 ohm: overshoot | <= 5 % | 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into hiz: 10-90 % rise, overshoot | overshoot <= 5 % | 300 ns, 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into cable_scope: 10-90 % rise, overshoot | overshoot <= 5 % | 300 ns, 0.3 % | +4.7 % |
| PASS | AW-6 | added noise, quiet DC source, OPA365: circuit .noise 10 Hz-100 MHz | <= 100 uV rms | 87.6 uV | +12.4 uV |
| PASS | AW-6/PW-2 | sum with supply noise, 2 MHz ripple and harmonics, Vmid buffer (10 nV/rtHz assumed) | <= 100 uV rms | 89.9 uV | +10.1 uV |
| PASS | AW-6/PW-2 | LM27762 ripple at the AWG output alone (5 mV / n on the LDO 2.2 uF, behind 0.8 uH; 1.7-2.3 MHz worst; both rails in phase; sim/powercal P4-b method) | <= 20 uV rms (powercal P4-b allocation, 20 % of AW-6) | 11.21 uV at 1.7 MHz (rails 0.49 / 0.38 mV at 2 MHz); flat 5 mV harmonics 20.96 uV | +8.79 uV |
| PASS | AW-6/PW-2 info | the same with the earlier rail assumptions: one nominal 10 uF, 10 mohm, no ESL / one nominal 10 uF, 20 mohm, no ESL | info (20 uV) | 19.56 / 29.04 uV |  |
| **FAIL** | AW-6 | same circuit with OPA354 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 131.3 uV | -31.3 uV |
| **FAIL** | AW-6 | same circuit with OPA356 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 102.2 uV | -2.2 uV |
| PASS | PW-3 | short to ground at +/-1 V commanded: output current | <= 30 mA | 20.2 mA | +9.8 mA |
| PASS | PW-3 | short at the DAC window ends: output current | <= 30 mA | 26.08 mA | +3.92 mA |
| PASS | PW-3/PW-1 | op-amp supply current in the short (+ and - pins summed), AFE total limit 100 mA | <= 100 mA | 25.9 mA | +74.1 mA |
| PASS | PW-1 | AFE in normal operation, AWG shorted (AW-4 allows it): powercal 49.1 mA (incl. the DAC0 buffer at 5 mA) + AWG increase 26.6 mA | <= 100 mA | 75.7 mA | +24.3 mA |
| PASS | PW-1 | same, buffer at 5 mA + its attenuator load 1.33 mA (model Iq 4.24 mA, worst buffer current 5.57 mA) | <= 100 mA | 77.0 mA | +23.0 mA |
| PASS | PW-3 | op-amp dissipation in the short | OPA365 SOT-23 limit *(check)* | 36 mW |  |
| PASS | AW-8 | DAC0 pin floating: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.720..-1.521 V | +0.380 V |
| PASS | AW-8 | DAC0 pin 0 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.720..-1.521 V | +0.380 V |
| PASS | AW-8 | DAC0 pin post-boot -0.1 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.720..-1.521 V | +0.380 V |
| PASS | AW-8 | DAC0 pin post-boot +0.2 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.702..-1.521 V | +0.398 V |
| PASS | AW-8 | DAC0 pin code 0 (0.578 V): output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.267..-1.187 V | +0.833 V |
| PASS | AW-8 | DAC0 pin mid 1.67 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -0.010..+0.070 V | +2.030 V |
| PASS | AW-8 | DAC0 pin window top 2.771 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | +1.257..+1.338 V | +0.762 V |
| PASS | AW-8 | DAC0 pin 3.3 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | +1.434..+1.513 V | +0.587 V |
| PASS | AW-8 | DAC0 pin swept 0..3.3 V in 0.1 V steps, 2 loads, 4 Vmid/rail corners | &#124;out&#124; <= 2.1 V | 1.720 V | +0.380 V |
| PASS | AW-8 | reset ramp: DAC0 jumps to 3.3 V, falls linearly to 0 V, rests, returns to 1.65 V (time scaled 1e4) | &#124;out&#124; <= 2.1 V throughout | peak 1.722 V, after return 1.722 V, final -33 mV | +0.378 V |
| PASS | AW-8 | 4 start-up orders x DAC0 floating / 0 V / 3.3 V x Vmid at t=0 or rising with the + rail x Vmid 1.55 / 1.685 V (48 runs) | &#124;out&#124; <= 2.1 V | 1.745 V (- rail first/DAC 0 V/Vmid at t=0/1.55) | +0.355 V |
| PASS | AW-8 | power-up with the AWG's own Vmid (330k / 330k, 12 pF tap) on +3.3 V_A, soft-start 20 us / 2 ms, DAC0 on the reset trace / 3.3 V / 0 V, both + rail corners, first 60 ms | &#124;out&#124; <= 2.1 V | 1.720 V (0 V held/soft-start 2 ms/+3.37; over 2.1 V for 0.00 s) | +0.380 V |
| PASS | AN/PR (abs max) | DAC0 buffer supply pins during the 48 start-up runs (V- at ground) | < 5.5 V (OPA365 abs max) | 3.052 V | +2.448 V |
| PASS | AN/PR (abs max) | op-amp supply pins, +3.37/-2.17 V + the calibrated LDO ripple, 4 start-up orders: max V+ minus V- | < 5.5 V (OPA365 abs max) | 4.783 V | +0.717 V |
| PASS | AN/PR (abs max) | bare rails (no Schottky) at the LM27762 datasheet maxima: VFB+ 1.218 V, VFB- -1.238 V (Sec 5.5), 0.1 % dividers: +3.342 / -2.103 V | < 5.5 V (OPA365 abs max) | 5.445 V | +0.055 V |
| PASS | AW-8 | output during the four start-up orders, DAC floating, Vmid present from t=0 | &#124;out&#124; <= 2.1 V | 1.743 V | +0.357 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V (3 commanded levels): op-amp supply pins, max V+ minus V- | < 5.5 V | 4.12 V | +1.38 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V for 10 s: series resistor power (assumed 2010, 0.5 W; its current is the macromodel limit, 65 mA typ in the part) | <= 0.5 W | 0.287 W | +0.213 W |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V: clamp power per diode (BAV99 package 250 mW *(check)*) | <= 0.25 W | 0.0 mW (clamp 0.0 mA) |  |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE total = 50.4 mA (powercal, datasheet maxima incl. the DAC0 buffer's 5 mA + its 1.35 mA load) + supply increase 73 mA; Due 300 mA + AFE (PR-4: a fault is judged against the PW-1 450 mA limit, docs/afe.md) | <= 450 mA | 423 mA | +27 mA |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered, estimate only: supply increase scaled to the 65 mA typical ISC (the macromodel conducts 76 mA): AFE 113 mA | <= 450 mA total (PR-4) *(check, estimate)* | 413 mA | +37 mA |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE supply rails stay in (max +, min -); the Due 3.3 V pin is only sensed, nothing returns to it | info (op-amp pin-to-pin < 5.5 V above) | +3.24 / -2.01 V |  |
| PASS | PR-4/PR-3 | [S1 49.9, 3-diode stacks, op-amp side] unpowered +/-5 V (supply-pin Schottkys + 4.7 k bleed): AFE rails and current into the rails | rails < 0.5 V, <= 100 uA | 2 mV, 0.23 uA | +0.498 V |
| PASS | PR-4 | stated level +/-1.8 V (>= +/-1.5 V): derived 65 mA x 49.85 ohm - 1.338 V (worst commanded, DAC window end) | >= 1.5 V and <= derived | 1.8 V <= 1.903 V | +0.103 V |
| PASS | PR-4 | forced +/-1.8 V, DAC at either window end, 4 corners, resistor 49.85 ohm: op-amp output current, clamp present | <= 65 mA (ISC typ) *(check)* | 57.1 mA (clamp 0.01 mA) | +7.9 mA |
| PASS | PR-4 | same, clamp removed (the clamps not conducting) | <= 65 mA (ISC typ) *(check)* | 57.1 mA | +7.9 mA |
| PASS | PR-4 | normal range: output at +/-1.15 V commanded, forced +/-2.0 V of the opposite sign: op-amp output current | <= 65 mA (ISC typ) *(check)* | 58.5 mA | +6.5 mA |
| PASS | PR-4/AW-8 | 3-diode stack: voltage at which it carries 1 mA (model, recalled figures *(check)*) | >= 2.1 V (AW-8 limit; above the level) | 2.15 V (2-diode stack 1.43 V) | +0.05 V |
| PASS | AW-7 | 3-diode stack: current at the op-amp output at 1.0 / 1.15 / 1.38 V | info | 1.870 / 4.27 / 15.1 uA |  |
| PASS | AW-7 | output error caused by the clamp, DAC over its window, hi-Z and 50 ohm, 2 Vmid/rail corners | <= 0.62 mV (one DAC code, AW-2; chosen allocation) | 0.0493 mV | +0.571 mV |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered/+5: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +2/+0 mV, into rails +0.23/+0.00 uA, DAC pin +0.000 V, buffer out/in +0.00/+0.000 V, buffer pins +0.00 V, op-amp pins +2.56/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered, DAC high-Z/+5: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +2/+0 mV, into rails +0.23/+0.00 uA, DAC pin +0.000 V, buffer out/in +0.00/+0.000 V, buffer pins +0.00 V, op-amp pins +2.56/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered/-5: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.23 uA, DAC pin -0.000 V, buffer out/in -0.00/-0.000 V, buffer pins -0.00 V, op-amp pins -0.00/-2.53 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered, DAC high-Z/-5: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.23 uA, DAC pin -0.000 V, buffer out/in -0.00/-0.000 V, buffer pins -0.00 V, op-amp pins -0.00/-2.53 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered/+1.8: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1/+0 mV, into rails +0.13/+0.00 uA, DAC pin +0.000 V, buffer out/in +0.00/+0.000 V, buffer pins +0.00 V, op-amp pins +1.37/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered, DAC high-Z/+1.8: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1/+0 mV, into rails +0.13/+0.00 uA, DAC pin +0.000 V, buffer out/in +0.00/+0.000 V, buffer pins +0.00 V, op-amp pins +1.37/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered/-1.8: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.13 uA, DAC pin -0.000 V, buffer out/in -0.00/-0.000 V, buffer pins -0.00 V, op-amp pins -0.00/-1.32 V |  |
| PASS | PR-4/PR-3/PR-2 | buffered circuit, unpowered, DAC high-Z/-1.8: rails (incl. the buffer's +3.3 V_A), current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.13 uA, DAC pin -0.000 V, buffer out/in -0.00/-0.000 V, buffer pins -0.00 V, op-amp pins -0.00/-1.32 V |  |
| PASS | PR-2/AN-3 | AFE rails off, Due drives DAC0 0.578..3.3 V: DAC pin voltage | -0.2..3.45 V | the Due drives the pin: 0.578..3.3 V |  |
| PASS | AN-3/AW-5 | AFE rails off, DAC0 0.578..3.3 V into the dead buffer (ESD diodes only) through 680 ohm: current from the DAC pin | <= 0.1 mA (AW-5's value; the datasheet gives none) | 10.2 uA (buffer supply pin charged to 2.83 V) | +89.8 uA |
| PASS | PR-3 | same: AFE rails (+3.3 V_A, + and - op-amp rails) and current into them through the Schottkys | rails < 0.5 V, <= 100 uA | 1.2 mV, 0.251 uA | +0.499 V |
| PASS | AN-3 info | bound: the dead buffer drawing current as 440 ohm across its supply pins, DAC0 0.578..3.3 V: current from the DAC pin | info (0.1 mA is AW-5's powered value) | 2.30 mA (supply pin 1.01 V) | -2204 uA |
| PASS | AN-3 info | bound: the dead buffer drawing current as 1 ohm across its supply pins, DAC0 0.578..3.3 V: current from the DAC pin | info (0.1 mA is AW-5's powered value) | 3.76 mA (supply pin 0.00 V) | -3655 uA |
| PASS | AN-3 info | trade, DAC0 at 2.771 / 3.3 V into a dead buffer modelled as a short (as 440 ohm) across its supply: Rbin 680 / 1k / 1360 | info (0.1 mA AW-5; bandwidth >= 8 MHz AW-3) | 3.76 (2.30) mA / 2.57 (1.80) mA / 1.90 (1.44) mA; BW 50 ohm, +4 pF at the input: 9.1 / 8.1 / 7.2 MHz; hi-Z 12.6 / 10.2 / 8.7 MHz |  |
| PASS | AW-8 info | sense-divider tap (far end at Vmid; the design, k = 1/3: 200k BNC-tap, 100k tap-far end) at AW-8's DC excursions (DAC0 0 V / 3.3 V, rail corners): output -1.720..+1.513 V | info (the ADC input; powercal checks its limits) | tap +0.544..+1.621 V |  |
| PASS | PR-4 info | sense-divider tap (far end at Vmid; the design, k = 1/3: 200k BNC-tap, 100k tap-far end), AWG output forced to +/-1.8 and +/-5 V: powered / unpowered | info (the ADC input; powercal checks its limits) | powered -0.579..+2.760 V; unpowered -2.131..+3.674 V |  |
| PASS | AW-8 info | sense-divider tap (far end at 3.0 V; the design, k = 1/3: 200k BNC-tap, 100k tap-far end) at AW-8's DC excursions (DAC0 0 V / 3.3 V, rail corners): output -1.720..+1.513 V | info (the ADC input; powercal checks its limits) | tap +1.427..+2.504 V |  |
| PASS | PR-4 info | sense-divider tap (far end at 3.0 V; the design, k = 1/3: 200k BNC-tap, 100k tap-far end), AWG output forced to +/-1.8 and +/-5 V: powered / unpowered | info (the ADC input; powercal checks its limits) | powered +0.333..+3.666 V; unpowered -1.667..+1.667 V |  |
| PASS | AW-8 info | sense-divider tap (far end at Vmid; comparison only, k = 2/3: 100k BNC-tap, 200k tap-far end) at AW-8's DC excursions (DAC0 0 V / 3.3 V, rail corners): output -1.720..+1.513 V | info (the ADC input; powercal checks its limits) | tap -0.588..+1.567 V |  |
| PASS | PR-4 info | sense-divider tap (far end at Vmid; comparison only, k = 2/3: 100k BNC-tap, 200k tap-far end), AWG output forced to +/-1.8 and +/-5 V: powered / unpowered | info (the ADC input; powercal checks its limits) | powered -2.790..+3.880 V; unpowered -3.565..+4.337 V |  |
| PASS | AW-8 info | sense-divider tap (far end at 3.0 V; comparison only, k = 2/3: 100k BNC-tap, 200k tap-far end) at AW-8's DC excursions (DAC0 0 V / 3.3 V, rail corners): output -1.720..+1.513 V | info (the ADC input; powercal checks its limits) | tap -0.147..+2.008 V |  |
| PASS | PR-4 info | sense-divider tap (far end at 3.0 V; comparison only, k = 2/3: 100k BNC-tap, 200k tap-far end), AWG output forced to +/-1.8 and +/-5 V: powered / unpowered | info (the ADC input; powercal checks its limits) | powered -2.333..+4.333 V; unpowered -3.333..+3.333 V |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 0 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 3.84 / 0.00 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 0 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 17.51 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 100 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 4.13 / 0.00 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 100 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 19.42 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 300 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 4.62 / 0.00 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 300 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 23.66 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 1000 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 4.68 / 0.00 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 1000 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 42.80 / 0.01 codes |  |
| PASS | guard | wrong Vmid: AW-7 offset check (limit 60 mV) | fails broken, passes restored | broken: -73.3 mV; restored: +6.9 mV |  |
| PASS | guard | slow stage: AW-3 bandwidth check (8 MHz) | fails broken, passes restored | broken: 1.9 MHz; restored: 15.1 MHz |  |
| PASS | guard | 50 ohm removed: AW-4 reflection check, 1 m open cable | fails broken, passes restored | broken: 100 % ring; restored: 0 % ring |  |
| PASS | guard | slope raised: AW-8 DAC0-at-3.3 V output check (2.1 V) | fails broken, passes restored | broken: +2.129 V; restored: +1.513 V |  |
| PASS | guard | buffer bias resistor too small: AW-5 DAC-load check (0.1 mA) | fails broken, passes restored | broken: 258 uA; restored: 8 uA |  |
| PASS | guard | noisy resistors: AW-6 noise check (100 uV) | fails broken, passes restored | broken: 303 uV; restored: 88 uV |  |
| PASS | guard | no feedback capacitor: AN-1 phase-margin check (45 deg) | fails broken, passes restored | broken: 7 deg; restored: 77 deg |  |
| PASS | guard | Rs removed (short): PW-3 short-current check (20 mA) | fails broken, passes restored | broken: 74 mA; restored: 20 mA |  |
| PASS | guard | series resistor 24.9 ohm: PR-4 level check: op-amp current at the stated +/-1.8 V (65 mA) | fails broken, passes restored | broken: 74 mA; restored: 56 mA |  |
| PASS | guard | negative rail at -1.2 V: AW-1 circuit-swing check into high-Z (one code) | fails broken, passes restored | broken: 289.5 mV; restored: 0.0 mV |  |
| PASS | guard | negative rail back at -1.8 V: AW-1 circuit-swing check into 50 ohm, datasheet weak rail corner (one code) | fails broken, passes restored | broken: 33.94 mV at -1.772 V; restored: 0.00 mV at -2.039 V |  |
| PASS | guard | negative rail back at -2.156 V: abs-max check: bare rails at the datasheet maxima (5.5 V) | fails broken, passes restored | broken: 5.532 V; restored: 5.445 V |  |
| PASS | guard | over-compensated attenuator: AW-4 cable overshoot check over the V+ parasitic corners (5 %) | fails broken, passes restored | broken: 41.8 %; restored: 1.2 % |  |
| PASS | guard | clamp stack of 2: PR-4/AW-8 clamp-knee check (1 mA at >= 2.1 V) | fails broken, passes restored | broken: 1.43 V; restored: 2.15 V |  |
| PASS | guard | clamp on the load side: PR-4 clamp power check (250 mW per diode at +/-5 V) | fails broken, passes restored | broken: 654 mW per diode; restored: 0 mW per diode |  |
| PASS | guard | supply-pin Schottkys removed: PR-3 unpowered rails < 0.5 V check, +/-5 V on the BNC | fails broken, passes restored | broken: 2327 mV; restored: 2 mV |  |
| PASS | guard | clamps to the op-amp rails: PR-4 op-amp pin-to-pin margin check (< 4.5 V, 1 V under abs max) | fails broken, passes restored | broken: 6.26 V; restored: 3.62 V |  |
| PASS | guard | ripple source uncalibrated: LM27762 ripple calibration: the source reads 5 mV +/-3 % on the LDO 2.2 uF alone at 2 MHz | fails broken, passes restored | broken: 0.927 mV; restored: 5.000 mV |  |
| PASS | guard | slow stage (PAM): AW-3 information: the one-level PAM step settles to 1 code at the symbol centre | fails broken, passes restored | broken: 7.57 codes; restored: 0.00 codes |  |
| PASS | guard | rail load regulation 200 uV/mA: AW-1 50 ohm check at the datasheet load regulation (one code) | fails broken, passes restored | broken: 0.76 mV; restored: 0.31 mV |  |
| PASS | guard | 1 nF on the buffer output (known unstable): AN-1 DAC0-buffer phase-margin check (45 deg), the loop break | fails broken, passes restored | broken: 8.5 deg; restored: 59.8 deg |  |
| PASS | guard | wrong load against Fig 7-16: model-vs-datasheet check (overshoot within 5 points of 13 %) | fails broken, passes restored | broken: 26.7 / 34.5 / 39.1 %; restored: 2.8 / 7.5 / 11.4 % |  |
| PASS | guard | loop break on the wrong load: buffer loop-break self-check (10 %) | fails broken, passes restored | broken: 37.9 %; restored: 2.2 % |  |
| PASS | guard | buffer bias resistor 10 k: AN-3 unpowered DAC-current check (0.1 mA) | fails broken, passes restored | broken: 309 uA; restored: 10 uA |  |
| PASS | guard | buffer's BAT54 removed: PR-3 unpowered rail check with DAC0 driving (0.5 V) | fails broken, passes restored | broken: 2289 mV; restored: 1 mV |  |
| PASS | guard | series resistor 0.5 ohm: PW-1 normal-operation total with the AWG shorted (100 mA) | fails broken, passes restored | broken: 120.7 mA; restored: 73.9 mA |  |
| PASS | guard | buffer on a 6 V rail: abs-max check on the DAC0 buffer supply pins (5.5 V) | fails broken, passes restored | broken: 5.664 V; restored: 3.041 V |  |
| PASS | guard | slow stage, buffer loaded: AW-3 bandwidth check with the buffer at 30 pF (8 MHz) | fails broken, passes restored | broken: 1.9 MHz; restored: 16.6 MHz |  |
| PASS | guard | AWG Vmid tap slowed (start-up): AW-8 start-up check, worst arm (simultaneous 10 us, DAC0 3.3 V) | fails broken, passes restored | broken: 2.607 V; restored: 1.627 V |  |
| PASS | guard | AWG Vmid tap slowed (power-up): AW-8 power-up check (20 us soft-start, DAC0 reset trace) | fails broken, passes restored | broken: 2.605 V; restored: 1.583 V |  |

## What-if `lowcost` (variant D, 2026-11-11, the $35/board target): the unbuffered AWG with the fast Vmid. Not the design

`python3 -I run.py --variant=lowcost --jobs=4` (`raw_lowcost/`, `netlists_lowcost/`). **Rejected 2026-11-11** (fails AW-8; PAM tail about 10x the design's); kept as a variant only. DAC0 drives the n1 attenuator directly, with no DAC0 buffer (115 rows, 13 FAIL after the PAM rows became information): Ra = (4.7k || 4.7k) + 3 x 4.7k = 16.45k, Rb = 4 x 4.7k = 18.8k (1 %, every placement drawn separately), Ca 20 / Cb 12 pF, Rx 330k to Vmid, Rf 249 + 49.9, Rg 249. Kept from the design: the AWG's own fast Vmid (330k / 330k, 12 pF, OPA365 follower, no output capacitor), 22 || 22 supply filters, BAT54S, the negative rail and the ripple model. The precision ADC reads the BNC as another agent's variant has it: 10k into a 1 Gohm input clamped by BAT54S dies to +3.3 V_A and the - rail. 111 rows, 16 FAIL.

**Side by side with the design** (PRBS/PAM is the instrument's main use; montreal5 flagged this cut):

| row | limit | design (buffered) | lowcost (D) |
|---|---|---|---|
| AW-8, 48 start-up runs | 2.1 V | **1.745 V** PASS | **2.367 V FAIL** (both rails in 10 us, DAC0 at 3.3 V) |
| AW-8, power-up (20 us / 2 ms soft-start) | 2.1 V | **1.720 V** PASS | **2.274 V FAIL** (DAC0 held at 3.3 V, 20 us) |
| AW-8, DAC0 at 3.3 V steady | 2.1 V | 1.513 V | 1.935 V (+0.165) |
| AW-3, PAM16 step at 1.6 Msym/s, AFE-added error at the symbol centre, DAC0 impedance 0 / 100 / 300 ohm (1 k) | information (no settling limit) | full-scale 1.5 V step **3.84 / 4.13 / 4.62 (4.68) codes**; one level **0.00** (DAC0 alone into the ADC: 17.5-42.8 / 0.00) | full-scale **48.4 / 48.5 / 48.4 (47.7) codes**; one level **2.07-2.14** |
| AW-2, one DAC code at the output | 1 mV | 0.620 / 0.624 mV | 0.618 / 0.622 mV |
| AW-1, window use position-aware [A] / [B] | 92 % | 88.8 / 85.1 % | 90.0 / 86.0 % (+2.0) |
| AW-1, into 50 ohm at 34 uV/mA | 0.62 mV | 0.31 mV | 0.29 mV |
| AW-6, total with supply and ripple | 100 uV | 89.9 uV | 95.2 uV (ripple 13.1 uV) |
| AW-5, DAC0 load | 0.1 mA | 8.5 uA | 79.7 uA (+20 uA) |
| AW-4, cable overshoot | 5 % | 1.2 % | 2.7 % |
| PR-3/PR-4 unpowered +/-5 V: AFE rails | 0.5 V | 0 V | **1.52 V FAIL**: through the ADC input's 10k and its clamp diodes into the dead rails (the input arrangement, not the AWG) |
| PR-4, +/-1.8 V level; pins at +/-5 V | 65 mA; 5.5 V | 57.1 mA; 4.12 V | 57.5 mA; 4.17 V |

**What the PAM figures mean.** The full-scale step's DAC ramp (1.5 V at 6 V/us) ends 61 ns before the symbol centre, so the design's 1-5 codes are the stage's last 0.1 % of settling and its cable ringing; its one-level steps are exact. D's residual is the Ca / Cb attenuator tail: about 3 % of a full-scale step and 2 codes on a single 100 mV level, at every DAC0 impedance, which the host cannot remove (SM-5 is held on the raw signal) and which the earlier loop runs showed as the level band growing several-fold. **AW-8 fails in D for a different reason than before:** DAC0 sits at 3.3 V from the Due's own rail while +3.3 V_A and Vmid are still rising; the design's buffer, on +3.3 V_A, cannot follow DAC0 ahead of the rail, and D has no such stage, so the fast Vmid alone does not fix it.

**The AWG Vmid follower, if it is half of a cheaper dual** (behavioural follower, A0 1e5, 50 ohm open-loop output resistance, 20 mA limit): it sinks at most **4.66 mA** (Rg's return with the AWG shorted, DAC0 at 0-3.3 V). Bandwidth and AN-1 do not depend on it (hi-Z 29.5-30.9 MHz, 50 ohm 15.5-16.6 MHz, AN-1 73.6-76.4 deg at 1-50 MHz GBW). The PAM step does: the full-scale error at the centre is 153.7 / 75.7 / 47.3 / 45.4 codes at 1 / 3 / 10 / 50 MHz GBW, against 48.4 with the OPA365. So the part needs **about 10 MHz GBW or more, 5 mA output, rail-to-rail at 1.6 V on a 3 V supply, and stability with no output capacitor**; below 10 MHz it adds to D's PAM error. Its noise counts in AW-6 at about 1.2x (the design's allowance is 10 nV/rtHz).

**The saving** is the coordinator's estimate, about $2.2 per board (the OPA365, its BAT54S die and 100 nF, less the extra Ca / Cb / Rx and 4.7k parts); not checked here. D also removes the design's 0.1 % 953 / 249 / 22 attenuator parts and adds ten 1 % 4.7k placements.

**The trade, plainly:** D keeps AW-1, AW-2, AW-4, AW-5, AW-6 and PR-4 within limits (AW-6 margin 4.8 uV, AW-1 2.0 %), but fails AW-8 at start-up (2.27-2.37 V against 2.1 V), and its PAM steps carry a 3 % attenuator tail, roughly ten times the design's residual on full-scale steps and 2 codes per level where the design has none. For the PRBS/PAM use that tail is the cost; for AW-8 the cost is a start-up excursion of about 0.27 V beyond the stated limit.

### Every row of the lowcost what-if (`raw_lowcost/results.json`)

| | ID | case | limit | worst result | margin |
|---|---|---|---|---|---|
| PASS | model | OPA365 model input noise density at 100 kHz vs datasheet | 4.5 nV/rtHz +/-15 % | 4.49 nV/rtHz | +15 % |
| PASS | model | OPA354 model input noise density at 1000 kHz vs datasheet | 6.5 nV/rtHz +/-15 % | 6.69 nV/rtHz | +12 % |
| PASS | model | loop-gain setup: &#124;T/(1+T)/beta&#124; against the simulated closed loop, 10 kHz-30 MHz | agree within 10 % | 5.4 % | +4.6 % |
| PASS | AW-7 | gain 1.10-1.20 [window theory 1/6-5/6 AREF, +/-30 mV centring] | 1.10..1.20 | 1.1356..1.1514 | +0.0356 |
| PASS | AW-7 info | offset at window centre [A] (calibrated by the MCP3564; AW-1 window use is the binding check) | info (was <= 60 mV) | 91.7 mV | -31.7 mV against the old 60 mV |
| PASS | AW-1 | window use, width [A] | <= 92 % | 82.6 % | +9.4 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [A] | <= 92 % | 90.0 % | +2.0 % |
| PASS | AW-5 | DAC pin load at window ends [A] | <= 0.1 mA | 78.3 uA | +21.7 uA |
| PASS | AW-2 | one DAC code at the output [A] (ideal 12-bit) | <= 1 mV | 0.618 mV | +0.382 mV |
| PASS | AW-7 | gain 1.10-1.20 [measured board window 0.578-2.771 V, +39.5 mV centre] | 1.10..1.20 | 1.1356..1.1514 | +0.0356 |
| PASS | AW-7 info | offset at window centre [B] (calibrated by the MCP3564; AW-1 window use is the binding check) | info (was <= 60 mV) | 95.1 mV | -35.1 mV against the old 60 mV |
| PASS | AW-1 | window use, width [B] | <= 92 % | 82.1 % | +9.9 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [B] | <= 92 % | 86.0 % | +6.0 % |
| PASS | AW-5 | DAC pin load at window ends [B] | <= 0.1 mA | 79.7 uA | +20.3 uA |
| PASS | AW-2 | one DAC code at the output [B] (ideal 12-bit) | <= 1 mV | 0.622 mV | +0.378 mV |
| PASS | AW-2 | info: single-code step incl. datasheet DNL +3 LSB (the Due's, not an AFE limit) | nominal step <= 1 mV | 2.47 mV |  |
| PASS | AW-7 info | nominal parts, DAC at Vmid (1.65 V): output (zero-offset pick Rf/Rg = Rb/Ra + Rb/Rx) | info (a few mV) | +9.63 mV |  |
| PASS | AW-1 | circuit swing: output at +/-1.0 V commanded (high-Z level), into hiz, 2 Vmid x 3 rail corners, weak corner +3.230 / -1.968 V (blanket +/-5 % of the setting): error against the linear map | <= 0.62 mV (one DAC code, AW-2) | 0.00 mV (smallest &#124;v(bnc)&#124; 0.9992 V, target 1.0 V) | +0.62 mV |
| PASS | AW-1 info | circuit swing: output at +/-1.0 V commanded (high-Z level), into r50, 2 Vmid x 3 rail corners, weak corner +3.235 / -2.039 V (LM27762 datasheet: VFB+/- limits (Sec 5.5) and 0.1 % feedback resistors): error against the linear map [model rails, 0.2 ohm = 200 uV/mA: information; the row below is judged] | <= 0.62 mV (one DAC code, AW-2) | 0.71 mV (smallest &#124;v(bnc)&#124; 0.5005 V, target 0.5 V) | -0.09 mV |
| PASS | AW-1 | circuit swing into r50, the same corners, rails at the datasheet load regulation 34 uV/mA (judged; VT-8 measures the + rail into 50 ohm) | <= 0.62 mV (one DAC code, AW-2) | 0.29 mV | +0.33 mV |
| PASS | AW-3/SM-3 | stage -3 dB bandwidth, OPA365, nominal, into 1 Mohm &#124;&#124; 15 pF | >= 8 MHz | 29.5 MHz | +21.5 MHz |
| PASS | AW-3 info | gain 10 kHz-8 MHz relative to DC, V+ parasitic 0.5 / 1.5 / 3.5 pF (attenuator compensation Ca, Cb) | info (host calibrates, CA-1) | 0.945..1.000 nominal, 0.899..1.000 over the three |  |
| PASS | AW-3/AW-4 | bandwidth into 50 ohm over capacitor/parasitic corners | >= 8 MHz | 14.8 MHz | +6.8 MHz |
| PASS | AW-3/SM-3 | bandwidth over 16 capacitor/parasitic corners | >= 8 MHz | 24.0..33.1 MHz | +16.0 MHz |
| PASS | AW-3/AW-7 | DAC output impedance tolerated (swept 0-3k; datasheet gives none) | gain 1.10-1.20 and BW >= 8 MHz | ok up to 1000 ohm of [0, 100, 300, 1000, 3000] |  |
| PASS | AN-1 | phase margin, OPA365, 4 loads, +2 pF at the inverting node | >= 45 deg | 67.3 deg | +22.3 deg |
| PASS | AW-4 | amplitude into 50 ohm / into high-Z: total series 49.9 ohm (accuracy cost of the protection, host calibrates it) | ideal 0.5005 for the resistors | 0.5005 | -0.00 % from ideal |
| PASS | AW-1 | into 50 ohm: BNC amplitude when the hi-Z amplitude is +/-1.0 V (<= 92 % of the window) | +/-0.5 V (AW-1 second clause) | +/-0.500 V | +0.000 V |
| PASS | AW-3/AW-4 | -3 dB bandwidth into hiz | >= 8 MHz | 29.5 MHz | +21.5 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_open | >= 8 MHz | 19.1 MHz | +11.1 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_r50 | >= 8 MHz | 17.0 MHz | +9.0 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_scope | >= 8 MHz | 17.8 MHz | +9.8 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into r50 | >= 8 MHz | 17.0 MHz | +9.0 MHz |
| PASS | AW-4 info | 1 m (5 ns) open cable, ideal 2 ns edge (stricter than any signal this stage can make): ringing after 60 ns, source 49.9 ohm | info (reflection coefficient (Zs-50)/(Zs+50)) | 0.0 % ring |  |
| PASS | AW-4 | same cable open, real stage, 42 ns DAC-class edge: far-end overshoot, worst of V+ parasitic 0.5 / 1.5 / 3.5 pF | <= 5 % | 2.7 % (2.7 / 0.5 / 0.1) | +2.3 % |
| PASS | AW-4 | same cable terminated in 50 ohm: overshoot | <= 5 % | 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into hiz: 10-90 % rise, overshoot | overshoot <= 5 % | 305 ns, 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into cable_scope: 10-90 % rise, overshoot | overshoot <= 5 % | 306 ns, 0.0 % | +5.0 % |
| PASS | AW-6 | added noise, quiet DC source, OPA365: circuit .noise 10 Hz-100 MHz | <= 100 uV rms | 87.3 uV | +12.7 uV |
| PASS | AW-6/PW-2 | sum with supply noise, 2 MHz ripple and harmonics, Vmid buffer (10 nV/rtHz assumed) | <= 100 uV rms | 95.2 uV | +4.8 uV |
| PASS | AW-6/PW-2 | LM27762 ripple at the AWG output alone (5 mV / n on the LDO 2.2 uF, behind 0.8 uH; 1.7-2.3 MHz worst; both rails in phase; sim/powercal P4-b method) | <= 20 uV rms (powercal P4-b allocation, 20 % of AW-6) | 13.09 uV at 1.7 MHz (rails 0.49 / 0.38 mV at 2 MHz); flat 5 mV harmonics 26.53 uV | +6.91 uV |
| PASS | AW-6/PW-2 info | the same with the earlier rail assumptions: one nominal 10 uF, 10 mohm, no ESL / one nominal 10 uF, 20 mohm, no ESL | info (20 uV) | 22.32 / 33.18 uV |  |
| **FAIL** | AW-6 | same circuit with OPA354 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 151.0 uV | -51.0 uV |
| **FAIL** | AW-6 | same circuit with OPA356 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 133.5 uV | -33.5 uV |
| PASS | PW-3 | short to ground at +/-1 V commanded: output current | <= 30 mA | 20.3 mA | +9.7 mA |
| PASS | PW-3 | short at the DAC window ends: output current | <= 30 mA | 25.94 mA | +4.06 mA |
| PASS | PW-3/PW-1 | op-amp supply current in the short (+ and - pins summed), AFE total limit 100 mA | <= 100 mA | 25.3 mA | +74.7 mA |
| PASS | PW-3 | op-amp dissipation in the short | OPA365 SOT-23 limit *(check)* | 36 mW |  |
| PASS | AW-8 | DAC0 pin floating: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.574..-1.384 V | +0.526 V |
| PASS | AW-8 | DAC0 pin 0 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.574..-1.384 V | +0.526 V |
| PASS | AW-8 | DAC0 pin post-boot -0.1 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.574..-1.384 V | +0.526 V |
| PASS | AW-8 | DAC0 pin post-boot +0.2 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.574..-1.384 V | +0.526 V |
| PASS | AW-8 | DAC0 pin code 0 (0.578 V): output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -1.255..-1.175 V | +0.845 V |
| PASS | AW-8 | DAC0 pin mid 1.67 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | -0.007..+0.072 V | +2.028 V |
| PASS | AW-8 | DAC0 pin window top 2.771 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | +1.251..+1.331 V | +0.769 V |
| PASS | AW-8 | DAC0 pin 3.3 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.17) | &#124;out&#124; <= 2.1 V | +1.855..+1.935 V | +0.165 V |
| PASS | AW-8 | DAC0 pin swept 0..3.3 V in 0.1 V steps, 2 loads, 4 Vmid/rail corners | &#124;out&#124; <= 2.1 V | 1.935 V | +0.165 V |
| PASS | AW-8 | reset ramp: DAC0 jumps to 3.3 V, falls linearly to 0 V, rests, returns to 1.65 V (time scaled 1e4) | &#124;out&#124; <= 2.1 V throughout | peak 1.833 V, after return 1.535 V, final -30 mV | +0.267 V |
| **FAIL** | AW-8 | 4 start-up orders x DAC0 floating / 0 V / 3.3 V x Vmid at t=0 or rising with the + rail x Vmid 1.55 / 1.685 V (48 runs) | &#124;out&#124; <= 2.1 V | 2.367 V (simultaneous 10 us/DAC 3.3 V/Vmid at t=0/1.55) | -0.267 V |
| **FAIL** | AW-8 | power-up with the AWG's own Vmid (330k / 330k, 12 pF tap) on +3.3 V_A, soft-start 20 us / 2 ms, DAC0 on the reset trace / 3.3 V / 0 V, both + rail corners, first 60 ms | &#124;out&#124; <= 2.1 V | 2.274 V (3.3 V held/soft-start 0.02 ms/+3.37; over 2.1 V for 0.00 s) | -0.174 V |
| PASS | AN/PR (abs max) | op-amp supply pins, +3.37/-2.17 V + the calibrated LDO ripple, 4 start-up orders: max V+ minus V- | < 5.5 V (OPA365 abs max) | 4.713 V | +0.787 V |
| PASS | AN/PR (abs max) | bare rails (no Schottky) at the LM27762 datasheet maxima: VFB+ 1.218 V, VFB- -1.238 V (Sec 5.5), 0.1 % dividers: +3.342 / -2.103 V | < 5.5 V (OPA365 abs max) | 5.445 V | +0.055 V |
| PASS | AW-8 | output during the four start-up orders, DAC floating, Vmid present from t=0 | &#124;out&#124; <= 2.1 V | 1.604 V | +0.496 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V (3 commanded levels): op-amp supply pins, max V+ minus V- | < 5.5 V | 4.17 V | +1.33 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V for 10 s: series resistor power (assumed 2010, 0.5 W; its current is the macromodel limit, 65 mA typ in the part) | <= 0.5 W | 0.314 W | +0.186 W |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V: clamp power per diode (BAV99 package 250 mW *(check)*) | <= 0.25 W | 0.0 mW (clamp 0.0 mA) |  |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE total = 49.1 mA (powercal, datasheet maxima) + supply increase 71 mA; Due 300 mA + AFE (PR-4: a fault is judged against the PW-1 450 mA limit, docs/afe.md) | <= 450 mA | 420 mA | +30 mA |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered, estimate only: supply increase scaled to the 65 mA typical ISC (the macromodel conducts 79 mA): AFE 107 mA | <= 450 mA total (PR-4) *(check, estimate)* | 407 mA | +43 mA |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE supply rails stay in (max +, min -); the Due 3.3 V pin is only sensed, nothing returns to it | info (op-amp pin-to-pin < 5.5 V above) | +3.24 / -2.01 V |  |
| **FAIL** | PR-4/PR-3 | [S1 49.9, 3-diode stacks, op-amp side] unpowered +/-5 V (supply-pin Schottkys + 4.7 k bleed): AFE rails and current into the rails | rails < 0.5 V, <= 100 uA | 1519 mV, 0.13 uA | -1.019 V |
| PASS | PR-4 | stated level +/-1.8 V (>= +/-1.5 V): derived 65 mA x 49.85 ohm - 1.331 V (worst commanded, DAC window end) | >= 1.5 V and <= derived | 1.8 V <= 1.910 V | +0.110 V |
| PASS | PR-4 | forced +/-1.8 V, DAC at either window end, 4 corners, resistor 49.85 ohm: op-amp output current, clamp present | <= 65 mA (ISC typ) *(check)* | 57.5 mA (clamp 0.01 mA) | +7.5 mA |
| PASS | PR-4 | same, clamp removed (the clamps not conducting) | <= 65 mA (ISC typ) *(check)* | 57.5 mA | +7.5 mA |
| PASS | PR-4 | normal range: output at +/-1.15 V commanded, forced +/-2.0 V of the opposite sign: op-amp output current | <= 65 mA (ISC typ) *(check)* | 58.9 mA | +6.1 mA |
| PASS | PR-4/AW-8 | 3-diode stack: voltage at which it carries 1 mA (model, recalled figures *(check)*) | >= 2.1 V (AW-8 limit; above the level) | 2.15 V (2-diode stack 1.43 V) | +0.05 V |
| PASS | AW-7 | 3-diode stack: current at the op-amp output at 1.0 / 1.15 / 1.38 V | info | 1.870 / 4.27 / 15.1 uA |  |
| PASS | AW-7 | output error caused by the clamp, DAC over its window, hi-Z and 50 ohm, 2 Vmid/rail corners | <= 0.62 mV (one DAC code, AW-2; chosen allocation) | 0.0655 mV | +0.554 mV |
| **FAIL** | PR-4/PR-3/PR-2 | recommended circuit, unpowered/+5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1512/+0 mV, into rails +0.11/+0.00 uA, DAC pin +0.00 V, op-amp pins +2.58/+0.00 V |  |
| **FAIL** | PR-4/PR-3/PR-2 | recommended circuit, unpowered, DAC high-Z/+5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1512/+0 mV, into rails +0.11/+0.00 uA, DAC pin +0.16 V, op-amp pins +2.58/+0.00 V |  |
| **FAIL** | PR-4/PR-3/PR-2 | recommended circuit, unpowered/-5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1519 mV, into rails -0.00/-0.11 uA, DAC pin -0.00 V, op-amp pins -0.00/-2.53 V |  |
| **FAIL** | PR-4/PR-3/PR-2 | recommended circuit, unpowered, DAC high-Z/-5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1519 mV, into rails -0.00/-0.11 uA, DAC pin -0.04 V, op-amp pins -0.00/-2.53 V |  |
| PASS | PR-2/AN-3 | AFE rails off, Due drives DAC0 over its window: DAC pin voltage | -0.2..3.45 V | the Due drives the pin: 0.578..2.771 V |  |
| PASS | AN-3/AW-5 | AFE rails off, DAC0 over its window: current drawn from the DAC pin (clamp conduction) | info (0.1 mA is the powered limit) | 81 uA | +19 uA |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 0 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 48.38 / 2.07 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 0 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 17.51 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 100 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 48.45 / 2.08 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 100 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 19.42 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 300 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 48.36 / 2.09 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 300 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 23.66 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 1000 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 47.72 / 2.14 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 1000 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 42.80 / 0.01 codes |  |
| PASS | guard | wrong Vmid: AW-7 offset check (limit 60 mV) | fails broken, passes restored | broken: -69.9 mV; restored: +9.6 mV |  |
| PASS | guard | slow stage: AW-3 bandwidth check (8 MHz) | fails broken, passes restored | broken: 5.5 MHz; restored: 29.5 MHz |  |
| PASS | guard | 50 ohm removed: AW-4 reflection check, 1 m open cable | fails broken, passes restored | broken: 100 % ring; restored: 0 % ring |  |
| **FAIL** | guard | rails raised: AW-8 DAC0-at-3.3 V output check (2.1 V) | fails broken, passes restored | broken: +2.019 V; restored: +1.855 V |  |
| PASS | guard | Ra too small: AW-5 DAC-load check (0.1 mA) | fails broken, passes restored | broken: 113 uA; restored: 78 uA |  |
| PASS | guard | noisy resistors: AW-6 noise check (100 uV) | fails broken, passes restored | broken: 267 uV; restored: 87 uV |  |
| PASS | guard | no feedback capacitor: AN-1 phase-margin check (45 deg) | fails broken, passes restored | broken: 17 deg; restored: 75 deg |  |
| PASS | guard | Rs removed (short): PW-3 short-current check (20 mA) | fails broken, passes restored | broken: 76 mA; restored: 20 mA |  |
| PASS | guard | series resistor 24.9 ohm: PR-4 level check: op-amp current at the stated +/-1.8 V (65 mA) | fails broken, passes restored | broken: 76 mA; restored: 57 mA |  |
| PASS | guard | negative rail at -1.5 V: AW-1 circuit-swing check into high-Z (one code) | fails broken, passes restored | broken: 117.4 mV; restored: 0.0 mV |  |
| PASS | guard | negative rail back at -1.8 V: AW-1 circuit-swing check into 50 ohm, datasheet weak rail corner (one code) | fails broken, passes restored | broken: 74.84 mV at -1.772 V; restored: 0.02 mV at -2.039 V |  |
| PASS | guard | negative rail back at -2.156 V: abs-max check: bare rails at the datasheet maxima (5.5 V) | fails broken, passes restored | broken: 5.532 V; restored: 5.445 V |  |
| PASS | guard | over-compensated attenuator: AW-4 cable overshoot check over the V+ parasitic corners (5 %) | fails broken, passes restored | broken: 5.3 %; restored: 2.7 % |  |
| PASS | guard | clamp stack of 2: PR-4/AW-8 clamp-knee check (1 mA at >= 2.1 V) | fails broken, passes restored | broken: 1.43 V; restored: 2.15 V |  |
| PASS | guard | clamp on the load side: PR-4 clamp power check (250 mW per diode at +/-5 V) | fails broken, passes restored | broken: 654 mW per diode; restored: 0 mW per diode |  |
| **FAIL** | guard | supply-pin Schottkys removed: PR-3 unpowered rails < 0.5 V check, +/-5 V on the BNC | fails broken, passes restored | broken: 2353 mV; restored: 1519 mV |  |
| PASS | guard | clamps to the op-amp rails: PR-4 op-amp pin-to-pin margin check (< 4.5 V, 1 V under abs max) | fails broken, passes restored | broken: 6.31 V; restored: 3.66 V |  |
| PASS | guard | ripple source uncalibrated: LM27762 ripple calibration: the source reads 5 mV +/-3 % on the LDO 2.2 uF alone at 2 MHz | fails broken, passes restored | broken: 0.927 mV; restored: 5.000 mV |  |
| **FAIL** | guard | AWG Vmid tap slowed (start-up): AW-8 start-up check, worst arm (simultaneous 10 us, DAC0 3.3 V) | fails broken, passes restored | broken: 2.564 V; restored: 2.367 V |  |
| **FAIL** | guard | AWG Vmid tap slowed (power-up): AW-8 power-up check (20 us soft-start, DAC0 reset trace) | fails broken, passes restored | broken: 2.578 V; restored: 2.274 V |  |
| PASS | AW info | AWG Vmid follower as a 1MHz GBW part (behavioural): AW-3 bandwidth hi-Z / 50 ohm (peaking); AN-1 of the gain stage; PAM step at the centre; its worst output current (AWG shorted, DAC0 0 / 0.578 / 2.771 / 3.3 V) | info (8 MHz, 45 deg, 1 code) | 30.9 / 16.2 MHz (0.00 dB); 73.6 deg; 153.74 codes; 4.66 mA |  |
| PASS | AW info | AWG Vmid follower as a 3MHz GBW part (behavioural): AW-3 bandwidth hi-Z / 50 ohm (peaking); AN-1 of the gain stage; PAM step at the centre; its worst output current (AWG shorted, DAC0 0 / 0.578 / 2.771 / 3.3 V) | info (8 MHz, 45 deg, 1 code) | 30.9 / 15.8 MHz (0.00 dB); 74.2 deg; 75.69 codes; 4.66 mA |  |
| PASS | AW info | AWG Vmid follower as a 10MHz GBW part (behavioural): AW-3 bandwidth hi-Z / 50 ohm (peaking); AN-1 of the gain stage; PAM step at the centre; its worst output current (AWG shorted, DAC0 0 / 0.578 / 2.771 / 3.3 V) | info (8 MHz, 45 deg, 1 code) | 30.2 / 15.5 MHz (0.00 dB); 76.0 deg; 47.26 codes; 4.66 mA |  |
| PASS | AW info | AWG Vmid follower as a 50MHz GBW part (behavioural): AW-3 bandwidth hi-Z / 50 ohm (peaking); AN-1 of the gain stage; PAM step at the centre; its worst output current (AWG shorted, DAC0 0 / 0.578 / 2.771 / 3.3 V) | info (8 MHz, 45 deg, 1 code) | 29.5 / 16.6 MHz (0.00 dB); 76.4 deg; 45.39 codes; 4.66 mA |  |

## Legacy design (`--variant=legacy`): the unbuffered stage, revisions 4-7

Superseded by the design above (owner, 2026-11-11) and kept reproducible. Its sections below keep the revision 6 prose; the table is revision 7.

### Recommendation (revision 6, superseded)

**OPA365, no feedback capacitor and no band limit** (owner decision, SC-5/MC-6).

| part | revision 3 | **revision 4** | part (`docs/jlcpcb-parts.md`) | shared with |
|---|---|---|---|---|
| Ra | 13.7 k | 13.7 k | C7256564, 0.1 %, 10 ppm/K | AWG only |
| Rb | 15.8 k | 15.8 k | C1705888, 0.1 %, 10 ppm/K | AWG only |
| Rx (V+ to Vmid) | 23.7 k | **330 k** | the scope's R2 type, 0.1 %, 25 ppm/K; its LCSC number is not recorded in `jlcpcb-parts.md` *(check)* | scope R2 |
| Rf | 191 (no stocked 0.1 % part) | **249 + 49.9 in series = 298.9** | 249: C2692731 (10 ppm/K); 49.9: the 1206 output resistor's type, C869759 (10 ppm/K) | scope RG; AWG Rs |
| Rg | 105 | **249** | C2692731 | scope RG |
| Ca (across Ra) | 20 pF | 20 pF | C-number not recorded *(check)* | AWG only |
| Cb (V+ to ground) | 22 pF | **12 pF** | Basic by snippet only, C-number not found *(check)* | scope C1 |
| LM27762 OUT- divider R3 / R4 (revision 6) | 47.5 k / 100 k (-1.80 V); revision 5 330 k &#124;&#124; 100 k / 100 k (-2.156 V) | **768 k &#124;&#124; 330 k / 330 k (-2.0733 V)** | the 768 k and 330 k types already in the BOM, 0.1 % | scope R1/R3 (768 k), scope R2 (330 k) |

**Part types:** 191, 105, 23.7k and 22 pF leave the BOM and nothing new enters it; revision 5 removed 47.5 k (one more placement: R3 is two parts), and revision 6 keeps three placements and adds no type (the divider moves from the 100 k type to the 768 k type). AWG-only types fall from seven (13.7k, 15.8k, 23.7k, 191, 105, 20 pF, 22 pF; 191 unstocked) to three (13.7k, 15.8k, 20 pF). The cost is one more placement: Rf is two parts.
G = 1 + Rf/Rg = 2.200 (was 2.819); slope DAC to output Rb/Ra = 1.1533 (1.1529 with the 0.57 mV residue). Unchanged: 10 ohm in each op-amp supply pin with 10 uF + 100 nF, Vmid a buffered low-impedance level,
a BAT54-class Schottky in each op-amp supply pin plus **4.7 k bleed** on +3.3 V (powercal baseline). The merged single bleed value is 4.7 k, which this model already carried, so the back-feed rows do not move for it.

### Negative rail (revision 6): -2.073 V, and the basis of the AW-1 50 ohm weak corner

**Owner decision (2026-11-11):** OUT- moves from -2.156 V to -2.073 V so that the bare rails at the LM27762's tolerance maxima stay under the OPA365's 5.5 V absolute maximum, and the AW-1 50 ohm swing row takes its weak corner at the LM27762 datasheet feedback-reference tolerance instead of a blanket +/-5 % of the setting.

**Datasheet basis** (SNVSAF7C, `models/lm27762/lm27762.pdf`, read for this revision): OUT- = -1.22 V x (R3 + R4) / R4 (Sec 7.2.2.3, Eq. 3), R4 no less than 50 kohm; VFB- -1.238 / -1.22 / -1.202 V min / typ / max and VFB+ 1.182 / 1.2 / 1.218 V, both **over the full temperature range** (Sec 5.5, Electrical Characteristics); adjustable -1.5 to -5 V. The datasheet gives **no FB- input current**, so the divider's source impedance (R3 &#124;&#124; R4 = 136 kohm here, 43 kohm at -2.156 V) times an unknown pin current is an unquantified offset on the rail *(check: FB- input current; VT-8 reads the rail)*. Load regulation (34 uV/mA typ at -1.8 V) is inside the model's 0.2 ohm rail resistance; line regulation (1.5 mV/V typ) is not added.

**Divider: R3 = 768 k &#124;&#124; 330 k, R4 = 330 k**, both 0.1 % types already in the BOM (the scope's R1/R3 and R2), three placements, no new type. Nominal -1.22 x 1.69945 = **-2.0733 V**. The other BOM-only divider with the same ratio, R3 768 k / R4 768 k + 330 k, has 452 kohm source impedance against 136 kohm and was not taken (the FB- current is unknown). With the 0.1 % resistors at their worst ratio:

| | weak (VFB at its low limit, ratio low) | nominal | strong (VFB at its high limit, ratio high) |
|---|---|---|---|
| - rail | -2.041 V | -2.073 V | -2.106 V |
| + rail (174 k / 100 k, powercal) | +3.235 V | +3.288 V | +3.342 V |
| blanket corner (+/-5 %, every other row) | +3.23 / -1.970 V | | +3.37 / -2.177 V |

**Bare rails at the datasheet maxima: 3.342 + 2.106 = 5.447 V, 0.053 V under the OPA365's 5.5 V** (revision 5: 5.532 V, over). That is DC only: the LM27762's start-up overshoot is not in the datasheet *(check, VT-8)*. A start-up re-run of powercal's P1 netlist at -2.073 V (a scratch copy of `sim/powercal/run.py` with only R3/R4 changed; `sim/powercal` itself is not edited here and still carries -2.156 V) gives: op-amp pins 4.893 V in every start-up order with the supply-pin Schottkys (P1-a, 0.607 V margin; revision 5 4.976 V), 5.489 V on the bare rails in the transient (11 mV margin), and **300 mV of overshoot per rail tolerated with the Schottkys** (5.446 V at 0.3 V; 5.642 V at 0.4 V), 0 mV without. Revision 5 tolerated 200 mV.

**AW-1 into 50 ohm at the datasheet weak corner (+3.235 / -2.041 V): 0.02 mV error, BNC -0.4974 V, margin 0.60 mV of the 0.62 mV (one code) limit.** In rail volts: a bisection with everything else fixed puts the row's edge at **-1.971 V**, so the datasheet weak corner sits **70 mV** below it; that 70 mV is what is left for more Schottky or filter drop at 19 mA than the recalled BAT54 model gives, or for an FB- pin current *(check)*. The blanket +/-5 % corner of this setting (-1.970 V) lies just past the edge and **fails, 1.04 mV** (the guard "blanket 5 % weak corner" holds this). So the row passes on the datasheet basis only, as the owner's decision states; it would not pass on the blanket basis.

Earlier scan of the rail (revision 5, the driver's own `swing_err`, worst of Vmid 1.55 / 1.685 at +3.23 V), for reference:

| - rail at the weak corner | -1.80 | -1.90 | -1.95 | -2.00 | -2.05 | -2.10 |
|---|---|---|---|---|---|---|
| AW-1 50 ohm error, negative half | 60.8 mV | 25.2 mV | 7.6 mV | 0.044 mV | 0.019 mV | 0.008 mV |

What moved against revision 5 (-2.156 V):

| | revision 4 (-1.80 V) | revision 5 (-2.156 V) | **revision 6 (-2.073 V)** |
|---|---|---|---|
| bare rails at LM27762 datasheet maxima | 5.208 V | 5.532 V, above OPA365's 5.5 V | **5.447 V** |
| op-amp pins, powercal P1 netlist (all start-up orders, Schottkys) | 4.617 V | 4.976 V | **4.893 V** (scratch re-run) |
| P1-b: overshoot per rail tolerated, both rails together | 400 mV | 200 mV | **300 mV** (scratch re-run) |
| op-amp pins, this driver (+3.37 V and the blanket strong - corner, recalled BAT54) | 4.289 V | 4.650 V | **4.566 V** |
| PR-4 +/-5 V powered, pin to pin | 3.76 V | 4.12 V | **4.03 V** |
| AW-1 50 ohm weak corner (basis) | -1.71 V (5 %) | -2.048 V (5 %) | **-2.041 V (datasheet)** |

**(b) A lower-drop -V pin arrangement (not chosen, revision 5).** No diode datasheet is in the repository (the Nexperia and Diodes downloads are blocked, `models/SOURCES.md`), so no Vf at 20 mA can be cited for a lower-drop Schottky, and the BAT54 figure itself is recalled *(check)*.

### How the values were picked (`run.py`'s DC map, scripted search)

Zero output at Vdac = Vmid requires **Rf/Rg = Rb/Ra + Rb/Rx**, and then the slope is exactly **Rb/Ra**. Ra and Rb set the slope and AW-5; Rx and Rf/Rg must then satisfy the equation.
The search took each of Ra, Rb, Rx, Rf, Rg from the stocked set (49.9, 105, 249, 953, 13.7k, 15.8k, 23.7k, 100k, 330k, 768k) or a series/parallel pair of set values, kept
combinations with slope 1.12-1.18 and nominal offset within 3 mV, then ran `dc_mc` (both DAC-window scenarios, AREF 3.2 and 3.3 V, 0.1 %) on them.

- **No all-single-part combination** comes within 25 mV of zero offset: the best, Rx 15.8k / Rf 105 / Rg 49.9, is 25.7 mV off; Rx 13.7k / Rf 249 / Rg 105 is 32.4 mV off. 191 has no stocked 0.1 % part, so the zero needs a pair somewhere.
- **The pick** keeps Ra and Rb (slope and AW-5 sizing) and moves Rx to 330 k, so the required Rf/Rg is 1.1533 + 0.0479 = 1.2012, against 298.9/249 = 1.2004: **nominal offset +0.57 mV analytic**.
- Runners-up with seven placements and no new type: Rx 768k, Rf 249 &#124;&#124; 23.7k, Rg 105 + 105 (+0.36 mV; keeps the 23.7k and 105 types); Rx 100k, Rf 249 + 953, Rg 953 &#124;&#124; 23.7k (-0.51 mV; Rf &#124;&#124; Rg 520 ohm, noisier).
  Keeping G near 2.8 needs Rb 105 + 15.8k, Rx 23.7k &#124;&#124; 330k, Rf 249 &#124;&#124; 953 (eight placements). A single new value (453 ohm against Rg 249) would need a stocked 0.1 % 453, which was not looked for and is not needed.
- The ngspice operating point at Vdac = Vmid = 1.65 V reads **+4.02 mV** (revision 3: +6.9 mV, the restored arm of the Vmid guard). The 3.5 mV above the analytic figure is the op-amp model's own offset and bias, not separated.
- `budget/awg_tol.py`, every part at its 0.1 % corner: slope 1.1505-1.1552, offset -3.0..+4.2 mV (revision 3 values: -3.7..+4.8 mV). At 0.2 % (0.1 % plus 25 ppm/K over an assumed +/-40 K *(check: AW-7 states no temperature range)*): 1.1482-1.1576 and 7.8 mV. With Rx alone at 1 % the offset is 4.5 mV, so a 1 % 330k would also do for Rx. 5 % parts fail AW-7 (its guard; with the guard set to 0.1 % its assertion fires).

### What lowering G changed, and the attenuator compensation

G falls from 2.82 to 2.20 because Rb/Rx falls from 0.667 to 0.048. Bandwidth rises (19.5 to 31.6 MHz into high-Z), phase margin falls (73.0 to 64.3 deg, the open cable), and the op-amp's noise contribution is about the same (73.2 uV against 74.0: lower gain, wider band), so AW-6 moves from 80.1 to 79.4 uV.

Rx also sets the attenuator: Ca x Ra must match (Rb &#124;&#124; Rx) x C(V+), and Rb &#124;&#124; Rx went from 9.5 k to 15.1 k. **With the old 20 / 22 pF the gain 1 MHz above DC was 0.82 of DC**, and every -3 dB row still passed (17 MHz), so the driver could not see it. Two checks were added:

- an informational row: gain 10 kHz-8 MHz relative to DC at V+ parasitic 0.5 / 1.5 / 3.5 pF;
- the AW-4 open-cable overshoot row now takes the **worst of the three parasitic corners** (it read 1.5 pF only). Broken on purpose: Ca 33 / Cb 22 pF is flat at 1.5 pF (0.993-1.009) and reads 5.7 % at 0.5 pF, so it fails. Revision 3's 20 / 22 pF read 2.4 % at 0.5 pF on its own resistors.

A capacitor sweep (10-47 pF each; a scratch script, not in `run.py`) shows the trade: matched at 1.5 pF means over-compensated at 0.5 pF and an overshoot over 5 %; under-compensated means a slow tail. **Ca 20 / Cb 12 pF** is matched at the 0.5 pF corner:
overshoot 3.0 / 0.7 / 0.1 % (0.5 / 1.5 / 3.5 pF); gain 10 kHz-8 MHz 0.952-1.002 of DC nominal and 0.906-1.002 over the corners (revision 3: 0.924-1.003 and 0.888-1.009); and it reuses the scope's 12 pF.
**Its cost is settling to 1 %, which no row limits:** the 42 ns edge into the open cable settles in 340 ns (revision 3: 73 ns), the 5 V/us DAC edge in 547 ns from its start (390 ns). Against AW-3's 1.6 Msym/s patterns (625 ns per symbol) that is inside a symbol but no longer far inside *(check whether AW-3 needs a settling limit)*. Ca 33 / Cb 22 settles in 95 ns but fails the corner overshoot.

### Protection, PR-4 and PW-1 (unchanged circuit)

**Output protection (owner decision 2026-11-11):** op-amp output -> **one 49.9 ohm, 0.1 % resistor** -> BNC, plus **a 3-diode stack each way to ground (6 BAV99-class diodes) on the op-amp side of the resistor.** 49.9 +/-0.05 ohm is inside AW-4's 50 ohm +/-1 %.

**Resistor power in a 10 s fault:** 0.309 W at +/-5 V (revision 5: 0.312 W; the macromodel conducts 79 mA, 77 mA in revision 4; at the 65 mA typical ISC it would be 0.21 W) and 0.21 W (65 mA, derived) at the stated level.

**Stated PR-4 level: +/-1.8 V** for 10 s, powered or unpowered. V forced = 65 mA x R - V commanded, R at its 0.1 % low end, 49.85 ohm (3.240 V):

| output commanded | what it is | level |
|---|---|---|
| +/-1.15 V | the normal range | **+/-2.09 V** |
| +/-1.408 V | **the DAC window end, the largest the Due can command (all Vmid and rail corners)** | **+/-1.832 V, stated as +/-1.8 V** |
| +/-2.1 V | AW-8's excursion during reset/boot | +/-1.14 V (a fault in the reset window is not covered) |

In the circuit: 56.2 mA at +/-1.8 V with and without the clamps (the clamp carries 0.02 mA); 57.7 mA for +/-1.15 V commanded and +/-2.0 V forced (revision 5: 56.3 and 57.7 mA; revision 4: 56.0 and 57.4 mA). The derived figures are the claim: the macromodel has no datasheet current limit, and 65 mA is a typical, not a maximum *(check)*.

**The clamp** cannot reduce the op-amp's current; on the load side it is worse than none (393 / 914 mA through 3 / 2 diodes at +/-5 V); on the op-amp side it turns on at 2.15 V (1 mA), above the stated level and AW-8's 2.1 V. Output error it causes: **0.022 mV** over the DAC window (revision 5: 0.030 mV; revision 4: 0.097 mV; one code is 0.62 mV). Unpowered at +/-5 V it takes 36 of 41 mA, leaving 5 mA in what the driver labels the op-amp's ESD path (source minus clamp current, so it also holds the Rf + Rg path to the unpowered Vmid; 8 mA without the clamp). No PR-4, PR-3 or AW row needs it.

**PW-1 in a fault.** At +/-5 V powered the op-amp supplies 79 mA (macromodel), the supply increase is 70 mA, the AFE 104 mA (33.8 mA from powercal, now read from `../powercal/results.json`, plus the increase): **Due 300 mA + AFE = 404 mA** (unchanged by the -2.073 V rail: the supply increase is 70.0 mA, as in revision 5).
`docs/afe.md` PR-4 says that during such a fault the Due and the AFE stay within **PW-1's 450 mA limit**, the 400 mA target applying to normal operation, so both rows are judged against 450 mA: **PASS, 46 mA spare** (estimate at the 65 mA typical ISC: 392 mA). Revision 4 read 403 mA.

**Back-feed (PR-3) with the 4.7 k bleed.** Unpowered at +/-5 V and +/-3 V: AFE rails 0 mV, 0.10 uA into the rails (limit 100 uA, rails < 0.5 V), DAC pin 0 V (PR-2), op-amp pins 2.52 V. Powered +/-5 V: AFE rails +3.24 / -2.02 V, op-amp pins 4.03 V apart through the Schottkys (abs max 5.5 V; revision 5: -2.10 V and 4.12 V; revision 4: -1.74 V and 3.76 V).

## Legacy: protection arrangements compared (`case_protect`; every arrangement carries the supply-pin Schottkys and the 4.7 k bleed)

Worst of 3 commanded levels (0.578 / 1.65 / 2.771 V) x forced +/-5 V (and +/-3 V). The AFE total column is Due 300 mA + AFE as simulated.

| arrangement | op-amp current +/-5 V | source current +/-5 V | clamp current +/-5 V | clamp / resistor power +/-5 V | op-amp current +/-3 V | AFE total, +/-5 V (sim) | unpowered +/-5 V: source / clamp / left for the op-amp's ESD | unpowered rails | 50 ohm / hi-Z | AW-3 BW into 50 ohm | noise |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 49.9, no clamp | 79 mA | 79 mA | 0.0 mA | 0.00 / 0.31 W (+0.00 W in R2) | 69 mA | 404 mA | 8 / 0 / 8 mA | 0 mV | 0.500 | 17.4 MHz | 79.4 uV |
| S1 49.9, 3-diode stacks, op-amp side | 79 mA | 79 mA | 0.0 mA | 0.00 / 0.31 W (+0.00 W in R2) | 69 mA | 404 mA | 41 / 36 / 5 mA | 0 mV | 0.500 | 17.4 MHz | 79.4 uV |
| S2 49.9, 3-diode stacks, BNC side | 79 mA | 471 mA | 392.5 mA | 1.96 / 0.31 W (+0.00 W in R2) | 69 mA | 404 mA | 401 / 393 / 8 mA | 0 mV | 0.500 | 17.4 MHz | 79.0 uV |
| S3 49.9, 2-diode stacks, op-amp side | 79 mA | 79 mA | 0.6 mA | 0.00 / 0.31 W (+0.00 W in R2) | 69 mA | 404 mA | 59 / 55 / 4 mA | 0 mV | 0.500 | 17.4 MHz | 79.5 uV |
| S4 49.9, 2-diode stacks, BNC side | 79 mA | 992 mA | 913.8 mA | 4.57 / 0.31 W (+0.00 W in R2) | 69 mA | 404 mA | 922 / 914 / 8 mA | 0 mV | 0.500 | 17.4 MHz | 78.8 uV |
| H 49.9 + 24.9, 2-diode stacks (rejected: Zout 75) | 59 mA | 117 mA | 91.2 mA | 0.21 / 0.17 W (+0.34 W in R2) | 53 mA | 388 mA | 108 / 104 / 4 mA | 0 mV | 0.401 | 19.1 MHz | 77.0 uV |

S1 remains the choice: S3's 2-diode knee (1.43 V) sits in AW-8's range. H is kept for comparison only.

## Legacy pass/fail table (`--variant=legacy`, `raw_legacy/results.json`, revision 8 rail model)

| | ID | case | limit | worst result | margin |
|---|---|---|---|---|---|
| PASS | model | OPA365 model input noise density at 100 kHz vs datasheet | 4.5 nV/rtHz +/-15 % | 4.49 nV/rtHz | +15 % |
| PASS | model | OPA354 model input noise density at 1000 kHz vs datasheet | 6.5 nV/rtHz +/-15 % | 6.69 nV/rtHz | +12 % |
| PASS | model | loop-gain setup: &#124;T/(1+T)/beta&#124; against the simulated closed loop, 10 kHz-30 MHz | agree within 10 % | 2.0 % | +8.0 % |
| PASS | AW-7 | gain 1.10-1.20 [window theory 1/6-5/6 AREF, +/-30 mV centring] | 1.10..1.20 | 1.1508..1.1551 | +0.0449 |
| PASS | AW-7 | offset at window centre [A] | <= 60 mV | 37.6 mV | +22.4 mV |
| PASS | AW-1 | window use, width [A] | <= 92 % | 81.5 % | +10.5 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [A] | <= 92 % | 84.4 % | +7.6 % |
| PASS | AW-5 | DAC pin load at window ends [A] | <= 0.1 mA | 93.1 uA | +6.9 uA |
| PASS | AW-2 | one DAC code at the output [A] (ideal 12-bit) | <= 1 mV | 0.620 mV | +0.380 mV |
| PASS | AW-7 | gain 1.10-1.20 [measured board window 0.578-2.771 V, +39.5 mV centre] | 1.10..1.20 | 1.1508..1.1551 | +0.0449 |
| PASS | AW-7 | offset at window centre [B] | <= 60 mV | 55.1 mV | +4.9 mV |
| PASS | AW-1 | window use, width [B] | <= 92 % | 81.0 % | +11.0 % |
| PASS | AW-1 | window use, position-aware (+/-1 V ends vs window ends) [B] | <= 92 % | 85.2 % | +6.8 % |
| PASS | AW-5 | DAC pin load at window ends [B] | <= 0.1 mA | 94.7 uA | +5.3 uA |
| PASS | AW-2 | one DAC code at the output [B] (ideal 12-bit) | <= 1 mV | 0.624 mV | +0.376 mV |
| PASS | AW-2 | info: single-code step incl. datasheet DNL +3 LSB (the Due's, not an AFE limit) | nominal step <= 1 mV | 2.48 mV |  |
| PASS | AW-7 info | nominal parts, DAC at Vmid (1.65 V): output (zero-offset pick Rf/Rg = Rb/Ra + Rb/Rx) | info (a few mV) | +4.04 mV |  |
| PASS | AW-1 | circuit swing: output at +/-1.0 V commanded (high-Z level), into hiz, 2 Vmid x 3 rail corners, weak corner +3.230 / -1.970 V (blanket +/-5 % of the setting): error against the linear map | <= 0.62 mV (one DAC code, AW-2) | 0.00 mV (smallest &#124;v(bnc)&#124; 0.9937 V, target 1.0 V) | +0.62 mV |
| PASS | AW-1 | circuit swing: output at +/-1.0 V commanded (high-Z level), into r50, 2 Vmid x 3 rail corners, weak corner +3.235 / -2.041 V (LM27762 datasheet: VFB+/- limits (Sec 5.5) and 0.1 % feedback resistors): error against the linear map | <= 0.62 mV (one DAC code, AW-2) | 0.02 mV (smallest &#124;v(bnc)&#124; 0.4974 V, target 0.5 V) | +0.60 mV |
| PASS | AW-3/SM-3 | stage -3 dB bandwidth, OPA365, nominal, into 1 Mohm &#124;&#124; 15 pF | >= 8 MHz | 30.9 MHz | +22.9 MHz |
| PASS | AW-3 info | gain 10 kHz-8 MHz relative to DC, V+ parasitic 0.5 / 1.5 / 3.5 pF (attenuator compensation Ca, Cb) | info (host calibrates, CA-1) | 0.951..1.002 nominal, 0.906..1.002 over the three |  |
| PASS | AW-3/AW-4 | bandwidth into 50 ohm over capacitor/parasitic corners | >= 8 MHz | 15.1 MHz | +7.1 MHz |
| PASS | AW-3/SM-3 | bandwidth over 16 capacitor/parasitic corners | >= 8 MHz | 26.3..34.7 MHz | +18.3 MHz |
| PASS | AW-3/AW-7 | DAC output impedance tolerated (swept 0-3k; datasheet gives none) | gain 1.10-1.20 and BW >= 8 MHz | ok up to 1000 ohm of [0, 100, 300, 1000, 3000] |  |
| PASS | AN-1 | phase margin, OPA365, 4 loads, +2 pF at the inverting node | >= 45 deg | 64.8 deg | +19.8 deg |
| PASS | AW-4 | amplitude into 50 ohm / into high-Z: total series 49.9 ohm (accuracy cost of the protection, host calibrates it) | ideal 0.5005 for the resistors | 0.5005 | -0.00 % from ideal |
| PASS | AW-1 | into 50 ohm: BNC amplitude when the hi-Z amplitude is +/-1.0 V (<= 92 % of the window) | +/-0.5 V (AW-1 second clause) | +/-0.500 V | +0.000 V |
| PASS | AW-3/AW-4 | -3 dB bandwidth into hiz | >= 8 MHz | 30.9 MHz | +22.9 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_open | >= 8 MHz | 19.5 MHz | +11.5 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_r50 | >= 8 MHz | 17.4 MHz | +9.4 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into cable_scope | >= 8 MHz | 18.2 MHz | +10.2 MHz |
| PASS | AW-3/AW-4 | -3 dB bandwidth into r50 | >= 8 MHz | 17.4 MHz | +9.4 MHz |
| PASS | AW-4 info | 1 m (5 ns) open cable, ideal 2 ns edge (stricter than any signal this stage can make): ringing after 60 ns, source 49.9 ohm | info (reflection coefficient (Zs-50)/(Zs+50)) | 0.0 % ring |  |
| PASS | AW-4 | same cable open, real stage, 42 ns DAC-class edge: far-end overshoot, worst of V+ parasitic 0.5 / 1.5 / 3.5 pF | <= 5 % | 2.8 % (2.8 / 0.6 / 0.1) | +2.2 % |
| PASS | AW-4 | same cable terminated in 50 ohm: overshoot | <= 5 % | 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into hiz: 10-90 % rise, overshoot | overshoot <= 5 % | 306 ns, 0.0 % | +5.0 % |
| PASS | AW-3 | 5 V/us DAC edge into cable_scope: 10-90 % rise, overshoot | overshoot <= 5 % | 306 ns, 0.0 % | +5.0 % |
| PASS | AW-6 | added noise, quiet DC source, OPA365: circuit .noise 10 Hz-100 MHz | <= 100 uV rms | 79.5 uV | +20.5 uV |
| PASS | AW-6/PW-2 | sum with supply noise, 2 MHz ripple and harmonics, Vmid buffer (10 nV/rtHz assumed) | <= 100 uV rms | 79.7 uV | +20.3 uV |
| PASS | AW-6/PW-2 | LM27762 ripple at the AWG output alone (5 mV / n on the LDO 2.2 uF, behind 0.8 uH; 1.7-2.3 MHz worst; both rails in phase; sim/powercal P4-b method) | <= 20 uV rms (powercal P4-b allocation, 20 % of AW-6) | 5.50 uV at 2.0 MHz (rails 0.49 / 0.38 mV at 2 MHz); flat 5 mV harmonics 13.77 uV | +14.50 uV |
| PASS | AW-6/PW-2 info | the same with the earlier rail assumptions: one nominal 10 uF, 10 mohm, no ESL / one nominal 10 uF, 20 mohm, no ESL | info (20 uV) | 7.61 / 11.63 uV |  |
| **FAIL** | AW-6 | same circuit with OPA354 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 144.5 uV | -44.5 uV |
| **FAIL** | AW-6 | same circuit with OPA356 at its own bandwidth (circuit .noise only) | <= 100 uV rms | 123.6 uV | -23.6 uV |
| PASS | PW-3 | short to ground at +/-1 V commanded: output current | <= 26 mA | 20.1 mA | +5.9 mA |
| PASS | PW-3 | short at the DAC window ends: output current | <= 26 mA | 25.92 mA | +0.08 mA |
| PASS | PW-3/PW-1 | op-amp supply current in the short (+ and - pins summed), AFE total limit 100 mA | <= 100 mA | 25.3 mA | +74.7 mA |
| PASS | PW-3 | op-amp dissipation in the short | OPA365 SOT-23 limit *(check)* | 37 mW |  |
| PASS | AW-8 | DAC0 pin floating: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -1.594..-1.391 V | +0.506 V |
| PASS | AW-8 | DAC0 pin 0 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -1.594..-1.391 V | +0.506 V |
| PASS | AW-8 | DAC0 pin post-boot -0.1 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -1.594..-1.391 V | +0.506 V |
| PASS | AW-8 | DAC0 pin post-boot +0.2 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -1.588..-1.391 V | +0.512 V |
| PASS | AW-8 | DAC0 pin code 0 (0.578 V): output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -1.269..-1.114 V | +0.831 V |
| PASS | AW-8 | DAC0 pin mid 1.67 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | -0.013..+0.142 V | +1.958 V |
| PASS | AW-8 | DAC0 pin window top 2.771 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | +1.253..+1.408 V | +0.692 V |
| PASS | AW-8 | DAC0 pin 3.3 V: output (Vmid 1.55..1.685, rails +3.23..3.37 / -1.97..-2.18) | &#124;out&#124; <= 2.1 V | +1.862..+2.017 V | +0.083 V |
| PASS | AW-8 | DAC0 pin swept 0..3.3 V in 0.1 V steps, 2 loads, 4 Vmid/rail corners | &#124;out&#124; <= 2.1 V | 2.017 V | +0.083 V |
| PASS | AW-8 | reset ramp: DAC0 jumps to 3.3 V, falls linearly to 0 V, rests, returns to 1.65 V (time scaled 1e4) | &#124;out&#124; <= 2.1 V throughout | peak 1.843 V, after return 1.547 V, final -36 mV | +0.257 V |
| **FAIL** | AW-8 | 4 start-up orders x DAC0 floating / 0 V / 3.3 V x Vmid at t=0 or rising with the + rail x Vmid 1.55 / 1.685 V (48 runs) | &#124;out&#124; <= 2.1 V | 2.537 V (simultaneous 10 us/DAC 3.3 V/Vmid with + rail/1.55) | -0.437 V |
| **FAIL** | AW-8 | power-up, Vmid charging with the PW-7 tau 1.65 s, DAC0 on the measured reset trace / 3.3 V / 0 V, 3 s real time | &#124;out&#124; <= 2.1 V | 2.587 V (3.3 V held/1.55; over 2.1 V for 3.00 s) | -0.487 V |
| PASS | AN/PR (abs max) | op-amp supply pins, +3.37/-2.18 V + the calibrated LDO ripple, 4 start-up orders: max V+ minus V- | < 5.5 V (OPA365 abs max) | 4.740 V | +0.760 V |
| PASS | AN/PR (abs max) | bare rails (no Schottky) at the LM27762 datasheet maxima: VFB+ 1.218 V, VFB- -1.238 V (Sec 5.5), 0.1 % dividers: +3.342 / -2.106 V | < 5.5 V (OPA365 abs max) | 5.447 V | +0.053 V |
| PASS | AW-8 | output during the four start-up orders, DAC floating, Vmid present from t=0 | &#124;out&#124; <= 2.1 V | 1.605 V | +0.495 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V (3 commanded levels): op-amp supply pins, max V+ minus V- | < 5.5 V | 4.21 V | +1.29 V |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V for 10 s: series resistor power (assumed 2010, 0.5 W; its current is the macromodel limit, 65 mA typ in the part) | <= 0.5 W | 0.317 W | +0.183 W |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V: clamp power per diode (BAV99 package 250 mW *(check)*) | <= 0.25 W | 0.0 mW (clamp 0.0 mA) |  |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE total = 49.1 mA (powercal, datasheet maxima) + supply increase 71 mA; Due 300 mA + AFE (PR-4: a fault is judged against the PW-1 450 mA limit, docs/afe.md) | <= 450 mA | 420 mA | +30 mA |
| PASS | PW-1/PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered, estimate only: supply increase scaled to the 65 mA typical ISC (the macromodel conducts 80 mA): AFE 107 mA | <= 450 mA total (PR-4) *(check, estimate)* | 407 mA | +43 mA |
| PASS | PR-4 | [S1 49.9, 3-diode stacks, op-amp side] +/-5 V powered: AFE supply rails stay in (max +, min -); the Due 3.3 V pin is only sensed, nothing returns to it | info (op-amp pin-to-pin < 5.5 V above) | +3.24 / -2.02 V |  |
| PASS | PR-4/PR-3 | [S1 49.9, 3-diode stacks, op-amp side] unpowered +/-5 V (supply-pin Schottkys + 4.7 k bleed): AFE rails and current into the rails | rails < 0.5 V, <= 100 uA | 1 mV, 0.22 uA | +0.499 V |
| PASS | PR-4 | stated level +/-1.8 V (>= +/-1.5 V): derived 65 mA x 49.85 ohm - 1.408 V (worst commanded, DAC window end) | >= 1.5 V and <= derived | 1.8 V <= 1.832 V | +0.032 V |
| PASS | PR-4 | forced +/-1.8 V, DAC at either window end, 4 corners, resistor 49.85 ohm: op-amp output current, clamp present | <= 65 mA (ISC typ) *(check)* | 58.2 mA (clamp 0.02 mA) | +6.8 mA |
| PASS | PR-4 | same, clamp removed (the clamps not conducting) | <= 65 mA (ISC typ) *(check)* | 58.2 mA | +6.8 mA |
| PASS | PR-4 | normal range: output at +/-1.15 V commanded, forced +/-2.0 V of the opposite sign: op-amp output current | <= 65 mA (ISC typ) *(check)* | 59.7 mA | +5.3 mA |
| PASS | PR-4/AW-8 | 3-diode stack: voltage at which it carries 1 mA (model, recalled figures *(check)*) | >= 2.1 V (AW-8 limit; above the level) | 2.15 V (2-diode stack 1.43 V) | +0.05 V |
| PASS | AW-7 | 3-diode stack: current at the op-amp output at 1.0 / 1.15 / 1.38 V | info | 1.870 / 4.27 / 15.1 uA |  |
| PASS | AW-7 | output error caused by the clamp, DAC over its window, hi-Z and 50 ohm, 2 Vmid/rail corners | <= 0.62 mV (one DAC code, AW-2; chosen allocation) | 0.0313 mV | +0.589 mV |
| PASS | PR-4/PR-3/PR-2 | recommended circuit, unpowered/+5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1/+0 mV, into rails +0.22/+0.00 uA, DAC pin +0.00 V, op-amp pins +2.50/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | recommended circuit, unpowered, DAC high-Z/+5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails +1/+0 mV, into rails +0.22/+0.00 uA, DAC pin +0.00 V, op-amp pins +2.50/+0.00 V |  |
| PASS | PR-4/PR-3/PR-2 | recommended circuit, unpowered/-5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.22 uA, DAC pin -0.00 V, op-amp pins -0.00/-2.50 V |  |
| PASS | PR-4/PR-3/PR-2 | recommended circuit, unpowered, DAC high-Z/-5: rails, current into rails, DAC pin | rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V | rails -0/-1 mV, into rails -0.00/-0.22 uA, DAC pin -0.00 V, op-amp pins -0.00/-2.50 V |  |
| PASS | PR-2/AN-3 | AFE rails off, Due drives DAC0 over its window: DAC pin voltage | -0.2..3.45 V | the Due drives the pin: 0.578..2.771 V |  |
| PASS | AN-3/AW-5 | AFE rails off, DAC0 over its window: current drawn from the DAC pin (clamp conduction) | info (0.1 mA is the powered limit) | 94 uA | +6 uA |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 0 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 53.16 / 2.16 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 0 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 17.51 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 100 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 53.28 / 2.17 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 100 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 19.42 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 300 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 53.28 / 2.19 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 300 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 23.66 / 0.00 codes |  |
| PASS | AW-3 info | PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance 1000 ohm, high-Z and 1 m cable to a scope: AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step | info (AW-3 sets no settling limit) | 52.27 / 2.24 codes |  |
| PASS | AW-3 info | baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance 1000 ohm: error at the symbol centre, full-scale / one-level step | info (DAC codes) | 42.80 / 0.01 codes |  |
| PASS | guard | wrong Vmid: AW-7 offset check (limit 60 mV) | fails broken, passes restored | broken: -76.3 mV; restored: +4.0 mV |  |
| PASS | guard | slow stage: AW-3 bandwidth check (8 MHz) | fails broken, passes restored | broken: 5.6 MHz; restored: 30.9 MHz |  |
| PASS | guard | 50 ohm removed: AW-4 reflection check, 1 m open cable | fails broken, passes restored | broken: 100 % ring; restored: 0 % ring |  |
| PASS | guard | rails raised: AW-8 DAC0-at-3.3 V output check (2.1 V) | fails broken, passes restored | broken: +2.188 V; restored: +2.017 V |  |
| PASS | guard | Ra too small: AW-5 DAC-load check (0.1 mA) | fails broken, passes restored | broken: 111 uA; restored: 93 uA |  |
| PASS | guard | noisy resistors: AW-6 noise check (100 uV) | fails broken, passes restored | broken: 268 uV; restored: 79 uV |  |
| PASS | guard | no feedback capacitor: AN-1 phase-margin check (45 deg) | fails broken, passes restored | broken: 17 deg; restored: 73 deg |  |
| PASS | guard | Rs removed (short): PW-3 short-current check (20 mA) | fails broken, passes restored | broken: 77 mA; restored: 20 mA |  |
| PASS | guard | series resistor 24.9 ohm: PR-4 level check: op-amp current at the stated +/-1.8 V (65 mA) | fails broken, passes restored | broken: 76 mA; restored: 57 mA |  |
| PASS | guard | negative rail at -1.5 V: AW-1 circuit-swing check into high-Z (one code) | fails broken, passes restored | broken: 103.1 mV; restored: 0.0 mV |  |
| PASS | guard | negative rail back at -1.8 V: AW-1 circuit-swing check into 50 ohm, datasheet weak rail corner (one code) | fails broken, passes restored | broken: 67.14 mV at -1.772 V; restored: 0.02 mV at -2.041 V |  |
| PASS | guard | negative rail back at -2.156 V: abs-max check: bare rails at the datasheet maxima (5.5 V) | fails broken, passes restored | broken: 5.532 V; restored: 5.447 V |  |
| PASS | guard | over-compensated attenuator: AW-4 cable overshoot check over the V+ parasitic corners (5 %) | fails broken, passes restored | broken: 5.6 %; restored: 2.8 % |  |
| PASS | guard | clamp stack of 2: PR-4/AW-8 clamp-knee check (1 mA at >= 2.1 V) | fails broken, passes restored | broken: 1.43 V; restored: 2.15 V |  |
| PASS | guard | clamp on the load side: PR-4 clamp power check (250 mW per diode at +/-5 V) | fails broken, passes restored | broken: 654 mW per diode; restored: 0 mW per diode |  |
| PASS | guard | supply-pin Schottkys removed: PR-3 unpowered rails < 0.5 V check, +/-5 V on the BNC | fails broken, passes restored | broken: 2282 mV; restored: 1 mV |  |
| PASS | guard | clamps to the op-amp rails: PR-4 op-amp pin-to-pin margin check (< 4.5 V, 1 V under abs max) | fails broken, passes restored | broken: 6.39 V; restored: 3.75 V |  |
| PASS | guard | ripple source uncalibrated: LM27762 ripple calibration: the source reads 5 mV +/-3 % on the LDO 2.2 uF alone at 2 MHz | fails broken, passes restored | broken: 0.927 mV; restored: 5.000 mV |  |
| PASS | guard | Vmid lagging the + rail (the check can pass): AW-8 start-up check, its worst arm (simultaneous 10 us, DAC0 3.3 V, 1.55 V) | fails broken, passes restored | broken: 2.537 V; restored: 2.067 V |  |
| PASS | guard | Vmid slow at power-up (the check can pass): AW-8 power-up check, reset-trace arm (2.1 V) | fails broken, passes restored | broken: 2.567 V; restored: 2.015 V |  |

FAIL rows (4): the two AW-6 alternatives (OPA354 144.5 uV, OPA356 123.6 uV; the OPA365 passes at 79.5 uV), and **AW-8 at start-up when Vmid lags** (below).

### Revision 7 (2026-11-11): the Schottky is BAT54S C7420333, and AW-8 is tested with Vmid starting late

The supply-pin Schottky is the fitted BAT54S model (`models-open/bat54s-c7420333/`, see the variant section above) for every design: typical for everything except the AW-1 swing rows, which take the datasheet maximum, with 2 uA leakage. The prose of revision 6 above keeps its figures; this table is current. 96 -> 99 rows, 2 -> 4 FAIL.
- **New (3), two of them FAIL:** AW-8 over 48 start-up runs, now including Vmid rising with the + rail behind its 1 ohm / 10 uF, **2.555 V** (both rails in 10 us, DAC0 at 3.3 V); AW-8 at power-up with Vmid charging at sim/powercal's PW-7 time constant (2 x 330k, 10 uF tap, 1.65 s) while DAC0 sits at its measured reset level, **2.587 V for 3 s** (above 2.1 V for 0.46 s on the reset trace itself); and its guard (Vmid at 0.1 ms: 2.016 V, passes). The cause and the fix are in the variant section: Vmid behind the DAC path while DAC0 is high. The fix there (an AWG-own Vmid starting in microseconds) applies to this design too, which shares the exposure.
- **Dropped:** the AW-1 50 ohm "blanket corner" guard. With the BAT54S model the row passes at that corner (0.06 mV), so the pass no longer rests on the corner's basis.
- **Moved by the diode, still PASS:** AW-8 DAC0 floating / 0 V -1.523 -> **-1.594 V**; start-up pins 4.566 -> **4.698 V**; PR-4 pins 4.03 -> 4.21 V, resistor 0.309 -> 0.317 W, forced +/-1.8 V 56.2 -> 58.2 mA, normal range 57.7 -> 59.7 mA; PW-3 dissipation 34 -> 37 mW; bandwidth hi-Z 31.6 -> 30.9 MHz; AN-1 64.3 -> 64.8 deg; cable overshoot 3.0 -> 2.8 %; AW-6 79.4 -> 79.5 uV; unpowered rails 0 -> 1 mV and 0.10 -> 0.22 uA (leakage); clamp error 0.022 -> 0.031 mV.

### Row changes against revision 5 (93 rows, 2 FAIL -> 96 rows, 2 FAIL)

Only the negative rail changed (-2.156 -> -2.073 V; blanket corners -2.05..-2.26 -> -1.97..-2.18 V) and the AW-1 50 ohm weak corner moved from the blanket 5 % to the datasheet basis (-2.048 V blanket at -2.156 V -> **-2.041 V datasheet** at -2.073 V).
- **New (3):** AN/PR (abs max) bare rails at the datasheet maxima, **5.447 V** (PASS, 0.053 V); guard "blanket 5 % weak corner" on the AW-1 50 ohm row (1.04 mV at -1.970 V broken, 0.02 mV restored); guard "negative rail back at -2.156 V" on the bare-rail row (5.532 V broken, 5.447 V restored).
- **Replaced:** guard "negative rail back at -1.8 V" now breaks to the datasheet weak corner of that setting (-1.772 V): 70.85 mV broken (was 92.9 mV at the blanket -1.71 V), 0.02 mV restored. The two AW-1 swing rows now name their weak corner and its basis in the label.
- **Moved, still PASS:** AW-1 50 ohm 0.02 mV (unchanged; -0.4974 V). AW-8 floating / 0 V / post-boot -0.1 / +0.2 V -1.604..-1.395 -> **-1.523..-1.321 V** (margin 0.496 -> 0.577 V); reset ramp after the return 1.556 -> 1.478 V (peak 1.843 V unchanged); start-up output 1.597 -> 1.516 V; op-amp supply pins in start-up 4.650 -> **4.566 V**.
  PR-4: pins at +/-5 V 4.12 -> 4.03 V; resistor 0.312 -> 0.309 W; rails in the fault -2.10 -> -2.02 V; forced +/-1.8 V 56.3 -> 56.2 mA (both rows); clamp error 0.030 -> 0.022 mV. PW-3 dissipation 33 -> 34 mW. Guards: Rs removed 75 -> 74 mA; rail clamps restored 3.59 -> 3.50 V.
- **Unchanged:** every other row, including both PW-1/PR-4 fault totals (404 mA, +46 mA against 450 mA; estimate 392 mA), AW-7, AW-5, AW-3, AN-1, AW-6 and the code-0 / mid / window-top / 3.3 V AW-8 rows.

### Row changes, revision 4 to revision 5 (92 rows, 3 FAIL -> 93 rows, 2 FAIL)

Only the negative rail changed (-1.80 -> -2.156 V, corners -1.71..-1.89 -> -2.05..-2.26 V), plus the AFE quiescent total now read from powercal (34.2 -> 33.8 mA, the new ladder).
- **FAIL -> PASS:** AW-1 circuit swing into 50 ohm, 92.90 mV (-0.4045 V) -> **0.02 mV (-0.4974 V)**.
- **New (1):** guard "negative rail back at -1.8 V" on that row: 92.9 mV broken, 0.0 mV restored.
- **Moved, still PASS:** AW-1 swing into high-Z 0.02 -> 0.00 mV. AW-8 floating / 0 V / post-boot -0.1 V -1.254..-1.077 -> -1.604..-1.395 V (margin 0.846 -> **0.496 V**), post-boot +0.2 V -> -1.598..-1.395 V, code 0 -1.246..-1.077 -> -1.269..-1.114 V; reset ramp after the return 1.225 -> 1.556 V (peak 1.843 V unchanged); start-up output 1.247 -> 1.597 V; op-amp supply pins in start-up 4.289 -> **4.650 V** (margin 1.211 -> 0.850 V).
  PR-4: pins at +/-5 V 3.76 -> 4.12 V; resistor 0.300 -> 0.312 W; rails in the fault -1.74 -> -2.10 V; forced +/-1.8 V 56.0 -> 56.3 mA (both rows); normal range 57.4 -> 57.7 mA; clamp error 0.097 -> 0.030 mV. PW-1/PR-4 total 403 -> 404 mA (supply increase 69 -> 70 mA, base 34.2 -> 33.8 mA); estimate 392 mA unchanged.
  DAC edge rise 303 / 302 -> 306 / 306 ns; PW-3 dissipation 35 -> 33 mW; nominal offset +4.02 -> +4.03 mV. Guards: Rs removed 73 -> 75 mA; 24.9 ohm 74 -> 75 mA broken; rail clamps restored 3.23 -> 3.59 V.
- **Unchanged:** every other row.

### Row changes, revision 3 to revision 4 (86 rows, 3 FAIL -> 92 rows, 3 FAIL)

- **New (6):** AW-1 circuit swing into high-Z (PASS, 0.02 mV) and into 50 ohm (**FAIL**, below); AW-7 info, nominal offset +4.02 mV; AW-3 info, flatness; guard "negative rail at -1.5 V" (swing row); guard "over-compensated attenuator" (overshoot row).
- **Replaced:** the AW-4 open-cable overshoot row reads the worst of three parasitic corners, 3.0 % (3.0 / 0.7 / 0.1), against 0.7 % at 1.5 pF alone. The two PW-1/PR-4 total rows: limit 400 -> **450 mA** (PR-4), 401 -> 403 mA, **FAIL -> PASS**; estimate 387 -> 392 mA. The PR-4 stated-level row (label 1.408 V instead of 1.409 V; 1.832 V either way).
- **Moved, still PASS:** AW-7 gain 1.1517-1.1542 -> 1.1508-1.1551 (0.1 % parts now); offset A 36.8 -> 37.6 mV, **B 54.1 -> 55.1 mV (margin 4.9 mV, the binding AW-7 row)**; AW-1 window use A 81.4/84.3 -> 81.5/84.4 %, B 80.9/85.1 -> 81.0/85.2 %; **AW-5 90.7 -> 93.1 uA (A), 92.3 -> 94.7 uA (B), margin 5.3 uA** (Rx no longer pulls V+ toward Vmid); AN-3 91 -> 94 uA.
  Bandwidth hi-Z 19.5 -> 31.6 MHz, 50 ohm corners 12.0 -> 15.1, 16 corners 16.2-22.4 -> 26.3-34.7, cable_open 15.8 -> 19.5, cable_r50 and r50 13.2 -> 17.4, cable_scope 15.1 -> 18.2 MHz; **AN-1 73.0 -> 64.3 deg**; loop-gain self-check 1.8 -> 2.1 %.
  DAC edge rise 226 -> 303 ns (hi-Z) and 224 -> 302 ns (scope cable), overshoot 0.0 % both; terminated cable 0.0 % unchanged.
  AW-6 80.1 -> 79.4 uV, with supply/ripple/Vmid 80.2 -> 79.5 uV; OPA354 150.8 -> 144.6, OPA356 139.3 -> 124.7 uV (still FAIL).
  PW-3 window ends 25.94 -> 25.92 mA (margin 0.08 mA); supply current in the short 24.7 -> 25.3 mA; dissipation 34 -> 35 mW.
  AW-8: floating / 0 V / post-boot -1.117..-0.941 -> -1.254..-1.077 V (the op-amp's negative swing limit, below); code 0 -1.110..-0.941 -> -1.246..-1.077 V; mid -0.010..+0.144 -> -0.013..+0.142 V; window top within 1 mV; DAC at 3.3 V and the sweep 2.016 -> 2.017 V (margin 0.083 V); reset ramp peak 1.854 -> 1.843 V, after return 1.075 -> 1.225 V; start-up 1.103 -> 1.247 V; supply pins 4.225 -> 4.289 V.
  PR-4: pins 3.82 -> 3.76 V; resistor 0.329 -> 0.300 W; forced +/-1.8 V 56.4 -> 56.0 mA (both rows); normal range 57.9 -> 57.4 mA; clamp error 0.043 -> 0.097 mV; unpowered op-amp pins 2.48 -> 2.52 V (4 rows; rails and currents unchanged).
  Guards (all still fail broken, pass restored): wrong Vmid -73.2/+6.9 -> -76.3/+4.0 mV; slow stage 6.8/19.5 -> 5.6/31.6 MHz; rails raised +2.501/+2.016 -> +2.188/+2.017 V; Ra too small 113/91 -> 111/93 uA; noisy resistors 196/80 -> 269/79 uV; no compensation 31/81 -> 17/72 deg; Rs removed 76 -> 73 mA; 24.9 ohm 76/56 -> 74/55 mA; Schottkys removed 2245 -> 2282 mV; rail clamps 6.14/3.29 -> 6.08/3.23 V.
- **Unchanged:** the model noise rows, AW-2 rows, the DAC output impedance row (ok up to 1000 ohm; gain 1.112 and 13.8 MHz there), the AW-4 50 ohm ratio and AW-1 50 ohm amplitude rows (0.5005), cable ring 0 %, PW-3 at +/-1 V (20.1 mA), the knee 2.15 V, the clamp-current info, the unpowered rows, the remaining guards.

### AW-1 into 50 ohm: why revision 4 failed it (fixed in revision 5 by a more negative rail; revision 6 keeps it at -2.073 V, above)

The AW-1 DC rows are the linear map and cannot see the op-amp's output swing. The new rows set the DAC to command +/-1.0 V (the high-Z level) at 2 Vmid x 3 rail corners and compare v(bnc) with the linear prediction. **Into 50 ohm the negative half stops at -0.40 to -0.47 V** (error 26-93 mV, worst at the -1.71 V rail); the positive half, and the whole high-Z case, are within 0.02 mV.
Cause, from the operating point at -1.8 V: the op-amp sources about 19 mA there, the 10 ohm supply filter drops 0.19 V and the BAT54 in the -V pin about 0.46 V, so the -V pin sits at -1.14 V and the output at -0.88 V. Without the 10 ohm the worst corner is still 27 mV short (-0.470 V); without the supply-pin Schottkys it is 0.01 mV, but they are what keep PR-3 (the guard reads 2282 mV on the rails without them).
**Revision 3 fails it worse** (same method, scratch run): 136 mV into 50 ohm (-0.359 V) and 48.5 mV into high-Z (-0.94 V at the -1.71 V rail), because its 296 ohm Rf + Rg loaded the output about twice as hard as the new 548 ohm. Revision 5 takes the third option (section "Negative rail"); the Schottky and the 10 ohm stay.

## Legacy: AW-8 over the whole 0-3.3 V sweep and the reset ramp

Worst **2.017 V** (limit 2.1 V, margin 0.083 V) over 0.1 V steps, both loads, four Vmid and rail corners; the reset ramp peaks at 1.843 V and stays within 1.478 V after the return step; floating pin -1.523..-1.321 V; start-up in four rail orders 1.516 V.
With Rx at 330 k a floating DAC0 would take the output to about -1.85 V on the linear map, and DAC0 at 0 V to -1.94 V (Vmid 1.685 V); the op-amp's negative swing limit holds both at -1.32..-1.52 V with the -2.073 V rail (-1.40..-1.60 V with -2.156 V, -1.08..-1.25 V with -1.8 V). Both linear-map values are inside 2.1 V, so the negative side of AW-8 no longer leans on the swing limit. The top is unchanged because the slope is.

## Legacy: requirement problems found (reported, not relaxed)

1. **The OPA365's absolute maximum and AW-1 into 50 ohm now share 0.1 V of negative rail.** At -2.073 V the bare rails are 5.447 V at the LM27762 datasheet maxima (0.053 V under 5.5 V, DC; 5.489 V in powercal's start-up netlist, scratch re-run), and the start-up overshoot tolerated per rail with the Schottkys is 300 mV; the LM27762's overshoot is not in its datasheet *(check; VT-8)*. AW-1 into 50 ohm passes only with its weak corner at the datasheet tolerance (-2.041 V, 70 mV inside the row's -1.971 V edge); the blanket 5 % corner (-1.970 V) fails it at 1.04 mV. Both margins rest on the recalled BAT54 drop *(check)* and on an FB- input current the datasheet does not give *(check)*.
2. **PR-4's level is set by 65 mA x 50 ohm**: +/-1.83 V for the DAC window end, +/-2.09 V for +/-1.15 V commanded, +/-1.14 V if the fault coincides with AW-8's 2.1 V excursion.
3. **AW-5**: 94.7 uA at the window ends (margin 5.3 uA, was 7.7 uA); Ra + Rb = 29.5 k, and Rx no longer helps.
4. **PW-3**: 25.92 mA at the window ends (limit 26 mA, margin 0.08 mA).
5. **PR-4 resistor power**: +/-5 V into 49.9 ohm is 0.31 W in one resistor.
6. **`docs/hardware.md`'s 30 ohm DAC output impedance is the temperature sensor's** (SAM3X/A datasheet 11057B, Table 46-37, printed p.1421); the DAC has none.
7. **The unpowered op-amp** is modelled as its ESD diodes only (the same treatment as powercal's G6).
8. **Settling** (no requirement row): 340 ns and 547 ns to 1 % for the fast and the DAC edge (above).

PW-1 (404 mA in a +/-5 V fault) is not a problem: PR-4 judges it against 450 mA.

## Legacy: AREF margin evidence (not a relaxation)

All AW-1/2/5/7 linear-map limits also hold at AREF 3.10 V (`dc_lowest_aref` = 3.1). The binding limit is AW-7 offset in scenario B (55.1 mV at 3.30 V; 4.9 mV spare).
0.2 % resistors (0.1 % plus an assumed temperature drift *(check)*) instead of 0.1 %: gain 1.149-1.157, offset 40.3 / 56.5 mV, window use 81.6 %.

## Legacy: checks I broke on purpose (revision 6, 18 guards)

| guard | what was broken | check | broken | restored |
|---|---|---|---|---|
| wrong Vmid | Vmid 70 mV off the window centre | AW-7 offset <= 60 mV | -76 mV FAIL | +4 mV PASS |
| slow stage | Cf 100 pF | AW-3 >= 8 MHz | 5.6 MHz FAIL | 31.6 MHz PASS |
| 50 ohm removed | series resistor 1 mohm | AW-4 cable ring <= 2 % (ideal edge) | 100 % FAIL | 0 % PASS |
| gain raised, no clamp | Rf 500 ohm | AW-8 DAC0 at 3.3 V <= 2.1 V | +2.19 V FAIL | +2.02 V PASS |
| Ra too small | Ra 9.09 k | AW-5 <= 0.1 mA | 111 uA FAIL | 93 uA PASS |
| noisy resistors | Rf, Rg x40 | AW-6 <= 100 uV | 269 uV FAIL | 79 uV PASS |
| no compensation | Rf, Rg x20, 6 pF at the inverting node | AN-1 >= 45 deg | 17 deg FAIL | 72 deg PASS |
| Rs removed (short) | both output resistors 0.5 ohm | PW-3 <= 20 mA (guard threshold) | 74 mA FAIL | 20 mA PASS |
| resistor 24.9 ohm | one 24.9 ohm instead of 49.9 | PR-4 op-amp current at +/-1.8 V <= 65 mA | 75 mA FAIL | 55 mA PASS |
| negative rail at -1.5 V | LM27762 -1.5 V instead of -2.073 V | AW-1 circuit swing into high-Z, one code | 111.9 mV FAIL | 0.0 mV PASS |
| negative rail back at -1.8 V (revision 5; revision 6 at the datasheet corner) | LM27762 -1.8 V (47.5k / 100k), datasheet weak corner -1.772 V | AW-1 circuit swing into 50 ohm, one code | 70.85 mV FAIL | 0.02 mV PASS |
| **blanket 5 % weak corner** (revision 6) | the AW-1 50 ohm weak corner at 95 % of -2.073 V (-1.970 V) and +3.23 V, the old basis | AW-1 circuit swing into 50 ohm, one code | 1.04 mV FAIL | 0.02 mV PASS (-2.041 V) |
| **negative rail back at -2.156 V** (revision 6) | OUT- divider 330k &#124;&#124; 100k / 100k | bare rails at the datasheet maxima < 5.5 V | 5.532 V FAIL | 5.447 V PASS |
| **over-compensated attenuator** | Ca 33 / Cb 22 pF | AW-4 cable overshoot over the parasitic corners <= 5 % | 5.7 % FAIL | 3.0 % PASS |
| clamp stack of 2 | 2 diodes per stack instead of 3 | knee (1 mA) >= 2.1 V | 1.43 V FAIL | 2.15 V PASS |
| clamp on the load side | the stacks on the BNC side | clamp power <= 250 mW per diode at +/-5 V | 654 mW FAIL | 0 mW PASS |
| supply-pin Schottkys removed | pins straight to the rails | PR-3 unpowered rails < 0.5 V | 2282 mV FAIL | 0 mV PASS |
| rail clamps instead of ground stacks | Schottky from the BNC to the rails | op-amp pin-to-pin < 4.5 V | 6.08 V FAIL | 3.50 V PASS |

Revision 6: the AW-1 50 ohm row's pass depends on its weak-corner basis, so the basis has a guard (the blanket corner must fail it, and does, 1.04 mV); the row was also re-run whole with `AW1_50_BASIS = 'blanket5'` (FAIL, 1.04 mV, -0.4963 V) and put back (PASS, 0.02 mV). The new bare-rail row fails with the revision 5 divider. Weakness found in revision 5: the 50 ohm swing row had no guard of its own (the -1.5 V guard reads the high-Z row); the new guard breaks the rail back to -1.8 V and the 50 ohm row fails at 92.9 mV. Weaknesses found in revision 4: **the -3 dB rows were blind to an 18 % mid-band gain step** (the old capacitors on the new Rx: 17 MHz, PASS), and the open-cable overshoot row read only the nominal parasitic, so a capacitor pair flat at 1.5 pF passed while failing at 0.5 pF; both are covered now (flatness row, corner overshoot row, its guard). **The AW-1 rows were the linear map only** and could not see the op-amp's swing; the circuit-swing rows and their guard are new. The "noisy resistors" and "no compensation" guards used absolute values tied to the old ratio; they are now multiples of the design's Rf and Rg. The "rails raised" guard (Rf 500 ohm) still fails, by 0.09 V instead of 0.40 V, because the new Rg is 249.
Self-checks in the table: model noise against the datasheet (4.49 vs 4.5, 6.69 vs 6.5 nV/rtHz), the loop-gain setup against the simulated closed loop (2.1 %), and `run.py` prints MISSING if any of AW-1..AW-8, PR-4, PW-2, PW-3, AN-1, AN-3, AN-5 produced no row (none missing).

## Model gaps and the bench test that closes each (both designs)

| gap | effect | closed by |
|---|---|---|
| Diode figures recalled, not read (BAV99, BAT54S, SMF TVS); no JLC stock read | the clamp knee (2.15 V at 1 mA), leakage, the unpowered 36 mA; **the BAT54 drop sets the AW-1 50 ohm swing** (revision 6 absorbs 70 mV more drop at 19 mA at the datasheet weak corner) and, at low current, the OPA365's pin-to-pin voltage (bare rails 5.447 V at the datasheet maxima) | read the datasheets; VT-6 (linearity, swing), VT-5 |
| OPA365 macromodel conducts 69-79 mA at +/-3..5 V, above the 65 mA typical, not fitted to the datasheet limit, no ESD on the output, unknown behaviour unpowered | the 404 mA total, the 79 mA, 10 s survival, the unpowered conduction; its swing under load | VT-5, VT-6 |
| ISC is a typical (65 mA), no maximum read | the stated level has no margin for a part that limits higher *(check)* | datasheet maximum; VT-5 |
| Output resistor TCR and self-heating not read; the 330k's LCSC number not recorded; 25 ppm/K parts over a temperature range AW-7 does not state | AW-4 1 % tolerance, 0.31 W; AW-7 drift | part choice at layout; VT-5, VT-6, VT-12 |
| V+ parasitic capacitance assumed 1.5 pF (0.5-3.5 pF corners); op-amp input capacitance from the model | attenuator compensation: overshoot 0.1-3.0 %, mid-band gain 0.91-1.00, settling | VT-4 on the built board; Cb is the part to change |
| LM27762 behavioural (steady, ramp): no overshoot, start-up, off-state output, 4.7 k bleed from powercal; FB- input current not in the datasheet | PW-2, abs max (300 mV of overshoot per rail tolerated with the -2.073 V rail, P1-b in a scratch re-run), PR-3, the negative swing; an FB- current shifts the rail through 136 kohm *(check)* | VT-8, VT-5 |
| DAC0 output impedance and noise unknown; the reset ramp was measured as a trace only | AW-8 uses a stiff source (worst case); noise swept | VT-6, VT-3, the owner's reset traces |
| Vmid buffer ideal + 1 ohm | AW-6 allowance 10 nV/rtHz | VT-3, VT-8 |
| Op-amp macromodel noise checked at one frequency each; PSRR above 1 MHz not verified | AW-6 79 uV, PW-2 | VT-3 |
| Temperature 27 C only | AW-6 margin 21 % | VT-12 |
| Lossless cable, no connector or layout parasitics | AW-3, AW-4 | VT-4, VT-17 |

## Files

`run.py` (driver; the design by default, `--variant=legacy` for the unbuffered stage), `models/awg_behavioural.lib` + `models/LICENSE` (own, CC BY-SA 4.0), `../../models-open/bat54s-c7420333/` (the fitted BAT54S model, own, CC BY-SA 4.0), `raw/results.json`, `raw/results_vmid.json`, `raw/run.log`, `netlists/` (the design), `raw_legacy/`, `netlists_legacy/`; `../../budget/awg_tol.py` (resistor tolerance, legacy AW-7).
