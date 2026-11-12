# Cold review of the power, reference and calibration block (powercal)

Reviewer's scratch scripts: `/tmp/claude-1000/review_scratch/` (`abl.py`, `abl2.py`, `sens.py`, `s7.py`, `h.py`). Datasheet text read from
`~/.local/share/afe-datasheets/{ads1115,lm27762,tph2502}.pdf` and `models/ref3030/ref30.pdf` through `pdftotext`. Nothing in the block was edited.

## Summary

| # | Claim | My figure | Verdict |
|---|---|---|---|
| 1a | Sense ratio 0.489 % / 6.87 mV FAIL | model reproduces; first-order hand check 0.23 % from channel match alone, model 0.376 % match-only, 0.489 % in full | FAIL stands and is robust; magnitude agrees to within about 2x, not exactly |
| 1b | Narrative "channel match 0.39 %, 1 % resistors 0.17 %, Zcm 0.15 %, offsets 0.10 %, they add" | removing each in the model: 0.243, 0.011, 0.067, 0.027 | **Disagree**: not in `report.md`, not reproducible, and the four sum to 0.81 not 0.489 |
| 1c | Option "fit one 0.1 % pair for Rt, Rb, Rd" (section 8.1) | with every resistor at 0 % tolerance: 0.478 % (from 0.489) | **Disagree**: the model says resistor tolerance is not the cause |
| 2 | Ladder anchors make the extrapolation worse (3.1-5.7 mV against 0.26-2.28 mV) | numbers reproduce exactly | Numbers agree; **the stated reason is incomplete** (anchors lose even with perfect ADS readings) |
| 3 | PW-1 83.2 mA normal, 117.6 mA fault | 83.15 and 117.6 by hand | Agree; two inputs not marked *(check)* |
| 4 | Rails +3.2205..3.4172 V, -1.9549..-2.0525 V | 3.2205 / 3.4172 / -1.9549 / -2.0525 | Agree. Section 8.4 "contradiction with the AWG stream" is **stale** in this worktree |
| 5 | PR-3 38.5 uA, 10k bleed, rail 0.378 V | 38.49 uA, 0.3784 V | Agree; one printed figure (51 uA) is 52.1 uA |

## 1. The sense-ratio FAIL

**Where the 0.1 % comes from.** SBAS444E Electrical Characteristics: "Gain channel match, match between any two inputs", 0.05 % typ, 0.1 % max,
and "Offset channel match, any two inputs", 3 LSB. So the figure is specified, and "ADS channel match 0.1 % (max)" in the table row is the
**input** to the model (`eps`, applied as an independent U(+-eps/2) gain on each of four inputs, so any two differ by at most 0.1 %). The
gain-error row (0.15 %) and the "gain match between any two gains" row are not used, which is correct for a ratio read.
The offset rows are specified at FSR +-2.048 V in LSBs of 62.5 uV; the model uses 125 uV *(check at +-4.096 V)*.

**The narrative figure.** "Removed one at a time (`report.md`): channel match 0.39 %, 1 % resistors 0.17 %, Zcm 0.15 %, offsets 0.10 %" cannot be
found in `report.md` or in any script (`sense.py` has no ablation; its `tolset` argument is never driven). I ran the ablation on the shipped
`sense.mc` (20,000 draws, same seed, 99.9th percentile of |gain|):

| case | gain % | offset mV |
|---|---|---|
| base (as shipped) | 0.489 | 6.87 |
| no channel mismatch (the report's own row) | 0.246 | 3.76 |
| no resistor tolerance (all 1 % set to 0) | 0.478 | 6.83 |
| no ADS offsets | 0.462 | 6.04 |
| no Zcm spread (6 Mohm +-25 % fixed at nominal) | 0.422 | 6.72 |
| no INL | 0.483 | 6.85 |
| no noise | 0.493 | 6.88 |
| channel match only (others off, Zcm spread kept) | 0.449 | 5.52 |
| 1 % resistors only | 0.194 | 1.88 |
| offsets only | 0.213 | 3.13 |
| everything off except the Zcm spread | 0.146 | 1.01 |
| match only, nothing else (n = 40,000) | 0.376 | 5.10 |

So removing the match costs 0.24 % (0.38 % when it is alone), tolerances 0.01 %, Zcm spread 0.07 %, offsets 0.03 %. Not 0.39, 0.17, 0.15, 0.10.
The four narrative numbers also sum to 0.81 %, against a total of 0.489 %, so "they add" is wrong as written. The 0.39 may be the sum of the
absolute per-channel sensitivities at the +-0.05 % corner (below: (4.1 + 2.3 + 1.8) x 0.05 = 0.41) but I cannot establish that from the files.
**The sentence contradicts the "no channel mismatch" row of `report.md` (0.246 %) and should be fixed; the pointer to `report.md` is wrong.**

**Double counting.** None on the gain side: the converter's gain error cancels in the ratio and is not used, and the match is applied once per
input. On the offset side the model draws an independent +-3 LSB (125 uV) per input, so two inputs can differ by 6 LSB = 750 uV, while the datasheet
bounds the difference of any two at 3 LSB (187 uV at the +-2.048 V LSB): conservative by up to 2x (spec) times 2x (LSB size) *(check)*. It moves the
result little (offsets off: 0.489 to 0.462 %, 6.87 to 6.04 mV) and does not change the FAIL, but it should be written down. The 1 LSB INL per channel
comes from an 8 SPS, +-2.048 V row *(check)*.

**Hand recomputation, chosen divider (Rt 15k, Rb 10k, Rd 1k, Rs 4.7k).** k = 10 / 25 = 0.4, 1/k = 2.5, (1-k)/k = 1.5. Wire off, B is about
3.0 - 0.0909 (3.0 - T) = 2.94 V; wire on, B is about 1.0 V (1/3 tap). The host gets 1-k from (T_off - T_on) / (B_off - B_on), about 0.6 x 1.94 = 1.16 V
of T difference. With per-channel gain errors g0 (REF), g1 (T), g2 (B), to first order the sweep's gain error is
2.5 (g1 - g0) + 1.5 e, with e = (B_on / dB)(g2 - g0) = 0.52 (g2 - g0), that is 2.5 g1 + 0.77 g2 - 3.27 g0.
Worst corner (|g| = 0.05 % each): 0.05 % x (2.5 + 0.77 + 3.27) = 0.33 %; Monte Carlo of that expression with uniform +-0.05 %: 99.9th percentile 0.23 %.
The shipped model, differentiated numerically by forcing one channel to +0.05 % at a time (`sens.py`): ch0 (REF) -0.206 %, ch1 (T) +0.115 %,
ch2 (B) +0.092 %, i.e. coefficients -4.1, +2.3, +1.8. Signs and the ch1 coefficient agree with my expression; the ch2 and ch0 coefficients are
about 2.4x and 1.25x mine. I did not trace the difference (the B term has a slope with A across the sweep that my first-order version ignores, the likely place *(unverified)*).
I agree with the FAIL and its order of magnitude, not with the third digit.

**The FAIL does not depend on the model's details.** Even at k = 1 a 0.1 % match on a three-channel ratio exceeds the 0.05 % allocation, and at k = 0.4 it is
amplified by 2.5. The 0.05 % is the author's own allocation (`sense.py` row note), not an SC-7 figure.

**What the ablation says about the remedies in section 8.1.** "Fit one 0.1 % pair for Rt, Rb, Rd (Extended, breaks V2-3)" removes resistor
tolerance, which the model says is worth 0.011 % (0.489 to 0.478). It does not touch the channel match or Zcm, which carry the error. That option
should be struck or re-evaluated, and the "1 % resistors 0.17 %" claim in section 5 withdrawn. What the model does point at is the channel mismatch
itself, for example by presenting one reference voltage to two inputs and measuring it *(untested suggestion)*.

Smaller points in `sense.py`: its docstring still describes the jumper as the "2/3 tap, ADS input 4" while `DES["tap"] = 2` is the 1/3 tap and `CHB = 2`
is input 3 (the design is right, the comment is stale). Zcm 6 Mohm +-25 % is typ-only in SBAS444E and the spread is a guess *(check)*; the "everything off
except Zcm spread" row shows it alone gives the 0.146 % / 1 mV floor.

## 2. The SC-7 extrapolation claim

`sc7.py` reproduces to the stated digits (cubic 1.2 LSB, top 2.2275 V, +3.5 V: A 0.63 mV, B 4.01 mV; parabolic 1.64 / 3.06; knots 2.25 / 5.33; a second seed
within 0.1 mV). One part of the logic is sound: a straight-line anchor fit is the tee fit again (anchors with `quad=False` return identical numbers, because
gain and offset are absorbed by the second fit), so only the quadratic's curvature can add information.

**But "worse because the ADS1115's channel match and offset exceed the INL they would correct" is not what the model shows.** Switching the ADS errors,
pin offset and leakage off in steps (`s7.py`, top 2.2275 V, A / B at +3.5 V, mV):

| INL | full | perfect ADS, no pin offset (leakage kept) | plus no leakage |
|---|---|---|---|
| cubic 1.2 | 0.63 / 4.01 | 0.63 / 1.93 | 0.63 / 1.43 |
| parabolic 1.2 | 1.64 / 3.06 | 1.64 / 0.51 | 1.64 / 0.00 |
| knots 1.2 | 2.25 / 5.33 | 2.25 / 4.35 | 2.25 / 3.84 |

With perfect ADS readings B is **still worse than A** for cubic and knots (1.43 and 3.84 mV against 0.63 and 2.25). That is a property of the
estimator: a quadratic through four widely spaced anchors (ground, 1.0, 2.0, 3.0 V, wider than the scope pin's 0.24-2.74 V) cannot represent a cubic or
random-knot INL and adds its own residual. Only for the parabolic truth, which a quadratic fits, do perfect anchors win. So the accurate statement is:
*this quadratic-anchor estimator is worse than the tee fit for two of the three INL shapes even with exact anchors, and the ADS1115's match and offset make it worse again.*
The design text's "with perfect anchors 1.9 mV against 0.6" is the cubic row above (leakage kept) and is presented as the price of the ADS, but it belongs to the estimator.
Nothing here shows that no use of the anchors could help (a lower-order correction, or the mid taps only, was not tried). The conclusion that **the tee fit alone is
inside the 0.1 % share for the three INL models used** is supported; "the ladder taps do not help" is supported only for this estimator.

Other points. (a) The 99.9th percentile is taken over n = 800 draws, about the second-largest value; two seeds agree to 0.1 mV, so it is stable enough, but the draw count should be stated.
(b) Ground and reference anchors are modelled as exact and the ADS offset on ground is not applied; that flatters B, so it strengthens "B is worse".
(c) The scope pin map (0.4622, 1.1175) and the INL shapes are assumptions *(check, VT-23)*, as the note says. (d) `design.md` section 6 lists the extrapolated fit as 0.065 % in the SC-7 sum,
but `sc7.py` sums 0.018 % (cubic 1.2, top 2.2275). With 0.018: 0.129 + 0.489 + 0.018 + 0.133 = 0.769 (printed 0.77; RSS 0.523, matches). With the 0.065 % the text names the sum would be 0.82 %.

## 3. PW-1

Independent arithmetic from datasheet values (TPH2502 "Quiescent Current per Amplifier" 7.5 mA max; ADS1115 300 uA; REF30E 37 uA; LM27762 IQ 390 uA typ) and the AWG
values Rf 470, Rg2 510, no Rg1 (Gs0 = 1.9216, K = 0.9216), +rail 3.4172 V, output -1.9 V into 49.5 + 50 ohm:

- Worst normal state: i_load = 1.9 / 99.5 = 19.10 mA; V_inv = (-1.9 + 0.9216 x 3.4172) / 1.9216 = 0.650 V; i_g2 = (3.4172 - 0.650) / 510 = 5.43 mA; op-amp sink = 19.10 + 5.43 = 24.53 mA.
- OUT-: 15 + 24.53 = 39.5 mA (matches 39.5).
- OUT+: scope dual 15 + AWG dual 15 + 5.43 + ADS 0.3 + REF 0.037 + ladder 3.009 / (6 x 330 x 0.99) = 1.535 + sense tie (3.009 + 0.95) / 20k = 0.198 + centres 0.011 + pull-ups 2 x 3.4172 / 4.7k = 1.454 + bleed 0.342 = 39.31 mA (matches 39.3).
- 5V pin: 39.31 + 39.5 x 1.10 + 0.39 = **83.15 mA**. Agree with 83.2.
- Fault: DAC at 3.3172 V into a short: i_load = 3.3172 / 49.5 = 67.0 mA, i_g2 = 0.19 mA, OUT+ = 15 + 15 + 0.19 + 66.8 + 0.3 + 0.037 + 1.535 + 0.2 + 0.011 + 1.454 + 0.342 = 100.7 mA,
  OUT- 15 mA, pin = 100.7 + 16.5 + 0.39 = **117.6 mA**; with the Due at 300 mA, 417.6 mA. Agree.

Not marked *(check)* and should be: (a) the LM27762 0.39 mA is a **typical** with no maximum in the datasheet (`common.py` says so; the PW-1 text in `design.md` does not);
(b) the 10 % pump overhead is marked, and the margin to 100 mA (16.8 mA) is four times it; (c) the worst normal state, -1.9 V into 50 ohm, is a state section 1 of the same note says the weak
rail **cannot reach** (-1.69 V), so it is conservative by about 2 mA; (d) this budget draws the AWG's offset path from the +rail (`awg_state(..., vrail)`), while the AWG note in this
worktree now takes it from the REF3030E. The 5V-pin figure survives (the reference is fed from the +rail, and 3.0 V in place of 3.42 V gives a smaller current, so 83.2 is conservative),
but the REF3030E's load changes (see 4).

## 4. LM27762 rails

Independent recomputation of V+ = 1.2 (R1 + R2) / R2 and V- = -1.22 (R3 + R4) / R4 (SNVSAF7C equations 1 and 3, from the PDF text; VFB+ 1.182 / 1.2 / 1.218 V and VFB- -1.238 / -1.22 / -1.202 V,
over temperature) with R1 = 120k, R2 = 68k, R3 = 56k + 8.2k, R4 = 100k, each +-1 % plus 0.1 % (100 ppm/K x 10 K) in the worst direction, and the author's 2 mV allowance:

| | min | nominal | max |
|---|---|---|---|
| V+ | 3.2205 | 3.318 | 3.4172 |
| V- | -1.9549 | -2.0032 | -2.0525 |

Reproduced to 0.1 mV (without the 2 mV allowance 3.2225..3.4152 and -1.9569..-2.0505; hand check of the top: 1.218 x (1 + 120 x 1.011 / (68 x 0.989)) = 3.4152). Sum at the corners 3.4172 + 2.0525 = 5.4697 V.
Agree. Margins: REF dropout 3.2205 - (3.003 + 0.2) = 17.5 mV, with SBVS032K 6.3 "VIN >= VOUT + 0.2 V" for the E grade (checked in the PDF text); PR-2 3.45 - 3.4172 = 33 mV; V2-2 5.5 - 5.4697 = 30 mV.

Questions. (a) The 2 mV regulation allowance is thin. Line regulation is 1.9 mV/V (+) and 1.5 mV/V (-) for VIN 2.7-5 V at 50 mA and the code comment sizes it on 0.5 V of VIN span, while PW-6 uses
4.5-5.25 V (0.75 V: 1.4 and 1.1 mV); load regulation is 11 and 34 uV/mA, specified at VOUT = 1.8 V (1.1 mV on + at the 100 mA fault, 1.4 mV on - at 40 mA). That is about 2.5 mV against 2 mV. It moves a 17.5 mV margin by 3 %, so only the marking is
missing *(check)*. (b) Tolerance and tempco are added linearly at the corner, deliberately hard and conservative.

**Are the AWG stream's corners (+3.235..3.342, -2.106..-2.041) wrong?** I cannot call them wrong in arithmetic: they are not derivable from the 120k / 68k / 64.2k / 100k set and are version 1's
rails (different resistors, 0.1 % feedback). They are **stale in this worktree**: `../awg/design.py` now has `RAIL_P = (3.2205, 3.4172)` and `RAIL_N = (-2.0525, -1.9549)` with the comment "1 % Basic LM27762 feedback (../powercal/design.md section 1)",
and `../awg/design.md` takes the offset "straight from the REF3030E" (up to 5.95 mA, 7.69 mA in total on the reference, "no longer feeds the offset" from the +3.3 V rail). So `powercal/design.md` section 8.4 (the contradiction, 98 mV, 81 mV) describes a
state that no longer exists, and `power.json`'s `awg_design_sha` (`158d4133...`) no longer equals the sha of `awg/design.py` (`5827ab42...`), nor does the report-table hash, so the "read at run time" record is out of date. The AWG model also uses REF30E
+-0.2 % where the datasheet's REF30E is +-0.1 % (2.997-3.003 V), a harmless conservatism.

Consequences to re-run (not recomputed here): powercal section 3 (source 1.74 mA; the AWG note says 7.69 mA of the 10 mA rating, and 186 uV movement with the AWG level through the 15 ppm/mA sourcing load
regulation, against this block's 7.4 uV for the whole movement of the ladder top); SC-9 path (3) ("7.4 uV"); and the reference's dropout at a 7.7 mA load. Also: powercal says -1.9 V into 50 ohm is not reachable (-1.69 V, from an 11.5 ohm
saturation per rail that is the AWG stream's *(check)*), while `awg/design.py` uses `RAIL_REACH_LO = -1.9226` from ngspice for the same weak rail; one is wrong or they describe different loads.

## 5. PR-3

Inputs from the scope design (R1 = 510k + 30k = 540k, R2 || R3 = 464k) and a 0.3 V clamp drop *(assumed, check: the TPH2502 gives no figure)*: per channel (12 - 0.8) / (540k x 0.99) = 20.95 uA, less 0.8 / (464k x 1.01) = 1.71 uA = 19.24 uA;
two channels **38.49 uA**. Agree (38.5). With the scope design's 0.6 V drop: 36.1 uA (matches its "36 uA"). Sinks at V (10k at +1 %, 188k feedback divider at +1 %): 104.3 uA per volt; the source falls with V (8 uA per volt),
so the intersection is **0.3784 V**. Agree (0.378). Bleed alone, without the feedback divider: 0.397 V. Quiescent cost: 3.3 / 10k = 0.33 mA; at 3.392 V and -1 %, 0.343 mA. Agree.

Small discrepancies. The `design.md` table gives the 10k bleed's sink at 0.5 V as 51 uA; the formula gives 49.5 + 2.6 = **52.1 uA** (`power.json` says 52.14). The source's sensitivity to the drop is
8 uA/V, so a 0.2 V clamp drop adds under 1 uA and the 0.5 V limit is not sensitive to it (a Schottky-like structure at 0.1 V adds about 2 uA). PR-3's second half (1.8 uA into the Due) is carried from the scope design, not derived, as its row says.

## Things the author should mark or correct

1. Section 5 narrative: "channel match 0.39 %, 1 % resistors 0.17 %, Zcm 0.15 %, offsets 0.10 %, they add" is unsupported and inconsistent with `report.md`'s own 0.246 % row; the pointer to `report.md` is wrong.
2. Section 8.1, option "0.1 % pair for Rt, Rb, Rd": contradicted by the model (tolerance worth 0.011 %).
3. Section 6: the anchors' failure belongs to the estimator as much as to the ADS1115; the extrapolated-fit figure in the sum (0.065 % in the text, 0.018 % in the sum) is inconsistent.
4. Section 8.4, section 3 and the SC-9 path (3): written against the AWG stream's previous design; the worktree's AWG now has the same rails and takes its offset from the reference.
5. *(check)* marks missing: LM27762 IQ has no maximum; regulation allowance 2 mV against about 2.5 mV; ADS offset and INL specified at +-2.048 V, model at +-4.096 V; Zcm spread; 51 against 52.1 uA.
