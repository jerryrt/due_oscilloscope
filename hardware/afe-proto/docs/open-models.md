# Open SPICE models for the AFE: what can be committed

Owner rule: every component that gets a SPICE model must have one that may
be redistributed in this public repository. This page is the result of the
search (2026-11-10/11) and the plan that follows from it. Classes:

- **REDISTRIBUTABLE**: an explicit grant, sentence quoted.
- **USE-ONLY**: a licence that forbids or does not grant redistribution;
  download yourself, never commit.
- **UNCLEAR**: no licence text read, or the text cannot be read as a grant.
  Treated as USE-ONLY.

## Result in one paragraph

**No vendor-published model for any IC in the roles below could be shown to
be redistributable.** TI, Analog Devices, Microchip, Murata, ROHM,
Nexperia and Renesas all say, in the text found, that redistribution is
barred or only "use/copy" is allowed; Diodes Inc., onsemi, ST and Infineon
were not resolved (details below). The only open model found is generic:
the KiCad/ngspice single-pole op-amp, public domain (Holger Vogt), kept in
`models-open/kicad_builtin_opamp/`. **So the plan is: write our own open
behavioural models, fitted to datasheet numbers, and publish those.** The
part numbers in `architecture.md` stay (the real parts are still
the BOM); only the simulation models change. Substituting a different
physical part buys nothing, because no candidate has an open model either.
LCSC/stock figures for the BOM parts are in `jlcpcb.md`; a part that has no
open model was not worth a fresh stock lookup, so none is repeated here
and none is guessed.

Files committed: `models-open/kicad_builtin_opamp/` (model, LICENSE,
SOURCE.txt). Nothing else qualified.

## Vendor licence findings

| source | class | sentence (quoted) | where read |
|---|---|---|---|
| Texas Instruments (OPA354/356/365, LM27762, TMUX1119, TS5A3159) | USE-ONLY | header: "The model is provided solely on an \"as is\" basis"; TS5A3159 HSPICE: may not be given or distributed without TI's written permission (`models/SOURCES.md`); REF3030 model is encrypted | model headers; `models/SOURCES.md`; e.g. OPA1641 header in `/usr/share/kicad/demos/simulation/q17/OPA1641.LIB` |
| Analog Devices / LTspice (AD8051 in the KiCad demo, ADA4xxx, ADR4530, ADG719 ...) | USE-ONLY | "You may not sell, loan, rent, lease, or license the SPICE Model, in whole, in part, or in modified form, to anyone outside Your company." | **Seen only as a search-result excerpt** of <https://www.analog.com/en/license/spice-models.html>; the page itself would not load here (timeout, then HTTP/2 reset), not circumvented. Model header (ad8051.lib in KiCad demos): "Refer to ... spice_general.html for License Statement. Use of this model indicates your acceptance with the terms" |
| Microchip AN1297 / MCP6xxx models | USE-ONLY | "intended and supplied to you, the Company's customer, for use solely and exclusively with products manufactured by the Company" and "All rights are reserved" | AN1297 p.12, `docs/datasheets/microchip/AN1297-Op-Amp-SPICE-Models.pdf` (read locally) |
| Murata (SimSurfing MLCC/ferrite/inductor data) | USE-ONLY | "You shall not redistribute or reproduce the DATA without prior consent of Murata." | MLCC terms via search excerpt; the ferrite-bead page's terms not read, assumed the same *(check)* |
| ROHM | USE-ONLY | excerpt reported: bars redistribution, copies for internal use only | search excerpt of <https://micro.rohm.com/en/spice-models>, not read in full *(check)* |
| Nexperia (BAV99, BAT54S family) | UNCLEAR | site terms: "any further copying, reproduction or redistribution of the software is expressly prohibited, unless a specific license agreement says otherwise"; model download itself returned HTTP 403 earlier, no model terms read | <https://nexperia.com/about/terms-and-policies/terms-of-use> excerpt |
| Diodes Inc. (BAV99 group file) | UNCLEAR | the BAV99 entry in the downloaded group file `Switching-Diodes.txt` carries no licence text. Other Diodes files (SBR) say: "supplied free of charge ... for the purpose of research and design and may be used or copied intact (including this notice) for that purpose only. All other rights are reserved." That is not a redistribution grant | <https://www.diodes.com/assets/Spice-Models/Discrete-Prodcut-Groups/Switching-Diodes.txt> (retrieved 2026-11-11), `.../Schottky-SBR-Rectifiers.txt` |
| Renesas / Intersil | UNCLEAR | model headers point to a datasheet "LICENSE STATEMENT"; page-level text: no reproduction without written approval | search excerpts only *(check)* |
| onsemi, ST, Infineon, Skyworks, Maxim | UNCLEAR | no licence text found | not resolved; do not assume |
| KiCad `Simulation_SPICE.sp` op-amp (Holger Vogt) | **REDISTRIBUTABLE** | "Author Holger Vogt, Public Domain" (file line 13); collection licence CC-BY-SA 4.0 (`LICENSE`, "if you wish to redistribute the KiCad libraries, or parts thereof ... Redistributed library collections must be shared under the same license agreement ... retain attribution") | `/usr/share/kicad/symbols/Simulation_SPICE.sp`, `/usr/share/doc/kicad-symbols/LICENSE.md` |
| ngspice built-in primitives (R, C, L, D, switch, B sources) | REDISTRIBUTABLE (simulator, BSD-3) | not a model licence question: we write netlists of primitives | ngspice distribution *(licence file not re-read here)* |

GitHub collections found by search (BSIM transistor sets CC-BY-4.0, a
germanium-BJT set MIT, GaTech Rincon-Mora examples with no licence in the
excerpt) contain no op-amp, reference, regulator, switch or converter
model that fits; none was adopted. Searching for an MIT/BSD/Apache vendor-
independent analog IC model library found nothing.

## Committed model and its check

| model | licence | ngspice 47 test | datasheet comparison |
|---|---|---|---|
| `kicad_builtin_opamp` (single pole, +/- offset, Rout, rail clamp) | public domain line + KiCad CC-BY-SA 4.0 collection licence | unity-gain buffer, 3.3 V single supply, Vin 1.65 V, `.op` Vout 1.64998 V; with `POLE=1k GAIN=100k VOFF=0 ROUT=35` f-3dB = 99.4 MHz, no peaking (max 0 dB) | datasheet GBW: OPA354 100 MHz. This is a fit by construction, not an independent check; note a one-pole model gives f-3dB = GBW at G=1, where OPA354 itself reads 170 MHz in TI's model (250 MHz in the datasheet) |
| `sw3157` (`models-open/sw3157/`: Ron(V) range-switch models `RSWV_NX` for the 74LVC1G3157 / TS5A3157 class and `RSWV_TM` for the TMUX1119, open state `RSWV_OPEN`; Ron(V) from digitised typical curves, scaled to datasheet corners by `make_lib.py`) | own work, CC BY-SA 4.0 (`LICENSE`) | used by `whatif/sw3157/sim/scope/sw.py` (DC sweep, AC, transient, op) in ngspice 47; Vc clamped to 0-3.3 V and Ron to >= 0.1 ohm for convergence; a flattened-Ron run gives zero switch INL, as it must | shape NX: Nexperia 74LVC1G3157 Fig. 10 (p. 8), 5.757-7.698 ohm, flatness 1.94 against Table 8's typical 2.0; shape TM: TMUX1119 Figure 5-1 (p. 9), mean of the 3 V and 3.63 V curves, scaled to Sec 5.6's 3.7 / 8.8 ohm and 1.9 ohm flatness. The TS5A3157 corners borrow the NX shape *(assumption)*; the 74LVC1G3157 maximum corner scales its curve to the 20 ohm RON(peak) limit *(assumption)* |

Limitations of this model, all of which the open behavioural models must
add: output clamp is a diode at the supply with N=0.01, so swing reaches
the rail (no 0.1 V rail offset, no output-current limit); no input noise,
no bias current, no input capacitance or input clamp diodes, no PSRR, no
second pole or phase margin, no slew limit.

## Per-component table

"Open model plan" says what we write. The model files go in
`models-open/<part>/` with their own header stating "written from the
datasheet numbers listed, public domain/CC0 *(owner to choose licence)*".

| component | part (BOM) | vendor model class | decision | datasheet numbers the open model is fitted to (source: `models/datasheet-facts.md`) |
|---|---|---|---|---|
| Scope-channel op-amp | OPA354 (or OPA365) | TI, USE-ONLY | no open model exists -> write open behavioural model on top of `kicad_builtin_opamp` | GBW 100 MHz (OPA354) / 50 MHz (OPA365); second pole/phase margin from the unity-gain f-3dB (250 MHz, G=1, RF=25 ohm) and the 90 MHz at G=2; slew 150 / 25 V/us; en 6.5 nV/rtHz at 1 MHz (4.5 at 100 kHz) and 1/f corner *(check, curve only)*; in 300 fA/rtHz; VOS +-2 mV typ; IB 3 pA (OPA354) / 0.2 pA (OPA365); Cin 2 pF (6 pF diff on OPA365); rail swing 0.1 V at 1 k; Rout 35 ohm; input clamps to rails; Iq 5 mA |
| AWG-output op-amp | OPA365 (+3.3/-1.8 V) | TI, USE-ONLY | no open model -> behavioural | GBW 50 MHz; en 4.5 nV/rtHz; slew 25 V/us; 25 mA drive (swing vs load from Sec 7.7 curve *(check)*); short-circuit +-65 mA; abs max 5.5 V (supply 5.1 V); Cin; Rout 30 ohm at 1 MHz; Iq 4.6 mA |
| Reference/Vmid buffer op-amp | OPA365 | TI, USE-ONLY | no open model -> behavioural (same file as above) | VOS 100 uV, drift 1 uV/C; 0.1-10 Hz noise 5 uVpp; en 4.5 nV/rtHz; IB 0.2 pA; stability to ~1 nF load (Sec 8.3.3) |
| 3.0 V reference | REF3030 (LCSC C38423, class *(check)*) | TI model encrypted, USE-ONLY | no open model -> behavioural: ideal source + output resistance, noise source, temperature/line/load terms | initial accuracy, drift ppm/C, noise 0.1-10 Hz and wideband, line and load regulation, output impedance vs frequency, Iq: read from REF30 datasheet `models/ref3030/ref30.pdf` *(numbers not extracted yet)* |
| +/- supply | LM27762 (LCSC C473398, Extended) | TI model does not parse in ngspice (`models/SOURCES.md`), USE-ONLY | no open model -> behavioural: two ideal sources with Rout, switching ripple at 2 MHz, PSRR and noise curves, start-up order and current limit | 2 MHz switching frequency, output ripple, PSRR vs frequency, noise (uV rms), Rout of each rail, current limit, start-up delay/order, input abs max |
| Analog switch (range) | TMUX1119 | TI model fails in ngspice, USE-ONLY | no open model -> behavioural switch (ngspice `.model SW`) plus Coff, Qinj | Ron 3.7 ohm typ at 3.3 V, charge injection 6 pC, Coff, leakage, ton/toff *(check: only Ron and Qinj read)* |
| Calibration switch | TS5A3159 | TI HSPICE, redistribution forbidden | no open model -> behavioural, as above | Ron, Ron flatness, Coff, Qinj, leakage from SCDS174D *(check)* |
| 16-bit DAC | DAC8551 (SPI) | none published | no open model exists -> write behavioural: ideal 16-bit code to voltage, Rout, settling, glitch energy, noise | resolution 16 bit, INL/DNL, offset/gain error, settling time, output noise density, glitch, Rout; from SLAS429E *(numbers not extracted yet)* |
| 24-bit/16-bit multi-input ADC | MCP3564 (8 SE, 24-bit); ADS8688 not chosen | none published | no open model exists -> write behavioural: sampled input with Cin, Rin, input current, noise, gain/offset error | Cin / Rin / leakage per channel, ENOB or noise, reference input load, sampling kick; from DS20006181C *(not extracted yet)* |
| Diode clamps | BAV99, BAT54S (LCSC all Extended, `jlcpcb.md`) | Diodes group file: no licence text (UNCLEAR); Nexperia: UNCLEAR | no open model confirmed -> write `.model D` from datasheet curves | IS, N, RS, CJO, VJ, M, BV, IBV, TT from datasheet VF-IF, Cd-VR, trr curves *(not extracted)*; Diodes' BAV99 entry `DI_BAV99` (IS=261p RS=0.140 BV=75 IBV=2.5u) is *not* committed and is for reference only |
| Ferrite bead | GZ1608D601TF (C1002, Basic) | maker's (Sunlord) model not sought; Murata's say no redistribution | no open model -> behavioural: R + L + C parallel fitted to the bead's impedance-vs-frequency table | impedance 600 ohm at 100 MHz (name suggests; *(check)* datasheet), DCR, rated current, Z at 1 MHz, 10 MHz, 100 MHz |
| Inductor | SDFL1608S100KTF (C1035, Basic) | not sought | behavioural L + DCR + Cpar + SRF | L 10 uH, DCR, SRF, Isat from the datasheet *(not read)* |
| Resistors | 0603 thin/thick film, 0.05-0.1 % | n/a | use as is: ngspice primitive `R` (add a `Cp` of ~0.05-0.1 pF only if SC-8 needs it *(check)*) | tolerance and TCR as Monte-Carlo parameters |
| Capacitors | X7R/C0G 0603 | Murata/TDK/Yageo models are USE-ONLY (Murata quoted above); Yageo, TDK not read | use as is: primitive `C` + ESR + ESL, DC-bias derating as a B-source if the simulation needs it *(check)* | ESR/ESL/self-resonance from the maker's datasheet curves |

The one place a vendor passive model would add something is MLCC DC-bias
loss on the decoupling at the op-amp and at Vmid. If a simulation shows
that matters, fit a bias curve to the datasheet and write it ourselves;
do not commit a Murata or TDK netlist.

## Role-by-role answer

| role | recommended | class | requirement-driving numbers |
|---|---|---|---|
| 1 scope op-amp | keep OPA354 (GBW 100 MHz, 6.5 nV/rtHz, rail-to-rail in, IB 3 pA, 2.5-5.5 V); model: open behavioural | n/a; vendor model USE-ONLY | requirement met by the real part exactly as before; the open model meets GBW by fitting, noise and bias by added sources |
| 2 AWG op-amp | keep OPA365 | USE-ONLY | GBW 50 MHz is inside the 40-60 MHz ask; en 4.5 meets 5; supply abs max 5.5 V vs 5.1 V (0.4 V margin, unchanged) |
| 3 buffer op-amp | keep OPA365 | USE-ONLY | meets low noise/offset |
| 4 reference | keep REF3030 | model encrypted | behavioural only |
| 5 +/- supply | keep LM27762 | USE-ONLY, unparsable | behavioural only |
| 6 switch / diodes | keep TMUX1119/TS5A3159, BAV99, BAT54S | USE-ONLY / UNCLEAR | behavioural / own `.model D` |
| 7 DAC/ADC | DAC8551, MCP3564 | none published | behavioural |

I searched for parts whose vendor *does* publish an open model and found
none, so no substitute with a better licence exists in this search. Where a
part was never looked up on LCSC (anything not in `jlcpcb.md`), stock is
unknown; do not infer it.

## What would change in the design

Nothing in the circuit: no resistor value, rail or part changes, because
the BOM parts are the same. What changes is the simulation inputs: the
`models/` TI/Microchip files stay local and uncommitted (`models/` is
untracked; keep it out of git, or commit only `SOURCES.md`), and simulations
that must be reproducible by anyone point to `models-open/` models once the
behavioural files exist. Until then the committed record can only show the
KiCad single-pole op-amp, which has no noise and so cannot test the
0.2 mV pin-noise limit (SC-noise) or the AWG noise limit (AW-6); those
two results stay hand-estimates or are reproduced locally with the TI
models.

## Things not done

- ADI's licence page and Murata's ferrite-bead page were not read in full;
  their classes rest on excerpts (marked).
- No JLCPCB/LCSC stock lookup was done for new parts, since no new part
  qualified.
- Behavioural models are not written yet; this page lists what to fit.
- ngspice's own licence file was not opened.
