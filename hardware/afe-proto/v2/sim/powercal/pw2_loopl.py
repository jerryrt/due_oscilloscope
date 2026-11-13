"""PW-2 ripple on TI's LM27762 transient model with per-capacitor loop inductance, one case per process.

    docker/pcb/run.sh -m 3G -t 3600 python3 -I hardware/afe-proto/v2/sim/powercal/pw2_loopl.py CASE [--tstop S] [--tmax S]

CASE: ideal (no inductance), asbuilt, x0.5, x2, control (asbuilt + 100 nH in series with C405 only: the ripple
must visibly worsen, proving the model responds to L). The circuit is lm_tran's 'su_5.25_max' (VIN 5.25 V, the
v2 feedback values at the rails' maximum corner, the AWG into 50 ohm): its reference is 0.16 mV pk-pk on OUT+,
20.7 mV on VIN, 1.39 MHz pump, OUT+ 3.4177 V, OUT- -2.0553 V.

It runs through simtools.ngspice_run (capped, timed out, a .save of five nodes) and prints one JSON line. The
model converges by lottery: NO_CONVERGE is a result, not a pass, and the exit status is 3 for it. Needs the TI
library (tools/fetch_models.py) and runs in docker/pcb; it is slow and is not part of the quick gate.
Inductance model L(d) = 2.2 nH + 0.87 nH/mm * d, distances from the integrated board: *(check)*, kvm_02's inference.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))          # hardware/afe-proto, for simtools
import power                                      # noqa: E402
from common import TPH                            # noqa: E402
from simtools import pw2                          # noqa: E402

CASES = {"ideal": dict(scale=0.0), "asbuilt": dict(scale=1.0), "x0.5": dict(scale=0.5), "x2": dict(scale=2.0),
         "control": dict(scale=1.0, extra_nh={"C405": 100.0})}


def circuit(lm1):
    rc = power.rail_corners()
    v_awg, _ = power.awg_values()
    b = power.budget(rc["max_p"], v_awg, 50.0, -1.9, TPH["iq_max"])
    ip, ineg = b["Ip"], b["In"]
    vref = 1.216

    def fb_for(vp, vn):
        return (100e3 * (vp / vref - 1), 100e3, 100e3 * (vn / vref - 1), 100e3)
    return dict(vin=5.25, fb=fb_for(rc["max_p"], rc["max_n"]), ip=ip, ineg=ineg, c1=("ideal", 1e-6 * 0.63))


def main(argv):
    case = argv[0]
    kw = {}
    for flag, key in (("--tstop", "tstop"), ("--tmax", "tmax"), ("--damp", "damp"), ("--short-until", "short_until")):
        if flag in argv:
            kw[key] = float(argv[argv.index(flag) + 1])
    kw.setdefault("tstop", 1.3e-3)
    kw.setdefault("tmax", 0.25e-6)
    curve = argv[argv.index("--curve") + 1] if "--curve" in argv else None      # a capacitor data folder (dcbias.csv, esr.csv)
    esl = float(argv[argv.index("--esl-nh") + 1]) * 1e-9 if "--esl-nh" in argv else pw2.ESL_H
    lm1 = pw2.load_harness(Path(curve) if curve else pw2.CSV_DIR, esl)
    work = Path(tempfile.mkdtemp(prefix=f"pw2-{case}-"))
    res, run = pw2.run_case(lm1, f"pw2_{case}".replace(".", "p"), work, mem="3G", timeout=3300,
                            **CASES[case], **circuit(lm1), **kw)
    print(json.dumps(dict(case=case, **res.__dict__, tstop=kw["tstop"], tmax=kw["tmax"],
                          curve=curve or "samsung-default", damp=kw.get("damp", pw2.DAMP), short_until=kw.get("short_until", 0.0), wall_s=run.wall_s if run else None, peak_rss_kb=(run.peak_rss_bytes or 0) // 1024 if run else None)))
    return 0 if res.status == "OK" else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
