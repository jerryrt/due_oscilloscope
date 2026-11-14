"""The open BAV99 model against the FACTS.md figures it was fitted to (and against the Table 7 limits).
Curve points are asserted within the reading accuracy FACTS.md states for them; the forward rows use exactly the stated accuracy."""
import math
import os
import re

import numpy as np
import pytest

from simtools import netlib_common as C

pytestmark = pytest.mark.ngspice

LIB = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "models-open", "bav99-open", "bav99.lib"))

# FACTS.md Fig. 1: VF (V) at IF (mA) by Tamb (C); accuracy +-5 mV to 30 mA, +-8 mV at 100 and 300 mA
IF_MA = [0.1, 0.3, 1, 3, 10, 30, 100, 300]
VF = {150: [.188, .263, .348, .429, .526, .639, .840, 1.210], 85: [.352, .415, .486, .554, .638, .739, .914, 1.247],
      25: [.497, .550, .611, .671, .743, .827, .984, 1.288], -40: [.654, .698, .745, .790, .847, .920, 1.060, 1.349]}
VF_TOL = [5e-3] * 6 + [8e-3, 8e-3]            # FACTS stated accuracy, no headroom
# FACTS.md Fig. 2: IR (uA) at VR (V); +-3 % (0.012 decade) at interior points, +-0.02 decade at 1 V and 95-99 V
VR = [1, 10, 25, 50, 75, 95, 99]
IR = {150: [9.6, 13.7, 16.5, 19.6, 22.6, 27.5, 29.4], 85: [.32, .48, .59, .72, .85, 1.07, 1.17],
      25: [4.9e-3, 6.9e-3, 8.5e-3, 1.05e-2, 1.32e-2, 1.94e-2, 2.2e-2], -40: [3.4e-5, 3.6e-5, 4.1e-5, 5.0e-5, 5.5e-5, 6.4e-5, 6.4e-5]}
IR_DEC = [0.02, 0.012, 0.012, 0.012, 0.012, 0.02, 0.02]
# FACTS.md Fig. 3: Cd (pF) at VR (V), 25 C, +-0.01 pF
CV = [0, 1, 2, 4, 8, 12, 16]
CD = [.60, .52, .49, .475, .46, .457, .455]


def _model_path(tmp_path, text=None):
    if text is None:
        return LIB
    p = tmp_path / "mut.lib"
    p.write_text(text)
    return str(p)


def _run(tmp_path, name, deck):
    C.run_ng(str(tmp_path), str(tmp_path), "", name, deck, 120)
    return np.atleast_2d(np.loadtxt(tmp_path / f"{name}.dat"))[0]


def _vf(tmp_path, temp, lib=LIB):
    """VF of diode 1 at each Fig. 1 current: A1 driven, CA and K2 grounded."""
    L = [f"vf {temp}", f".include {lib}", f".temp {temp}", "Vz z 0 0"]
    for j, i in enumerate(IF_MA):
        L += [f"I{j} 0 a{j} DC {i * 1e-3}", f"X{j} a{j} 0 0 BAV99_OPEN"]
    vecs = " ".join(f"v(a{j})" for j in range(len(IF_MA)))
    L += [".control", "dc Vz 0 0 1", f"wrdata vf{temp}.dat {vecs}", ".endc", ".end"]
    return _run(tmp_path, f"vf{temp}", "\n".join(L))[1::2]


def _ir(tmp_path, temp):
    """Reverse current of diode 1 in uA at each Fig. 2 voltage: CA (and K2) at +VR, A1 at 0."""
    L = [f"ir {temp}", f".include {LIB}", f".temp {temp}", ".options gmin=1e-15", "Vz z 0 0"]
    for j, v in enumerate(VR):
        L += [f"V{j} c{j} 0 DC {v}", f"X{j} 0 c{j} c{j} BAV99_OPEN"]
    vecs = " ".join(f"i(V{j})" for j in range(len(VR)))
    L += [".control", "dc Vz 0 0 1", f"wrdata ir{temp}.dat {vecs}", ".endc", ".end"]
    return -_run(tmp_path, f"ir{temp}", "\n".join(L))[1::2] * 1e6


def _cd(tmp_path, lib=LIB):
    L = ["cd", f".include {lib}", ".temp 25"]
    for j, v in enumerate(CV):
        L += [f"V{j} c{j} 0 DC {v} AC 1", f"X{j} 0 c{j} c{j} BAV99_OPEN"]
    vecs = " ".join(f"i(V{j})" for j in range(len(CV)))
    L += [".control", "ac lin 1 1meg 1meg", f"wrdata cd.dat {vecs}", ".endc", ".end"]
    row = _run(tmp_path, "cd", "\n".join(L))     # wrdata of complex vectors: per vector (scale, re, im)
    im_ = row[2::3]
    return np.abs(im_) / (2 * math.pi * 1e6) * 1e12


@pytest.mark.parametrize("temp", [150, 85, 25, -40])
def test_forward_curve_at_each_temperature(tmp_path, temp):
    got = _vf(tmp_path, temp)
    for g, want, tol, i in zip(got, VF[temp], VF_TOL, IF_MA):
        assert abs(g - want) <= tol, f"{temp} C, {i} mA: model {g:.4f} V vs curve {want:.3f} V (+-{tol * 1e3:.0f} mV)"


def test_forward_voltage_below_table7_maxima(tmp_path):
    L = ["t7", f".include {LIB}", ".temp 25", "Vz z 0 0"]
    pts = [(1, .715), (10, .855), (50, 1.0), (150, 1.25)]
    for j, (i, _) in enumerate(pts):
        L += [f"I{j} 0 a{j} DC {i * 1e-3}", f"X{j} a{j} 0 0 BAV99_OPEN"]
    L += [".control", "dc Vz 0 0 1", "wrdata t7.dat " + " ".join(f"v(a{j})" for j in range(4)), ".endc", ".end"]
    got = _run(tmp_path, "t7", "\n".join(L))[1::2]
    for g, (i, mx) in zip(got, pts):
        assert g < mx, f"VF at {i} mA = {g:.3f} V, Table 7 maximum {mx} V"
    assert got[1] > 0.6      # and it is a real diode drop, not a short


@pytest.mark.parametrize("temp", [150, 85, 25, -40])
def test_reverse_current_vs_voltage(tmp_path, temp):
    got = _ir(tmp_path, temp)
    for g, want, dec, v in zip(got, IR[temp], IR_DEC, VR):
        assert abs(math.log10(g / want)) <= dec + 1e-9, f"{temp} C, {v} V: {g:.4g} uA vs curve {want:.4g} uA (+-{dec} decade)"


def test_reverse_current_below_table7_maxima(tmp_path):
    assert _ir(tmp_path, 25)[[2]].max() < 0.030 and _ir(tmp_path, 25)[5] < 0.5   # 25 V < 30 nA; 95 V point under the 80 V 0.5 uA max
    hot = _ir(tmp_path, 150)
    assert hot[2] < 30 and hot[4] < 50                                    # 25 V < 30 uA, 75 V < 50 uA at 150 C


def test_capacitance_vs_reverse_voltage(tmp_path):
    got = _cd(tmp_path)
    for g, want, v in zip(got, CD, CV):
        assert abs(g - want) <= 0.01, f"VR {v} V: Cd {g:.4f} pF vs {want} pF"
    assert got[0] < 1.5


def test_two_diodes_in_series_between_a1_and_k2(tmp_path):
    L = ["ser", f".include {LIB}", ".temp 25", "Vz z 0 0", "I1 0 a DC 10m", "X1 a 0 c BAV99_OPEN",
         ".control", "dc Vz 0 0 1", "wrdata ser.dat v(a) v(c)", ".endc", ".end"]
    a, c = _run(tmp_path, "ser", "\n".join(L))[[1, 3]]
    assert abs(a - 2 * VF[25][4]) < 0.015 and abs(c - VF[25][4]) < 0.01      # the midpoint sits at one drop


def test_recovery_time_is_the_table7_maximum(tmp_path):
    L = ["trr", f".include {LIB}", ".options gmin=1e-15", ".temp 25", "Vs s 0 PULSE(1.75 -1.0 20n 0.6n 0.6n 100n 400n)",
         "Rs s a 50", "X1 a b b BAV99_OPEN", "Rl b 0 50", ".tran 0.02n 80n 0 0.02n",
         ".control", "run", "wrdata trr.dat i(Vs)", ".endc", ".end"]
    C.run_ng(str(tmp_path), str(tmp_path), "", "trr", "\n".join(L), 120)
    a = np.loadtxt(tmp_path / "trr.dat"); t, i = a[:, 0], -a[:, 1]
    k0 = int(np.argmax(t > 20.3e-9)); kz = k0 + int(np.argmax(i[k0:] < 0))
    tz = t[kz - 1] + (t[kz] - t[kz - 1]) * i[kz - 1] / (i[kz - 1] - i[kz])
    ipk = kz + int(np.argmin(i[kz:])); kr = ipk + int(np.argmax(i[ipk:] > -1e-3))
    tr = t[kr - 1] + (t[kr] - t[kr - 1]) * (-1e-3 - i[kr - 1]) / (i[kr] - i[kr - 1])
    assert 3.6e-9 <= tr - tz <= 4.1e-9, f"trr {(tr - tz) * 1e9:.2f} ns (Table 7 max 4 ns, TT is set to hit it)"
    assert i[ipk] < -8e-3        # the reverse current does reach the 10 mA of the test conditions


def test_break_control_a_mutated_ideality_fails_the_forward_check(tmp_path):
    """The forward test must be able to fail: N 1.93 -> 1.5 moves VF at 10 mA by far more than 5 mV."""
    text = open(LIB).read()
    mut = re.sub(r"(\bN=)[0-9.e+-]+", r"\g<1>1.5", text, count=1)
    assert mut != text
    p = _model_path(tmp_path, mut)
    got = _vf(tmp_path, 25, lib=p)
    assert abs(got[4] - VF[25][4]) > 5e-3
    assert abs(_vf(tmp_path, 25)[4] - VF[25][4]) <= 5e-3      # and the unmutated one still passes


def test_break_control_a_mutated_parallel_capacitance_fails_the_capacitance_check(tmp_path):
    text = open(LIB).read()
    mut = re.sub(r"(\nCP a k )[0-9.e+-]+p", r"\g<1>0.9p", text, count=1)
    assert mut != text
    got = _cd(tmp_path, lib=_model_path(tmp_path, mut))
    assert abs(got[0] - CD[0]) > 0.01
    assert abs(_cd(tmp_path)[0] - CD[0]) <= 0.01
