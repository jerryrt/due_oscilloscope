"""ads1115-open: input-load model and ideal code helper, against FACTS.md (sections cited per table)."""
import re
import sys
from pathlib import Path

import pytest

PART = Path(__file__).resolve().parents[2] / "models-open" / "ads1115-open"
sys.path.insert(0, str(PART))
import ads1115_open as adc  # noqa: E402
from simtools.netlib_common import run_ng  # noqa: E402

pytestmark = pytest.mark.ngspice

# FACTS sec 3 (p5), typical values. FSR -> (ZCM, ZDIFF) in ohm
Z = {6.144: (10e6, 22e6), 4.096: (6e6, 15e6), 2.048: (6e6, 4.9e6),
     1.024: (3e6, 2.4e6), 0.512: (100e6, 0.71e6), 0.256: (100e6, 0.71e6)}
# FACTS sec 2 Table 8-3: MUXSEL -> (P index, N index or None for GND)
MUX = {0: (0, 1), 1: (0, 3), 2: (1, 3), 3: (2, 3), 4: (0, None), 5: (1, None), 6: (2, None), 7: (3, None)}
VDD = 3.3
REL = 0.01      # FACTS gives typ values only; the model is built from them, so 1% = numerical agreement


def run(tmp_path, name, drives, fsr, mux, lib=None, extra=""):
    """drives: {pin: volts} -> {pin: current into the pin (A)}, one .op."""
    lib = lib or PART / "ads1115.lib"
    nl = [f"* {name}", f".include {lib}", f"Vdd vdd 0 {VDD}",
          f"X1 a0 a1 a2 a3 0 vdd ADS1115_IN_OPEN FSR={fsr} MUXSEL={mux} {extra}"]
    for p, v in drives.items():
        nl.append(f"Vp{p} a{p} 0 {v}")
    nl += [".control", "op"] + [f"print i(vp{p})" for p in drives] + [".endc", ".end"]
    out = run_ng(str(tmp_path), str(tmp_path / "w"), "t_", name, "\n".join(nl), 120)
    res = {}
    for p in drives:
        m = re.search(rf"i\(vp{p}\)\s*=\s*(\S+)", out)
        assert m, out[-600:]
        res[p] = -float(m.group(1))   # source current is into the + node of the source; flip to into-pin
    return res


def z_cm(tmp_path, fsr, mux, lib=None):
    """Datasheet method: short P and N (or drive P alone), average current per pin, two voltages."""
    p, n = MUX[mux]
    pins = [p] + ([n] if n is not None else [])
    a = run(tmp_path, f"cm1_{fsr}_{mux}", {k: 1.0 for k in pins}, fsr, mux, lib)
    b = run(tmp_path, f"cm2_{fsr}_{mux}", {k: 2.0 for k in pins}, fsr, mux, lib)
    return 1.0 / (b[p] - a[p])


def z_diff(tmp_path, fsr, mux, lib=None):
    """Datasheet method (p14): N held at 0.7 V, P stepped, current through the N pin."""
    p, n = MUX[mux]
    a = run(tmp_path, f"d1_{fsr}_{mux}", {p: 0.7, n: 0.7}, fsr, mux, lib)
    b = run(tmp_path, f"d2_{fsr}_{mux}", {p: 1.7, n: 0.7}, fsr, mux, lib)
    return 1.0 / abs(b[n] - a[n])


@pytest.mark.parametrize("fsr", sorted(Z))
@pytest.mark.parametrize("mux", [0, 1, 2, 3])
def test_pair_impedances(tmp_path, fsr, mux):
    zcm, zd = Z[fsr]
    assert z_cm(tmp_path, fsr, mux) == pytest.approx(zcm, rel=REL)
    assert z_diff(tmp_path, fsr, mux) == pytest.approx(zd, rel=REL)


@pytest.mark.parametrize("fsr", sorted(Z))
@pytest.mark.parametrize("mux", [4, 5, 6, 7])
def test_single_ended_is_zcm_parallel_zdiff(tmp_path, fsr, mux):
    # derived from Fig 7-5: ZCM to the 0.7 V node and ZDIFF to the grounded N input, in parallel
    zcm, zd = Z[fsr]
    assert z_cm(tmp_path, fsr, mux) == pytest.approx(zcm * zd / (zcm + zd), rel=REL)


def test_common_mode_bias_goes_to_07v(tmp_path):
    # FACTS sec 3 Fig 7-5: ZCM returns to 0.7 V, so a pin AT 0.7 V draws no current (leakage-free pair)
    i = run(tmp_path, "bias", {0: 0.7, 1: 0.7}, 2.048, 0)
    assert abs(i[0]) < 1e-9 and abs(i[1]) < 1e-9


@pytest.mark.parametrize("mux", sorted(MUX))
def test_unselected_pins_show_only_leakage(tmp_path, mux):
    p, n = MUX[mux]
    free = [k for k in range(4) if k not in (p, n)]
    i = run(tmp_path, f"lk{mux}", {k: 1.0 for k in free}, 2.048, mux)
    for k in free:
        assert i[k] == pytest.approx(100e-9, rel=0.01)   # ILEAK default, a MODELLING CHOICE


def test_leakage_parameter_is_live(tmp_path):
    i = run(tmp_path, "lk_param", {3: 1.0}, 2.048, 0, extra="ILEAK=1u")
    assert i[3] == pytest.approx(1e-6, rel=0.01)


def test_clamps_off_inside_03v_and_on_beyond(tmp_path):
    # FACTS sec 1: diodes must stay off within 0.3 V of the rails; on beyond (clamp current is a modelling choice)
    for v in (VDD + 0.3, -0.3):
        i = run(tmp_path, f"clamp_in_{v}", {3: v}, 2.048, 0)[3]
        assert abs(i - 100e-9 * (1 if v > 0 else -1)) < 20e-9, i
    hi = run(tmp_path, "clamp_hi", {3: VDD + 1.0}, 2.048, 0)[3]
    lo = run(tmp_path, "clamp_lo", {3: -1.0}, 2.048, 0)[3]
    assert hi > 1e-3 and lo < -1e-3


# ---- ideal code helper (FACTS sec 6) ----
LSB = {6.144: 187.5e-6, 4.096: 125e-6, 2.048: 62.5e-6, 1.024: 31.25e-6, 0.512: 15.625e-6, 0.256: 7.8125e-6}


@pytest.mark.parametrize("fsr", sorted(LSB))
def test_code_lsb_and_limits(fsr):
    assert adc.lsb(fsr) == pytest.approx(LSB[fsr], rel=1e-12)
    assert adc.code(LSB[fsr], fsr) == 1
    assert adc.code(-LSB[fsr], fsr) == -1
    assert adc.code(0.0, fsr) == 0
    assert adc.code(fsr, fsr) == 32767          # +FS saturates at the top code
    assert adc.code(-fsr, fsr) == -32768
    assert adc.code(10 * fsr, fsr) == 32767 and adc.code(-10 * fsr, fsr) == -32768
    assert adc.code(32767 * LSB[fsr], fsr) == 32767


def test_code_vdd_and_single_ended():
    assert adc.code(4.096, 4.096, vdd=3.3) == round(3.3 / 125e-6)   # FACTS p15: full scale unreachable
    assert adc.code(-0.1, 2.048, single_ended=True) == 0
    with pytest.raises(ValueError):
        adc.lsb(3.0)


# ---- break controls (rule 5): each check must fail on a mutated target ----
def test_break_control_mutated_model_fails_impedance_check(tmp_path):
    src = (PART / "ads1115.lib").read_text()
    bad = src.replace("((FSR>1.5)?6e6:", "((FSR>1.5)?3e6:")
    assert bad != src
    lib = tmp_path / "mut.lib"
    lib.write_text(bad)
    z = z_cm(tmp_path, 2.048, 0, lib=lib)
    assert z != pytest.approx(Z[2.048][0], rel=REL)      # the check the real model passes must trip here


def test_break_control_wrong_fsr_changes_code():
    assert adc.code(1.0, 1.024) != adc.code(1.0, 2.048)
    assert adc.code(1.0, 2.048) == round(1.0 / 62.5e-6)
