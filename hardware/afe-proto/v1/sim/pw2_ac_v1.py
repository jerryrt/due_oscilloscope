"""v1's LM27762 capacitor-distance ripple (the LR-5 deviation evidence), by v2's AC (line-spectrum) analysis.

A thin driver: v2's `pw2_ac` module is imported and its geometry tables (distances, pin-link widths, via counts) are replaced
by v1's; no line of v2's code is copied and nothing in v2/ is edited. v1's capacitors are mapped onto the module's slots
(the module names v2's own parts), see SLOT. See pw2_ac_README.md.

    docker/pcb/run.sh -m 3G -c 2 -t 300 bash -c 'cd /work/hardware/afe-proto && python3 -I v1/sim/pw2_ac_v1.py'
"""
import contextlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AFE = HERE.parents[1]
V2DIR = AFE / "v2" / "sim" / "powercal" / "pw2_ac"
OUT = AFE / "v1" / "results" / "pw2_ac_v1.json"

# v1 capacitor -> the module's slot (the module's names are v2's: vin=C401/C402, cpout=C403/C404, outp=C405/C406, outn=C407/C408,
# flying C409). The first (nearer) capacitor of each rail takes the first slot.
SLOT = {"C403": "C401", "C404": "C402",          # VIN 10u (v1 C403 pin 3/8/12 side, 2.8 mm; C404, 5.1 mm)
        "C405": "C403", "C406": "C404",          # CPOUT (pin 5)
        "C407": "C405", "C408": "C406",          # OUT+  (pin 11, +3V3A)
        "C409": "C407", "C410": "C408",          # OUT-  (pin 6, VNEG)
        "C402": "C409"}                          # flying (in no bank: the module reports its L only)
# measured on kicad/afe-proto.kicad_pcb with v1/sim/pw2_ac_v1_geom.py (pad centre of the cap's own pad to the nearest same-net U401 pad)
V1_DIST_MM = {"C403": 2.81, "C404": 5.07, "C405": 10.35, "C406": 12.45, "C407": 5.55, "C408": 5.76, "C409": 6.16, "C410": 8.26, "C402": 2.87}
V1_C401_100N_MM = 7.86
# pin-link width: the track segment(s) on the cap's signal net touching its pad (same tool); C402's is the C1N side
V1_WIDTH_MM = {"C403": 0.3, "C404": 0.3, "C405": 0.2, "C406": 0.2, "C407": 0.25, "C408": 0.25, "C409": 0.25, "C410": 0.25, "C402": 0.2}
V1_C401_WIDTH_MM = 0.3
V1_VIA = {r: 1 for r in V1_DIST_MM}            # GND vias within 1.5 mm of each cap's GND pad (same tool): 1 each
# the spec team's standard: first cap <= 3.5 mm, second at 5-6 mm (5.5 taken). The flying cap keeps v1's value.
STD_DIST_MM = {"C403": 3.5, "C404": 5.5, "C405": 3.5, "C406": 5.5, "C407": 3.5, "C408": 5.5, "C409": 3.5, "C410": 5.5, "C402": 2.87}
STD_C401_100N_MM = 5.5
# the 100n VIN decoupler (not in v2's bank, a sensitivity case): every value *(check)*
C100N_F, C100N_ESR, C100N_ESL = 100e-9, 0.03, 0.5e-9
NODE_V1 = {"vin": ("C403", "C404"), "cpout": ("C405", "C406"), "outp": ("C407", "C408"), "outn": ("C409", "C410")}
LIMIT_MV = 20.0


def load_v2():
    spec = importlib.util.spec_from_file_location("pw2_ac_v2", V2DIR / "pw2_ac.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def set_geometry(pa, dist, width, via):
    """Replace the module's tables in place (slot-keyed), return the previous ones."""
    old = (dict(pa.DIST_MM), dict(pa.WIDTH_MM), dict(pa.VIA_COUNT))
    for t, new in ((pa.DIST_MM, dist), (pa.WIDTH_MM, width), (pa.VIA_COUNT, via)):
        t.clear()
        t.update({SLOT[r]: v for r, v in new.items()})
    return old


def restore(pa, old):
    for t, o in zip((pa.DIST_MM, pa.WIDTH_MM, pa.VIA_COUNT), old):
        t.clear()
        t.update(o)


class with_100n:
    """Add the 100n VIN decoupler to the module's VIN bank for the duration (patches pa.z_node; never touches pure-C runs)."""
    def __init__(self, pa, dist_mm):
        self.pa, self.d = pa, dist_mm

    def __enter__(self):
        pa = self.pa
        self.orig = pa.z_node
        l_h = pa.loop_l_nh(self.d, V1_C401_WIDTH_MM, 1) * 1e-9
        orig, vin = self.orig, pa.NODES["vin"]

        def z_node(f, caps, c_each, esr, l_nh=None, esl=pa.ESL_H, g_extra=0.0, pure_c=False):
            z = orig(f, caps, c_each, esr, l_nh, esl, 0.0, pure_c)
            if pure_c or tuple(caps) != tuple(vin):
                return 1.0 / (1.0 / z + g_extra)
            w = 2 * np.pi * np.asarray(f, float)
            y100 = 1.0 / (C100N_ESR + 1j * w * (C100N_ESL + l_h) - 1j / (w * C100N_F))
            return 1.0 / (1.0 / z + y100 + g_extra)
        pa.z_node = z_node
        return self

    def __exit__(self, *exc):
        self.pa.z_node = self.orig
        return False


def _worst_bands(res, case, node):
    ds = [k for k in res["cases"][case] if k != "model"]
    out = {}
    for b in res["cases"][case][ds[0]][node]["bands_mv"]:
        out[b] = {k: max(res["cases"][case][fl][node]["bands_mv"][b][k] for fl in ds) for k in ("rms", "pkpk")}
    return out


def harmonic_table(pa, tr, l_nh, node, kmax=4):
    """Rail pk-pk (mV) of the lines within k f_pump +- 0.25 f_pump, k = 1..kmax, at the model's pump frequency, through the network
    with the capacitors' loop L `l_nh` (the module's own case_lines; the same 30 MHz limit)."""
    esr = pa.Esr()
    fp, _ = pa.pump_frequency(tr["t"], tr["v"]["cp"])
    d = pa.node_lines(tr)[node]
    c_each = tr["cap"][node] / len(pa.NODES[node])
    c = pa.case_lines(d["I"], d["f"], node, c_each, esr, tr["g"][node], l_nh, 1.0, fp, False)
    c = np.where(d["f"] <= pa.FMAX_HZ, c, 0)
    out = {}
    for k in range(1, kmax + 1):
        mk = (np.abs(d["f"] - k * fp) <= pa.BAND_FRAC * fp) & (d["f"] >= pa.SPLIT_FRAC * fp)
        out[str(k)] = pa.pp(pa.lines_to_wave(np.where(mk, c, 0))) * 1e3
    return out


def run_set(pa, tr, dist, width, via, c100_mm=None):
    """estimate() with the given geometry; returns (full result, summary)."""
    old = set_geometry(pa, dist, width, via)
    try:
        with (contextlib.nullcontext() if c100_mm is None else with_100n(pa, c100_mm)):
            res = pa.estimate(tr)
            summ = _summary(pa, tr, res)
    finally:
        restore(pa, old)
    return res, summ


def _summary(pa, tr, res):
    lf = res["l_nh"]["asbuilt"]
    summ = {"l_nh_by_slot": lf, "worst_1.7_2.3MHz_pkpk_mv": res["worst_datasheet_mv"]["asbuilt"],
            "model_f_pkpk_mv": {n: res["cases"]["asbuilt"]["model"][n]["phasor"] for n in pa.NODES},
            "ideal_worst_pkpk_mv": res["worst_datasheet_mv"]["ideal"],
            "L_x0.5_worst_mv": res["worst_datasheet_mv"]["L_x0.5"], "L_x2_worst_mv": res["worst_datasheet_mv"]["L_x2"],
            "bands_worst_mv": {n: {"asbuilt": _worst_bands(res, "asbuilt", n), "ideal": _worst_bands(res, "ideal", n)} for n in pa.NODES},
            "pump_harmonics_pkpk_mv_model_f": {n: {"asbuilt": harmonic_table(pa, tr, lf, n), "ideal": harmonic_table(pa, tr, res["l_nh"]["ideal"], n)}
                                               for n in pa.NODES},
            "verdict_vs_20mV": {n: pa.verdict(res["worst_datasheet_mv"]["asbuilt"][n]) for n in pa.NODES}}
    return summ


def main():
    pa = load_v2()
    tr = pa.load_window(V2DIR / "results" / "transient_ideal_window.npz")
    v2json = json.loads((V2DIR / "results" / "pw2_ac_results.json").read_text())
    out = {"what": "v1 LM27762 capacitor-distance ripple by v2's AC analysis (pw2_ac_README.md)", "limit_mv": LIMIT_MV,
           "slot_map_v1_to_module_slot": SLOT, "nodes_v1": NODE_V1, "limit_note": "PW-2 20 mV pk-pk on OUT+/OUT-; VIN is not judged by it in v2's row"}
    rows = {}
    for name, dist, c100 in (("v1", V1_DIST_MM, V1_C401_100N_MM), ("standard_3.5_5.5", STD_DIST_MM, STD_C401_100N_MM)):
        res, summ = run_set(pa, tr, dist, V1_WIDTH_MM, V1_VIA)
        _, s100 = run_set(pa, tr, dist, V1_WIDTH_MM, V1_VIA, c100_mm=c100)
        rows[name] = dict(dist_mm=dist, c401_100n_mm=c100, loop_l_nh_v1_names={r: summ["l_nh_by_slot"][SLOT[r]] for r in dist},
                          vin_bank_only=summ, vin_bank_plus_100n=s100)
    out["sets"] = rows
    # controls
    ctl = {}
    v2d = dict(pa.DIST_MM), dict(pa.WIDTH_MM), dict(pa.VIA_COUNT)
    ref = pa.estimate(tr)["worst_datasheet_mv"]["asbuilt"]               # v2's own geometry, module untouched
    ctl["v2_geometry_reproduces_v2_json"] = {n: [ref[n], v2json["worst_datasheet_mv"]["asbuilt"][n]] for n in ref}
    far = dict(V1_DIST_MM)
    far["C403"] += 10.0
    _, sfar = run_set(pa, tr, far, V1_WIDTH_MM, V1_VIA)
    ctl["C403_plus_10mm_vin_worst_mv"] = [sfar["worst_1.7_2.3MHz_pkpk_mv"]["vin"], rows["v1"]["vin_bank_only"]["worst_1.7_2.3MHz_pkpk_mv"]["vin"]]
    ctl["tables_restored"] = (dict(pa.DIST_MM), dict(pa.WIDTH_MM), dict(pa.VIA_COUNT)) == v2d
    out["controls"] = ctl
    out["v2_reference"] = {"worst_as_built_mv": v2json["worst_datasheet_mv"]["asbuilt"], "ideal_mv": v2json["worst_datasheet_mv"]["ideal"],
                           "vin_dc_1M_rms_ideal_asbuilt": [v2json["vin_pw4_band"]["ideal"]["dc_1M"]["rms"]["worse_datasheet"], v2json["vin_pw4_band"]["asbuilt"]["dc_1M"]["rms"]["worse_datasheet"]]}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    o = main()
    for k, v in o["sets"].items():
        print(k, json.dumps(v["vin_bank_only"]["worst_1.7_2.3MHz_pkpk_mv"], default=float), "with100n", json.dumps(v["vin_bank_plus_100n"]["worst_1.7_2.3MHz_pkpk_mv"], default=float))
    print(json.dumps(o["controls"], default=float))
