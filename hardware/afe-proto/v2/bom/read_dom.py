"""Read the domestic (jlc-smt.com) CNY price ladder and library class of every catalog part that has no domestic ladder yet.

Method of v2/jlc-basic.md and whatif/bom.md: the server-rendered record on https://www.jlc-smt.com/lcsc/detail/<C>.html carries
orderLibraryType and priceList. Plain requests, no login, 3 s apart. If a page answers with the bot challenge (no priceList) the
script STOPS and leaves the remaining parts as they are; it never tries another way in.
Usage: python3 -I read_dom.py [C-number ...]   (default: every catalog row with an empty ladder_cny)
Parts whose ladder is already read are left alone, so version 1's reconciliation keeps its 2026-11-11 prices."""
import csv, datetime, json, os, re, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "catalog.csv")
rows = list(csv.DictReader(open(P))); cols = list(rows[0].keys())
todo = sys.argv[1:] or [r["lcsc"] for r in rows if not r["ladder_cny"]]
for r in rows:
    if r["lcsc"] not in todo: continue
    url = "https://www.jlc-smt.com/lcsc/detail/%s.html" % r["lcsc"]
    s = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0"}), timeout=30).read().decode("utf8", "ignore")
    m = re.search(r'"orderLibraryType":"(\w+)"', s); i = s.find('"priceList":[')
    if not m or i < 0:
        print(r["lcsc"], "CHALLENGE or no record: stopping"); break
    j = s.index("]", i); lad = json.loads(s[i + len('"priceList":'):j + 1])
    r["ladder_cny"] = ";".join("%d:%s" % (p["startNumber"], p["productPrice"]) for p in lad)
    r["class_dom"] = "base" if m.group(1) == "base" else "expand"
    r["class_dom_src"] = "jlc-smt.com orderLibraryType=%s" % m.group(1)
    r["ladder_cny_src"] = "%s read %s UTC" % (url, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"))
    print(r["lcsc"], r["class_dom"], r["ladder_cny"])
    time.sleep(3)
with open(P, "w", newline="") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
