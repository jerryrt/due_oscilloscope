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

t20, t100, f0, _ = quiet()
print("baseline: $%.4f at 20, $%.4f at 100, flags %d" % (t20 / FX, t100 / FX, len(f0)))
assert not f0, f0

SC = os.path.join(HERE, "../sim/scope/parts.csv"); AW = os.path.join(HERE, "../sim/awg/parts.csv")
CAT = os.path.join(HERE, "catalog.csv")

# 1. a duplicated line: scope R1a (C23192, qty 2, derived 0.002 USD x 6.118 below the 1000-piece tier, 2 joints each)
p = copy(SC, "scope_dup.csv")
edit_csv(p, lambda rows: rows + [dict(next(r for r in rows if r["refdes_per_channel"] == "R1a"))])
a, b, f, _ = quiet({"scope": p})
want20 = 2 * 0.002 * RATIO + 2 * 2 * 0.01
check("duplicated scope line R1a (+2 x 510k)", a - t20, want20, True, "DUPLICATE LINE", f)
check("  ... at 100 boards", b - t100, want20, True, "DUPLICATE LINE", f)

# 2. a wrong quantity: AWG R4 (1k, C21190) 1 -> 10; 0.0017 USD x 6.118, tier 1 at 200 pieces
p = copy(AW, "awg_qty.csv")
edit_csv(p, lambda rows: [dict(r, qty="10") if r["refs"] == "R4" else r for r in rows])
a, b, f, _ = quiet({"awg": p})
want = 9 * 0.0017 * RATIO + 9 * 2 * 0.01
check("wrong quantity AWG R4 1 -> 10", a - t20, want, False, "DUPLICATE", f)
# the same break at an order tier edge: 1 -> 1000 changes the unit price tier (1000 x 20 = 20000 pieces, tier 10000: 0.001 USD)
p2 = copy(AW, "awg_qty2.csv")
edit_csv(p2, lambda rows: [dict(r, qty="1000") if r["refs"] == "R4" else r for r in rows])
a, b, f, _ = quiet({"awg": p2})
want = 1000 * 0.001 * RATIO + 1000 * 2 * 0.01 - (0.0017 * RATIO + 2 * 0.01)
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
a, b, f, res = quiet({"intl": p})
d = a - t20
want = -(6.915 * 1) - 0.01 * 10 - 20.0 / 20          # price, its joints and its loading fee all vanish from the total
ok &= (len(res[20]["lo"]["unpriced"]) == 2 and any("NO PRICE" in x for x in f))
print("%-46s unpriced lines %d, flag NO PRICE present %s (total falls %.3f CNY: price, joints and loading fee of the part) %s" % (
    "ADS1115 price removed", len(res[20]["lo"]["unpriced"]), any("NO PRICE" in x for x in f), -d, "PASS" if len(res[20]["lo"]["unpriced"]) == 2 and any("NO PRICE" in x for x in f) else "FAIL"))

# 5. the power/calibration stream appears: its placeholder rows go, and the tool says so
pc = os.path.join(work, "powercal.csv")
with open(pc, "w") as f_:
    f_.write("refs,value,lcsc,role,qty\nU1,LM27762,C473398,rails,1\n")
a, b, f, res = quiet({"powercal": pc})
dropped = [x for x in f if "skipped" in x]
expect = sum(int(r["qty_per_board"]) for r in csv.DictReader(open(SC))) + sum(int(r["qty"]) for r in csv.DictReader(open(AW))) + 1
good = len(dropped) >= 20 and res[20]["lo"]["placements"] == expect
ok &= good
print("%-46s %d placeholder rows skipped, placements %d (expected %d: scope + awg + the one powercal row)  %s" % ("powercal/parts.csv appears", len(dropped), res[20]["lo"]["placements"], expect, "PASS" if good else "FAIL"))

# 6. version 1 reconciliation breaks when version 1's list is wrong: one 249R removed from the ladder
p = copy(os.path.join(HERE, "v1.csv"), "v1_bad.csv")
edit_csv(p, lambda rows: [dict(r, qty="7") if r["ref"] == "R43-R50" else r for r in rows])
import contextlib
with contextlib.redirect_stdout(io.StringIO()):
    bom.main(["--path=v1=" + p, "--md", os.path.join(work, "bom_bad.md")])
txt = open(os.path.join(work, "bom_bad.md")).read()
good = "**NO**" in txt
ok &= good
print("%-46s reconciliation rows marked NO: %d  %s" % ("version 1 ladder 8 -> 7 parts", txt.count("**NO**"), "PASS" if good else "FAIL"))

shutil.rmtree(work)
print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
