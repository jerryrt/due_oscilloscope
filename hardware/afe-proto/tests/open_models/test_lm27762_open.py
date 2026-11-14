"""LM27762_OPEN / LM27762_OPEN_AVG against the figures in models-open/lm27762-open/FACTS.md.

Every assertion cites the FACTS.md row it checks and uses the accuracy FACTS.md states for it (a
typical value with no stated spread gets the stated tolerance written beside it). The two checks at
the end break the model on purpose and require the matching test to fail.

The switching tests run 0.3-1.2 ms of a 20 ns-step transient and take a few seconds each.
"""
import math
import re
from pathlib import Path

import numpy as np
import pytest

from simtools import netlib_common as nc

pytestmark = pytest.mark.ngspice

PART = Path(__file__).resolve().parents[2] / "models-open" / "lm27762-open"
LIB = PART / "lm27762.lib"

# Board-like dividers (FACTS 6): OUT+ = 1.2*(R1+R2)/R2, OUT- = -1.22*(R3+R4)/R4
R33 = (210e3, 120e3)       # +3.300 V
R205 = (100e3, 147e3)      # -2.0498 V
R18P = (50e3, 100e3)       # +1.8 V
R18N = (47.5e3, 100e3)     # -1.7995 V
R_IQ = (17.5e6, 10e6, 6.8e6, 10e6)   # dividers so large they load the rails by < 0.2 uA (IQ is "no load")


def run(tmp_path, name, body, lib=LIB, timeout=300, mem=None):
    """Write <name>.cir with the model included, run ngspice through the project's capped runner."""
    text = f"* {name}\n.include {lib}\n{body}\n.end\n"
    return nc.run_ng(str(tmp_path), str(tmp_path), "t_", name, text, timeout, mem=mem)


def values(out):
    d = {}
    for m in re.finditer(r"^([\w().#]+) = (\S+)", out, re.M):
        try:
            d[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    return d


def board(vin=5.0, variant="AVG", r33=R33, r205=R205, enp=None, enn=None, ilp=0, iln=0, icp=0,
          vfbp=1.2, vfbn=-1.22, fsw=2e6, extra="", vin_src=None, pullup=True):
    """The application circuit: caps per the datasheet (CIN 4.7 uF, C1 1 uF, CP 4.7 uF, COUT 2.2 uF, FACTS 8),
    dividers on both rails, PGOOD pulled to a 5 V rail through 10 kohm. Load currents flow out of OUT+, into
    OUT- (from ground, through the load) and into CP. The switching variant gets its loads ramped in after
    the pump has started, because with the pump idle the CP node has no DC path."""
    enp = vin if enp is None else enp
    enn = vin if enn is None else enn
    sw = variant == "SW"

    def cur(name, a, b, val, delay=0.0):
        if not val:
            return f"{name} {a} {b} 0"
        return f"{name} {a} {b} pwl(0 0 {delay} 0 {delay + 20e-6} {val})" if sw else f"{name} {a} {b} {val}"

    return f"""
{vin_src or f'Vin vin 0 {vin}'}
Venp enp 0 {enp}
Venn enn 0 {enn}
Vpu pu 0 5
{'Rpu pu pg 10k' if pullup else 'Rpg pg 0 1g'}
X1 vin 0 op fp on fn cp c1p c1n enp enn pg LM27762_OPEN{'_AVG' if not sw else ''} VFBP={vfbp} VFBN={vfbn} FSW={fsw}
R1 op fp {r33[0]}
R2 fp 0 {r33[1]}
R3 on fn {r205[0]}
R4 fn 0 {r205[1]}
Co op 0 2.2u
Cn on 0 2.2u
Ccp cp 0 4.7u
Cin vin 0 4.7u
C1 c1p c1n 1u
{cur('Ilp', 'op', '0', ilp, 100e-6)}
{cur('Iln', '0', 'on', iln, 100e-6)}
{cur('Icp', '0', 'cp', icp, 100e-6)}
{extra}
"""


OP_CTL = ".op\n.control\nrun\nprint v(op) v(on) v(cp) v(pg) i(vin)\n.endc\n"


def op(tmp_path, name, lib=LIB, **kw):
    out = run(tmp_path, name, board(**kw) + OP_CTL, lib=lib)
    d = values(out)
    assert "v(op)" in d, out[-1500:]
    return d


def tran(tmp_path, name, tstop, vecs, lib=LIB, step="20n", timeout=300, **kw):
    f = tmp_path / f"{name}.dat"
    ctl = f".tran {step} {tstop}\n.control\nrun\nwrdata {f} {' '.join(vecs)}\n.endc\n"
    run(tmp_path, name, board(**kw) + ctl, lib=lib, timeout=timeout)
    a = np.loadtxt(f)
    return a[:, 0], [a[:, 1 + 2 * i] for i in range(len(vecs))]


# ---- FACTS Fig 5-4 (25 C, VIN 5.5 V): charge pump output resistance, (A, ohm), log-log, +-25 % in ohm, +-20 % in A
FIG54 = [(0.001, 300), (0.003, 120), (0.01, 35), (0.03, 7), (0.06, 3.5), (0.1, 2.5), (0.3, 2.2)]


def fig54_r(i):
    x = np.log([p[0] for p in FIG54])
    y = np.log([p[1] for p in FIG54])
    return float(np.exp(np.interp(math.log(i), x, y)))


def in_fig54_envelope(i, r):
    lo = min(fig54_r(i * 0.8), fig54_r(i * 1.2)) * 0.75
    hi = max(fig54_r(i * 0.8), fig54_r(i * 1.2)) * 1.25
    return lo <= r <= hi


# ======================= checks (also used, mutated, by the break controls) =======================

def check_load_regulation(tmp_path, lib=LIB):
    """FACTS 5: load regulation 11 uV/mA (OUT+, 1.8 V) and 34 uV/mA (OUT-, -1.8 V), 0 to 250 mA, VIN 5 V.
    The table gives no spread; +-20 % is the tolerance of this test."""
    z = op(tmp_path, "lr0", lib=lib, r33=R18P, r205=R18N)
    f = op(tmp_path, "lr1", lib=lib, r33=R18P, r205=R18N, ilp=0.25, iln=0.25)
    dp = (z["v(op)"] - f["v(op)"]) / 250 * 1e6
    dn = (f["v(on)"] - z["v(on)"]) / 250 * 1e6      # OUT- becomes less negative under load
    assert 11 * 0.8 <= dp <= 11 * 1.2, dp
    assert 34 * 0.8 <= dn <= 34 * 1.2, dn
    return dp, dn


def check_cp_droop(tmp_path, lib=LIB):
    """FACTS Fig 5-4: CP droop as output resistance vs load at VIN 5.5 V, inside the figure's reading accuracy.
    The load on CP is the injected current plus the negative LDO's own 200 uA bias (a model choice, in the total)."""
    bad = []
    for i in (0.001, 0.003, 0.01, 0.03, 0.06, 0.1, 0.3):
        d = op(tmp_path, f"cp{int(i * 1e3)}", lib=lib, vin=5.5, enp=0, icp=i)
        itot = i + 0.2e-3
        r = (5.5 + d["v(cp)"]) / itot
        if not in_fig54_envelope(itot, r):
            bad.append((i, round(r, 2), round(fig54_r(itot), 2)))
    assert not bad, bad


# ======================= output voltage and regulation =======================

@pytest.mark.parametrize("vfbp,vfbn", [(1.182, -1.238), (1.2, -1.22), (1.218, -1.202)])
def test_output_voltages_follow_the_feedback_equations(tmp_path, vfbp, vfbn):
    """FACTS 6 Eq 1 and Eq 3 with the FACTS 5 reference min/typ/max (FB+ 1.182/1.2/1.218, FB- -1.238/-1.22/-1.202)."""
    d = op(tmp_path, f"vo{vfbp}", vfbp=vfbp, vfbn=vfbn)
    assert d["v(op)"] == pytest.approx(vfbp * (R33[0] + R33[1]) / R33[1], abs=5e-3)
    assert d["v(on)"] == pytest.approx(vfbn * (R205[0] + R205[1]) / R205[1], abs=5e-3)
    assert d["v(pg)"] < 0.5      # both rails up: PGOOD low (FACTS 7)


def test_load_regulation(tmp_path):
    check_load_regulation(tmp_path)


def test_line_regulation(tmp_path):
    """FACTS 5: line regulation 1.9 mV/V (OUT+) and 1.5 mV/V (OUT-), VIN 2.7..5 V, 50 mA; signs from Fig 5-6 / 5-5
    (OUT+ falls and OUT- becomes more negative as VIN rises). +-20 % on the typ figures."""
    lo = op(tmp_path, "ln27", vin=2.7, r33=R18P, r205=R18N, ilp=0.05, iln=0.05)
    hi = op(tmp_path, "ln50", vin=5.0, r33=R18P, r205=R18N, ilp=0.05, iln=0.05)
    sp = (lo["v(op)"] - hi["v(op)"]) / 2.3 * 1e3
    sn = (lo["v(on)"] - hi["v(on)"]) / 2.3 * 1e3
    assert 1.9 * 0.8 <= sp <= 1.9 * 1.2, sp
    assert 1.5 * 0.8 <= sn <= 1.5 * 1.2, sn


def test_dropout_is_the_fig_5_3_line(tmp_path):
    """FACTS Fig 5-3: dropout = 117 mV (OUT+) and 80 mV (OUT-) at 250 mA, straight through the origin, +-3 mV.
    OUT+: VIN 3.0 V with a 3.3 V target. OUT-: VIN 3.0 V with a -4.9 V target, out of reach of CP, so the
    LDO's own drop is read as OUT- minus CP. The knee into dropout is softer than the figure's line (the
    pass device has finite gain); this test reads it where the output is far below target."""
    for i, p in ((0.1, 0.47), (0.25, 0.47)):
        d = op(tmp_path, f"dop{int(i * 1e3)}", vin=3.0, ilp=i)
        assert 3.0 - d["v(op)"] == pytest.approx(0.117 * i / 0.25, abs=3e-3)
    for i in (0.1, 0.25):
        d = op(tmp_path, f"don{int(i * 1e3)}", vin=3.0, r205=(300e3, 100e3), iln=i)
        assert d["v(on)"] - d["v(cp)"] == pytest.approx(0.080 * i / 0.25, abs=3e-3)


def test_charge_pump_droop_matches_fig_5_4(tmp_path):
    check_cp_droop(tmp_path)


def test_rneg_2p5_ohm_at_100ma(tmp_path):
    """FACTS 5: RNEG 2.5 ohm typ, VIN 5.5 V, 100 mA. Averaged variant, +-25 % (the Fig 5-4 reading accuracy)."""
    d = op(tmp_path, "rneg", vin=5.5, enp=0, icp=0.1 - 0.2e-3)
    r = (5.5 + d["v(cp)"]) / 0.1
    assert 2.5 * 0.75 <= r <= 2.5 * 1.25, r


def test_current_limit_500ma(tmp_path):
    """FACTS 4: positive LDO input current limit 500 mA typ, output shorted to ground. +-10 % is this test's tolerance."""
    out = run(tmp_path, "ilim", board(enn=0) + "Rs op 0 10m\n.op\n.control\nrun\nprint i(vin) v(op)\n.endc\n")
    d = values(out)
    assert 0.5 * 0.9 <= -d["i(vin)"] - 0.1e-3 <= 0.5 * 1.1, d


# ======================= quiescent, shutdown, UVLO, enables, PGOOD =======================

def test_quiescent_and_shutdown_current(tmp_path):
    """FACTS 5: IQ 390 uA typ (VIN 5 V, no load, both enables on) and ISD 0.5 uA typ / 5 uA max. +-3 % / +-20 %."""
    d = op(tmp_path, "iq", r33=R_IQ[:2], r205=R_IQ[2:], pullup=False)
    assert -d["i(vin)"] == pytest.approx(390e-6, rel=0.03)
    s = op(tmp_path, "isd", r33=R_IQ[:2], r205=R_IQ[2:], enp=0, enn=0, pullup=False)
    assert 0.5e-6 * 0.8 <= -s["i(vin)"] <= 0.5e-6 * 1.2 and -s["i(vin)"] <= 5e-6


def test_uvlo_thresholds_and_hysteresis(tmp_path):
    """FACTS 4: shutdown when VIN falls to 2.4 V, normal operation resumes above 2.6 V. VIN ramped at 0.2 V/ms with a
    100 ohm load on a 1.8 V OUT+; the rising edge is where OUT+ reaches 0.9 V, the falling edge where it drops below 1.7 V."""
    f = tmp_path / "uv.dat"
    body = board(r33=R18P, r205=R18N, enp=5, enn=5, ilp=0, vin_src="Vin vin 0 pwl(0 0 25m 5 25.1m 5 50m 0)",
                 extra="Rl op 0 100") + f".tran 20u 50m\n.control\nrun\nwrdata {f} v(op) v(vin)\n.endc\n"
    run(tmp_path, "uv", body)
    a = np.loadtxt(f)
    t, vo, vi = a[:, 0], a[:, 1], a[:, 3]
    up = np.argmax((vo > 0.9) & (t < 25.05e-3))
    pk = np.argmax(vo)
    down = pk + np.argmax(vo[pk:] < 1.7)
    assert vi[up] == pytest.approx(2.6, abs=0.05), vi[up]
    assert vi[down] == pytest.approx(2.4, abs=0.06), vi[down]


def test_enable_thresholds_bracket_vil_and_vih(tmp_path):
    """FACTS 5/7: EN low <= 0.4 V is off, EN high >= 1.2 V is on, per rail (VIL max 0.4, VIH min 1.2)."""
    for pin, node in (("Venp", "op"), ("Venn", "on")):
        f = tmp_path / f"en_{pin}.dat"
        body = board(enp=5 if pin == "Venn" else 0, enn=5 if pin == "Venp" else 0) + \
            f".dc {pin} 0 1.5 0.05\n.control\nrun\nwrdata {f} v({node})\n.endc\n"
        run(tmp_path, f"en_{pin}", body)
        a = np.loadtxt(f)
        v = np.interp([0.4, 1.2], a[:, 0], np.abs(a[:, 1]))
        assert v[0] < 0.1 and v[1] > 1.8, (pin, v)


def test_pgood_truth_table(tmp_path):
    """FACTS 7 Table 6-1: PGOOD (open drain, low = good) over the enable states. 'Bad' rails are made unreachable
    with a target the supply cannot reach (VIN 3.3 V: OUT+ target 5 V, OUT- target -4.9 V)."""
    ok = dict(vin=5.0)
    rows = [  # (name, kwargs, PGOOD should be low)
        ("ll", dict(enp=0, enn=0), False),
        ("hl_good", dict(enn=0), True),
        ("lh_good", dict(enp=0), True),
        ("hh_good", dict(), True),
        ("hl_bad", dict(vin=3.3, enn=0, r33=(330e3, 100e3)), False),
        ("lh_bad", dict(vin=3.3, enp=0, r205=(260e3, 100e3)), False),
        ("hh_pbad", dict(vin=3.3, r33=(330e3, 100e3)), False),
        ("hh_nbad", dict(vin=3.3, r205=(260e3, 100e3)), False),
    ]
    for name, kw, low in rows:
        d = op(tmp_path, f"pg_{name}", **{**ok, **kw})
        assert (d["v(pg)"] < 0.5) == low, (name, d)


def test_pgood_threshold_is_95_percent_of_target(tmp_path):
    """FACTS 7: PGOOD asserts when the output exceeds 95 % of target. OUT+ target 3.3 V; VIN swept across it with a 10 mA
    load so the output follows VIN down. +-0.5 % on the 95 % point."""
    f = tmp_path / "pgt.dat"
    body = board(vin=3.0, enn=0, ilp=0.01, vin_src="Vin vin 0 3.0") + \
        f".dc Vin 3.0 3.4 0.005\n.control\nrun\nwrdata {f} v(op) v(pg)\n.endc\n"
    run(tmp_path, "pgt", body)
    a = np.loadtxt(f)
    vo, pg = a[:, 1], a[:, 3]
    k = np.argmax(pg < 2.5)
    assert 3.3 * 0.945 <= vo[k] <= 3.3 * 0.955, vo[k]


def test_shutdown_outputs_are_pulled_to_ground_through_50k(tmp_path):
    """FACTS 4: in shutdown each OUT pin is discharged through 50 kohm to GND. +-5 % on that resistor is the test."""
    for node, sign in (("op", 1), ("on", -1)):
        out = run(tmp_path, f"dis_{node}", board(enp=0, enn=0, pullup=False, r33=R_IQ[:2], r205=R_IQ[2:]) +
                  f"Vt {node} 0 {sign}\n.op\n.control\nrun\nprint i(vt)\n.endc\n")
        r = abs(sign / values(out)["i(vt)"])
        assert 50e3 * 0.95 <= r <= 50e3 * 1.05, (node, r)


# ======================= PSRR (FACTS Fig 7-3 / 7-4) =======================

def test_psrr_at_the_figure_points_that_the_model_reproduces(tmp_path):
    """FACTS Fig 7-4 (OUT+) and 7-3 (OUT-): VIN 3.7 V, 100 mA, 1.8 V outputs. Points checked within +-3 dB (the figures'
    +-2..3 dB); the points the model misses are listed in PROVENANCE.md and not asserted here."""
    f = tmp_path / "psrr.dat"
    body = board(vin=3.7, r33=R18P, r205=R18N, ilp=0.1, iln=0.1, vin_src="Vin vin 0 dc 3.7 ac 1") + \
        f".ac dec 10 10 1meg\n.control\nrun\nwrdata {f} v(op) v(on)\n.endc\n"
    run(tmp_path, "psrr", body)
    a = np.loadtxt(f)
    fr = a[:, 0]

    def db(col, f0):
        k = np.argmin(abs(fr - f0))
        return 20 * math.log10(abs(a[k, col] + 1j * a[k, col + 1]))

    for f0, want in ((3e3, -57), (1e4, -50), (1e5, -26)):      # OUT+, Fig 7-4
        assert db(1, f0) == pytest.approx(want, abs=3), (f0, db(1, f0))
    for f0, want in ((10, -53), (1e3, -50), (1e4, -45), (3e4, -40)):    # OUT-, Fig 7-3 (VIN 3.7 V, 100 mA trace)
        assert db(4, f0) == pytest.approx(want, abs=3), (f0, db(4, f0))


# ======================= the switching variant =======================

def test_switching_pump_at_heavy_load_is_constant_frequency_and_matches_fig_5_4(tmp_path):
    """FACTS 5/Fig 5-4: at 250 mA, VIN 5.5 V the pump runs continuously (constant frequency, FACTS 4) and its
    output resistance is about 2.5 ohm (Fig 5-4 reading accuracy)."""
    t, (cp, pmp, iin) = tran(tmp_path, "swheavy", "700u", ["v(cp)", "v(x1.xp.pmp)", "i(vin)"], variant="SW", vin=5.5,
                             enp=0, icp=0.25 - 0.2e-3)
    m = t > 0.5e-3
    r = (5.5 + cp[m].mean()) / 0.25
    assert 2.5 * 0.75 <= r <= 2.5 * 1.25, r
    assert pmp[m].min() > 0.5                                  # never skips a cycle
    assert -iin[m].mean() == pytest.approx(0.25 + 90e-6, rel=0.03)    # input current = output current (+90 uA bias from VIN)


@pytest.mark.parametrize("fsw", [1.7e6, 2.0e6, 2.3e6])
def test_pump_frequency_at_heavy_load(tmp_path, fsw):
    """FACTS 5: fSW 1.7 / 2.0 / 2.3 MHz (min/typ/max), VIN 3.6 V. The model's FSW parameter, read back from the C1+ node
    at 150 mA (constant-frequency operation); +-2 %."""
    t, (c1p,) = tran(tmp_path, f"swf{int(fsw / 1e5)}", "400u", ["v(c1p)"], variant="SW", vin=3.6, enp=0,
                     r205=(100e3, 247e3), icp=0.15 - 0.2e-3, fsw=fsw)
    m = t > 250e-6
    x, tt = c1p[m] - 1.8, t[m]
    k = np.where((x[:-1] < 0) & (x[1:] >= 0))[0]
    cross = tt[k] + (-x[k]) / (x[k + 1] - x[k]) * (tt[k + 1] - tt[k])
    f = (len(cross) - 1) / (cross[-1] - cross[0])
    assert f == pytest.approx(fsw, rel=0.02), f


def test_light_load_pulse_skipping_and_agreement_with_the_averaged_model(tmp_path):
    """FACTS 4 (6.3.3) and Fig 5-4: at 10 mA the pump switches only in bursts (duty far below 1) and the average CP droop
    is the Fig 5-4 value, agreeing with the averaged variant. How the bursts are spaced is the model's own choice
    (LM27762_PFMVH) and is not tested beyond the duty."""
    t, (cp, pmp) = tran(tmp_path, "swlight", "1.2m", ["v(cp)", "v(x1.xp.pmp)"], variant="SW", vin=5.5, enp=0,
                        icp=0.01 - 0.2e-3)
    m = t > 0.6e-3
    drop = 5.5 + cp[m].mean()
    r = drop / 0.01
    assert in_fig54_envelope(0.01, r), r
    assert pmp[m].mean() < 0.25, pmp[m].mean()
    avg = op(tmp_path, "avglight", vin=5.5, enp=0, icp=0.01 - 0.2e-3)
    assert drop == pytest.approx(5.5 + avg["v(cp)"], rel=0.10)


def test_switching_variant_regulates_both_rails_at_the_board_operating_point(tmp_path):
    """FACTS 6: VIN 5 V, +3.3 V and -2.05 V by the dividers, 100 mA on each rail, after start-up from the soft-started
    references (the transient starts with the pump idle)."""
    t, (op_, on_) = tran(tmp_path, "swboard", "800u", ["v(op)", "v(on)"], variant="SW", vin=5.0, ilp=0.1, iln=0.1)
    m = t > 0.6e-3
    assert op_[m].mean() == pytest.approx(3.3, abs=0.01)
    assert on_[m].mean() == pytest.approx(-2.0498, abs=0.01)


# ======================= known misses: strict xfail, so a miss never passes silently =======================
# Each asserts the FACTS figure. It fails today; if the model is ever fixed the strict xfail turns the run red
# until the marker is removed.

def _psrr_db(tmp_path, name):
    f = tmp_path / f"{name}.dat"
    body = board(vin=3.7, r33=R18P, r205=R18N, ilp=0.1, iln=0.1, vin_src="Vin vin 0 dc 3.7 ac 1") + \
        f".ac dec 10 10 1meg\n.control\nrun\nwrdata {f} v(op) v(on)\n.endc\n"
    run(tmp_path, name, body)
    a = np.loadtxt(f)

    def db(col, f0):
        k = np.argmin(abs(a[:, 0] - f0))
        return 20 * math.log10(abs(a[k, col] + 1j * a[k, col + 1]))
    return db


@pytest.mark.xfail(strict=True, reason="OUT+ PSRR: model -56.4 dB at 10 Hz vs Fig 7-4 -65 (+-3), -56.3 dB at 1 kHz vs -61 (+-2), "
                   "-36.0 dB at 30 kHz vs -40 (+-2); the DC line-regulation path sets the floor")
def test_known_miss_psrr_out_plus(tmp_path):
    db = _psrr_db(tmp_path, "psrrp")
    for f0, want, tol in ((10, -65, 3), (1e3, -61, 2), (3e4, -40, 2)):
        assert db(1, f0) == pytest.approx(want, abs=tol), (f0, db(1, f0))


@pytest.mark.xfail(strict=True, reason="OUT- PSRR: model -51.2 dB at 3 kHz vs Fig 7-3 -47 (+-3), -35.6 dB at 100 kHz vs -46 (+-3); "
                   "the figure's 50-60 kHz peak and dip are not reproduced")
def test_known_miss_psrr_out_minus(tmp_path):
    db = _psrr_db(tmp_path, "psrrn")
    for f0, want in ((3e3, -47), (1e5, -46)):
        assert db(4, f0) == pytest.approx(want, abs=3), (f0, db(4, f0))


@pytest.mark.xfail(strict=True, reason="OUT- ripple at 100 mA, VIN 3.7 V, +-3 V: model 0.03-0.06 mV p-p vs Fig 5-1 0.95 mV (+-0.15); "
                   "about 17x too small, no calibrated CP-to-OUT- path")
def test_known_miss_out_minus_ripple(tmp_path):
    t, (on_,) = tran(tmp_path, "ripn", "450u", ["v(on)"], variant="SW", vin=3.7, r33=(150e3, 100e3),
                     r205=(145.9e3, 100e3), ilp=0.1, iln=0.1)
    pp = np.ptp(on_[t > 350e-6]) * 1e3
    assert pp == pytest.approx(0.95, abs=0.15), pp


@pytest.mark.xfail(strict=True, reason="OUT- load regulation at VIN 4.3 V, -3.3 V: model droops about 80 mV over 0-240 mA "
                   "(-3.301 to -3.221 V) vs Fig 5-7 about 3 mV (+-3); soft dropout knee needs more headroom")
def test_known_miss_out_minus_load_regulation_at_vin_4p3(tmp_path):
    rn = (170.49e3, 100e3)
    z = op(tmp_path, "f57a", vin=4.3, r33=(175e3, 100e3), r205=rn)
    f = op(tmp_path, "f57b", vin=4.3, r33=(175e3, 100e3), r205=rn, iln=0.24)
    assert abs(f["v(on)"] - z["v(on)"]) <= 0.006, f["v(on)"] - z["v(on)"]


@pytest.mark.xfail(strict=True, reason="OUT+ dropout: at VIN = target + 117 mV (Fig 5-3, 250 mA) the model output sags 2.6 % "
                   "(3.214 V of 3.3 V), i.e. the 2 % dropout point is about 0.26 V, not 0.117 V")
def test_known_miss_dropout_at_2_percent_sag(tmp_path):
    d = op(tmp_path, "sag2", vin=3.3 + 0.1175, enn=0, ilp=0.25)
    assert d["v(op)"] >= 0.98 * 3.3, d["v(op)"]


@pytest.mark.xfail(strict=True, reason="unloaded pulse rate: model about 20 kHz (with its 200 uA CP bias) vs FACTS 6.3.3 "
                   "'can drop into the sub-2-kHz range when unloaded'")
def test_known_miss_unloaded_burst_rate(tmp_path):
    t, (pmp,) = tran(tmp_path, "burst", "6m", ["v(x1.xp.pmp)"], variant="SW", vin=5.5, enp=0, timeout=600)
    m = t > 2e-3
    n = np.sum((pmp[m][1:] > 0.5) & (pmp[m][:-1] <= 0.5))
    assert n / (t[-1] - 2e-3) < 2000, n / (t[-1] - 2e-3)


# ======================= break controls =======================

def _mutated(tmp_path, old, new):
    text = LIB.read_text()
    assert old in text, old
    p = tmp_path / "mutant.lib"
    p.write_text(text.replace(old, new))
    return p


def test_break_control_cp_droop_check_fails_on_a_mutated_droop(tmp_path):
    """The Fig 5-4 check must fail when the pulse-skip plateau (0.28 V) is cut to 0.08 V."""
    (tmp_path / "ok").mkdir()
    check_cp_droop(tmp_path / "ok")
    bad = _mutated(tmp_path, "0.28*tanh(i/0.5m)", "0.08*tanh(i/0.5m)")
    (tmp_path / "bad").mkdir()
    with pytest.raises(AssertionError):
        check_cp_droop(tmp_path / "bad", lib=bad)


def test_break_control_load_regulation_check_fails_on_a_mutated_gain(tmp_path):
    """The load-regulation check must fail when the OUT+ pass gain is cut to a fifth."""
    (tmp_path / "ok").mkdir()
    check_load_regulation(tmp_path / "ok")
    bad = _mutated(tmp_path, ".param LM27762_KGP=20 ", ".param LM27762_KGP=4 ")
    (tmp_path / "bad").mkdir()
    with pytest.raises(AssertionError):
        check_load_regulation(tmp_path / "bad", lib=bad)
