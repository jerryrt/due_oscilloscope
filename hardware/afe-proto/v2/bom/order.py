"""Purchasable order tables at 5 and 100 boards, for AFE version 2 and version 1, from the one engine (bom.py).

Run through the engine:   python3 -I bom.py --order          (writes the four files named below; stdlib only)

  ../bom/order-5-100.md / .csv       version 2   (hardware/afe-proto/v2/bom/)
  ../../bom/v1/order-5-100.md / .csv version 1   (hardware/afe-proto/bom/v1/; STAGED here, to land with the v1 landing)

Same cost model as bom.py (JLC China Economic SMT, domestic CNY ladders; see bom.py's header): parts at the ladder tier holding
(boards in one order) x (pieces per board); an order holds at most 50 boards, so 100 boards are two orders of 50; per order setup,
a loading fee per Extended type, a fee per SMT joint, X-ray per leadless piece, PCB engineering fee plus area; stencil free on the
Economic service. Owner-fitted parts (not assembled by JLC) at the tier for (boards x quantity), no loading or joint fee.
Everything here is computed from bom.Data; `test_bom_order.py` recomputes the totals with bom.cost() as an independent oracle.

Version 1 is read by an adapter, not edited: its parts list is `v1-input/design-parts.csv` (the JLC/owner part list of version 1's
kicad/design.py, which is its source of truth; regenerate with `bom.py --refresh-v1-design <dir with design.py>`) and its own
bom.txt (copied beside it), which the adapter holds against the design, line by line, and reports every disagreement. Prices come
from catalog.csv / intl.csv (the engine's single price store), not from bom.txt."""
import csv, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
AFE = os.path.normpath(os.path.join(HERE, "..", ".."))
V1_IN = os.path.join(HERE, "v1-input")
VOLUMES = (5, 100)
OUT_V2 = os.path.join(HERE, "order-5-100")
OUT_V1 = os.path.join(AFE, "bom", "v1", "order-5-100")


def _ident():
    """the board's identity from the config (pcbtools/boards/v2.py: NAME, MODEL, REV, ASSY_REV): nothing about it is typed here"""
    import importlib.util
    sp = importlib.util.spec_from_file_location("_v2cfg_ident", os.path.join(AFE, "pcbtools", "boards", "v2.py"))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return m


CFG = _ident()
IDENT = "%s-%s-REV%s" % (CFG.NAME, CFG.MODEL, CFG.REV)          # the file-name prefix of every v2 order and upload file
IDENT_TEXT = "%s %s REV %s, assembly revision %s" % (CFG.NAME, CFG.MODEL, CFG.REV, CFG.ASSY_REV or "none (the first assembly of this revision)")
READ_NOTE = "prices: catalog.csv / intl.csv ladders, source and read date per part in the Sources table; read dates 2026-11-11 to 2026-11-13"


# ------------------------------------------------------------------------------------------------ the board as the source
BOARD_V2 = os.path.join(AFE, "v2", "layout", "integrated", "afe-v2-integrated.kicad_pcb")


def read_board(path):
    """Every footprint of a KiCad 10 board, parsed from its text: dict(ref, value, lcsc, fitted, fp, x, y, rot, layer, dnp). Read-only."""
    t = open(path).read()
    out = []
    for f in re.split(r"\n\t\(footprint ", t)[1:]:
        g = lambda k: (re.search(r'\(property "%s" "([^"]*)"' % k, f) or [None, ""])[1]
        at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", f)
        attr = re.search(r"\(attr ([^)]*)\)", f)
        out.append(dict(ref=g("Reference"), value=g("Value"), lcsc=g("LCSC"), fitted=g("Fitted by"), fp=f.split('"')[1],
                        x=float(at.group(1)), y=float(at.group(2)), rot=float(at.group(3) or 0), layer=re.search(r'\(layer "([^"]*)"', f).group(1),
                        dnp="dnp" in (attr.group(1).split() if attr else [])))
    return out


def smt_rows(fps):
    """The footprints JLC assembles: Fitted by JLC and not DNP."""
    return sorted((p for p in fps if p["fitted"] == "JLC" and not p["dnp"]), key=lambda p: natkey(p["ref"]))


def lines_from_rows(rows):
    """Engine-format lines grouped by LCSC number; refs are the board's own designators."""
    by = {}
    for r in rows: by.setdefault(r["lcsc"], []).append(r)
    L = []
    for c, rs in by.items():
        rs.sort(key=lambda r: natkey(r["ref"]))
        vals = []
        for r in rs:
            if r["value"] not in vals: vals.append(r["value"])
        L.append(dict(stream="board", ref=",".join(r["ref"] for r in rs), value=" / ".join(vals), lcsc=c, role="", qty=len(rs), block="other", include=True,
                      fixed_usd=None, replaces=""))
    return L


def owner_lines(data, own):
    """Owner-fitted lines from footprints (rows with ref, fp, lcsc): BNC by its LCSC ladder, Due-socket headers as version 2's header rows, the rest unpriced."""
    ex = {r["ref"]: r for r in data.extra}
    L = []
    def grp(pred): return sorted((r["ref"] for r in own if pred(r)), key=natkey)
    def hdr(ref_v2, refs):
        e = ex[ref_v2]
        if refs: L.append(dict(stream="board", ref=",".join(refs), value=e["value"], lcsc="", role=e["role"], qty=len(refs), block="owner", include=True,
                               fixed_usd=float(e["fixed_usd"]), replaces="", note=e["note"]))
    bnc = grp(lambda r: r["lcsc"] == "C2837587")
    L.append(dict(stream="board", ref=",".join(bnc), value="BNC 50 ohm right-angle THT KH-BNC50-3511", lcsc="C2837587", role="CH1, CH2 and AWG BNCs (owner-fitted)",
                  qty=len(bnc), block="owner", include=True, fixed_usd=None, replaces=""))
    hdr("J-hdr8", grp(lambda r: "1x08" in r["fp"])); hdr("J-hdr10", grp(lambda r: "1x10" in r["fp"])); hdr("J-hdr36", grp(lambda r: "2x18" in r["fp"]))
    cal = grp(lambda r: "PinHeader_1x03" in r["fp"])
    L.append(dict(stream="board", ref=",".join(cal), value="CAL ratio header 1x3 pin strip", lcsc="", role="J501 (TAP4 | B | TAP3); a pin strip piece", qty=len(cal),
                  block="owner", include=True, fixed_usd=None, replaces="", note="UNPRICED: part and price not in any repo file; the shunt is fitted by the user *(check)*"))
    mh = grp(lambda r: r["ref"].startswith("MH"))
    for ref_v2 in ("MH-so25", "MH-sc25"):
        e = ex[ref_v2]
        L.append(dict(stream="board", ref=",".join(mh), value=e["value"], lcsc="", role=e["role"], qty=len(mh), block="owner", include=True, fixed_usd=None,
                      replaces="", note=e["note"]))
    return L


def pkgname(fp): return fp.split(":")[-1]


def jlc_bom_csv(rows):
    """JLC's BOM upload: Comment, Designator, Footprint, LCSC Part #, one line per (value, footprint, LCSC)."""
    g = {}
    for r in rows: g.setdefault((r["value"], pkgname(r["fp"]), r["lcsc"]), []).append(r["ref"])
    out = ["Comment,Designator,Footprint,LCSC Part #"]
    for (v, fp, c), refs in sorted(g.items(), key=lambda kv: natkey(sorted(kv[1], key=natkey)[0])):
        out.append(",".join(['"%s"' % x.replace('"', '""') for x in (v, ",".join(sorted(refs, key=natkey)), fp, c)]))
    return "\n".join(out) + "\n"


def jlc_cpl_csv(rows):
    """JLC's CPL upload: Designator, Mid X, Mid Y, Layer, Rotation. Positions in mm as the board stores them with Y negated (the KiCad position-file
    and Fabrication Toolkit convention) and the board's absolute origin (its Gerbers use it too, no aux origin); rotation is KiCad's, counter-clockwise,
    0-360, unmodified. JLC corrects some packages from its own rotation database, so the preview in JLC's viewer must be checked *(check)*."""
    out = ["Designator,Mid X,Mid Y,Layer,Rotation"]
    for r in sorted(rows, key=lambda r: natkey(r["ref"])):
        out.append("%s,%.4fmm,%.4fmm,%s,%g" % (r["ref"], r["x"], -r["y"], "Top" if r["layer"] == "F.Cu" else "Bottom", r["rot"] % 360))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------------ version 1 adapter
def refresh_v1_design(design_dir, out=None):
    """Write v1-input/design-parts.csv from a version 1 kicad/ folder (reads design.py, which defines PARTS; read-only)."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, design_dir)
    import design
    sys.path.pop(0)
    out = out or os.path.join(V1_IN, "design-parts.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ref", "value", "lcsc", "mpn", "fp", "block", "fitted_by", "dnp"])
        for p in design.PARTS:
            if p["fitted_by"] == "none": continue
            w.writerow([p["ref"], p["value"], p.get("lcsc", ""), p.get("mpn", ""), p["fp"], p["block"], p["fitted_by"], int(bool(p["dnp"]))])
    return out


def parse_bomtxt(path):
    """bom.txt's JLC part lines: {lcsc: dict(qty, cny20, cny100, cls, name)}."""
    out = {}
    pat = re.compile(r"^\s*\d+\s+(.+?)\s+(C\d+)\s+(Basic|Extended)\s+.*?\s(\d+)\s+([\d.]+)\s+([\d.]+)\s*$", re.M)
    for m in pat.finditer(open(path).read()):
        out[m.group(2)] = dict(name=m.group(1), cls=m.group(3), qty=int(m.group(4)), cny20=float(m.group(5)), cny100=float(m.group(6)))
    return out


def natkey(ref):
    m = re.match(r"([A-Za-z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def v1_lines(data, flags, bomtxt=None, design_csv=None):
    """Version 1's lines in the engine's format, plus the disagreement list between the design and bom.txt."""
    import bom
    design_csv = design_csv or os.path.join(V1_IN, "design-parts.csv")
    bomtxt = bomtxt or os.path.join(V1_IN, "bom.txt")
    rows = bom.rd(design_csv)
    jlc = [r for r in rows if r["fitted_by"] == "JLC" and r["dnp"] == "0"]
    dnp = [r for r in rows if r["fitted_by"] == "JLC" and r["dnp"] != "0"]
    by = {}
    for r in jlc: by.setdefault(r["lcsc"], []).append(r)
    L = lines_from_rows(jlc)
    own = [r for r in rows if r["fitted_by"] == "owner"]
    L += owner_lines(data, own)
    known = {"C2837587"}
    for r in own:
        if r["lcsc"] and r["lcsc"] not in known: flags.append("v1 owner-fitted part %s has an LCSC number the adapter does not price" % r["ref"])
    # ---- the disagreement report: design.py (truth) against the plain-text BOM
    dis = []
    bt = parse_bomtxt(bomtxt)
    cnt = {c: len(rs) for c, rs in by.items()}
    for c in sorted(set(cnt) | set(bt), key=lambda c: int(c[1:])):
        if cnt.get(c, 0) != bt.get(c, {}).get("qty", 0):
            dis.append("%s: design.py has %d, bom.txt has %d" % (c, cnt.get(c, 0), bt.get(c, {}).get("qty", 0)))
    if not dis: dis.append("none: the design's %d JLC placements and %d types equal bom.txt's %d placements and %d types, type by type (C21189: %d in both)" % (
        len(jlc), len(by), sum(v["qty"] for v in bt.values()), len(bt), cnt.get("C21189", 0)))
    if dnp: dis.append("%s: in the design as DNP (no part fitted, not ordered): %s" % ("note", ", ".join(r["ref"] + " " + r["value"] for r in dnp)))
    txt = open(bomtxt).read()
    if "R109 removed" in txt.splitlines()[0] and "R109" in txt:
        # R109 appears in bom.txt only as 'R109' mentions in historic text; the 0Rb list is what counts
        listed = re.findall(r"^\s+(R\d+)\s+x1\s+.*(?:bridge|link|VNEG)", txt, re.M)
        if "R109" in listed: dis.append("R109 still listed in bom.txt as a bridge although the design removed it")
    d0 = [r["ref"] for r in by.get("C21189", [])]
    dis.append("0 ohm bridges: design.py lists %d (%s)" % (len(d0), ", ".join(sorted(d0, key=natkey))))
    return L, dis, bt, jlc


# ------------------------------------------------------------------------------------------------ the order computation
def consolidate(L):
    """One row per LCSC number for JLC-assembled lines, in first-seen order: refs, value, qty per board."""
    agg, seq = {}, []
    for x in L:
        if not x["include"] or not x["lcsc"] or x["block"] == "owner": continue
        a = agg.get(x["lcsc"])
        if a is None:
            a = agg[x["lcsc"]] = dict(lcsc=x["lcsc"], refs=[], values=[], qty=0, streams=[])
            seq.append(x["lcsc"])
        a["refs"].append(x["ref"]); a["qty"] += x["qty"]
        if x["value"] not in a["values"]: a["values"].append(x["value"])
    return [agg[c] for c in seq]


def build(data, L, B, pcb_rate):
    """The order for B boards: lines, fees, PCB, owner-fitted, totals. All money in CNY."""
    import bom
    flags = []
    per = min(B, bom.PER_ORDER_MAX)
    orders = math.ceil(B / per)
    rows = consolidate(L)
    n = {r["lcsc"]: r["qty"] for r in rows}
    parts = {c: bom.Part(data, c, flags) for c in n}
    jlc, unpriced = [], []
    for r in rows:
        p = parts[r["lcsc"]]
        pieces = per * r["qty"]
        if p.lad is None:
            unpriced.append(r["refs"]); unit = None
        else: unit = bom.tier(p.lad, pieces)
        cat = data.catalog.get(r["lcsc"], {})
        src = cat.get("ladder_cny_src", "") if cat.get("ladder_cny") else "D: international USD ladder x %.3f (no domestic ladder read); %s" % (
            bom.D_RATIO, data.intl.get(r["lcsc"], {}).get("url", "") + " read " + data.intl.get(r["lcsc"], {}).get("read_utc", "") + " UTC")
        jlc.append(dict(lcsc=r["lcsc"], refs=",".join(r["refs"]), value=" / ".join(r["values"]), pkg=p.pkg, cls="Basic" if p.cls == "base" else "Extended",
                        qty=r["qty"], joints=p.joints or 0, leadless=p.leadless, pieces_per_order=pieces, unit=unit, derived=p.derived,
                        ext_board=None if unit is None else unit * r["qty"], ext_total=None if unit is None else unit * r["qty"] * B,
                        source=src, mfr=p.mfr))
    ext = [j for j in jlc if j["cls"] == "Extended"]
    load_order = min(bom.LOAD * len(ext), bom.LOAD_CAP)
    joints_board = sum(j["joints"] * j["qty"] for j in jlc)
    placements = sum(j["qty"] for j in jlc)
    def xr(graduated): return orders * sum(bom.xray(per * j["qty"], graduated) for j in jlc if j["leadless"])
    xray_pieces = sum(per * j["qty"] for j in jlc if j["leadless"])
    area = bom.BOARD_MM[0] * bom.BOARD_MM[1] / 1e6
    pcb_order = bom.PCB_ENG + pcb_rate * per * area
    fees = [("setup (engineering) fee", "%d order(s) x %g CNY" % (orders, bom.SETUP), orders * bom.SETUP),
            ("stencil", "free on the Economic service (JLC SMT fee table, `whatif/bom.md` and v1 `bom.md` read 2026-11-11/12) *(check)*", 0.0),
            ("Extended-part loading fee", "%d Extended type(s) x %g CNY x %d order(s) (cap %g CNY per order)" % (len(ext), bom.LOAD, orders, bom.LOAD_CAP), orders * load_order),
            ("SMT joints", "%d joints per board x %d boards x %g CNY" % (joints_board, B, bom.JOINT), joints_board * B * bom.JOINT),
            ("X-ray, leadless parts (whole tier)", "%d pieces per order in %d order(s); 10 CNY each for 1-10 pieces, 5 CNY for 11-50" % (xray_pieces, orders), xr(False))]
    xray_grad = xr(True)
    # owner-fitted
    note = {r["ref"]: r["note"] for r in data.extra}
    owner, ownunp = [], []
    for x in L:
        if not x["include"] or x["block"] != "owner": continue
        o = dict(refs=x["ref"], value=x["value"], lcsc=x["lcsc"], qty=x["qty"], pkg="THT", cls="owner-fitted", unit=None, ext_total=None, source="")
        if x["lcsc"]:
            p = bom.Part(data, x["lcsc"], flags)
            if p.lad is not None:
                o["unit"] = bom.tier(p.lad, B * x["qty"]); o["pieces"] = B * x["qty"]
                cat = data.catalog.get(x["lcsc"], {}); o["source"] = cat.get("ladder_cny_src", "")
        elif x["fixed_usd"] is not None:
            o["unit"] = x["fixed_usd"] * bom.FX
            o["source"] = x.get("note") or note.get(x["ref"], "")
        if o["unit"] is None and not o["source"]:
            o["source"] = x.get("note") or note.get(x["ref"], "") or "UNPRICED"
        if o["unit"] is None: ownunp.append(o)
        else: o["ext_total"] = o["unit"] * x["qty"] * B
        owner.append(o)
    parts_total = sum(j["ext_total"] for j in jlc if j["ext_total"] is not None)
    fees_total = sum(f[2] for f in fees)
    pcb_total = pcb_order * orders
    jlc_total = parts_total + fees_total + pcb_total
    owner_total = sum(o["ext_total"] for o in owner if o["ext_total"] is not None)
    grand = jlc_total + owner_total
    return dict(B=B, per=per, orders=orders, jlc=jlc, fees=fees, pcb_order=pcb_order, pcb_total=pcb_total, area_cm2=area * 1e4, owner=owner,
                parts_total=parts_total, fees_total=fees_total, jlc_total=jlc_total, owner_total=owner_total, grand=grand, xray_grad_extra=xray_grad - xr(False),
                ext=[j["lcsc"] for j in ext], placements=placements, joints=joints_board, unpriced=unpriced, ownunp=ownunp, flags=flags, pcb_rate=pcb_rate)


# ------------------------------------------------------------------------------------------------ rendering
def usd(c):
    import bom
    return c / bom.FX


def money(c): return "%.2f CNY ($%.2f)" % (c, usd(c))


def csv_rows(name, o):
    import bom
    rows = []
    B = o["B"]
    for j in o["jlc"]:
        rows.append([name, B, "jlc-part", j["refs"], j["qty"], j["value"], j["pkg"], j["lcsc"], j["cls"], j["pieces_per_order"], "" if j["unit"] is None else "%.6f" % j["unit"],
                     "" if j["ext_total"] is None else "%.4f" % j["ext_total"], "UNPRICED *(check)*" if j["unit"] is None else ("D " if j["derived"] else "") + j["source"]])
    for lab, basis, v in o["fees"]:
        rows.append([name, B, "fee", lab, "", "", "", "", "", "", "", "%.4f" % v, basis])
    rows.append([name, B, "fee", "X-ray if charged tier by tier (extra over whole tier)", "", "", "", "", "", "", "", "%.4f" % o["xray_grad_extra"], "alternative; not in the total"])
    rows.append([name, B, "pcb", "PCB fabrication", "", "", "%g x %g mm 2-layer" % bom.BOARD_MM, "", "", "", "", "%.4f" % o["pcb_total"],
                 "%d order(s) x (20 CNY + %g CNY/m2 x %.2f cm2 x %d boards) *(check against the live quote)*" % (o["orders"], o["pcb_rate"], o["area_cm2"], o["per"])])
    for p in o["owner"]:
        rows.append([name, B, "owner-fitted", p["refs"], p["qty"], p["value"], p["pkg"], p["lcsc"], p["cls"], p.get("pieces", ""),
                     "" if p["unit"] is None else "%.6f" % p["unit"], "" if p["ext_total"] is None else "%.4f" % p["ext_total"], "UNPRICED *(check)*: " + p["source"] if p["unit"] is None else p["source"]])
    for lab, v in (("JLC parts", o["parts_total"]), ("JLC fees", o["fees_total"]), ("PCB", o["pcb_total"]), ("JLC order total (parts + fees + PCB)", o["jlc_total"]),
                   ("owner-fitted (priced lines only)", o["owner_total"]), ("ORDER TOTAL", o["grand"]), ("PER BOARD", o["grand"] / B)):
        rows.append([name, B, "total", lab, "", "", "", "", "", "", "", "%.4f" % v, ""])
    return rows


CSV_COLS = ["design", "boards", "section", "refs_or_item", "qty_per_board", "value", "package", "lcsc", "class", "pieces_per_order", "unit_cny", "extended_cny", "price_basis_or_source"]


def render(name, title, data, outs, extra_notes, dis=None):
    import bom
    w = []
    a = w.append
    a("# %s: purchasable order at 5 and 100 boards (JLC China Economic SMT, PCB included)\n" % title)
    if name == "v2":
        a("**Board:** %s. Upload files: `%s-bom.csv` and `%s-cpl.csv` beside this file.\n" % (IDENT_TEXT, IDENT, IDENT))
    a("Generated by `python3 -I v2/bom/bom.py --order` (engine `v2/bom/bom.py`, tables from `v2/bom/order.py`); rerun it rather than editing this file. "
      "CSV beside it: `order-5-100.csv`. Money is CNY, with USD at **%.4f CNY per USD** (Bank of China spot selling rate, 2026-11-12 05:30 Beijing; it moves daily *(check)*). "
      "Prices are domestic (jlc-smt.com) CNY ladders read 2026-11-11 to 2026-11-13, or the international USD ladder x %.3f where no domestic ladder was read (marked D); the "
      "Sources table gives each one's page and read date. No coupon, no shipping, no tax, no attrition (JLC's attrition rule for Extended parts of 8 pins or fewer is not in the totals *(check)*).\n" % (bom.FX, bom.D_RATIO))
    a("**Model.** One order takes at most %d boards (Economic PCBA), so 100 boards are two orders of 50. Parts are priced at the ladder tier holding (boards in one order) x "
      "(pieces per board); owner-fitted parts at the tier for (boards x pieces). Per order: setup %g CNY, stencil free, %g CNY loading per distinct Extended type (cap %g), "
      "%g CNY per SMT joint, X-ray per leadless piece (10 CNY each for 1-10 pieces, 5 CNY for 11-50), PCB %g CNY + %g CNY/m2 x board area. Board outline **%g x %g mm** "
      "(the board as built, `bom.BOARD_MM`). The fees are the engine's published-rule model (`bom.py`, `whatif/bom.md`), not a live JLC quote *(check in the live calculator before ordering)*.\n" % (
          bom.PER_ORDER_MAX, bom.SETUP, bom.LOAD, bom.LOAD_CAP, bom.JOINT, bom.PCB_ENG, outs[5]["pcb_rate"], bom.BOARD_MM[0], bom.BOARD_MM[1]))
    a("## Headline\n")
    a("| | 5 boards (1 order of 5) | 100 boards (2 orders of 50) |\n|---|---|---|")
    for lab, k in (("parts (JLC-assembled)", "parts_total"), ("JLC fees (setup, loading, joints, X-ray)", "fees_total"), ("PCB fabrication", "pcb_total"),
                   ("**JLC order total**", "jlc_total"), ("owner-fitted parts (priced lines only)", "owner_total"), ("**ORDER TOTAL**", "grand")):
        a("| %s | %s | %s |" % (lab, money(outs[5][k]), money(outs[100][k])))
    a("| **per board** | **%s** | **%s** |" % (money(outs[5]["grand"] / 5), money(outs[100]["grand"] / 100)))
    a("| per board, JLC side only (parts + fees + PCB) | %s | %s |" % (money(outs[5]["jlc_total"] / 5), money(outs[100]["jlc_total"] / 100)))
    a("| if X-ray is charged tier by tier instead of the whole tier (extra) | +%s | +%s |" % (money(outs[5]["xray_grad_extra"]), money(outs[100]["xray_grad_extra"])))
    a("| JLC placements / SMT joints per board | %d / %d | %d / %d |" % (outs[5]["placements"], outs[5]["joints"], outs[100]["placements"], outs[100]["joints"]))
    a("| distinct Extended types | %d | %d |\n" % (len(outs[5]["ext"]), len(outs[100]["ext"])))
    for B in VOLUMES:
        o = outs[B]
        a("## %d boards (%d order(s) of %d)\n" % (B, o["orders"], o["per"]))
        a("### JLC-assembled parts\n")
        a("`qty` = pieces per board; unit price is the tier holding %d x qty pieces (one order); extended = unit x qty x %d boards.\n" % (o["per"], B))
        a("| refs | qty/board | value | package | LCSC | class | unit CNY | extended CNY |\n|---|---|---|---|---|---|---|---|")
        for j in o["jlc"]:
            a("| %s | %d | %s | %s | %s | %s | %s | %s |" % (j["refs"], j["qty"], j["value"], j["pkg"], j["lcsc"], j["cls"],
                ("%.4f%s" % (j["unit"], " D" if j["derived"] else "")) if j["unit"] is not None else "UNPRICED *(check)*",
                "%.2f" % j["ext_total"] if j["ext_total"] is not None else ""))
        a("| **parts total** | | | | | | | **%.2f** |\n" % o["parts_total"])
        a("### Assembly fees and PCB\n")
        a("| item | basis | CNY |\n|---|---|---|")
        for lab, basis, v in o["fees"]: a("| %s | %s | %.2f |" % (lab, basis, v))
        a("| **fees total** | | **%.2f** |" % o["fees_total"])
        a("| PCB fabrication (%g x %g mm, 2-layer 1.6 mm) | %d order(s) x (%g CNY + %g CNY/m2 x %.2f cm2 x %d boards) = %.2f CNY per order; a published rule, not a quote *(check)* | %.2f |" % (
            bom.BOARD_MM[0], bom.BOARD_MM[1], o["orders"], bom.PCB_ENG, o["pcb_rate"], o["area_cm2"], o["per"], o["pcb_order"], o["pcb_total"]))
        a("| **JLC order total (parts + fees + PCB)** | | **%.2f** |\n" % o["jlc_total"])
        a("### Owner-fitted parts (not assembled by JLC; no loading or joint fee)\n")
        a("| refs | qty/board | part | LCSC | unit CNY | extended CNY | price basis |\n|---|---|---|---|---|---|---|")
        for p in o["owner"]:
            a("| %s | %d | %s | %s | %s | %s | %s |" % (p["refs"], p["qty"], p["value"], p["lcsc"] or "-", "%.4f" % p["unit"] if p["unit"] is not None else "UNPRICED *(check)*",
                "%.2f" % p["ext_total"] if p["ext_total"] is not None else "", (p["source"] or "")[:300]))
        a("| **owner-fitted total, priced lines** | | | | | **%.2f** | |\n" % o["owner_total"])
        a("### Totals\n")
        a("| | CNY | USD |\n|---|---|---|")
        for lab, v in (("JLC order total", o["jlc_total"]), ("owner-fitted (priced lines)", o["owner_total"]), ("**ORDER TOTAL**", o["grand"]), ("**per board = total / %d**" % B, o["grand"] / B)):
            a("| %s | %.2f | %.2f |" % (lab, v, usd(v)))
        a("")
    a("## Unpriced items (NOT in any total)\n")
    unp = [p for p in outs[5]["owner"] if p["unit"] is None]
    for p in unp: a("- %s (%s x%d): %s *(check)*" % (p["refs"], p["value"], p["qty"], p["source"]))
    for u in outs[5]["unpriced"]: a("- JLC part with no price: %s" % u)
    if not unp and not outs[5]["unpriced"]: a("- none")
    a("")
    if dis is not None:
        a("## Disagreements between the version 1 design and its plain-text BOM\n")
        for d in dis: a("- " + d)
        a("")
    a("## Notes and flags\n")
    for t in extra_notes: a("- " + t)
    for f in outs[5]["flags"] + [x for x in outs[100]["flags"] if x not in outs[5]["flags"]]: a("- engine flag: " + f)
    a("")
    a("## Sources: price, read date, class\n")
    a("| LCSC | part | class | ladder source (page, read date) |\n|---|---|---|---|")
    for j in outs[5]["jlc"]: a("| %s | %s | %s | %s |" % (j["lcsc"], j["mfr"] or j["value"], j["cls"], j["source"]))
    for p in outs[5]["owner"]:
        if p["lcsc"] or p["unit"] is not None: a("| %s | %s | owner-fitted | %s |" % (p["lcsc"] or "-", p["value"], (p["source"] or "")[:400]))
    a("")
    return "\n".join(w) + "\n"


def write_design(name, title, data, L, pcb_rate, md_path, extra_notes, dis=None):
    import bom
    outs = {B: build(data, L, B, pcb_rate) for B in VOLUMES}
    md = render(name, title, data, outs, extra_notes, dis)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path + ".md", "w", newline="") as f: f.write(md)
    with open(md_path + ".csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(CSV_COLS)
        for B in VOLUMES: w.writerows(csv_rows(name, outs[B]))
    return outs


def write_all(data, out_v2=None, out_v1=None, board=None):
    """Regenerate every order file and JLC upload file. Returns {design: {B: order}}."""
    import bom
    board = board or BOARD_V2
    o2 = out_v2 or OUT_V2
    o1 = out_v1 or OUT_V1
    fps = read_board(board)
    smt = smt_rows(fps)
    own = [p for p in fps if p["fitted"] == "owner"]
    L2 = lines_from_rows(smt) + owner_lines(data, own)
    # root cause, disclosed: the engine's own v2 lists (stream parts.csv + extra.csv) against the board, per LCSC
    eng = {}
    for x in bom.lines(data, []):
        if x["include"] and x["lcsc"] and x["block"] != "owner": eng[x["lcsc"]] = eng.get(x["lcsc"], 0) + x["qty"]
    brd = {}
    for p in smt: brd[p["lcsc"]] = brd.get(p["lcsc"], 0) + 1
    diffs = ["%s: board %d, engine lists %d (%+d)" % (c, brd.get(c, 0), eng.get(c, 0), brd.get(c, 0) - eng.get(c, 0)) for c in sorted(set(brd) | set(eng), key=lambda c: int(c[1:]))
             if brd.get(c, 0) != eng.get(c, 0)]
    dnp = [p for p in fps if p["fitted"] == "JLC" and p["dnp"]]
    notes2 = ["**Source: the final board.** Lines are the footprints of `v2/layout/integrated/afe-v2-integrated.kicad_pcb` with `Fitted by = JLC` and not DNP (%d footprints), "
              "grouped by the board's LCSC field, designators in the board's own numbering. Owner-fitted footprints (`Fitted by = owner`, %d) are the owner table; test points are not parts. "
              "DNP, not ordered: %s." % (len(smt), len(own), ", ".join("%s %s" % (p["ref"], p["value"]) for p in dnp) or "none"),
              "**Why the earlier order table lacked the 13 bridges:** the engine's v2 lists (the three streams' `parts.csv` plus `extra.csv`) are the schematic-era block lists and "
              "carry no 0 ohm bridge BR101-BR511 (they are layout objects, `v2/kicad/design.py` `BRIDGES`), so C21189 was never summed. The order now comes from the board. "
              "Engine lists against the board, per LCSC (the schematic-era lists differ from the board in): %s." % ("; ".join(diffs) or "no difference"),
              "Prices and fees are the engine's (ladders in `catalog.csv` / `intl.csv`, fee model in `bom.py`); only the part list changed.",
              "Owner-fitted headers are a retail listing (EUR, no quantity break, shipping excluded), the BNC a domestic ladder; the M2.5 standoffs and screws, and J501 (CAL pin strip), "
              "have no priced part in the repo and are unpriced.",
              "PCB at 410 CNY/m2 (jlc.com notice of 2026-09-21, read 2026-11-12) + 20 CNY engineering fee over the board outline (`bom.BOARD_MM`, the board as built). A special 20 CNY prototype order "
              "(<= 10 cm, 5-10 boards, `server_guide_4114`) was read for v1 but its fit with an SMT order is not stated, so it is not used *(check)*.",
              "**JLC upload files** from the same board: `%s-bom.csv` (Comment, Designator, Footprint, LCSC Part #) and `%s-cpl.csv` (Designator, Mid X, Mid Y, Layer, Rotation); owner-fitted, "
              "DNP and test-point footprints are in neither. CPL: positions in mm with Y negated and the board's absolute origin (KiCad position-file / Fabrication Toolkit convention), rotation KiCad's "
              "unmodified; JLC's per-package rotation corrections and the Mid X/Y origin were not verified against JLC's viewer *(check)*." % (IDENT, IDENT)]
    r2 = write_design("v2", "AFE version 2", data, L2, bom.PCB_RATE, o2, notes2)
    for nm, txt in (("%s-bom.csv" % IDENT, jlc_bom_csv(smt)), ("%s-cpl.csv" % IDENT, jlc_cpl_csv(smt))):
        with open(os.path.join(os.path.dirname(o2), nm), "w", newline="") as f: f.write(txt)
    f1 = []
    L1, dis, bt, v1jlc = v1_lines(data, f1)
    # held against bom.txt: its own unit prices at 20 and 100 boards against the engine's ladders at the same tiers
    for c, b in sorted(bt.items(), key=lambda kv: int(kv[0][1:])):
        p = bom.Part(data, c, [])
        if p.lad is None: dis.append("%s: bom.txt prices it, the engine has no ladder" % c); continue
        u20, u100 = bom.tier(p.lad, 20 * b["qty"]), bom.tier(p.lad, 50 * b["qty"])
        if abs(u20 - b["cny20"]) > 5e-5 or abs(u100 - b["cny100"]) > 5e-5:
            dis.append("%s (%s): bom.txt unit price %.4f @20 / %.4f @100 CNY, the engine's ladder gives %.4f / %.4f (%s)" % (
                c, b["name"], b["cny20"], b["cny100"], u20, u100, "engine: " + (data.catalog.get(c, {}).get("ladder_cny_src", "") or "international x 6.118")[:120]))
    dis.append("bom.txt's own PCB line uses 370 CNY/m2 (the 2026-09-14 price); the order files use 410 CNY/m2 (jlc.com notice of 2026-09-21, read 2026-11-12), as the version 2 order does.")
    dis.append("bom.txt prices the owner-fitted standoff as M3 x 8 (C66568) and screws M3 x 5 (C357542), and the headers at a $2.50 placeholder; the design has MH601 and MH602 as "
               "M2.5 standoffs. The order files follow the design: M2.5 standoff and screw unpriced, the headers priced as in the version 2 order (retail listing).")
    dis.append("bom.txt's first header lines say its totals 'predate the 3 REFCAL bridges' (stale); its per-line quantities already carry all 16 0 ohm bridges and match the design.")
    notes1 = ["Version 1 lines come from `v1-input/design-parts.csv` (kicad/design.py of the version 1 landing branch, whose designators are the board's; R109 removed, 16 pieces of 0 ohm Rb, 99 JLC placements); "
              "`v1-input/bom.txt` is a copy of that branch's bom.txt, used only for the disagreement check. The version 1 landing's `bom/v1/` files are read-only to this work and are not edited.",
              "**JLC upload files:** `jlc-bom.csv` (Comment, Designator, Footprint, LCSC Part #) is generated from design.py. **No `jlc-cpl.csv`: unavailable.** Version 1's final board is not on main or the "
              "landing branch yet (`kicad/wip/v1_merge5.kicad_pcb` still has R109), so there is no position source; it will be generated from the final board when it lands.",
              "The 0 ohm bridge C21189 now has a domestic ladder read 2026-11-13 (0.0124 CNY at 1 piece); version 1's bom.txt priced it at the 1 ohm ladder (0.0186) as a placeholder.",
              "Nine version 1 Basic resistor/capacitor ladders (C23024, C22978, C23046, C23196, C4190, C31850, C22797, C23242, C1658) are copied from version 1's bom.md (read "
              "2026-11-12); a re-read on 2026-11-13 met the bot challenge and stopped *(check)*.",
              "Stock was not read for any part *(check before ordering, ADS1115 and TPH2502 first)*."]
    r1 = write_design("v1", "AFE version 1", data, L1, bom.PCB_RATE, o1, notes1, dis)
    with open(os.path.join(os.path.dirname(o1), "jlc-bom.csv"), "w", newline="") as f: f.write(jlc_bom_csv(v1jlc))
    return dict(v2=r2, v1=r1, v1_disagreements=dis, v2_smt=smt, v2_engine_diffs=diffs)
