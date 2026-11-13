"""Check version 1's BOM: the totals the engine (v2/bom/bom.py) prints equal the data, the data equal kicad/design.py, and breaking the data moves them.

Run (from hardware/afe-proto, inside the image):  python3 -I bom/v1/selftest.py       Exit 0 only if every case behaves.
The expected totals are written here from the csv files and the model's constants (restated below), not taken from bom.py's cost();
bom.main is used only to obtain what the engine prints."""
import csv, io, os, shutil, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
AFE = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(AFE, "v2", "bom"))
sys.path.insert(0, os.path.join(AFE, "kicad"))
import bom, design

D = os.path.join(HERE, "data")
FX, RATIO, SETUP, LOAD, JOINT, XR = 6.6912, 6.118, 50.0, 20.0, 0.01, [(10, 10.0), (50, 5.0)]
PCB_ENG, PCB_RATE, AREA = 20.0, 410.0, 0.1 * 0.05334        # the engine's own board outline (100 x 53.34), see bom.md
STREAMS = {"scope": "scope_parts.csv", "awg": "awg_parts.csv", "powercal": "powercal_parts.csv"}
work = tempfile.mkdtemp()
ok = True


def rows(path): return list(csv.DictReader(open(path)))


def paths(over=None):
    p = {k: os.path.join(D, v) for k, v in STREAMS.items()}
    p["basic"] = os.path.join(AFE, "v2", "jlc-basic.csv")
    p.update(over or {})
    return p


def engine(over=None):
    with contextlib.redirect_stdout(io.StringIO()):
        res, flags = bom.main(["--root", D] + ["--path=%s=%s" % kv for kv in paths(over).items()])
    return res, flags


def lad(s): return sorted((int(a), float(b)) for a, b in (t.split(":") for t in s.split(";") if t))
def tier(l, n): return [p for q, p in l if q <= n][-1] if any(q <= n for q, p in l) else l[0][1]


def expected(over=None, B=20):
    """whole-tier-X-ray total per board in CNY, from the csv files alone"""
    P = paths(over)
    cat = {r["lcsc"]: r for r in rows(os.path.join(D, "catalog.csv"))}
    il = {r["lcsc"]: r for r in rows(os.path.join(D, "intl.csv"))}
    per = min(B, 50)
    n, joints, jl = {}, 0, {}
    for name in STREAMS:
        for r in rows(P[name]):
            n[r["lcsc"]] = n.get(r["lcsc"], 0) + int(r["qty"]); jl[r["lcsc"]] = int(r["qty"]) + jl.get(r["lcsc"], 0)
    def ladder(c):
        if cat[c]["ladder_cny"]: return lad(cat[c]["ladder_cny"])
        return [(q, p * RATIO) for q, p in lad(il[c]["ladder_usd"])]
    parts = sum(n[c] * tier(ladder(c), per * n[c]) for c in n)
    joints = sum(n[c] * int(cat[c]["joints"]) for c in n)
    ext = [c for c in n if cat[c]["class_dom"] == "expand"]
    xr = sum(next(cc for m, cc in XR if per * n[c] <= m) * per * n[c] for c in n if cat[c]["leadless"] == "1") / per
    fees = SETUP / per + LOAD * len(ext) / per + JOINT * joints + xr
    pcb = (PCB_ENG + PCB_RATE * per * AREA) / per
    owner = 0.0
    for r in rows(os.path.join(D, "extra.csv")):
        if r["block"] != "owner" or r["include"] != "yes": continue
        if r["lcsc"]: owner += int(r["qty"]) * tier(lad(cat[r["lcsc"]]["ladder_cny"]), B * int(r["qty"]))
        elif r["fixed_usd"]: owner += float(r["fixed_usd"]) * FX * int(r["qty"])
    return parts + fees + pcb + owner, sum(n.values()), joints, len(ext)


def check(name, good, text):
    global ok
    ok &= bool(good)
    print("%-52s %s  %s" % (name, text, "PASS" if good else "FAIL"))


# 0. the engine prints what the data says, at both board counts
res, flags = engine()
for B in (20, 100):
    e, place, joints, next_ = expected(B=B)
    got = res[B]["lo"]["total"]
    check("engine total = data, %d boards" % B, abs(got - e) < 1e-9, "engine %.4f CNY = $%.2f, data %.4f" % (got, got / FX, e))
check("99 placements, 234 joints, 4 Extended, no flags", (res[20]["lo"]["placements"], res[20]["lo"]["joints"], len(res[20]["lo"]["ext"]), flags) == (99, 234, 4, []), "")
# 1. the data are design.py's: placements per LCSC number, and the whole refs set
jlc = [p for p in design.PARTS if p["fitted_by"] == "JLC" and not p["dnp"]]
refs = sorted(r["refs"] for name in STREAMS for r in rows(os.path.join(D, STREAMS[name])))
check("streams = design.py JLC placements", refs == sorted(p["ref"] for p in jlc), "%d refs" % len(refs))
# 2. bom.md on disk is what the engine writes now
out = os.path.join(work, "bom.md")
with contextlib.redirect_stdout(io.StringIO()):
    bom.main(["--root", D, "--md", out] + ["--path=%s=%s" % kv for kv in paths().items()])
check("bom.md is the engine's current output", open(out).read() == open(os.path.join(HERE, "bom.md")).read(), "")


def broken(name, drop_ref, stream, want_dplace, want_djoints, want_dext):
    """break one stream on purpose: delete a designator; the total must move by exactly what the data predict"""
    p = os.path.join(work, stream + "_x.csv")
    rs = rows(os.path.join(D, STREAMS[stream]))
    assert any(r["refs"] == drop_ref for r in rs), drop_ref
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, list(rs[0].keys())); w.writeheader(); w.writerows(r for r in rs if r["refs"] != drop_ref)
    over = {stream: p}
    r2, f2 = engine(over)
    for B in (20, 100):
        e0, e1 = expected(B=B)[0], expected(over, B)
        got = r2[B]["lo"]["total"] - res[B]["lo"]["total"]
        check("%s (%d boards)" % (name, B), abs(got - (e1[0] - e0)) < 1e-9 and got < 0 and e1[1:] == (99 + want_dplace, 234 + want_djoints, 4 + want_dext),
              "total moves %+.4f CNY/board, predicted %+.4f, placements %d" % (got, e1[0] - e0, r2[B]["lo"]["placements"]))


by = {p["ref"]: p for p in jlc}
ref_u = [p["ref"] for p in jlc if p["lcsc"] == "C54120492"][0]
tph = [p["ref"] for p in jlc if p["lcsc"] == "C118223"][0]
stream_of = lambda ref: {"ch1": "scope", "ch2": "scope", "awg": "awg", "power": "powercal", "cal": "powercal"}[by[ref]["block"]]
broken("one TPH2502 removed (2 -> 1, tier moves)", tph, stream_of(tph), -1, -8, 0)
broken("the REF3030E removed (Extended type gone)", ref_u, stream_of(ref_u), -1, -3, -1)
# 3. a duplicated line is flagged and counted twice
p = os.path.join(work, "dup.csv")
rs = rows(os.path.join(D, STREAMS["awg"]))
with open(p, "w", newline="") as f:
    w = csv.DictWriter(f, list(rs[0].keys())); w.writeheader(); w.writerows(rs + [rs[0]])
r3, f3 = engine({"awg": p})
check("duplicated AWG line is flagged", any("DUPLICATE LINE" in x for x in f3) and r3[20]["lo"]["placements"] == 100, "flags: %d" % len(f3))
shutil.rmtree(work)
print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
