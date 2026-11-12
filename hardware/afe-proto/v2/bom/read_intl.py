"""Read the international JLC price ladder, class and stock of every LCSC number the BOM tool needs.

Method: the public JSON API of jlcpcb.com that v2/jlc-basic.md describes (selectSmtComponentList, keyword = C-number),
no login, one request per part, 1.5 s apart.  Writes intl.csv.  Usage: python3 -I read_intl.py C118223 C37593 ...
With no arguments it reads every LCSC number found in the three parts.csv files, extra.csv and v1.csv."""
import csv, json, os, sys, time, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"

def wanted():
    out = set()
    for f in ("../sim/scope/parts.csv", "../sim/awg/parts.csv", "../sim/powercal/parts.csv", "extra.csv", "v1.csv"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            for r in csv.DictReader(open(p)):
                c = (r.get("lcsc") or "").strip()
                if c.startswith("C"): out.add(c)
    return sorted(out, key=lambda c: int(c[1:]))

def read(c):
    body = json.dumps({"currentPage": 1, "pageSize": 5, "keyword": c, "searchSource": "search"}).encode()
    rq = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(rq, timeout=30))
    for it in d["data"]["componentPageInfo"]["list"]:
        if it.get("componentCode") == c:
            lad = ";".join("%d:%s" % (p["startNumber"], p["productPrice"]) for p in it["componentPrices"])
            return dict(lcsc=c, mfr=it.get("componentModelEn") or it.get("componentName") or "", pkg=it.get("componentSpecificationEn") or "",
                        library=it.get("componentLibraryType"), preferred=it.get("preferredComponentFlag"),
                        stock=it.get("stockCount"), ladder_usd=lad,
                        read_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                        url="https://jlcpcb.com/partdetail/" + (it.get("urlSuffix") or c))
    return dict(lcsc=c, mfr="", pkg="", library="NOT FOUND", preferred="", stock="", ladder_usd="", read_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"), url="")

if __name__ == "__main__":
    todo = sys.argv[1:] or wanted()
    rows = []
    for c in todo:
        try: rows.append(read(c))
        except Exception as e: rows.append(dict(lcsc=c, mfr="", pkg="", library="ERROR " + str(e)[:40], preferred="", stock="", ladder_usd="", read_utc="", url=""))
        time.sleep(1.5)
    old = {}
    p = os.path.join(HERE, "intl.csv")
    if os.path.exists(p) and sys.argv[1:]:
        old = {r["lcsc"]: r for r in csv.DictReader(open(p))}
    for r in rows: old[r["lcsc"]] = r
    cols = ["lcsc", "mfr", "pkg", "library", "preferred", "stock", "ladder_usd", "read_utc", "url"]
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, cols); w.writeheader()
        for c in sorted(old, key=lambda c: int(c[1:])): w.writerow({k: old[c].get(k, "") for k in cols})
    print(len(rows), "read")
