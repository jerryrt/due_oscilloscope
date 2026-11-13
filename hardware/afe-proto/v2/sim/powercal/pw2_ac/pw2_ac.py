"""PW-2 cap-distance ripple by AC (harmonic) analysis.

TI's LM27762 transient model stalls ('Timestep too small') on any series inductance in its capacitors, so the effect
of each capacitor's mounting inductance cannot be had by transient simulation. This module takes what the transient
model CAN do, the ideal case (pure-C capacitors), and treats the pump as a periodic current source into each rail:

  1. the ideal transient gives each rail's ripple waveform V(t) over an integer number of pump cycles;
  2. its harmonics V_k (k f0) are turned into the injected current I_k = Y_tr(k f0) V_k, where Y_tr is the admittance the
     transient deck put on that node (the lumped capacitor, plus the resistive load, plus the 1.2 ohm source on VIN);
  3. each rail's impedance Z(f) is built from the passive parts: per capacitor ESR(f) + j w ESL + j w L_i + 1/(j w C),
     in parallel across the rail's capacitors, in parallel with the same load/source conductance;
  4. ripple_k = I_k Z(k f0), summed three ways (linear, RSS, exact phasor synthesis).

What it does not have: the converter's source impedance and loop (the model has no LDO loop), the load network's own
filter, mutual inductance between the capacitors' loops. See README.md. Every number that is not derived from the
board or a stated formula is marked *(check)* and carried in the `sources` table of the results file.
"""
import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AFE = HERE.parents[3]                                   # hardware/afe-proto
sys.path.insert(0, str(HERE.parent))                    # power, common (v2/sim/powercal)

C0 = 299792458.0
MU0 = 4e-7 * math.pi
ESL_H = 0.373e-9        # Samsung CL21A106KAYNNN, from the page by the study's parser: NOT re-derived (|Z| curve is not in the repo)
CSV_DIR = AFE / "models-open" / "cl21a106kaynnne"
ARRAYS = AFE / "tests" / "fixtures" / "arrays" / "v2-integrated-990d4b03.npz"
LIMIT_MV = 20.0         # PW-2

# board geometry (v2 integrated fixture): 2 layers, 1.6 mm overall (general thickness 1.6; the file carries no stackup block)
H_MM = 1.6
ER = 4.5                # FR4: the file states none *(check)*
T_CU_MM = 0.035         # 1 oz copper *(check)*; not used by the Hammerstad-Jensen form below (zero-thickness strip)
VIA_DRILL_MM = 0.3      # v_drill of every via on the integrated fixture (np.unique = [0.3])
VIA_RADIUS_MM = 1.5     # a GND via within this radius of a capacitor's GND pad is its return *(check)*

# as-built pad-to-pin distances (mm), the earlier agent's table, and the pin-link width of each capacitor (POWER block table)
DIST_MM = {"C409": 1.77, "C405": 2.33, "C406": 7.64, "C407": 5.59, "C408": 8.42,
           "C403": 4.24, "C404": 7.59, "C401": 8.55, "C402": 5.95}
WIDTH_MM = {"C405": 0.3, "C406": 0.3, "C401": 0.3, "C402": 0.3,
            "C403": 0.2, "C404": 0.2, "C407": 0.2, "C408": 0.2, "C409": 0.2}     # C409's width is not in the table: 0.2 *(check)*
# the earlier agent's fit L = 2.2 + 0.87 d, kept only as a comparison case
FIT_L0_NH, FIT_K_NH_MM = 2.2, 0.87

# node -> the capacitors in its bank. C409 is the flying capacitor (not a bank); C403/C404 are the pump output (not PW-2)
NODES = {"vin": ("C401", "C402"), "cpout": ("C403", "C404"), "outp": ("C405", "C406"), "outn": ("C407", "C408")}
NODE_NAME = {"vin": "VIN (+5V_F)", "cpout": "CPOUT (LM_CP)", "outp": "OUT+ (+3V3A)", "outn": "OUT- (VNEG)"}
PW2_NODES = ("outp", "outn", "vin")
HARM = 20               # harmonics kept in the synthesis; the first 10 are reported separately


# --------------------------------------------------------------------------- inductance: stated formulas

def microstrip_hj(w_mm, h_mm=H_MM, er=ER):
    """Hammerstad-Jensen microstrip: (Z0 ohm, er_eff) of a strip of width w over a plane h below (zero thickness).
    Valid 0.01 < w/h < 100 with er <= 128 (their stated range)."""
    u = w_mm / h_mm
    a = 1 + math.log((u**4 + (u / 52) ** 2) / (u**4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    ereff = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
    z0 = 60 / math.sqrt(ereff) * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))
    return z0, ereff


def _lprime(w_mm, h_mm=H_MM, er=ER):
    z0, ereff = microstrip_hj(w_mm, h_mm, er)
    return z0 * math.sqrt(ereff) / C0 * 1e6          # H/m * 1e9 nH/H / 1e3 mm/m = 1e6 nH/mm per (H/m)


microstrip_l_nh_per_mm = _lprime


def via_l_nh(h_mm=H_MM, d_mm=VIA_DRILL_MM):
    """Johnson's via inductance L = 5.08 h [ln(4h/d) + 1] nH, h and d in INCHES: written here in mm (5.08 nH/in = 0.2 nH/mm). *(check)* from memory."""
    return 0.2 * h_mm * (math.log(4 * h_mm / d_mm) + 1)


def loop_l_nh(dist_mm, width_mm, n_vias, h_mm=H_MM, er=ER, d_mm=VIA_DRILL_MM):
    """Mounting loop of one capacitor: its pin link (microstrip over the plane) in series with the ground return through
    n_vias parallel vias (no mutual coupling between them: optimistic for n > 1) *(check)*."""
    return _lprime(width_mm, h_mm, er) * dist_mm + via_l_nh(h_mm, d_mm) / max(n_vias, 1)


def via_counts(npz=ARRAYS, radius=VIA_RADIUS_MM):
    """GND vias within `radius` of each capacitor's GND pad on the integrated fixture (the board's own data)."""
    z = np.load(npz, allow_pickle=True)
    nets, refs = list(z["__nets"]), list(z["fp_ref"])
    g = nets.index("/GND")
    out = {}
    for r in DIST_MM:
        i = refs.index(r)
        pads = [j for j in np.where(z["p_fp"] == i)[0] if z["p_net"][j] == g]
        if not pads:
            out[r] = 1                                    # C409 has no ground pad: one via assumed *(check)*; it is no bank
            continue
        j = pads[0]
        d = np.hypot(z["v_x"] - z["p_x"][j], z["v_y"] - z["p_y"][j])
        out[r] = int(np.sum((d <= radius) & (z["v_net"] == g)))
    return out


VIA_COUNT = {"C401": 1, "C402": 1, "C403": 1, "C404": 2, "C405": 1, "C406": 1, "C407": 1, "C408": 2, "C409": 1}   # via_counts() result, frozen (test checks)


def l_formula(scale=1.0, dist=None, n_vias=None):
    dist, n_vias = dist or DIST_MM, n_vias or VIA_COUNT
    return {c: scale * loop_l_nh(dist[c], WIDTH_MM[c], n_vias[c]) for c in dist}


def l_agent_fit(scale=1.0, dist=None):
    dist = dist or DIST_MM
    return {c: scale * (FIT_L0_NH + FIT_K_NH_MM * dist[c]) for c in dist}


# --------------------------------------------------------------------------- the capacitor and the rail

class Esr:
    """ESR(f) from esr.csv by linear interpolation (np.interp clamps outside the table)."""
    def __init__(self, csv_dir=CSV_DIR):
        a = np.genfromtxt(csv_dir / "esr.csv", delimiter=",", skip_header=1)
        a = a[np.argsort(a[:, 0])]
        self.f, self.r = a[:, 0], a[:, 1]

    def __call__(self, f):
        return np.interp(f, self.f, self.r)


def z_cap(f, c, esr, esl=ESL_H, l_h=0.0):
    """One capacitor's series chain: ESR(f) + j w (ESL + L) + 1/(j w C)."""
    w = 2 * np.pi * np.asarray(f, float)
    return esr(f) + 1j * w * (esl + l_h) - 1j / (w * c)


def z_parallel(zs):
    return 1.0 / sum(1.0 / z for z in zs)


def z_node(f, caps, c_each, esr, l_nh=None, esl=ESL_H, g_extra=0.0, pure_c=False):
    """Impedance of a rail: its capacitors in parallel, and the conductance g_extra (load, source) across them.
    pure_c = the transient deck's own network (capacitance only, no ESR, no ESL, no L)."""
    w = 2 * np.pi * np.asarray(f, float)
    y = 0.0
    for c in caps:
        if pure_c:
            y = y + 1j * w * c_each
        else:
            y = y + 1.0 / z_cap(f, c_each, esr, esl, (l_nh or {}).get(c, 0.0) * 1e-9)
    return 1.0 / (y + g_extra)


# --------------------------------------------------------------------------- harmonics

def resample(t, x, f0, t_end, ncyc, per_cycle=64):
    """x on a uniform grid of ncyc whole periods of f0 ending at t_end, `per_cycle` points per period, endpoint excluded."""
    n = ncyc * per_cycle
    tg = t_end - ncyc / f0 + np.arange(n) / (per_cycle * f0)
    return tg, np.interp(tg, t, x)


def harmonics(x, per_cycle, kmax=HARM):
    """Peak-amplitude phasors c_k (x ~ mean + sum Re(c_k e^{j k w0 t})), k = 1..kmax, from uniform samples that cover a
    whole number of periods. Returns (mean, c)."""
    m = len(x)
    ncyc = m // per_cycle
    ks = np.arange(1, kmax + 1)
    # DFT bin of harmonic k over ncyc cycles is k*ncyc
    spec = np.fft.rfft(x) / m
    return float(spec[0].real), 2 * spec[ks * ncyc]


def refine_f0(t, x, f0, t_end, ncyc, span=0.01, n=201):
    """f0 that maximises the fundamental of x over the window (a switching node is the best x): the cycle count is an
    integer only at the right f0."""
    best, bf = -1.0, f0
    for f in np.linspace(f0 * (1 - span), f0 * (1 + span), n):
        tg, xg = resample(t, x, f, t_end, ncyc)
        a = abs(harmonics(xg, 64, 1)[1][0])
        if a > best:
            best, bf = a, f
    return bf


def synth(c, nphi=4096):
    """Waveform over one period from phasors c (k = 1..len(c))."""
    ph = 2 * np.pi * np.arange(nphi) / nphi
    k = np.arange(1, len(c) + 1)
    return np.real(np.exp(1j * np.outer(ph, k)) @ c)


def pp(x):
    return float(np.max(x) - np.min(x))


def ripple_sums(v):
    """v: phasors V_k (peak volts) of a rail. Returns pk-pk figures in the units of v:
    linear = 2 sum|V_k| (every harmonic peaks together: an upper bound on the pk-pk),
    rss = 2 sqrt(sum |V_k|^2) (random phases, equal to the pk-pk of a single sine), phasor = pk-pk of the synthesised waveform."""
    a = np.abs(v)
    return dict(linear=float(2 * a.sum()), rss=float(2 * np.sqrt((a**2).sum())), phasor=pp(synth(v)))


# --------------------------------------------------------------------------- the transient (ideal case) and the node data

def get_pw2():
    """x1's simtools.pw2. If the checkout has not caught up with origin/pcbtools yet it is read from a scratch copy of
    origin's files built under pcbtools/.scratch (see README)."""
    try:
        return importlib.import_module("simtools.pw2")
    except ImportError:
        root = AFE / "pcbtools" / ".scratch" / "orig" / "afe-proto"
        sys.path.insert(0, str(root))
        return importlib.import_module("simtools_o.pw2")


def circuit(lm1):
    """lm_tran's 'su_5.25_max' circuit, the one pw2_loopl.py runs (VIN 5.25 V, v2 feedback values at the maximum corner)."""
    import power
    from common import TPH
    rc = power.rail_corners()
    v_awg, _ = power.awg_values()
    b = power.budget(rc["max_p"], v_awg, 50.0, -1.9, TPH["iq_max"])
    vref = 1.216

    def fb_for(vp, vn):
        return (100e3 * (vp / vref - 1), 100e3, 100e3 * (vn / vref - 1), 100e3)
    return dict(vin=5.25, fb=fb_for(rc["max_p"], rc["max_n"]), ip=b["Ip"], ineg=b["In"], c1=("ideal", 1e-6 * 0.63))


def node_admittance(deck):
    """From the deck the transient ran: per node, the lumped capacitance and the conductance the deck puts across it
    (load resistor; the 1.2 ohm source on VIN). Parsed, not assumed."""
    import re
    cap = {}
    for name, node in (("Cin", "vin"), ("Ccpo", "cpout"), ("Cop", "outp"), ("Con", "outn")):
        c = 0.0
        for ln in deck.split("\n"):
            m = re.match(rf"^C(C40\d) (\S+) (\S+) (\S+)$", ln)
            if m and m.group(2) == node:
                c += float(m.group(4))
        cap[node] = c
    g = {"vin": 0.0, "cpout": 0.0, "outp": 0.0, "outn": 0.0}
    for ln in deck.split("\n"):
        m = re.match(r"^(Rldp|Rldn|Rsrc) (\S+) (\S+) (\S+)$", ln)
        if m:
            nm, a, b, val = m.groups()
            node = {"Rldp": "outp", "Rldn": "outn", "Rsrc": "vin"}[nm]
            g[node] += 1 / float(val)
    return cap, g


def run_transient(workdir, mem="2G", timeout=900):
    """The IDEAL case once through the runner. Returns dict(t, v{outp,outn,vin,cp,cpout}, cap, g, meta)."""
    pw2 = get_pw2()
    lm1 = pw2.load_harness()
    kw = circuit(lm1)
    kw.update(tstop=1.3e-3, tmax=0.25e-6)
    deck, _ = pw2.case_deck(lm1, "pw2ac_ideal", scale=0.0, **kw)
    cap, g = node_admittance(deck)
    res, run = pw2.run_case(lm1, "pw2ac_ideal", workdir, mem=mem, timeout=timeout, scale=0.0, **kw)
    if run is None:
        raise RuntimeError(f"the ideal transient did not converge: {res.detail}")
    plot = next(iter(run.plots().values()))
    t = plot["time"].real
    v = {k: plot[f"v({k})"].real for k in ("outp", "outn", "vin", "cp", "cpout")}
    return dict(t=t, v=v, cap=cap, g=g, res=res.__dict__, wall_s=run.wall_s, peak_rss_kb=(run.peak_rss_bytes or 0) // 1024)


def save_window(path, tr, window=150e-6):
    m = tr["t"] >= tr["t"][-1] - window
    np.savez_compressed(path, t=tr["t"][m], **{f"v_{k}": x[m] for k, x in tr["v"].items()},
                        **{f"c_{k}": x for k, x in tr["cap"].items()}, **{f"g_{k}": x for k, x in tr["g"].items()},
                        meta=json.dumps(dict(res=tr["res"], wall_s=tr["wall_s"], peak_rss_kb=tr["peak_rss_kb"])))


def load_window(path):
    z = np.load(path)
    nodes = ("outp", "outn", "vin", "cp", "cpout")
    return dict(t=z["t"], v={k: z[f"v_{k}"] for k in nodes}, cap={k: float(z[f"c_{k}"]) for k in NODES},
                g={k: float(z[f"g_{k}"]) for k in NODES}, meta=json.loads(str(z["meta"])))


# --------------------------------------------------------------------------- the ripple estimate (line spectrum of the window)
#
# The model's pump is a PFM burst generator: cp toggles at ~2.14 MHz inside bursts of about 2 us that repeat at ~85 kHz, so the
# rail ripple is a burst-rate sawtooth (capacitor-dominated) and carries almost nothing at k x pump. A Fourier series at one
# f0 therefore cannot describe it; the whole window is decomposed into its lines m / T_w instead (T_w = 100 us, 10 kHz apart),
# and the pump harmonics are reported as bands of that spectrum. The network acts line by line.

TW = 100e-6             # analysis window: the last 100 us of the transient (pw2.analyse's)
NPTS = 2 ** 14          # 6.1 ns grid: Nyquist 82 MHz
BAND_FRAC = 0.25        # a pump-harmonic band is k f_pump +- BAND_FRAC f_pump (covers the burst sidebands) *(check)*
FMAX_HZ = 30e6          # lines above this are dropped from the case ripple: the injected current there is not stable against the resampling grid (README) *(check)*
SPLIT_FRAC = 0.5        # lines below SPLIT_FRAC x f_pump are the burst-rate (low) band, not scaled with the pump frequency


def window_lines(t, x, tw=TW, n=NPTS):
    """x over the last tw of the record on n uniform points, made periodic by subtracting the straight line that joins its
    two ends (leakage from the end mismatch would otherwise swamp the high lines), and decomposed.
    Returns (f_m, c_m, ramp, mean): peak-amplitude phasors of lines m = 1..n/2, the removed ramp (added back to any waveform)
    and the mean. x_grid = mean + ramp + irfft(lines)."""
    te = t[-1]
    tg = te - tw + np.arange(n + 1) * tw / n
    xg = np.interp(tg, t, x)
    ramp = (xg[-1] - xg[0]) * np.arange(n) / n
    xp = xg[:n] - xg[0] - ramp
    mean = float(xp.mean())
    spec = np.fft.rfft(xp - mean) / n
    f = np.arange(1, n // 2 + 1) / tw
    return f, 2 * spec[1:], xg[0] + ramp + mean, mean


def lines_to_wave(c, n=NPTS):
    """Inverse of the line decomposition (zero mean)."""
    spec = np.zeros(n // 2 + 1, complex)
    spec[1:] = c / 2 * n
    return np.fft.irfft(spec, n)


def pump_frequency(t, cp, tw=TW, n=NPTS, lo=1.0e6, hi=4.0e6):
    """Pump frequency inside the bursts: the centroid of the cp node's spectrum between lo and hi, and the burst duty as the
    ratio of the mean-crossing rate (what pw2.analyse reports as 'pump_hz') to it."""
    f, c, _, _ = window_lines(t, cp, tw, n)
    m = (f >= lo) & (f <= hi)
    pw = np.abs(c[m]) ** 2
    fp = float((f[m] * pw).sum() / pw.sum())
    x = cp - cp.mean()
    ups = np.where((x[:-1] < 0) & (x[1:] >= 0))[0]
    mean_cross = (len(ups) - 1) / (t[ups[-1]] - t[ups[0]]) if len(ups) > 2 else float("nan")
    return fp, mean_cross


def band_masks(f, f_pump, kmax=10):
    """Boolean masks over lines: low (burst-rate band), pump (k = 1..kmax bands), and the other high lines."""
    low = f < SPLIT_FRAC * f_pump
    pump = np.zeros(len(f), bool)
    for k in range(1, kmax + 1):
        pump |= np.abs(f - k * f_pump) <= BAND_FRAC * f_pump
    pump &= ~low
    return low, pump, ~(low | pump)


def case_lines(i_lines, f, node, c_each, esr, g, l_nh, s=1.0, f_pump=2.14e6, pure_c=False):
    """V_m = I_m Z(f_m'), with f_m' = f_m below the split and s f_m above (the pump run at s x the model's frequency, the same
    I_m: same charge per cycle at the same average current means the same current as a function of phase) *(check)*."""
    fe = np.where(f < SPLIT_FRAC * f_pump, f, s * f)
    return i_lines / (1.0 / z_node(fe, NODES[node], c_each, esr, l_nh, g_extra=g, pure_c=pure_c))


def metrics(c, ramp, f, f_pump):
    """Ripple figures of one rail from its line phasors (peak volts): the waveform's pk-pk, the linear and RSS sums over lines,
    and the same split into the burst-rate band, the pump-harmonic bands and the rest."""
    low, pump, rest = band_masks(f, f_pump)
    w = lines_to_wave(c) + ramp
    out = dict(phasor=pp(w), linear=float(2 * np.abs(c).sum()), rss=float(2 * np.sqrt((np.abs(c) ** 2).sum())))
    for name, mk in (("low", low), ("pump", pump), ("rest", rest)):
        cm = np.where(mk, c, 0)
        out[f"phasor_{name}"] = pp(lines_to_wave(cm))
        out[f"var_share_{name}"] = float((np.abs(c[mk]) ** 2).sum() / max((np.abs(c) ** 2).sum(), 1e-300))
    out["pump_linear"] = float(2 * np.abs(c[pump]).sum())
    out["pump_rss"] = float(2 * np.sqrt((np.abs(c[pump]) ** 2).sum()))
    return out


BANDS_HZ = {"dc_1M": (0.0, 1e6), "1M_10M": (1e6, 10e6), "10M_30M": (10e6, 30e6)}     # PW-4's band is DC-1 MHz


def band_figures(c, ramp, f, bands=BANDS_HZ):
    """rms (about the mean) and pk-pk of the rail's ripple restricted to each band of lines [lo, hi). The DC-1 MHz band carries the
    ramp that made the window periodic (it is below 10 kHz); the others do not."""
    out = {}
    for name, (lo, hi) in bands.items():
        mk = (f >= lo) & (f < hi)
        w = lines_to_wave(np.where(mk, c, 0)) + (ramp if lo == 0.0 else 0.0)
        out[name] = dict(rms=float(np.std(w)), pkpk=pp(w))
    return out


def node_lines(tr):
    """Per node: lines of the window, the injected current I_m = Y_tr(f_m) V_m (Y_tr: the deck's own capacitance and conductance)."""
    out = {}
    for node in NODES:
        f, c, ramp, mean = window_lines(tr["t"], tr["v"][node])
        y = 1j * 2 * np.pi * f * tr["cap"][node] + tr["g"][node]
        out[node] = dict(f=f, V=c, I=y * c, ramp=ramp, mean=mean)
    return out


def estimate(tr, scales=None, esr=None, cases=None, dl_nh=2.0, fmax=FMAX_HZ):
    """All the figures from the ideal transient window `tr`."""
    esr = esr or Esr()
    fp, mean_cross = pump_frequency(tr["t"], tr["v"]["cp"])
    nl = node_lines(tr)
    c_each = {n: tr["cap"][n] / len(NODES[n]) for n in NODES}
    freqs = {"model": fp, "1.7MHz": 1.7e6, "2.0MHz": 2.0e6, "2.3MHz": 2.3e6}
    if scales:
        freqs = scales
    lf, lfit = l_formula(1.0), l_agent_fit(1.0)
    zero = {c: 0.0 for c in DIST_MM}
    case_l = {"ideal": zero, "asbuilt": lf, "L_x0.5": l_formula(0.5), "L_x2": l_formula(2.0), "agent_fit": lfit,
              "control_C407+100nH": {**lf, "C407": lf["C407"] + 100.0}}
    case_l.update(cases or {})

    def run(node, l_nh, f_eval, pure_c=False, fm=fmax):
        d = nl[node]
        c = case_lines(d["I"], d["f"], node, c_each[node], esr, tr["g"][node], l_nh, f_eval / fp, fp, pure_c)
        if fm:
            c = np.where(d["f"] <= fm, c, 0)
        m = metrics(c, d["ramp"], d["f"], fp)
        m["bands"] = band_figures(c, d["ramp"], d["f"])
        return m

    def mv(m):
        o = {k: v * 1e3 for k, v in m.items() if k != "bands" and not k.startswith("var_share")}
        o.update({k: v for k, v in m.items() if k.startswith("var_share")})
        if "bands" in m:
            o["bands_mv"] = {b: {k: x * 1e3 for k, x in v.items()} for b, v in m["bands"].items()}
        return o
    res = dict(f_pump_hz=fp, mean_crossing_hz=mean_cross, burst_duty=mean_cross / fp, frequencies_hz=freqs, cases={}, nodes={}, sensitivity={})
    for node in NODES:
        d = nl[node]
        m0 = metrics(d["V"], d["ramp"], d["f"], fp)
        m0["bands"] = band_figures(d["V"], d["ramp"], d["f"])
        a = np.abs(d["V"])
        top = np.argsort(a)[::-1][:5]
        res["nodes"][node] = dict(mean_v=d["mean"], pp_transient_mv=pp(np.interp(
            np.arange(NPTS) / NPTS * TW + (tr["t"][-1] - TW), tr["t"], tr["v"][node])) * 1e3, **mv(m0),
            top_lines_khz_uv=[(float(d["f"][i] / 1e3), float(a[i] * 1e6)) for i in top],
            pump_harmonic_peak_uv=[float(np.abs(d["V"][np.abs(d["f"] - k * fp) <= BAND_FRAC * fp]).max() * 1e6) for k in range(1, 11)],
            injected_current_pump_band_rms_ma=float(np.sqrt((np.abs(d["I"][band_masks(d["f"], fp)[1]]) ** 2).sum() / 2) * 1e3),
            injected_current_low_rms_ma=float(np.sqrt((np.abs(d["I"][band_masks(d["f"], fp)[0]]) ** 2).sum() / 2) * 1e3))
    vals = {n: run(n, None, fp, True, fm=None) for n in NODES}                       # every line: the transient's own network
    res["validation_pure_C"] = {n: dict(**mv(vals[n]), transient_pp_mv=res["nodes"][n]["pp_transient_mv"],
                                        ratio_phasor_over_transient=vals[n]["phasor"] * 1e3 / res["nodes"][n]["pp_transient_mv"],
                                        ratio_linear_over_transient=vals[n]["linear"] * 1e3 / res["nodes"][n]["pp_transient_mv"]) for n in NODES}
    # the pure-C network read through the same band limit as the cases: how much of the transient's own ripple it keeps
    res["validation_pure_C_bandlimited"] = {n: run(n, None, fp, True)["phasor"] * 1e3 / res["nodes"][n]["pp_transient_mv"] for n in NODES}
    res["bandwidth_sweep_mv"] = {case: {str(int(fm / 1e6)): {n: run(n, case_l[case], fp, fm=fm)["phasor"] * 1e3 for n in NODES}
                                       for fm in (5e6, 10e6, 20e6, 30e6, 40e6, 83e6)} for case in ("ideal", "asbuilt")}
    res["fmax_hz"] = fmax
    for name, l_nh in case_l.items():
        res["cases"][name] = {fl: {n: mv(run(n, l_nh, f0)) for n in NODES} for fl, f0 in freqs.items()}
    res["l_nh"] = case_l
    ds = [k for k in freqs if k != "model"]
    res["worst_datasheet_mv"] = {case: {n: max(res["cases"][case][fl][n]["phasor"] for fl in ds) for n in NODES} for case in case_l}
    res["vin_pw4_band"] = pw4_table(res, ds=[k for k in freqs if k != "model"])
    res["fmax_table_vin_mv"] = {case: {k: v["vin"] for k, v in d.items()} for case, d in res["bandwidth_sweep_mv"].items()}
    res["notes"] = NOTES
    res["verdict"] = {n: verdict(res["worst_datasheet_mv"]["asbuilt"][n]) for n in PW2_NODES}
    for c in ("C401", "C402", "C403", "C404", "C405", "C406", "C407", "C408"):
        node = next(n for n, cs in NODES.items() if c in cs)
        row = {"node": node}
        for tag, l_new in (("plus_dl", lf[c] + dl_nh), ("x2", 2 * lf[c]), ("plus_100nh", lf[c] + 100.0)):
            lc = dict(lf)
            lc[c] = l_new
            row[tag] = {fl: run(node, lc, f0)["phasor"] * 1e3 for fl, f0 in freqs.items()}
        base = {fl: res["cases"]["asbuilt"][fl][node]["phasor"] for fl in freqs}
        row["base"] = base
        for tag in ("plus_dl", "x2", "plus_100nh"):
            row["rise_" + tag] = {fl: row[tag][fl] - base[fl] for fl in freqs}
        res["sensitivity"][c] = row
    res["dl_nh"] = dl_nh
    return res


def pw4_table(res, ds):
    """VIN in the bands: the transient, then each case at the model's frequency and the worse of the datasheet range (per figure)."""
    t = res["nodes"]["vin"]["bands_mv"]
    out = {"transient": {b: dict(v) for b, v in t.items()}}
    for case in ("ideal", "asbuilt", "L_x0.5", "L_x2"):
        row = {}
        for b in BANDS_HZ:
            row[b] = {}
            for k in ("rms", "pkpk"):
                vals = {fl: res["cases"][case][fl]["vin"]["bands_mv"][b][k] for fl in res["cases"][case]}
                row[b][k] = dict(model=vals["model"], worse_datasheet=max(vals[fl] for fl in ds), spread_model_to_worse=max(vals[fl] for fl in ds) - vals["model"])
        out[case] = row
    return out


NOTES = {
    "pw4": "PW-4 (rms noise rise on the Due 3.3 V pin and AREF <= 0.3 mV over DC-1 MHz) is NOT judged here. The VIN figures are the 5 V "
           "ripple in that band; how it reaches the Due 3.3 V and AREF through the Due's regulator is a property of the pump itself "
           "(the ideal layout included) and is VT-8's measurement.",
    "edge_content": "The 10-30 MHz VIN content is unvalidated: it is the model's switch-edge current, it depends on the band limit (fmax_table_vin_mv), "
                    "and nothing here checks it against the real part. VT-8's 5 V measurement with a wideband probe is the check.",
    "out_rails": "The model cannot resolve the cap-distance question on OUT+ and OUT-: it injects 0.3 mA (burst band) and 0.02 mA (pump band) into OUT+ "
                 "(0.13 / 0.008 mA into OUT-), the rails are insensitive to L, and the real chain's behaviour is VT-8's.",
    "sensitivity": "Distance acts at the CP and VIN capacitors (C403, C404, C402, C401), not at the output capacitors.",
}


def verdict(mv, limit=LIMIT_MV):
    """with margin: at most half the limit; little: up to the limit; fail: over it."""
    return "with margin" if mv <= 0.5 * limit else "little margin" if mv <= limit else "fail"


def sources_table():
    """Quantity, value, formula or file, status: what every number rests on."""
    z08, e08 = microstrip_hj(0.2), None
    rows = [
        ("ESL per capacitor", f"{ESL_H*1e9:.3f} nH", "models-open/cl21a106kaynnne/PROVENANCE.md: median over 3-10 MHz of (X + 1/(wC))/w, C = 10 uF, from the |Z| and ESR curves of Samsung's page",
         "cited, NOT re-derived: the repo holds esr.csv and dcbias.csv only, the |Z| curve is not in it; page not committed and no longer byte-identical (check)"),
        ("ESR(f)", "esr.csv, np.interp", "models-open/cl21a106kaynnne/esr.csv", "from the page by the study's parser"),
        ("C per capacitor", "10 uF x k(V) x 0.9", "parsed from the transient deck (derated at the node's set-point voltage); k from dcbias.csv", "the harness's own"),
        ("board thickness h", f"{H_MM} mm", "tests/fixtures/v2-8a1f7ac/v2-integrated-990d4b03.kicad_pcb (general (thickness 1.6)); 2 copper layers, plane on the back",
         "board file; no stackup block, so the top-copper-to-plane distance is the whole 1.6 mm (dielectric = overall)"),
        ("er (FR4)", f"{ER}", "not in the board file", "(check) typical FR4"),
        ("copper thickness", f"{T_CU_MM} mm", "not in the board file", "(check) not used: zero-thickness strip"),
        ("microstrip L'", f"w=0.2: {_lprime(0.2):.3f} nH/mm; w=0.3: {_lprime(0.3):.3f} nH/mm",
         "Hammerstad-Jensen Z0, er_eff; L' = Z0 sqrt(er_eff)/c (pcbtools: pw2_ac.microstrip_hj)", "formula (check: valid for a plane directly below the strip; a pour gap or split changes it)"),
        ("via inductance", f"{via_l_nh():.3f} nH per via", "Johnson: L = 5.08 h [ln(4h/d)+1] nH, h = 1.6 mm, d = 0.3 mm drill (v_drill of the fixture, all 41 vias)", "formula from memory (check)"),
        ("GND vias per capacitor", json.dumps(VIA_COUNT), f"v2-integrated-990d4b03.npz: GND vias within {VIA_RADIUS_MM} mm of the capacitor's GND pad", "board data; the radius is a choice (check); mutual inductance between vias ignored"),
        ("pin-link widths", json.dumps(WIDTH_MM), "the POWER block's table (C405/406/401/402 0.3 mm, C403/404/407/408 0.2 mm)", "given by the spec lead; C409 not in it (check)"),
        ("pad-to-pin distances", json.dumps(DIST_MM), "the earlier agent's table (as-built)", "not re-measured here (check)"),
        ("agent fit", f"L = {FIT_L0_NH} + {FIT_K_NH_MM} d nH", "the earlier agent's table", "a fit, not validated (check): kept as the case 'agent_fit'"),
        ("injected current", "I_m = Y_tr(f_m) V_m, lines m/100 us of the last 100 us", "ripple lines of the ideal transient through the admittance the deck put on the node (C, load, 1.2 ohm source on VIN): the current the capacitors carry plus the resistive part", "derived; ignores the source/LDO impedance (limit)"),
        ("pump frequency", "centroid of cp spectrum 1-4 MHz (inside bursts)", "the model's cp node: bursts at the pump frequency repeating at ~85 kHz; pw2.analyse's 1.25 MHz is the mean-crossing rate over bursts and idle", "measured on the transient"),
        ("datasheet f scaling", "lines above 0.5 f_pump evaluated at s x f, same I_m", "same average current Q f0: pulse charge falls as 1/f0 while its duration falls as 1/f0, so the current as a function of phase is unchanged; the burst-rate band is not scaled", "assumption (check)"),
    ]
    return [dict(quantity=a, value=b, formula_or_file=c, status=d) for a, b, c, d in rows]


def main(argv):
    import tempfile
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    win = out / "transient_ideal_window.npz"
    if argv and argv[0] == "transient":
        work = Path(tempfile.mkdtemp(prefix="pw2ac-", dir=str(AFE / "pcbtools" / ".scratch")))
        tr = run_transient(work)
        save_window(win, tr)
        print(json.dumps(dict(wall_s=tr["wall_s"], peak_rss_kb=tr["peak_rss_kb"], res=tr["res"])))
        return 0
    tr = load_window(win)
    res = estimate(tr)
    res["sources"] = sources_table()
    res["limit_mv"] = LIMIT_MV
    res["transient_run"] = tr["meta"]
    (out / "pw2_ac_results.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res[k] for k in ("f_pump_hz", "mean_crossing_hz", "burst_duty", "validation_pure_C")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
