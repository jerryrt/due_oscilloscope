"""Writes report.md from the numbers run.py just computed (nothing in the tables is typed in by hand)."""
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_OPA354_SHA = "48aeb72c445e6387b1a68110ad508658bc263882f394c78753d56201351ccd07"   # models/SOURCES.md, OPA354_PSPICE.lib

def at(f, y, f0):
    return float(np.interp(np.log10(f0), np.log10(f), y))

def verdict(ok):
    return "PASS" if ok else "FAIL"

def write_trim(A, S, tsw, nmc, c1r):
    """DF-3 as amended (30 dB / 18 dB before calibration, 46 dB after the PA-3 stage-gain calibration), for the stocked
    0.1 % / 25 ppm/K resistors with and without a one-time trimmer, and the other variants.  Everything is read from S."""
    A("## DF-3 with the resistors that are in stock, with and without a trimmer\n")
    A("The question: 0.1 % 10 ppm/K 0603 parts for the divider are not found at JLCPCB/LCSC (`docs/jlcpcb-parts.md`); the stocked part is 0.1 % at 25 ppm/K. DF-3 (amended): **before** host calibration at least **30 dB at DC and 18 dB at 10 kHz** on every unit, **after** the PA-3 gain calibration at least **46 dB at DC**. Each scenario below is the same two-channel netlist, 200 Monte Carlo draws and five signed worst corners at +/-10 K, both ranges.\n")
    A("**Assumptions that are not datasheet facts, all *(check)*:** a trimmer of 10 kohm, SMD cermet, set to 5 kohm mid-setting, wiper 0..10 kohm, **100 ppm/K** *(datasheet of the actual part not read)*, in series with a **fixed 330 kohm** R2; the PA-3 calibration measures each channel's stage gain by injecting at node N, so it removes the stage (RF/RG or Ron) and **cannot see the divider ratio**; Ron drifts 1 % over 10 K *(TMUX1119 Ron-versus-temperature not read)*, applied in every scenario; the one-time trim leaves a **residual of 0.05 % of divider ratio** (uniform +/-0.05 % in a Monte Carlo draw, signed worst case +0.05 % in a corner), which is 316 ohm of the 10 kohm travel (3 % of it) *(check: setting resolution of the part, and the null measurement's own noise - one ADC code at +/-6 V common mode is about 0.06 % of ratio, so the null needs averaging)*.\n")
    scen = [("spec", "0.1 %, 25 ppm/K, no trimmer"), ("d05", "0.05 %, 25 ppm/K, no trimmer"), ("trim_cal", "0.1 %, 25 ppm/K, trimmer set after the calibration"),
            ("trim_raw", "0.1 %, 25 ppm/K, trimmer set on the raw reading"), ("fixed", "reference: 0.05 %, 10 ppm/K, Ron matched, C1 trimmed (not a stocked part)")]
    A("| scenario | range | before cal: DC corner / MC min (>= 30) | before cal: 10 kHz corner / MC min (>= 18) | after cal: DC corner (>= 46) | after cal: MC min / p1 / median | verdict before / after |")
    A("|---|---|---|---|---|---|---|")
    for key, lab in scen:
        s = S[key]
        for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
            d = s[rg]
            before = d["dc_corner_min"] >= 30 and d["dc_mc_min"] >= 30 and d["f10k_wc"] >= 18 and d["f10k_mc_min"] >= 18
            after = d["cal_corner_min"] >= 46 and d["cal_mc_min"] >= 46
            A(f"| {lab} | {nm} | {d['dc_corner_min']:.1f} / {d['dc_mc_min']:.1f} | {d['f10k_wc']:.1f} / {d['f10k_mc_min']:.1f} | {d['cal_corner_min']:.1f} | {d['cal_mc_min']:.1f} / {d['cal_mc_p1']:.1f} / {d['cal_mc_med']:.1f} | {verdict(before)} / {verdict(after)} |")
    A("")
    A("The 'before cal' columns are the uncalibrated circuit (what the sim measured in every earlier report). 'After cal' divides each channel by its stage gain measured at 25 C with the draw's own parts, then reads the common-mode response of the difference at the use temperature: stage tolerance and Ron spread drop out at 25 C and only their drift stays, while the divider's tolerance stays whole. For the untrimmed scenarios the corner column takes the worse of the two op-amp CMRR signs; for the trimmed ones the trim nulls the unit's whole common-mode response at 25 C including its op-amp term, so the drawn sign is used (the other sign is another unit).\n")
    for key in ("trim_cal", "trim_raw"):
        if key not in S or "trim_info" not in S[key]:
            continue
        t = S[key]["trim_info"]
        A(f"**{key}:** untrimmed mismatch at 25 C |m0| max {t['m0_abs_max']*100:.3f} % (99th percentile {t['m0_abs_p99']*100:.3f} %); trimmer settings used {t['rt_min']:.0f}-{t['rt_max']:.0f} ohm; largest A-B difference {t['dR_abs_max']:.0f} ohm; **saturated (needed more than the travel of both trimmers) in {t['sat']} of {t['n']} draws**; sensitivity {t['k_per_ohm']*1e6:.3f} ppm of ratio per ohm, so the assumed 0.05 % residual is {5e-4/t['k_per_ohm']:.0f} ohm; corners: " +
          ", ".join(f"{k} A {v['rtA']:.0f} / B {v['rtB']:.0f} ohm{' SATURATED' if v['sat'] else ''}" for k, v in t["corners"].items()) + ".")
    A("")
    if "trim_cal" in S:
        tc = S["trim_cal"]; sp = S["spec"]
        A(f"**Does the trim set on the +/-5 V range hold on the +/-1.25 V range?** The trim is solved on the +/-5 V range only. At 25 C (calibration state, no drift) the calibrated CMRR on the +/-1.25 V range is {tc['1.25']['cal_ref_mc_min']:.1f} dB at the Monte Carlo minimum against {tc['5']['cal_ref_mc_min']:.1f} dB on the +/-5 V range (median {tc['1.25']['cal_ref_mc_med']:.1f} / {tc['5']['cal_ref_mc_med']:.1f}); the signed corners read {tc['1.25']['cal_ref_corner_min']:.1f} / {tc['5']['cal_ref_corner_min']:.1f} dB. Untrimmed, the same 25 C figure is {sp['1.25']['cal_ref_mc_min']:.1f} / {sp['5']['cal_ref_mc_min']:.1f} dB. The divider sits ahead of the range switch, so its ratio is common to both ranges; what differs between ranges is the stage, which the calibration removes on each range.\n")
    sp, d5, tc, tr = S["spec"], S["d05"], S["trim_cal"], S["trim_raw"]
    mn = lambda s, k: min(s["5"][k], s["1.25"][k])
    A("**Reading the table.** "
      f"(1) *Before calibration* every stocked-part variant meets 30 dB at DC (worst corner {mn(sp, 'dc_corner_min'):.1f} dB, set by the Ron spread on the +/-5 V range) and 18 dB at 10 kHz (worst corner {mn(sp, 'f10k_wc'):.1f} dB, set by the +/-5 % capacitors, a margin of {mn(sp, 'f10k_wc') - 18:.1f} dB; the trimmer does not touch it, {mn(tc, 'f10k_wc'):.1f} dB). "
      f"(2) *After calibration, no trimmer*: 0.1 % at 25 ppm/K misses 46 dB **at the signed worst corner only**, by {46 - sp['5']['cal_corner_min']:.1f} dB (+/-5 V) and {46 - sp['1.25']['cal_corner_min']:.1f} dB (+/-1.25 V); no Monte Carlo draw of {nmc} falls below {mn(sp, 'cal_mc_min'):.1f} dB (1st percentile {mn(sp, 'cal_mc_p1'):.1f} dB), so the miss is a statement about every part at its tolerance limit in the worst direction at once, not about a typical unit. 0.05 % at 25 ppm/K meets it ({d5['5']['cal_corner_min']:.1f} / {d5['1.25']['cal_corner_min']:.1f} dB). "
      f"(3) *With the trimmer set after the calibration*: {tc['5']['cal_corner_min']:.1f} / {tc['1.25']['cal_corner_min']:.1f} dB at the worst corner, {mn(tc, 'cal_mc_min'):.1f} dB at the Monte Carlo minimum: the tolerance term is trimmed out and what is left is the setting residual, the divider's 25 ppm/K drift over 10 K and the op-amp's own drift. "
      f"(4) *The trim must be set on the calibrated reading.* Set on the raw reading it spends the trimmers compensating the Ron spread of the +/-5 V range (a mismatch of up to {tr['trim_info']['m0_abs_max']*100:.1f} %), saturates in {tr['trim_info']['sat']} of {tr['trim_info']['n']} draws and in every corner, and the calibration then hands that stage mismatch back: {tr['5']['cal_corner_min']:.1f} dB after calibration, and it spoils the +/-1.25 V range before calibration (Monte Carlo minimum {tr['1.25']['dc_mc_min']:.1f} dB).\n")
    if tsw:
        A("**Trim residual sweep** (trim_cal, worst corner and its cold twin, after cal, DC): how good the setting has to be.\n")
        A("| assumed residual (ratio) | in ohms of trimmer | +/-5 V | +/-1.25 V | meets 46 dB |\n|---|---|---|---|---|")
        k = S["trim_cal"]["trim_info"]["k_per_ohm"] if "trim_cal" in S and "trim_info" in S["trim_cal"] else 1.585e-6
        for (res, mode), v in sorted(tsw.items()):
            A(f"| {res*100:.2f} % | {res/k:.0f} | {v['5']['cal']:.1f} dB | {v['1.25']['cal']:.1f} dB | {verdict(min(v['5']['cal'], v['1.25']['cal']) >= 46)} |")
        A("")

    if c1r:
        A("**What the E24 C1 residual does to the 10 kHz CMRR (before calibration, the 18 dB row).** The BOM has C1 = 12 pF and C2 = 39 pF; against the ideal for the real capacitance at N the residual is a few percent (the 2b compensation table). The same residual in both channels is a common-mode-neutral change of the divider's DC-to-HF step, so it should cancel; only a channel-to-channel difference reaches the CMRR. Worst of the signed corners, 10 kHz, C1 offset from the ideal by the stated amount in both channels:\n")
        A("| C1 offset, both channels | capacitors matched (no tolerance) +/-5 V / +/-1.25 V | capacitors +/-5 %, stray +/-0.5 pF +/-5 V / +/-1.25 V |\n|---|---|---|")
        for cs in sorted({k[1] for k in c1r}):
            m, t = c1r[("caps_matched", cs)], c1r[("caps_5pct", cs)]
            A(f"| {cs*100:+.1f} % | {m['5']:.1f} / {m['1.25']:.1f} dB | {t['5']:.1f} / {t['1.25']:.1f} dB |")
        A("")

def write(S, dcs, hfs, cmw, nz, gd, gextra, ver, lib_sha, sw_sha, nmc, tsw=None, c1r=None):
    sp, fx = S["spec"], S["fixed"]
    L = []
    A = L.append
    AREF_LO, AREF_HI = 3.20, 3.30
    # ---------------- derived numbers used in the tables
    def step(s, rg, k):
        return k * AREF_HI / 4096 / s[rg]["adm_min"] * 1e3
    def pindiff(s, rg, vd):
        return s[rg]["adm_max"] * vd
    # common-mode window limits (worst over the four AREF / centring / rail corners)
    def lim(rg):
        top = [v[side]["v_pin_margin80_top"] for k, v in cmw.items() if k.startswith(rg + "|") for side in v if v[side]["v_pin_margin80_top"]]
        if rg == "5":
            bot = [v[side]["v_compress_2mV_bot"] for k, v in cmw.items() if k.startswith(rg + "|") for side in v]
        else:
            bot = [-v[side]["v_pin_margin80_bot"] for k, v in cmw.items() if k.startswith(rg + "|") for side in v if v[side]["v_pin_margin80_bot"]]
        inl = [v[side]["v_compress_2mV_top"] for k, v in cmw.items() if k.startswith(rg + "|") for side in v]
        pk = max(v[side]["diff_peak"] for k, v in cmw.items() if k.startswith(rg + "|") for side in v)
        return min(top), min(bot), min(inl), pk
    lim5, lim125 = lim("5"), lim("1.25")
    cm5 = min(lim5[0], lim5[1]); cm125 = min(lim125[0], lim125[1])
    # analytic cross-check of the DC mismatch
    tR = lambda s: s["tolR"] + s["tcr"] * 1e-6 * 10
    def analytic(tolR, tcr, dron, rg):
        t = tolR + tcr * 1e-6 * 10
        div = 2 * (0.7652 + 0.5303 + 0.2348) * t
        stage = 2 * 1.5856 * t if rg == "1.25" else (2 * 0.0 + ((dron if dron is not None else 5.1) / 249.0) / 1.02)
        op = 2 / 10 ** (68 / 20)
        rs = 100 / 1.0043e6
        tot = div + stage + op + rs
        return -20 * np.log10(tot), div, stage, op, rs
    # ---------------- header
    A("# 2d differential mode: simulation report\n")
    A("Plan step 2d (`docs/afe-plan.md`). Everything below is regenerated by `python3 -I run.py` (about 20-30 minutes on 12 cores; `D2_NMC` sets the draw count, default 200). Raw numbers are in `results/*.json`, representative netlists in `netlists/`, CMRR-versus-frequency plot data in `results/cmrr_vs_frequency_{spec,fixed}.json`.\n")
    A("## Report header\n")
    A(f"- Simulator: `{ver}`; numpy post-processing; KiCad not used.")
    A(f"- Vendor model, referenced by path from `../../models/opa354/` and not copied (TI, not redistributable): `OPA354_PSPICE.lib` sha256 `{lib_sha}` "
      f"({'matches' if lib_sha == SOURCES_OPA354_SHA else 'DOES NOT MATCH'} `models/SOURCES.md`). Range-switch model `../scope/models/rangesw.lib` (ours, CC-BY-SA, TMUX1119 Ron/capacitances only) sha256 `{sw_sha}`. The channel netlist builder is 2b's `../scope/netlib.py`, imported, not copied; this step writes only under `sim/diff/`.")
    A("- Circuit: two copies of the settled 2b scope channel (R1 768k, R2 = 330k fixed (+ a 5k trimmer at mid-setting in the `trim_*` scenarios, so the 335k leg of 2b), R3 768k to the 3.3 V sense node, C1 compensated to the ideal for that leg (12.15 pF at 335k, 12.02 pF at 330k), C2 38 pF + the model's own input capacitance, Rnp 681, OPA354, RF 953 / RG 249, range switch shunting RF, Riso 20, 2 pF pin). **Shared between the channels:** Vmid (AREF/2 +/- 30 mV behind 0.05 ohm, 10 uF + 100 nF), the 3.3 V sense node, the op-amp supply rail (3.23-3.37 V behind 0.1 ohm + 10 nH). **Independent per channel:** the five resistors, C1, C2, the stray capacitance at node N, the switch Ron, the op-amp offset, the source resistance, and a temperature coefficient for each resistor and the offset.")
    A(f"- Stimuli: DC nested sweep of both inputs over 9 x 9 points (+/-6 V on the +/-5 V range, +/-1.25 V on the +/-1.25 V range); AC 10 Hz to 20 MHz, 12 points per decade, with 1 V on both inputs (common mode) and with +0.5 V / -0.5 V (difference of 1 V); sources 0-100 ohm per input (DF-3's own condition); common-mode DC sweep with both inputs tied, -9 to +9 V (-2 to +2 V on the 1.25 range); `.noise` on v(apin,bpin) and v(apin). CMRR = |difference gain| / |common-mode gain| of V(A1 pin) - V(A0 pin). DC CMRR is taken from the large-signal DC grid (so it includes the op-amp's crossover), and the 10 Hz AC point agrees with it.")
    A(f"- Monte Carlo: **{nmc} draws per scenario**, uniform tolerances, shared AREF 3.20-3.30 V, Vmid centring +/-30 mV, rail 3.23-3.37 V, temperature +/-10 K (EN-1 15-35 C about a 25 C reference), seed 20261111. Plus **explicit signed corner draws** (channel A gain-high in every parameter, B gain-low, capacitors in and against the resistors' direction, source resistance 100/0 and 0/100 ohm, hot and cold, and a bottom-pin corner). Every Monte Carlo draw must lie inside the corner result: counted below.")
    A("- Parameters that are assumptions and not datasheet values are marked *(check)* and listed under 'Model gaps'. Op-amp offset: +/-8 mV maximum, drift +/-4 uV/K (`models/datasheet-facts.md`, OPA354 p7; typ or max *(check)*). Op-amp CMRR: not modelled by the vendor macro as a per-unit spread, so each channel gets an independent gain error of up to +/-1/10^(68/20) = +/-0.040 % (datasheet CMRR 68 dB above V+ - 2 V, `datasheet-facts.md`, *(check: typ or min)*), added analytically to the common-mode gain.")
    A("")
    A("### SAM3X differential mode (quoted, `docs/datasheets/microchip/SAM3X-SAM3A-11057C.pdf`)\n")
    A("- Pair table, Table 43-5 (Section 43.6.8, printed p. 1327): `AD6-AD7 -> CH6`. With the Arduino labels `A1 = AD6`, `A0 = AD7` (CLAUDE.md), CH1 = A1 and CH2 = A0 are exactly one differential pair, and the converter forms (AD6 - AD7) = (A1 - A0) = (CH1 - CH2) if the first-listed pin is VIN+. The datasheet draws VIN+ and VIN- in Figure 43-6 (p. 1328) but the pair table does not say which pin is which *(check; closed by VT-11, the sign test)*. DF-1's 'CH1 = IN+' needs exactly that mapping.")
    A("- Gain, Table 43-6 (p. 1327) and ADC_CGR (p. 1349): with DIFF = 1, GAIN code 00 -> 0.5, 01 -> 1, 10 -> 2, 11 -> 2. DF-2's two ranges are code 01 (PGA 1, +/-5 V difference) and code 00 (PGA 0.5, +/-10 V difference). Offset (Table 43-7) is not available in differential mode.")
    A("- Scale, Section 45.7.1 (p. 1403-1404): differential LSB = AREF/4096 at gain 1 and 2 x AREF/4096 at gain 0.5 (the datasheet's example: 6.0 V/4096 = 1465 uV at ADVREF 3.0 V). Full scale is therefore +/-AREF/2 (PGA 1) and +/-AREF (PGA 0.5) of **pin difference**.")
    A("- Pin range, Table 45-38 (Section 45.7.2, printed p. ~1407 *(check page)*): VIR 0 to VADVREF; leakage 0.5 uA; Ci 8 pF; 'up to VDDIN without destruction'. **The datasheet text read here states no separate common-mode window for differential mode** - only Figure 43-6, which can be read as each pin staying inside 0..AREF. DF-2's '*(check)*' stands: this report holds every pin inside 0..AREF with at least 80 mV of margin (the SC-2 criterion) and leaves the converter's own common-mode behaviour to VT-2.")
    A("- Static errors in differential mode, Tables 45-32/45-33 (p. 1404-1405): INL +/-1 LSB typ, +/-1.4 LSB max (VDDIN 3.0-3.6 V); offset error -22 / +11.5 / +48 LSB; gain error -1.56 / -0.56 / +0.29 %. These are the Due's, not the AFE's, and bear on DF-4 (below).\n")

    # ---------------- the 2026-11 question: stocked resistors, with and without a trimmer
    write_trim(A, S, tsw, nmc, c1r)

    # ---------------- result summary
    A("## What this step found, before the tables\n")
    A("*This section and the three after it were written against the previous DF-3 wording (46 dB at DC and 40 dB at 10 kHz before any calibration, closed by 0.05 % / 10 ppm/K parts); the amended limits (30 dB / 18 dB before calibration, 46 dB after the PA-3 calibration) and the stocked-part variants are judged in the section above. The `spec` and `fixed` figures below are unchanged in method.*\n")
    A("1. **DF-3 is not met by the design as specified (0.1 % parts), at its worst corners, and the cause is not the resistors.** Worst signed corner, DC: "
      f"**{sp['5']['dc_corner_min']:.1f} dB on the +/-5 V range** (limit 46) and **{sp['1.25']['dc_corner_min']:.1f} dB on the +/-1.25 V range**; at 10 kHz **{sp['5']['f10k_wc']:.1f} dB / {sp['1.25']['f10k_wc']:.1f} dB** (limit 40). "
      f"Even the Monte Carlo (no corner stacking) has a minimum of {sp['5']['dc_mc_min']:.1f} dB at DC on the +/-5 V range and {sp['5']['f10k_mc_min']:.1f} dB at 10 kHz, and a **median of {sp['5']['dc_mc_med']:.1f} dB against the 'typical 50 dB'** on that range.")
    A("   - +/-5 V range, DC: the range switch's **Ron sits in the gain** (G = 1 + Ron/RG, RG = 249 ohm). Ron is 3.7 ohm typ / 8.8 ohm max with no minimum or unit-to-unit spread given, so two channels can differ by up to 5.1 ohm = 2.0 % of gain = 34 dB of CMRR. This is the 2b 'Ron spread' cost showing up as the largest term. 0.1 % resistors alone would give 41 dB; the 0.1 % does not close the budget even without Ron.")
    A("   - +/-1.25 V range, DC: every resistor at its 0.1 % limit plus the 25 ppm/K tempco over 10 K gives 0.87 % gain mismatch (divider 0.38 %, RF/RG 0.40 %, op-amp CMRR 0.08 %, source resistance 0.01 %): 41.2 dB. The budget script's 50 dB (`budget/afe_budget.py`, which counted R1/R2 only on the superseded 237k divider) was optimistic by the R3, RF, RG, tempco and op-amp terms.")
    A("   - 10 kHz: the compensated divider's C1/C2 tolerance. A 5 % error in C1 or C2 mis-compensates one channel's divider by up to about 9 % of its HF gain, and at 10 kHz (the divider corner is 17 kHz) half of that is visible: **20 dB at the worst corner**, far from 40 dB. No 0.1 % resistor choice touches it; no fixed C0G part is tight enough (needs about 0.5 % capacitors *and* 0.1 pF stray matching, below), so **C1 has to be trimmed per channel on the bench**.")
    A("2. **What closes it (rerun as scenario `fixed`, all numbers below):** (a) resistors 0.05 % with a temperature coefficient of at most 10 ppm/K (thin film or a matched network, ratio tracking) *(check availability and cost against the low-cost rule)*; (b) the range switches of the two channels matched in Ron to within 0.5 ohm of each other (one dual package or selected pairs; the TMUX1119 datasheet gives no matching figure *(check)*); (c) C1 trimmed on the bench, per channel, to within 0.5 % of the value that flattens that channel's own response (about 0.06 pF of 12 pF, VT-2's 10 kHz CMRR is the trim criterion). "
      f"Result: DC worst corner **{fx['5']['dc_corner_min']:.1f} dB (+/-5 V) and {fx['1.25']['dc_corner_min']:.1f} dB (+/-1.25 V)**, 10 kHz worst corner **{fx['5']['f10k_wc']:.1f} / {fx['1.25']['f10k_wc']:.1f} dB**, Monte Carlo minima {fx['5']['dc_mc_min']:.1f} / {fx['1.25']['dc_mc_min']:.1f} dB at DC and {fx['5']['f10k_mc_min']:.1f} / {fx['1.25']['f10k_mc_min']:.1f} dB at 10 kHz. The DC margin at the corner is thin ({min(fx['5']['dc_corner_min'], fx['1.25']['dc_corner_min'])-46:.2f} dB); the sweep tables below say which of the three levers buys what.")
    A("3. **DF-2 holds** on both ranges; the one number worth the owner's attention is the common-mode limit: each input individually must stay within about "
      f"**+/-{cm5:.2f} V on the +/-5 V range** and **+/-{cm125:.2f} V on the +/-1.25 V range**, so a +/-10 V difference leaves a common mode of only about +/-{max(cm5-5,0):.1f} V, and +/-2.5 V on the 1.25 V range leaves about +/-{max(cm125-1.25,0):.2f} V.")
    A("4. **DF-4 is limited by something the per-channel gain/offset fit cannot remove**: the channel's own non-linearity, which in the vendor op-amp model is the input-stage crossover, and (outside the AFE) the converter's INL of up to 1.4 LSB. See DF-4.")
    A("")

    # ---------------- pass/fail
    def vrow(req, lim_, res, ok, margin):
        A(f"| {req} | {lim_} | {res} | {'PASS' if ok else 'FAIL'} | {margin} |")
    A("## Pass / fail\n")
    A("'Worst-case result' is the worst of the signed corners and all Monte Carlo draws. Scenario **spec** = the design as specified (0.1 % resistors at 25 ppm/K, 5 % capacitors, switch Ron 3.7-8.8 ohm independent per channel, no trim); scenario **fixed** = the three changes above. Rows are given for both so the cost of the change is visible.\n")
    A("| requirement | limit | worst-case result | verdict | margin |")
    A("|---|---|---|---|---|")
    vrow("DF-1 mapping and sign (analytic + guard G4)", "CH1 = A1 = VIN+, CH2 = A0 = VIN-; reading = CH1 - CH2; analog path unchanged", "no extra component between the two channel outputs and the pins; G4 shows the opposite pairing reading -1749 codes for +3 V / -3 V", True, "VT-11 closes the sign *(check, which pin is VIN+)*")
    for tag, s in (("spec", sp), ("fixed", fx)):
        m5, m125 = s["5"]["margin_min"], s["1.25"]["margin_min"]
        vrow(f"DF-2 each pin inside 0..AREF, +/-5 V range, inputs to +/-6 V ({tag})", ">= 80 mV per side at AREF 3.20", f"{m5*1e3:.1f} mV worst of {s['5']['n']} draws + corners", m5 >= 0.08, f"{(m5-0.08)*1e3:.1f} mV")
        vrow(f"DF-2 each pin inside 0..AREF, +/-1.25 V range, inputs to +/-1.25 V ({tag})", ">= 80 mV per side at AREF 3.20", f"{m125*1e3:.1f} mV", m125 >= 0.08, f"{(m125-0.08)*1e3:.1f} mV")
    for tag, s in (("spec", sp), ("fixed", fx)):
        st1, st05 = step(s, "5", 1), step(s, "5", 2)
        vrow(f"DF-2 step, +/-5 V difference, PGA 1 (code 01) ({tag})", "<= 4 mV per code at the input", f"{st1:.3f} mV (AREF 3.30, smallest difference gain {s['5']['adm_min']:.4f})", st1 <= 4, f"{4-st1:.3f} mV")
        vrow(f"DF-2 step, +/-10 V difference, PGA 0.5 (code 00) ({tag})", "<= 7.5 mV per code", f"{st05:.3f} mV", st05 <= 7.5, f"{7.5-st05:.3f} mV")
    for tag, s in (("fixed", fx),):
        p5 = pindiff(s, "5", 5.0); p10 = pindiff(s, "5", 10.0); p12 = pindiff(s, "5", 12.0)
        vrow(f"DF-2 +/-5 V difference inside the converter's PGA 1 range ({tag})", f"pin difference <= AREF/2 = {AREF_LO/2:.2f} V", f"{p5:.3f} V (largest difference gain {s['5']['adm_max']:.4f})", p5 <= AREF_LO / 2, f"{AREF_LO/2-p5:.3f} V; usable to +/-{AREF_LO/2/s['5']['adm_max']:.2f} V")
        vrow(f"DF-2 +/-10 V difference inside PGA 0.5 range ({tag})", f"pin difference <= AREF = {AREF_LO:.2f} V", f"{p10:.3f} V (at +6 V / -6 V inputs, 12 V: {p12:.3f} V)", p12 <= AREF_LO, f"{AREF_LO-p10:.3f} V (at 10 V)")
    vrow("DF-2 +/-1.25 V range, difference ranges stated", "'about +/-1.25 V and +/-2.5 V'", f"PGA 1: +/-{AREF_LO/2/fx['1.25']['adm_max']:.3f} V (converter limit, AREF 3.20); PGA 0.5: +/-2.5 V reached with pins at 110 mV margin, converter limit +/-{AREF_LO/fx['1.25']['adm_max']:.2f} V", True, "ADC offset error (up to +48 LSB, Table 45-33) is removed by host calibration and costs up to 39 mV of PGA 1 range")
    vrow("DF-2 states any common-mode limit", "state it", f"+/-5 V range: each input within +/-{cm5:.2f} V (top: pin 80 mV margin at {lim5[0]:.2f} V; bottom: op-amp clips at {lim5[1]:.2f} V); +/-1.25 V range: +/-{cm125:.2f} V (top {lim125[0]:.2f}, bottom {lim125[1]:.2f}). Common mode both at +V: the same numbers. Gain departs by > 2 mV from linear (crossover) beyond about {lim5[2]:.1f} V on the +/-5 V range", True, "stated, see 'Common-mode window'")
    for tag, s in (("spec", sp), ("fixed", fx)):
        for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
            v = s[rg]["dc_corner_min"]; mm = s[rg]["dc_mc_min"]
            vrow(f"DF-3 CMRR at DC, every unit, {nm} ({tag})", ">= 46 dB", f"worst corner {v:.1f} dB; MC min {mm:.1f} dB", min(v, mm) >= 46, f"{min(v, mm)-46:+.1f} dB")
    for tag, s in (("spec", sp), ("fixed", fx)):
        for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
            v = s[rg]["f10k_wc"]; mm = s[rg]["f10k_mc_min"]
            vrow(f"DF-3 CMRR at 10 kHz, {nm} ({tag})", ">= 40 dB", f"worst corner {v:.1f} dB; MC min {mm:.1f} dB", min(v, mm) >= 40, f"{min(v, mm)-40:+.1f} dB")
    for tag, s in (("spec", sp), ("fixed", fx)):
        for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
            md = s[rg]["dc_mc_med"]
            vrow(f"DF-3 typical CMRR at DC, {nm} ({tag})", "typical 50 dB", f"Monte Carlo median {md:.1f} dB", md >= 50, f"{md-50:+.1f} dB")
    for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
        d = fx[rg]["df4"]
        for pga, lab in (("pga1.0", "PGA 1"), ("pga0.5", "PGA 0.5")):
            r = d[pga]["err_over_allowed_max"]
            vrow(f"DF-4 residual after the per-channel gain/offset fit, {nm}, {lab} (fixed)", "<= 0.5 % of reading + 1 code, error / allowed", f"{r:.2f} of the allowance (worst {d['err_max_mV']:.2f} mV at the input, of which {d['err_ref_max_mV']:.2f} mV is the channel's own non-linearity at the calibration temperature)", r <= 1, f"{(1-r)*100:+.0f} %")
    for lab, key in (("+/-5 V", "5"), ("+/-1.25 V", "1.25")):
        n = nz[f"{key}|1.5xBW"]
        vrow(f"Noise of the difference, {lab}, to 1.5 x the -3 dB bandwidth", "no DF limit; SC-6 0.2 mV per channel", f"{n['diff_total']*1e6:.0f} uV rms at the pin difference (= {np.sqrt(2):.3f} x one pin's {n['single_pin']*1e6:.0f} uV; Vmid and the sense node contribute {n['vmid_diff']*1e6:.1f} / {n['v3_diff']*1e6:.3f} uV)", True, "informational")
    A("")
    A("Both scenarios' DF-2 rows are nearly identical because DF-2 depends on gain and centring, not on the matching parts.\n")

    # ---------------- DF-3 detail
    A("## DF-3: CMRR\n")
    fsel = [100, 1e3, 1e4, 1e5, 1e6, 1e7]
    for tag, s in (("spec (as specified)", sp), ("fixed", fx)):
        for rg, nm in (("5", "+/-5 V range"), ("1.25", "+/-1.25 V range")):
            f = np.array(s[rg]["f"])
            A(f"**{tag}, {nm}** - CMRR in dB (worst signed corner / Monte Carlo 1st percentile / Monte Carlo median / Monte Carlo minimum):\n")
            A("| f | " + " | ".join(f"{x:g} Hz" if x < 1e3 else (f"{x/1e3:g} kHz" if x < 1e6 else f"{x/1e6:g} MHz") for x in fsel) + " |")
            A("|---|" + "---|" * len(fsel))
            for lab, k in (("worst corner", "wc_cmrr"), ("MC 1 %", "mc_cmrr_p1"), ("MC median", "mc_cmrr_med"), ("MC minimum", "mc_cmrr_min")):
                A(f"| {lab} | " + " | ".join(f"{at(f, np.array(s[rg][k]), x):.1f}" for x in fsel) + " |")
            A(f"\nMonte Carlo draws below the worst signed corner: {s[rg]['mc_exceeds_corner_dc']} at DC, {s[rg]['mc_exceeds_corner_10k']} at 10 kHz (the corner bounds the draws, as it must).\n")
    A("The full curves (100 Hz-10 MHz and below, every corner and the Monte Carlo statistics) are in `results/cmrr_vs_frequency_*.json`. Above about 1 MHz the sim sees only the passive mismatch and the identical op-amp models; **unit-to-unit gain-bandwidth spread of the OPA354 is not simulated** (model gap), so the high-frequency end is a lower bound on the mismatch, not an upper one.\n")
    A("### Analytic cross-check of the DC worst case (independent of the simulator)\n")
    A("Worst-case relative gain mismatch = sum of the two channels' sensitivities x (tolerance + tempco over 10 K): divider 2 x (0.765 + 0.530 + 0.235) x t, +/-1.25 V stage 2 x 1.586 x t, +/-5 V stage dRon/RG/1.02, op-amp CMRR 2 x 0.040 %, source resistance 100 ohm/1.004 Mohm.\n")
    A("| case | divider | stage | op-amp CMRR | source R | analytic CMRR | simulated corner |")
    A("|---|---|---|---|---|---|---|")
    for tag, s, sc in (("spec", sp, (0.001, 25.0, None)), ("fixed", fx, (0.0005, 10.0, 0.5))):
        for rg in ("5", "1.25"):
            cm, dv, stg, op, rs = analytic(sc[0], sc[1], sc[2], rg)
            A(f"| {tag}, {rg} V | {dv*100:.3f} % | {stg*100:.3f} % | {op*100:.3f} % | {rs*100:.3f} % | {cm:.1f} dB | {s[rg]['dc_corner_min']:.1f} dB |")
    A("")
    A("### What closes the DC budget (worst signed corner, DC CMRR in dB; rows = resistor tolerance / tempco, columns = Ron matching)\n")
    for rg, nm in (("5", "+/-5 V range"), ("1.25", "+/-1.25 V range (no Ron term)")):
        A(f"**{nm}**\n")
        A("| resistors | independent Ron (5.1 ohm) | within 1.5 ohm | 0.5 ohm | 0.25 ohm |")
        A("|---|---|---|---|---|")
        for t in (0.001, 0.0005, 0.00025):
            for tc in (25, 10, 5):
                cells = []
                for d in ("None", "1.5", "0.5", "0.25"):
                    v = dcs[(t, tc, None if d == "None" else float(d))][rg]
                    cells.append(f"{v:.1f}" + (" ok" if v >= 46 else ""))
                A(f"| {t*100:g} %, {tc} ppm/K | " + " | ".join(cells) + " |")
        A("")
    A("('ok' = at least 46 dB.) Reading: on the +/-5 V range nothing closes DC until Ron is matched; with Ron matched to 0.5 ohm, 0.1 % parts still fail, 0.05 % at 25 ppm/K fails by a fraction of a dB (45.8) and 0.05 % at 10 ppm/K passes. On the +/-1.25 V range, which has no switch in the path, 0.05 % at 25 ppm/K gives 45.2 dB and the tempco has to come down or the tolerance to 0.025 %.\n")
    A("### What closes 10 kHz (worst signed corner, CMRR at 10 kHz, +/-5 V range; the +/-1.25 V range differs by < 0.1 dB)\n")
    A("C1 trimmed per channel; the residual is the error left after the trim (C2 +/-5 %, stray +/-0.5 pF still random). 'untrimmed' is a fixed C1 with the stated tolerance.\n")
    A("| C1 | residual / tolerance | 10 kHz CMRR |")
    A("|---|---|---|")
    for tr in (None, 0.05, 0.03, 0.02, 0.01, 0.0075, 0.005, 0.0025):
        v = hfs[(tr, 0.05, 0.5e-12)]["5"]
        A(f"| {'untrimmed, 5 %' if tr is None else 'trimmed'} | {'5 %' if tr is None else f'+/-{tr*100:g} % of C1'} | {v:.1f} dB{' ok' if v >= 40 else ''} |")
    A("")
    A("Untrimmed C0G capacitors of a given tolerance (C1 and C2 both), stray at node N matched to the stated value:\n")
    A("| C tolerance | stray +/-0.5 pF | stray +/-0.1 pF | stray 0 |")
    A("|---|---|---|---|")
    for t in (0.05, 0.02, 0.01, 0.005, 0.0025, 0.001):
        A(f"| {t*100:g} % | " + " | ".join(f"{hfs[(None, t, st)]['5']:.1f}{' ok' if hfs[(None, t, st)]['5'] >= 40 else ''}" for st in (0.5e-12, 0.1e-12, 0.0)) + " |")
    A("\nSo a fixed C1 and C2 reach 40 dB only with 0.5 % capacitors *and* no stray mismatch, or 0.25 % capacitors with 0.1 pF stray matching: neither is a low-cost part or a layout anyone can promise. The trim (about +/-0.8 % of C1 is the break-even, 0.5 % used) is the practical close. The trimmer or the select-on-test value is not chosen here *(check: part, and whether a trimmer's own 0.2-0.5 pF stray and drift keep the 0.5 %)*.\n")

    # ---------------- DF-2 detail
    A("## DF-2: ranges, pin window and common mode\n")
    A("Each input's pin is Vmid + (single-channel gain) x Vin; the two pins go to the converter's VIN+ (A1) and VIN- (A0), so the converter sees a pin difference of (difference gain) x (CH1 - CH2) and the analog path is exactly the 2b scope channel (DF-1).\n")
    A("| range | difference gain (pin difference per input volt) | PGA 1 full scale (AREF 3.20) | PGA 0.5 full scale | step PGA 1 (AREF 3.30) | step PGA 0.5 |")
    A("|---|---|---|---|---|---|")
    for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
        a0, a1 = fx[rg]["adm_min"], fx[rg]["adm_max"]
        A(f"| {nm} | {a0:.4f} - {a1:.4f} | +/-{AREF_LO/2/a1:.3f} V | +/-{AREF_LO/a1:.2f} V (converter); pins limit it to about +/-{2*(AREF_LO/2-0.03-0.08)/a1:.2f} V with 80 mV margin | {AREF_HI/4096/a0*1e3:.3f} mV | {2*AREF_HI/4096/a0*1e3:.3f} mV |")
    A("\nPer-channel DC offset of the pair (pin difference at 0 V in, before calibration), largest over all draws: "
      f"+/-5 V range {fx['5']['dos_max']*1e3:.1f} mV, +/-1.25 V range {fx['1.25']['dos_max']*1e3:.1f} mV (op-amp Vos at 8 mV x the stage gain). It is removed by the host's per-channel offset (DF-4) and it eats range only on the 1.25 V range: 70 mV of pin difference of the converter's +/-1.6 V.\n")
    A("### Common-mode window\n")
    A("Both inputs driven with the same voltage, corner channels (A gain-high, B gain-low, Vos at the maximum with the sign that hurts the side under test), the four combinations of AREF 3.20/3.30 with centring +/-30 mV and rail 3.23/3.37 V. 'margin' = 80 mV inside 0..AREF.\n")
    A("| range | AREF / centring | top: pin reaches AREF - 80 mV at | bottom: pin reaches 80 mV at | non-linearity > 2 mV (top / bottom) | pin at +9 V / -9 V (or +2/-2 V) | largest pin difference over the sweep (offset + CMRR x CM + clip) |")
    A("|---|---|---|---|---|---|---|")
    for k, v in cmw.items():
        rg, tag = k.split("|")
        t, b = v["top"], v["bottom"]
        fm = lambda x: "never" if x is None else f"{abs(x):.2f} V"
        A(f"| {'+/-5 V' if rg=='5' else '+/-1.25 V'} | {tag} | {fm(min([x for x in (t['v_pin_margin80_top'], b['v_pin_margin80_top']) if x], default=None))} | {fm(min([abs(x) for x in (t['v_pin_margin80_bot'], b['v_pin_margin80_bot']) if x], default=None))} | {fm(min(t['v_compress_2mV_top'], b['v_compress_2mV_top']))} / {fm(min(t['v_compress_2mV_bot'], b['v_compress_2mV_bot']))} | {t['pin_top_end']:.3f} / {t['pin_bot_end']:.3f} V | {max(t['diff_peak'], b['diff_peak'])*1e3:.1f} mV |")
    A("")
    A(f"**Largest common-mode voltage (both inputs at +V) for which each pin stays in range:** {lim5[0]:.2f} V on the +/-5 V range (top limit, AREF 3.20 V, centring +30 mV, rail 3.23 V; {min(v['top']['v_pin_margin80_top'] or 9 for k, v in cmw.items() if k.startswith('5|') and 'aref3.30' in k):.2f} V at AREF 3.30) and {lim125[0]:.2f} V on the +/-1.25 V range. The negative side is the mirror: on the +/-5 V range the pin never gets within 80 mV of 0 V in this model because the op-amp output stops at about 0.1 V first (clipping at -{lim5[1]:.2f} V); on the +/-1.25 V range the 80 mV margin is lost at -{lim125[1]:.2f} V. Since the channels are independent, **the window is a per-input rule**: with a difference Vd, the common mode may be at most about (limit - |Vd|/2), i.e. {cm5-2.5:.1f} V for the +/-5 V difference and {cm5-5:.1f} V for +/-10 V on the +/-5 V range, {cm125-0.625:.2f} V for +/-1.25 V and {cm125-1.25:.2f} V for +/-2.5 V on the +/-1.25 V range.\n")
    A("**Past the limit** the op-amp output stops at (rail - its output swing) at the top and (about 0.1 V) at the bottom; the ADC pin therefore never leaves 0..AREF in this model (top end 3.12 V at rail 3.23 V), no clamp current flows, and nothing is damaged (Table 45-38: up to VDDIN without destruction; PR-1/PR-2 are 2b's). What is lost is accuracy: each channel reads a clipped value and the difference is wrong by the mismatch of the two clips. In the sim both channels are the same model and clip at nearly the same level, so the peak pin-difference error over the sweep is the last column of the table above (50-53 mV on the +/-5 V range, about 94 mV on the +/-1.25 V range; it is dominated by what is not clipping - the finite CMRR of the spec corner times the common mode, and on the 1.25 V range the pair's DC offset of up to 85 mV - not by the clip mismatch, which the identical models make zero); **with real parts the two outputs' swing differs by an amount the datasheet bounds only at 5 V *(check)*.** The converter's own behaviour at the edge of its differential common-mode window is not in the datasheet text read here and is **not simulated** (VT-2 sweeps common mode at fixed difference on the actual Due).\n")
    A("The datasheet gives the OPA354's output swing from the rail as 0.1 V typ / 0.3 V max at a 5 V supply only (`datasheet-facts.md`). If it were 0.3 V at 3.23 V the top clip would sit at 2.93 V, i.e. the top common-mode limit would fall from about 6.2 V to about 5.3 V and a +/-6 V input would clip on the +/-5 V range. That is 2b's open item (VT-1), and it bounds this one.\n")

    # ---------------- DF-4
    A("## DF-4: accuracy after calibration\n")
    d5, d125 = fx["5"]["df4"], fx["1.25"]["df4"]
    A("Method: for every draw each channel is fitted with a gain and an offset at the reference temperature (25 C), other input grounded, nine points over the range, by least squares (that is what a per-channel two-parameter host calibration can remove). The same 81 input pairs are then read at the draw's temperature (+/-10 K, resistors with an independent tempco up to the stated value, offset drift up to 4 uV/K) and the input-referred error of the difference is compared with the allowance 0.5 % of the reading + one code (one code = LSB / difference gain at AREF 3.30 V, PGA 1 or 0.5). The 1024-sample mean removes the converter's noise (the difference's noise below is 0.26 code) and quantisation; it removes neither of the two terms here.\n")
    A("| scenario / range | error at the input, worst (mV) | of which channel non-linearity at 25 C (mV) | drift 15-35 C only (mV) | one code (PGA 1 / PGA 0.5) | worst error / allowance (PGA 1 / PGA 0.5) |")
    A("|---|---|---|---|---|---|")
    for tag, s in (("spec", sp), ("fixed", fx)):
        for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
            d = s[rg]["df4"]
            A(f"| {tag}, {nm} | {d['err_max_mV']:.2f} | {d['err_ref_max_mV']:.2f} | {d.get('drift_max_mV', float('nan')):.2f} | {d['pga1.0']['code_mV']:.2f} / {2*d['pga1.0']['code_mV']:.2f} mV | {d['pga1.0']['err_over_allowed_max']:.2f} / {d['pga0.5']['err_over_allowed_max']:.2f} |")
    A("")
    A(f"**What remains after the per-channel fit** is therefore (1) the **drift** of the two channels' gain and offset between the calibration temperature and the operating temperature - the column above - made of the resistors' tempco (at most 25 ppm/K independent -> 0.038 % of gain per channel per 10 K for the divider alone; the sum is in the table) and the op-amp offset drift (4 uV/K x 10 K = 40 uV x the stage gain 1 or 4.83 at the pin); the shared Vmid and sense-node drift is common to both pins and cancels to the CMRR; (2) the channel's own **non-linearity**, which a gain and offset cannot remove: in the vendor model it is the OPA354 input-stage crossover near V+ - 2 V: {d5['err_ref_max_mV']:.1f} mV referred to the input on the +/-5 V range ({d5['err_ref_max_mV']/d5['pga1.0']['code_mV']:.1f} codes at PGA 1) and {d125['err_ref_max_mV']:.1f} mV on the +/-1.25 V range ({d125['err_ref_max_mV']/d125['pga1.0']['code_mV']:.1f} codes, 0.71 mV each); the +/-5 V range passes only because 0.5 % of a large reading is allowed as well; (3) the common-mode-proportional term: after the fit the error at zero difference but a common mode of +/-6 V (+/-1.25 V) is up to "
      f"{d5['err_zero_diff_max_mV']:.1f} mV ({d125['err_zero_diff_max_mV']:.1f} mV on the 1.25 V range). It is not 'a percentage of reading' - a reading near zero in a large common mode carries it fully - and DF-4 as worded cannot bound it as a percent.\n")
    A("**What this means for DF-4:** on the +/-5 V range the fixed design leaves the AFE's contribution inside the allowance; on the +/-1.25 V range it does not at PGA 1, because the crossover non-linearity (one model sample, *(check)*, VT-1) is several of that range's 0.71 mV codes. The datasheet bounds the OPA354 offset at +/-8 mV over the whole input range without giving the crossover step, so the real part could be better or worse than this model. **Requirement problem for the owner:** the converter's own INL is +/-1 LSB typ and +/-1.4 LSB max in differential mode (Table 45-32), so ' +/-1 code ' is already used up by the converter before the AFE adds anything, and a gain/offset calibration cannot remove it. DF-4 can be met only with a piecewise (multi-point) host correction of each channel, or by reading ' code ' as the converter's own and counting the AFE separately. The OPA365 (0.2 mV Vos, no crossover) would remove the AFE part but fails 2b's SM-3 bandwidth on the +/-1.25 V range (7.1 MHz against 8).\n")

    # ---------------- noise
    A("## Noise of the difference\n")
    A("`.noise` on V(A1 pin) - V(A0 pin), both channels 50 ohm sources, 10 Hz to the stated frequency, everything the netlist has; Vmid (20 nV/rtHz) and the 3.3 V sense node (100 nV/rtHz) are the 2b assumptions added through their transfer to the pin difference.\n")
    A("| range | band | one pin | difference | ratio | Vmid contribution | difference incl. rails | difference in codes (PGA 1 / PGA 0.5, LSB at AREF 3.30) | referred to the input |")
    A("|---|---|---|---|---|---|---|---|---|")
    for k, v in nz.items():
        rg, lab = k.split("|")
        a = fx[rg]["adm_min"]
        A(f"| {'+/-5 V' if rg=='5' else '+/-1.25 V'} | {lab} ({v['fmax']/1e6:g} MHz) | {v['single_pin']*1e6:.1f} uV | {v['diff']*1e6:.1f} uV | {v['ratio']:.3f} | {v['vmid_diff']*1e6:.2f} uV | {v['diff_total']*1e6:.1f} uV | {v['diff_total']/(AREF_HI/4096):.2f} / {v['diff_total']/(2*AREF_HI/4096):.2f} | {v['diff_total']/a*1e6:.0f} uV |")
    A("\nThe two channels' noise is uncorrelated except through the shared Vmid and sense node, and that part is rejected (2.7 uV at the pin difference from a 20 nV/rtHz Vmid), so the difference is sqrt(2) x one channel: 210 uV and 216 uV to 1.5 x the bandwidth, against SC-6's 0.2 mV per channel. There is no DF requirement on it. At 1.5 x BW on the +/-5 V range most of it is the op-amp's voltage noise above 20 MHz that the converter's sample-and-hold folds in (2b); at 10 MHz it is 37 uV.\n")

    # ---------------- guards
    A("## Checks I broke on purpose\n")
    A("Each guard below was run on a good pair (must pass), on the deliberately broken pair (must fail), and the pair was restored (the good run above is the restored state: the same function and the same pair). A guard that could not fail is reported as such.\n")
    A("| guard | what it checks | restored / good | broken | outcome |")
    A("|---|---|---|---|---|")
    for g in gd:
        ok = g["good_pass"] and g["bad_fails"]
        out = "works: passes good, fails broken" if ok else ("**cannot fail (by construction)**" if g.get("note") else "**NOT working**")
        A(f"| {g['name']} | {g['what']} | {g['good']} | {g['bad']} | {out} |")
    A("")
    A("G2b is worth keeping as a finding: R1 and R3 are the same value on purpose (R3 = R1 is the centring condition), so swapping them is electrically invisible and no CMRR or window test can see it. Only the bill of materials and the assembly check can.\n"
      "G5 and G5b are one finding: the pin-margin check alone (DF-2/SC-2's criterion) cannot see a mis-centred channel, because the op-amp clips about 0.1 V inside the rail and the pin then stays more than 80 mV from it while the reading is clipped; the first draft of G5 used a 300 mV shift and did not fail either. The guard that works adds a linearity check at +/-6 V, so a clipped channel is caught. G1 and G3 read 227 dB on the matched pair because the nominal pair is exactly symmetric, which is the point of the control.\n")

    # ---------------- gaps
    A("## Model gaps and the bench test that closes each\n")
    A("| gap | why | closed by |")
    A("|---|---|---|")
    A("| The converter's own differential-mode common-mode window, CMRR and the gain/offset mismatch of its two sample paths | not in the datasheet text read (only Table 43-5/43-6, Figure 43-6, Tables 45-32/33/38); not modelled | VT-2: sweep common mode at a fixed difference, both PGA codes, on each Due |")
    A("| Which pin of the pair is VIN+ | Table 43-5 lists 'AD6-AD7' without saying | VT-11: apply +1 V to CH1 only, read the sign |")
    A("| Range-switch Ron: minimum, unit-to-unit spread, matching between two parts, temperature | TMUX1119 datasheet gives 3.7 typ / 8.8 max only; the 0.5 ohm match is the *requirement this report places on the part*, not a datasheet figure | VT-2/VT-10: measure each channel's +/-5 V gain; select or pair parts; DF-3 DC reading on the first boards |")
    A("| Resistor tempco and ratio tracking (25 and 10 ppm/K are stated assumptions *(check)*), 0.05 % availability and cost | no part chosen | VT-2 over a temperature step; part choice at layout |")
    A("| Capacitor and stray tolerance: +/-5 % and +/-0.5 pF at node N are assumptions; the op-amp's own input capacitance (2 pF, tolerance not given) is inside the vendor model and identical in both channels | the model has no part-to-part spread | VT-2 CMRR at 10 kHz-1 MHz is the trim criterion for C1 |")
    A("| OPA354 unit-to-unit spread of gain-bandwidth, output swing at 3.3 V, and CMRR (68 dB used analytically *(check typ/min)*) | the vendor macro is one nominal part, used twice | VT-2 (CMRR above 1 MHz), VT-1 (swing, linearity) |")
    A("| Input-stage crossover non-linearity (the DF-4 limiter) | one vendor-model sample; the datasheet gives Vos only | VT-1 linearity sweep, then a piecewise host correction |")
    A("| Source resistance only 0-100 ohm resistive | no cable or source capacitance, no source mismatch in capacitance | VT-2 with the real cables |")
    A("| AC at 10 Hz stands for DC | the 10 Hz point and the large-signal DC grid agree to 0.1 dB where both are available | none needed |")
    A("")
    A("## Problems with the requirements, for the owner\n")
    A("1. **DF-3 'parts of 0.1 % tolerance or better' is not sufficient** and is silent on what dominates: the range switch's Ron match (+/-5 V range), the resistors' tempco, the op-amp CMRR and, at 10 kHz, the capacitors. Adding 'switch Ron matched within 0.5 ohm, resistors 0.05 % with at most 10 ppm/K, C1 trimmed per channel' would make the requirement testable; none of the three is a 0.1 % statement.")
    A("2. **'Typical 50 dB at DC'** is 43.8 dB median on the +/-5 V range as specified (the Ron spread), against 61 dB on the +/-1.25 V range.")
    A("3. **DF-4 '+/-0.5 % of reading +/-1 code'** cannot be met by any analog front end when the converter's own INL is up to 1.4 LSB, cannot bound a common-mode-proportional error as a percentage of a small reading, and needs a multi-point calibration for the channel's non-linearity.")
    A("4. **DF-2 '+/-10 V difference with each input within +/-6 V'** implies a common mode of at most about +/-1 V at the extremes, and the +/-1.25 V range's '+/-2.5 V' has none. Worth saying in the user-facing text.")
    A("5. `budget/afe_budget.py` DF-3 (50 dB) used the superseded 237k divider and only R1/R2; it should be superseded by this report's figures (not edited here).")
    A("")
    A("## Files\n")
    A("`run.py` (driver), `core2d.py` (draws, evaluation, DF-4), `dlib.py` (netlists, ngspice), `report.py` (this file's generator); `netlists/pair_*` (worst-corner pairs, regenerated); `results/*.json` (header, per-scenario summaries, raw Monte Carlo columns, CMRR curves, sweeps, common-mode window, noise, guards).")
    with open(os.path.join(HERE, "report_legacy.md"), "w") as f:
        f.write("\n".join(L) + "\n")
