"""Netlist text from both boards' netlib.py, for the golden comparison.

    python3 tests/netlib_snapshot.py --write     # regenerate tests/golden/netlib_*.txt
    (the test compares against the committed files; regenerate only for a deliberate netlist change)

The builders are pure string functions, so this needs numpy and nothing else:
no ngspice, no vendor model. Each netlib is loaded by path under its own name
because both are called netlib and both keep state (use_variant) that is reset.
"""
import importlib.util
import sys
from pathlib import Path

AFE = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).resolve().parent / "golden"


def load(rel, name):
    path = AFE / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


def v1_text():
    nl = load("sim/scope/netlib.py", "netlib_v1")
    out = []
    try:
        for var in sorted(nl.VARIANTS):
            nl.use_variant(var)
            p = dict(nl.P0)
            p.setdefault("op", "OPA354")
            p.setdefault("rng", "x1")
            out.append(f"##### variant {var}\n{nl.header(p, 'g')}\n{nl.rails(p)}\n{nl.core(p)}\n"
                       f"{nl.core(p, pre='b', loopbreak=True)}\n")
            out.append(f"##### rails extras {var}\n{nl.rails(p, ac_vm=True, ac_v3=True, ac_dac=True)}\n")
            out.append(f"##### sense {var}\n{nl.sense_and_dac(p, 3.3)}\n{nl.sense_and_dac(p, 3.3, ac_v3=True, ac_dac=True)}\n")
            out.append(f"##### c1 {var}\n{nl.c1_of(p)!r}\n")
    finally:
        nl.use_variant("hz")
    return "".join(out)


def v2_text():
    nl = load("v2/sim/scope/netlib.py", "netlib_v2")
    p = dict(nl.P0)
    out = [f"##### header\n{nl.header('t')}\n{nl.header('t', 'x')}\n",
           f"##### rails\n{nl.rails(p)}\n{nl.rails(p, ac_vcc=True)}\n",
           f"##### rp\n{nl.rp_of(p)!r} {nl.rsum(p['R1'])!r}\n"]
    for k, kw in (("a", {}), ("b", dict(loopbreak=True)), ("a", dict(esd=True)), ("b", dict(inj=True)),
                  ("a", dict(loopbreak=True, esd=True, inj=True))):
        out.append(f"##### chan {k} {kw}\n{nl.chan(p, k, **kw)}\n")
    q = dict(p, xt=0.01, Cx=1e-12, Cxin=2e-12, Cxp=3e-12)
    out.append(f"##### coupling\n{nl.coupling(q)}\n{nl.chan(q, 'a')}\n{nl.chan(q, 'b')}\n")
    return "".join(out)


def main():
    if "--write" in sys.argv:
        GOLDEN.mkdir(exist_ok=True)
        (GOLDEN / "netlib_v1.txt").write_text(v1_text())
        (GOLDEN / "netlib_v2.txt").write_text(v2_text())
        print("written")


if __name__ == "__main__":
    main()
