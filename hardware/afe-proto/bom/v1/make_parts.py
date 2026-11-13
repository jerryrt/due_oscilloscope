"""Write version 1's parts stream files for the version 2 BOM engine (v2/bom/bom.py) from kicad/design.py, the source of truth.

Run (from hardware/afe-proto, inside the image):  python3 -I bom/v1/make_parts.py

One line per fitted designator (JLC-assembled, not DNP), split across the engine's three stream names by the design's own
block: scope = ch1 + ch2, awg = awg, powercal = power + cal. Columns are the engine's awg-style stream format
(refs, value, lcsc, role, qty). Then it checks that every LCSC number used has a catalog.csv row, that the placements equal
design.py's, and that the per-type counts equal bom.txt (S4's list). The owner-fitted parts are not here: extra.csv."""
import csv, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
AFE = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(AFE, "kicad"))
import design

STREAM_OF = {"ch1": "scope", "ch2": "scope", "awg": "awg", "power": "powercal", "cal": "powercal"}
out = {"scope": [], "awg": [], "powercal": []}
for p in design.PARTS:
    if p["fitted_by"] != "JLC" or p["dnp"]:
        continue
    out[STREAM_OF[p["block"]]].append((p["ref"], p["value"], p["lcsc"], p["note"], 1))
for name, rows in out.items():
    rows.sort(key=lambda r: (r[0][0], int(re.sub(r"\D", "", r[0]) or 0), r[0]))
    with open(os.path.join(HERE, "data", name + "_parts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["refs", "value", "lcsc", "role", "qty"])
        w.writerows(rows)
n = sum(len(r) for r in out.values())
cat = {r["lcsc"] for r in csv.DictReader(open(os.path.join(HERE, "data", "catalog.csv")))}
miss = sorted({r[2] for rows in out.values() for r in rows} - cat)
cnt = {}
for rows in out.values():
    for r in rows:
        cnt[r[2]] = cnt.get(r[2], 0) + 1
txt = open(os.path.join(HERE, "bom.txt"), encoding="utf-8").read()
bt = {m.group(2): int(m.group(4)) for m in re.finditer(r"^\s*\d+\s+(.+?)\s+(C\d+)\s+(Basic|Extended)\s+.*?\s(\d+)\s+[\d.]+\s+[\d.]+\s*$", txt, re.M)}
diff = sorted(k for k in set(cnt) | set(bt) if cnt.get(k, 0) != bt.get(k, 0))
print("placements %d, types %d; not in catalog.csv: %s; differs from bom.txt: %s" % (n, len(cnt), miss or "none", diff or "none"))
sys.exit(1 if (miss or diff) else 0)
