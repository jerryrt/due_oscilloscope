"""Checks of models-open/tph2502-open/tph2502.lib against the figures in its FACTS.md.

Every tolerance below is either the reading accuracy FACTS.md states for a curve point, or (for a
table row, which carries none) a band stated in the test and chosen no wider than the row's own
min/max where it has one. Rows the model cannot meet are not tested here; PROVENANCE.md lists them.
Board-less, one ngspice run per case. Marker: ngspice.
"""
import math
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simtools import netlib_common as nc  # noqa: E402

pytestmark = pytest.mark.ngspice

TOL_TYP = 0.10    # chosen here, not a FACTS accuracy: the tolerance for table rows that give a typ value and no accuracy

LIB = Path(__file__).resolve().parents[2] / "models-open" / "tph2502-open" / "tph2502.lib"
SUPPLY = "Vp vp 0 5\nVn vn 0 0\n"
_KV = re.compile(r"^([A-Za-z_][\w.\[\]()#]*)\s*=\s*(-?[0-9.]+(?:[eE][-+]?\d+)?)", re.M)


def ng(tmp_path, name, body, lib=LIB):
    text = f"* {name}\n.include {lib}\n{body}\n.end\n"
    out = nc.run_ng(str(tmp_path / "net"), str(tmp_path / "work"), "t_", name, text, 240, mem="1G")
    res = {k.lower(): float(v) for k, v in _KV.findall(out)}
    assert "no such" not in out.lower() and "fatal" not in out.lower(), out[-1500:]
    return res, out


def x(extra="", pins="inp inn vp vn out"):
    return f"X1 {pins} TPH2502_OPEN {extra}\n"


# ---------------------------------------------------------------- DC follower accuracy
def follower_err(tmp_path, vin, extra="", load="Rl out 0 100k"):
    body = SUPPLY + f"Vin inp 0 {vin}\n" + x(extra, "inp out vp vn out") + load + "\n.control\nop\nlet e=v(out)-v(inp)\nprint e\n.endc"
    r, _ = ng(tmp_path, f"fol_{vin}_{abs(hash(extra)) % 997}", body)
    return r["e"]


@pytest.mark.parametrize("vin", [0.5, 1.5, 2.5, 3.5, 4.5])
def test_dc_follower_accuracy(tmp_path, vin):
    # FACTS s3 VOS max +/-500 uV; default VOS is 0, so the error is the finite-gain error only (~vin/A0)
    assert abs(follower_err(tmp_path, vin)) < 50e-6


def test_offset_parameter_passes_through(tmp_path):
    e = follower_err(tmp_path, 2.5, "VOS=500u")
    assert 480e-6 < abs(e) < 520e-6            # VOS is the knob, +/-500 uV is FACTS s3's max


# ---------------------------------------------------------------- open loop gain and shape
def open_loop(tmp_path, name, extra="", f0=1.0, f1=2e9, pts=20):
    body = (SUPPLY + "Vin inp 0 dc 2.5 ac 1\n" + x(extra, "inp inn vp vn out") +
            "Lfb out inn 1e12\nCg inn 0 1\nRl out 0 1k\n"
            f".control\nac dec {pts} {f0} {f1}\nlet g=db(v(out))\nlet fr=frequency\nprint g[0]\n"
            "meas ac fu when g=0 cross=last\n"
            "meas ac g100 find g at=100\nmeas ac g1k find g at=1k\nmeas ac g1meg find g at=1meg\n"
            "meas ac g10meg find g at=10meg\nmeas ac g100meg find g at=100meg\n.endc")
    return ng(tmp_path, name, body)[0]


def test_open_loop_gain_and_bode(tmp_path):
    r = open_loop(tmp_path, "olg")
    # FACTS s4: AVOL table typ 110 dB (min 85); the 143 dB of the curves is not used (inconsistency 5)
    assert 109 < r["g[0]"] < 111
    # FACTS s5 Bode points, reading accuracy +/-10 dB; 10 Hz (138 dB) is the known miss and is not asserted
    for key, want in [("g100", 118), ("g1k", 98), ("g1meg", 40), ("g10meg", 20), ("g100meg", 5)]:
        assert abs(r[key] - want) <= 10, (key, r[key], want)
    # gain curve reaches 0 dB near 300 MHz, +/- a factor 2 (FACTS s5)
    assert 150e6 <= r["fu"] <= 600e6


# ---------------------------------------------------------------- closed loop bandwidths
def stage_bw(tmp_path, name, gain, extra=""):
    if gain == 1:
        fb = "Rf out inn 25\n"        # RF = 25 ohm at G=+1 (FACTS s5)
        pins = "inp inn vp vn out"
        net = fb
    else:
        net = f"Rf out inn 620\nRg inn 0 {620 / (gain - 1)}\n"     # RF = 620 ohm for G >= 2 (FACTS s5 curve labels)
        pins = "inp inn vp vn out"
    body = (SUPPLY + f"Vin inp 0 dc {2.5/gain} ac 1\n" + x(extra, pins) + net + "Rl out 0 1k\n"
            ".control\nac dec 40 1e5 2e9\nlet m=db(v(out)/v(inp))\nlet m0=m[0]\n"
            "let tgt=m0-3\nmeas ac f3 when m=tgt cross=1\nprint m0\n.endc")
    return ng(tmp_path, name, body)[0]


def test_bandwidth_g1(tmp_path):
    r = stage_bw(tmp_path, "bw1", 1)           # 250 MHz, G=+1 (FACTS s5, typ only): +/-10 % chosen here (TOL_TYP)
    assert abs(r["f3"] / 250e6 - 1) < TOL_TYP


def test_bandwidth_g2(tmp_path):
    r = stage_bw(tmp_path, "bw2", 2)           # 90 MHz, G=+2
    assert abs(r["f3"] / 90e6 - 1) < TOL_TYP


def test_gbw_gain_of_10(tmp_path):
    r = stage_bw(tmp_path, "bw10", 10)         # GBW 120 MHz at G=+10, so about 12 MHz
    assert abs(r["m0"] - 20) < 0.01
    gbw = r["f3"] * 10
    assert abs(gbw / 120e6 - 1) < TOL_TYP, gbw


def test_gbw_break_control(tmp_path):
    r = stage_bw(tmp_path, "bw10b", 10, "GBW=60meg")
    gbw = r["f3"] * 10
    assert not abs(gbw / 120e6 - 1) < TOL_TYP  # the halved GBW must fail the test above


# ---------------------------------------------------------------- slew rate
def slew(tmp_path, name, lo, hi, extra=""):
    t20, t80 = lo + 0.2 * (hi - lo), lo + 0.8 * (hi - lo)
    body = (SUPPLY + f"Vin inp 0 pulse({lo} {hi} 20n 0.2n 0.2n 200n 400n)\n" + x(extra, "inp out vp vn out") +
            "Rl out 0 1k\n.control\ntran 0.05n 120n\n"
            f"meas tran trr trig v(out) val={t20} rise=1 targ v(out) val={t80} rise=1\n.endc")
    r = ng(tmp_path, name, body)[0]
    return (t80 - t20) / r["trr"] / 1e6        # V/us


def test_slew_4v_step(tmp_path):
    assert abs(slew(tmp_path, "sr4", 0.5, 4.5) / 200 - 1) < TOL_TYP   # 200 V/us, 4 V step (FACTS s6, typ only)


@pytest.mark.xfail(strict=True, reason="known miss: 2 V step reads ~223 V/us (20-80 %) against the 180 V/us row (+24 %); the model slews at one value (PROVENANCE.md)")
def test_slew_2v_step_known_miss(tmp_path):
    assert abs(slew(tmp_path, "sr2", 1.5, 3.5) / 180 - 1) < TOL_TYP


def rise_10_90(tmp_path, name, lo, hi):
    t10, t90 = lo + 0.1 * (hi - lo), lo + 0.9 * (hi - lo)
    body = (SUPPLY + f"Vin inp 0 pulse({lo} {hi} 20n 0.05n 0.05n 200n 400n)\n" + x("", "inp out vp vn out") +
            "Rl out 0 1k\n.control\ntran 0.01n 60n\n"
            f"meas tran trr trig v(out) val={t10} rise=1 targ v(out) val={t90} rise=1\n.endc")
    return ng(tmp_path, name, body)[0]["trr"]


def test_rise_time_2vpp(tmp_path):
    assert abs(rise_10_90(tmp_path, "tr2", 1.5, 3.5) / 7e-9 - 1) < 0.35    # 7 ns, 2 Vpp (FACTS s6); band chosen here


@pytest.mark.xfail(strict=True, reason="known miss: the model's 10-90 % rise for a 200 mV step is ~0.85 ns against the 2 ns row (-57 %) (PROVENANCE.md)")
def test_rise_time_200mvpp_known_miss(tmp_path):
    assert abs(rise_10_90(tmp_path, "tr02", 2.4, 2.6) / 2e-9 - 1) < 0.35   # 2 ns, 200 mVpp


def test_slew_break_control(tmp_path):
    assert not abs(slew(tmp_path, "sr4b", 0.5, 4.5, "SR=100meg") / 200 - 1) < TOL_TYP


# ---------------------------------------------------------------- output swing, currents
def comparator(tmp_path, name, ihi, extra="", supplies=SUPPLY, load="Rl out 2.5 100k", vp=5.0, vn=0.0):
    pos, neg = (3.0, 2.0) if ihi else (2.0, 3.0)
    body = (supplies + f"Vi1 inp 0 {pos}\nVi2 inn 0 {neg}\n" + x(extra) + load +
            "\n.control\nop\nprint v(out)\n.endc")
    return ng(tmp_path, name, body)[0]["v(out)"]


def test_swing_100k_high(tmp_path):
    d = 5.0 - comparator(tmp_path, "swh", True)       # FACTS s9: 2 mV typ, 30 mV max from the rail, 100 kohm
    assert 1e-3 <= d <= 3.5e-3


def test_swing_100k_low(tmp_path):
    d = comparator(tmp_path, "swl", False)
    assert 1e-3 <= d <= 3.5e-3


def test_swing_headroom_grows_with_load_labelled_choice(tmp_path):
    # MODELLING CHOICE, not a datasheet figure: RSAT = 11.5 ohm per rail; 17.5 mA costs ~0.2 V (bench must measure it)
    d = 5.0 - comparator(tmp_path, "swh17", True, load="Rl out 0 {2.7/17.5m}")
    # the load pulls 17.5 mA only if out = 2.7 V; accept the self-consistent point: I = Vout / R, Vout = 5 - 0.002 - 11.5 I
    r_load = 2.7 / 17.5e-3
    vout = (5 - 0.002) / (1 + 11.5 / r_load)
    assert abs((5.0 - d) - vout) < 5e-3


def test_short_circuit_source_and_sink(tmp_path):
    body = SUPPLY + "Vi1 inp 0 3\nVi2 inn 0 1\n" + x() + "Vsh out 0 0\n.control\nop\nprint i(vsh)\n.endc"
    isrc = ng(tmp_path, "scs", body)[0]["i(vsh)"]
    body = SUPPLY + "Vi1 inp 0 1\nVi2 inn 0 3\n" + x() + "Vsh out vp 0\n.control\nop\nprint i(vsh)\n.endc"
    isnk = abs(ng(tmp_path, "scn", body)[0]["i(vsh)"])
    # FACTS s9 typ: source 290 mA, sink 160 mA (min 100 each); band chosen here: +/-5 %
    assert abs(isrc / 0.290 - 1) < 0.05, isrc
    assert abs(isnk / 0.160 - 1) < 0.05, isnk


# ---------------------------------------------------------------- supply current
def test_supply_current(tmp_path):
    body = ("Vp vp 0 2.5\nVn vn 0 -2.5\nVin inp 0 0\n" + x(pins="inp out vp vn out") + "Rl out 0 100k\n"
            ".control\nop\nprint i(vp) i(vn)\n.endc")
    r = ng(tmp_path, "iq", body)[0]
    # FACTS s2: 6.5 mA typ per amplifier (max 7.5); the IQ-vs-T curve reads +/-0.3 mA
    assert abs(-r["i(vp)"] - 6.5e-3) < 0.3e-3
    assert abs(r["i(vn)"] - 6.5e-3) < 0.3e-3


def test_supply_current_includes_load(tmp_path):
    body = (SUPPLY + "Vin inp 0 2.5\n" + x(pins="inp out vp vn out") + "Rl out 0 250\n"
            ".control\nop\nprint i(vp)\n.endc")           # 10 mA sourced
    r = ng(tmp_path, "iql", body)[0]
    assert abs(-r["i(vp)"] - (6.5e-3 + 10e-3)) < 0.3e-3


# ---------------------------------------------------------------- input network
def input_c(tmp_path, name, drive_both):
    # open-loop, output unconnected to the inputs: the input pins see only the input network
    if drive_both:
        body = SUPPLY + "Vin inp 0 dc 2.5 ac 1\nVi2 inn inp 0\n" + x() + "Rl out 0 1k\n"
        body = SUPPLY + "Vin inp 0 dc 2.5 ac 1\nEi inn 0 inp 0 1\n" + x() + "Rl out 0 1k\n"
    else:
        body = SUPPLY + "Vin inp 0 dc 2.5 ac 1\nVi2 inn 0 2.5\n" + x() + "Rl out 0 1k\n"
    body += ".control\nac lin 1 1meg 1meg\nlet c=im(-i(vin))/(2*3.14159265*1meg)\nprint c\n.endc"
    return ng(tmp_path, name, body)[0]["c"]


def test_input_capacitances(tmp_path):
    c_one = input_c(tmp_path, "cin1", False)      # INP to ground, INN fixed: CDIFF + CCM = 3.7 pF
    assert abs(c_one / 3.7e-12 - 1) < 0.02
    body = (SUPPLY + "Vin inp 0 dc 2.5 ac 1\nEi inn 0 inp 0 1\n" + x() + "Rl out 0 1k\n"
            ".control\nac lin 1 1meg 1meg\nlet c=im(-i(vin))/(2*3.14159265*1meg)\nprint c\n.endc")
    c_cm = ng(tmp_path, "cincm", body)[0]["c"]      # both inputs together: CCM only, 1 pF (FACTS s8)
    assert abs(c_cm / 1.0e-12 - 1) < 0.02


def test_input_bias_current(tmp_path):
    # FACTS s3: 0.3 pA typ at 27 C. ngspice's default abstol (1 pA) is above it, so the deck tightens it.
    # read as the drop across a 1 Gohm in series with the pin: far above the solver's current resolution
    body = (SUPPLY + "Vin ina 0 2.5\nRs ina inp 1e9\nVi2 inn 0 2.5\n" + x() + "Rl out 0 100k\n.options gmin=1e-18\n"
            ".control\nop\nlet ib=(v(ina)-v(inp))/1e9\nprint ib\n.endc")
    ib = ng(tmp_path, "ib", body)[0]["ib"]
    assert 0.2e-12 < abs(ib) < 0.4e-12


def test_input_common_mode_clamp(tmp_path):
    # MODELLING CHOICE (FACTS s3 printed range V- -0.1 .. V+ -0.1): the follower stops following past V+ - 0.1
    def out_at(v):
        body = SUPPLY + f"Vin inp 0 {v}\n" + x(pins="inp out vp vn out") + "Rl out 0 100k\n.control\nop\nprint v(out)\n.endc"
        return ng(tmp_path, f"cm{v}", body)[0]["v(out)"]
    assert abs(out_at(4.0) - 4.0) < 1e-3
    a, b = out_at(5.0), out_at(5.3)           # both inputs past the range: the input stage is dead, the output holds near V+ - 0.1
    assert 4.89 < a < 4.92 and 4.89 < b < 4.92


# ---------------------------------------------------------------- output impedance
def zout(tmp_path, name, loop_closed, freq):
    if loop_closed:
        net = "Vin inp 0 2.5\n" + x(pins="inp out vp vn out")
    else:
        net = "Vin inp 0 2.5\n" + x(pins="inp inn vp vn out") + "Lfb out inn 1e12\nCg inn 0 1\n"
    body = SUPPLY + net + f"Iac 0 out dc 0 ac 1\n.control\nac lin 1 {freq} {freq}\nlet z=mag(v(out))\nprint z\n.endc"
    return ng(tmp_path, name, body)[0]["z"]


def test_output_impedance_open_loop(tmp_path):
    assert abs(zout(tmp_path, "zol", False, 1e3) / 21 - 1) < 0.05            # FACTS s9: 21 ohm at 1 kHz


def test_output_impedance_closed_loop(tmp_path):
    assert zout(tmp_path, "zcl1k", True, 1e3) < 0.01                          # 0.01 ohm at 1 kHz (FACTS s9)
    for f, want in [(1e5, 0.02), (1e6, 0.15), (1e7, 1.5)]:                    # curve, accuracy a factor 1.5 (FACTS s9)
        z = zout(tmp_path, f"zcl{int(f)}", True, f)
        assert want / 1.5 <= z <= want * 1.5, (f, z)


@pytest.mark.xfail(strict=True, reason="known miss: closed-loop Zout at 100 MHz reads ~7.7 ohm against 25 ohm in the curve (factor 1.5 band: 16.7-37.5); PROVENANCE.md")
def test_output_impedance_100mhz_known_miss(tmp_path):
    z = zout(tmp_path, "zcl100M", True, 1e8)
    assert 25 / 1.5 <= z <= 25 * 1.5


# ---------------------------------------------------------------- noise
def noise_dens(tmp_path, name, extra):
    body = (SUPPLY + "Vin inp 0 dc 2.5 ac 1\n" + x(extra, "inp out vp vn out") + "Rl out 0 100k\n"
            ".control\nnoise v(out) Vin lin 1 1meg 1meg 1\nsetplot noise1\nprint onoise_spectrum\n.endc")
    return ng(tmp_path, name, body)[0]["onoise_spectrum"]


def test_noise_off_by_default(tmp_path):
    assert noise_dens(tmp_path, "noff", "") < 1e-9


def test_noise_parameter(tmp_path):
    n = noise_dens(tmp_path, "non", "EN=6.5n")           # FACTS s7: 6.5 nV/rtHz at 1 MHz
    assert abs(n / 6.5e-9 - 1) < 0.15


# ---------------------------------------------------------------- the break control for the file as a whole
def test_mutated_library_fails_swing_check(tmp_path):
    mut = tmp_path / "mut.lib"
    mut.write_text(LIB.read_text().replace("VSAT0=2m", "VSAT0=200m"))
    body = (SUPPLY + "Vi1 inp 0 3\nVi2 inn 0 2\n" + x() + "Rl out 2.5 100k\n.control\nop\nprint v(out)\n.endc")
    d = 5.0 - ng(tmp_path, "mutsw", body, lib=mut)[0]["v(out)"]
    assert not (1e-3 <= d <= 3.5e-3)


# ---------------------------------------------------------------- supply rejection (PSRR)
# FACTS s4: PSRR min 80 dB (typ 120), VS = 2.4..5.5 V, VCM = VS/2, 25 C; no PSRR-vs-frequency data, so the
# frequency rule min(PSRR_DB, AOL(f)) is a MODELLING CHOICE (PROVENANCE.md). Test conditions: VS = 5 V, VCM = 2.5 V, G = +1.
def psrr_db(tmp_path, name, pin, f, extra="", lib=LIB):
    vp = "Vp vp 0 dc 5" + (" ac 1" if pin == "vp" else "") + "\n"
    vn = "Vn vn 0 dc 0" + (" ac 1" if pin == "vn" else "") + "\n"
    body = (vp + vn + "Vin inp 0 2.5\n" + x(extra, "inp out vp vn out") + "Rl out 0 1k\n"
            f".control\nac lin 1 {f} {f}\nlet p=-db(v(out))\nprint p\n.endc")
    return ng(tmp_path, name, body, lib=lib)[0]["p"]


@pytest.mark.parametrize("pin", ["vp", "vn"])
def test_psrr_dc_default_min(tmp_path, pin):
    # 100 Hz is far below the ~12.8 kHz corner; the 1/AOL term costs ~0.3 dB at 80 dB
    assert abs(psrr_db(tmp_path, f"ps80{pin}", pin, 100) - 80) < 1.0


@pytest.mark.parametrize("pin", ["vp", "vn"])
def test_psrr_parameter_selects_value(tmp_path, pin):
    assert abs(psrr_db(tmp_path, f"ps60{pin}", pin, 100, "PSRR_DB=60") - 60) < 1.0


def test_psrr_typ_is_capped_by_own_aol(tmp_path):
    # PSRR_DB=120 exceeds the model's AOL (110 dB, FACTS table), so the rule min(PSRR, AOL) holds it at or below ~110 dB
    p = psrr_db(tmp_path, "ps120", "vp", 100, "PSRR_DB=120")
    assert 105 < p < 111       # reads 107.3 at 100 Hz: the sum of 1/120 dB and the 1/AOL term


def test_psrr_no_better_than_aol_above_corner(tmp_path):
    for f in (1e6, 1e7):
        aol = open_loop_gain_at(tmp_path, f)
        for pin in ("vp", "vn"):
            p = psrr_db(tmp_path, f"psh{pin}{int(f)}", pin, f)
            assert p <= aol + 0.5, (pin, f, p, aol)       # rejection (dB) not above AOL(dB); 0.5 dB is the model's own zero/pole shape
            assert p >= aol - 6.0                            # and not wildly below it (sum of the two terms)


def open_loop_gain_at(tmp_path, f):
    # open-loop gain of the model at f, in dB
    body = (SUPPLY + "Vin inp 0 dc 2.5 ac 1\n" + x("", "inp inn vp vn out") +
            f"Lfb out inn 1e12\nCg inn 0 1\nRl out 0 1k\n.control\nac lin 1 {f} {f}\nlet g=db(v(out))\nprint g\n.endc")
    return ng(tmp_path, f"aol{int(f)}", body)[0]["g"]


def test_psrr_break_controls(tmp_path):
    # PSRR term removed: rejection reads far above 80 dB at 100 Hz, so the DC check must fail
    mut = tmp_path / "nopsrr.lib"
    mut.write_text(LIB.read_text().replace("V(sv)*(1/psrr_lin+1/a0) + I(Vsd)*kdd", "0"))
    assert not abs(psrr_db(tmp_path, "mut1", "vp", 100, lib=mut) - 80) < 1.0
    # frequency term removed (rejection stays flat at 80 dB): the high-frequency rejection no longer follows AOL, so the above-corner check must fail
    mut2 = tmp_path / "noHF.lib"
    mut2.write_text(LIB.read_text().replace(" + I(Vsd)*kdd", ""))
    p = psrr_db(tmp_path, "mut2", "vp", 1e7, lib=mut2)
    aol = open_loop_gain_at(tmp_path, 1e7)
    assert not (aol - 6.0 <= p <= aol + 0.5)
