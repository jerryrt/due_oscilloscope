import math, os, struct, sys, zlib
import pytest
np = pytest.importorskip('numpy', reason='needs the venv with numpy (.venv-gui); a skip here is NOT a pass')
sys.path.insert(0, os.path.dirname(__file__))
import h7_ets as e


def frame(seq, payload):
    h = struct.pack("<4sBBHIIIII", b"DUE0", 4, 0, 2, seq, 2000000, 0, 0, 0)
    return h + struct.pack("<I", zlib.crc32(h) & 0xFFFFFFFF) + payload


def test_plan_visits_every_bin():
    p = e.plan(40, 500)                                  # 5 MS/s update, 500 points: W = 20000 ticks
    assert p["g"] == 8 and p["p_a"] % 8 == 0 and p["p_a"] >= 100
    k = np.arange(p["bins"] * 2); bins = ((k * p["p_a"]) % p["W"]) // p["g"]
    assert len(set(bins.tolist())) == p["bins"]


def test_a_period_that_shares_a_factor_leaves_bins_empty():
    p = e.plan(40, 500); bad = p["p_a"] + 8 * 5 if math.gcd((p["p_a"] + 40) // 8, p["bins"]) != 1 else p["p_a"] + 16
    while math.gcd(bad // 8, p["bins"]) == 1: bad += 8
    _, counts = e.reconstruct(np.zeros(p["bins"] * 4), bad, p["W"], 8)
    assert (counts == 0).any()


def test_reconstruct_recovers_a_known_waveform():
    p = e.plan(40, 500); W, g = p["W"], p["g"]
    f = lambda t: np.where((t % W) < W // 2, 1.0, -1.0) + 0.3 * np.sin(2 * np.pi * (t % W) / W)   # asymmetric on purpose
    k = np.arange(p["bins"] * 3); v = f(k * p["p_a"] + 12345)                                     # arbitrary constant offset
    wave, counts = e.reconstruct(v, p["p_a"], W, g)
    assert counts.min() >= 1
    truth = f(np.arange(p["bins"]) * g)
    s, aligned = e.align(wave, truth)
    assert np.nanmax(np.abs(aligned - truth)) < 0.35      # bin-width smearing at the edges only, shift found


def test_the_shift_is_recovered_not_assumed():
    p = e.plan(40, 500); k = np.arange(p["bins"] * 2)
    f = lambda t: np.sin(2 * np.pi * (t % p["W"]) / p["W"])
    wave, _ = e.reconstruct(f(k * p["p_a"] + 800), p["p_a"], p["W"], p["g"])
    s, _ = e.align(wave, f(np.arange(p["bins"]) * p["g"]))
    assert s != 0


def test_a_gap_in_the_capture_is_not_bridged():
    pay = bytes(4064)
    data = b"".join(frame(s, pay) for s in (0, 1, 2, 5, 6, 7, 8, 9))        # frames 3 and 4 are missing
    assert len(e.gapless_samples(data)) == 5 * 2032                       # the longer run only


def test_plan_skips_a_period_that_shares_a_factor_with_the_cycle():
    p = e.plan(40, 500, p_a_min=96)          # 96/8 = 12 shares a factor 4 with 2500: it must not be chosen
    assert p["p_a"] != 96 and math.gcd(p["p_a"] // 8, p["bins"]) == 1
