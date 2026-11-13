"""Break bom.py on purpose and check that each break moves the total the way the cost model predicts, or is flagged.

Run:  python3 -I selftest.py [--tmp DIR]       Exit status 0 only if every case behaves.
The predictions are written out here from the price ladders and the model's constants, not taken from bom.py's own functions;
only Data/run are used to obtain the totals."""
import csv, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bom

FX, RATIO = 6.6912, 6.118
tmpdir = sys.argv[sys.argv.index("--tmp") + 1] if "--tmp" in sys.argv else None
work = tempfile.mkdtemp(dir=tmpdir)
ok = True


def totals(paths=None):
    res, flags = bom.main(["--path=" + k + "=" + v for k, v in (paths or {}).items()]) if paths else bom.main([])
    return res[20]["lo"]["total"], res[100]["lo"]["total"], flags, res


def price(c, pieces, catalog=None, intl=None):
    """Unit price in CNY at `pieces`, written here from the two ladder files (domestic ladder if read, else international x 6.118)."""
    cat = {r["lcsc"]: r for r in csv.DictReader(open(catalog or os.path.join(HERE, "catalog.csv")))}[c]
    if cat["ladder_cny"]: lad, k = cat["ladder_cny"], 1.0
    else: lad, k = {r["lcsc"]: r for r in csv.DictReader(open(intl or os.path.join(HERE, "intl.csv")))}[c]["ladder_usd"], RATIO
    p = None
    for t in lad.split(";"):
        a, b = t.split(":")
        if int(a) <= pieces or p is None: p = float(b) * k
    return p


def copy(src, name):
    d = os.path.join(work, name); shutil.copy(src, d); return d


def edit_csv(path, fn):
    rows = list(csv.DictReader(open(path))); cols = list(rows[0].keys())
    rows = fn(rows)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)


def check(name, got, want, flagged, flag_text, flags, tol=1e-9):
    global ok
    good = abs(got - want) < tol and (flag_text is None or any(flag_text in f for f in flags)) == flagged
    ok &= good
    print("%-46s change %+.6f CNY/board (predicted %+.6f)  flagged=%s  %s" % (name, got, want, any(flag_text in f for f in flags) if flag_text else "-", "PASS" if good else "FAIL"))


import io, contextlib
def quiet(*a, **k):
    with contextlib.redirect_stdout(io.StringIO()): return totals(*a, **k)

def expected_unpriced(paths=None):
    """Lines that legitimately carry no price, computed from the data (not from bom.cost): an included line with no LCSC number and no
    fixed price (owner-fitted M2.5 standoff and screw, the calibration pins, placeholders), and an included line whose LCSC part has
    neither a domestic nor an international ladder in the catalogue. Returns the sorted refs."""
    d = bom.Data(bom.HERE, {k: v for k, v in (paths or {}).items()})
    out = []
    for x in bom.lines(d, []):
        if not x["include"]: continue
        if not x["lcsc"]:
            if x["fixed_usd"] is None: out.append(x["ref"])
        elif not d.catalog.get(x["lcsc"], {}).get("ladder_cny") and not d.intl.get(x["lcsc"], {}).get("ladder_usd"):
            out.append(x["ref"])
    return sorted(out)


t20, t100, f0, _r = quiet()
base_place = _r[20]["lo"]["placements"]
print("baseline: $%.4f at 20, $%.4f at 100, flags %d" % (t20 / FX, t100 / FX, len(f0)))
assert not [x for x in f0 if not x.startswith("note:")], f0
exp0 = expected_unpriced()
base_unpriced = len(_r[20]["lo"]["unpriced"])
print("baseline unpriced lines: engine %d, computed from the catalogue %d (%s)" % (base_unpriced, len(exp0), ", ".join(exp0)))
assert base_unpriced == len(exp0) and exp0, (base_unpriced, exp0)
assert {"MH-so25", "MH-sc25"} <= set(exp0), exp0       # the owner-fitted M2.5 lines are among them
n0 = len([x for x in f0 if x.startswith("note:")])
print("baseline notes (placeholder rows dropped because powercal/parts.csv exists):", n0)
assert n0 >= 20

SC = os.path.join(HERE, "../sim/scope/parts.csv"); AW = os.path.join(HERE, "../sim/awg/parts.csv")
CAT = os.path.join(HERE, "catalog.csv")

# 1. a duplicated line: scope R1a (qty 2, derived USD ladder x 6.118 below the 1000-piece tier, 2 joints each; its LCSC read from the file)
p = copy(SC, "scope_dup.csv")
edit_csv(p, lambda rows: rows + [dict(next(r for r in rows if r["refdes_per_channel"] == "R1a"))])
a, b, f, _ = quiet({"scope": p})
LC1 = next(r["lcsc"] for r in csv.DictReader(open(SC)) if r["refdes_per_channel"] == "R1a")
n0 = sum(int(r["qty_per_board"]) for r in csv.DictReader(open(SC)) if r["lcsc"] == LC1)
want20 = (n0 + 2) * price(LC1, 20 * (n0 + 2)) - n0 * price(LC1, 20 * n0) + 2 * 2 * 0.01
check("duplicated scope line R1a (+2 x its part)", a - t20, want20, True, "DUPLICATE LINE", f)
want100 = (n0 + 2) * price(LC1, 50 * (n0 + 2)) - n0 * price(LC1, 50 * n0) + 2 * 2 * 0.01
check("  ... at 100 boards", b - t100, want100, True, "DUPLICATE LINE", f)

# 2. a wrong quantity: AWG R4 (510 ohm, C23193) 1 -> 10; 0.0015 USD x 6.118, tier 1 at 200 pieces
p = copy(AW, "awg_qty.csv")
edit_csv(p, lambda rows: [dict(r, qty="10") if r["refs"] == "R4" else r for r in rows])  # R4 is Rg2, C4211 (shared with R3)
nR = sum(int(r["qty"]) for r in csv.DictReader(open(AW)) if r["lcsc"] == "C4211")
a, b, f, _ = quiet({"awg": p})
want = (nR + 9) * price("C4211", 20 * (nR + 9)) - nR * price("C4211", 20 * nR) + 9 * 2 * 0.01
check("wrong quantity AWG R4 1 -> 10", a - t20, want, False, "DUPLICATE", f)
# the same break at an order tier edge: 1 -> 1000 changes the unit price tier (about 20000 pieces, a higher tier)
p2 = copy(AW, "awg_qty2.csv")
edit_csv(p2, lambda rows: [dict(r, qty="1000") if r["refs"] == "R4" else r for r in rows])
a, b, f, _ = quiet({"awg": p2})
want = (nR + 999) * price("C4211", 20 * (nR + 999)) - nR * price("C4211", 20 * nR) + 999 * 2 * 0.01
check("wrong quantity AWG R4 1 -> 1000 (tier moves)", a - t20, want, False, "DUPLICATE", f)

# 3. an Extended part counted as Basic: ADS1115 marked Basic in the catalog; one loading fee (20 CNY / 20 boards) goes
p = copy(CAT, "catalog_basic.csv")
edit_csv(p, lambda rows: [dict(r, class_dom="base") if r["lcsc"] == "C37593" else r for r in rows])
a, b, f, _ = quiet({"catalog": p})
check("Extended ADS1115 marked Basic (20 boards)", a - t20, -20.0 / 20, True, "is marked Basic but is not a Basic row", f)
check("  ... at 100 boards (orders of 50)", b - t100, -20.0 / 50, True, "on jlcpcb.com (international API)", f)
# 3b. an Extended passive marked Basic: the 4.7k pulled out of jlc-basic.csv's Basic list is the reverse; here a precision part is relabelled
p = copy(CAT, "catalog_basic2.csv")
edit_csv(p, lambda rows: [dict(r, class_dom="base") if r["lcsc"] == "C118223" else r for r in rows])
a, b, f, _ = quiet({"catalog": p})
check("Extended TPH2502 marked Basic", a - t20, -20.0 / 20, True, "is marked Basic", f)

# 4. a price missing: the ADS1115's international and domestic ladder removed -> no total for it, and a flag
p = copy(os.path.join(HERE, "intl.csv"), "intl_gone.csv")
edit_csv(p, lambda rows: [dict(r, ladder_usd="") if r["lcsc"] == "C37593" else r for r in rows])
pc = copy(CAT, "catalog_noladder.csv")
edit_csv(pc, lambda rows: [dict(r, ladder_cny="") if r["lcsc"] == "C37593" else r for r in rows])
a, b, f, res = quiet({"intl": p, "catalog": pc})
d = a - t20
want = -price("C37593", 20) - 0.01 * 10 - 20.0 / 20          # price, its joints and its loading fee all vanish from the total
paths4 = {"intl": p, "catalog": pc}
exp4 = expected_unpriced(paths4)
# the one removed part adds exactly the included lines that use C37593 (computed from the data, not typed in)
n_ads = len([x for x in bom.lines(bom.Data(bom.HERE, {}), []) if x["include"] and x["lcsc"] == "C37593"])
got = len(res[20]["lo"]["unpriced"])
good = got == base_unpriced + n_ads == len(exp4) and any("NO PRICE" in x for x in f) and abs(d - want) < 1e-6
ok &= good
print("%-46s unpriced %d = baseline %d + %d line(s) of C37593 (computed %d), flag NO PRICE %s, total falls %.3f CNY  %s" % (
    "ADS1115 price removed", got, base_unpriced, n_ads, len(exp4), any("NO PRICE" in x for x in f), -d, "PASS" if good else "FAIL"))

# 4b. broken once, on purpose: a line with no price that nothing marks as owner-fitted must be CAUGHT. The engine counts it (baseline + 1),
# and the stale rule (the old hard-coded 2, or the unmodified baseline) disagrees with it, so a count that is not computed fails here.
pe = copy(os.path.join(HERE, "extra.csv"), "extra_unmarked.csv")
edit_csv(pe, lambda rows: rows + [dict(rows[0], ref="X-unmarked", value="unpriced test part", lcsc="", qty="1", block="other", placeholder_for="", include="yes", replaces="", fixed_usd="")])
a2, b2, f2, res2 = quiet({"extra": pe})
got2 = len(res2[20]["lo"]["unpriced"])
exp2 = expected_unpriced({"extra": pe})
good = got2 == base_unpriced + 1 == len(exp2) and got2 != 2 and got2 != len(exp0)
ok &= good
print("%-46s unpriced %d vs baseline %d (a hard-coded 2 or the old baseline would now disagree)  %s" % ("unmarked unpriced line added", got2, base_unpriced, "PASS" if good else "FAIL"))

# 5. the power/calibration stream is absent again: its placeholder rows come back and no row is reported dropped
a, b, f, res = quiet({"powercal": os.path.join(work, "no_such_powercal.csv")})
back = res[20]["lo"]["placements"]
good = not [x for x in f if x.startswith("note:")] and back > base_place
ok &= good
print("%-46s placements %d (baseline %d), dropped notes %d  %s" % ("powercal/parts.csv absent", back, base_place, len([x for x in f if x.startswith("note:")]), "PASS" if good else "FAIL"))

shutil.rmtree(work)
print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
