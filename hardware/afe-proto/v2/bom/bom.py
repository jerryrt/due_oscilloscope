"""AFE version 2 bill of materials: merge the stream parts lists, price them on the domestic service, write bom.md.

Run:  python3 -I bom.py [--md bom.md] [--quiet]        (stdlib only; numpy is not needed)

Inputs, all read every run so the totals follow the files:
  ../sim/scope/parts.csv  ../sim/awg/parts.csv  ../sim/powercal/parts.csv (absent until that stream writes one)
  extra.csv      what no stream lists (rails, reference, converter, ladder, sense network, owner-fitted parts).
                 A row with placeholder_for=<stream> is dropped as soon as that stream's parts.csv exists.
  blocks.csv     which cost block a stream's part belongs to (default: other)
  catalog.csv    package, joints, domestic class and any domestic CNY ladder that was read
  intl.csv       international class, stock and USD ladder, written by read_intl.py
  ../jlc-basic.csv  JLC Basic passives read from JLC's own pages
  v1.csv         version 1's parts by block (kept as data; no longer priced or reported)

Cost model = whatif/bom.md's domestic Economic model (it was reconciled against version 1 once; that comparison is no longer generated):
  parts at the price tier holding (boards in the order) x (quantity per board) pieces; 100 boards = two orders of 50;
  per order: setup 50 CNY, 20 CNY per distinct Extended type (cap 800), 0.01 CNY per SMT joint, X-ray per leadless
  piece (10 CNY for 1-10, 5 for 11-50), PCB 20 CNY + 370 CNY/m2; owner-fitted parts at the tier for (boards x quantity).
A part with no domestic ladder is priced as the international USD ladder x CNY_PER_USD_PART and is marked D."""
import argparse, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
FX = 6.6912                      # CNY per USD, Bank of China spot selling rate 2026-11-12 05:30 Beijing (whatif/bom.md)
D_RATIO = 6.118                  # domestic CNY = international USD x 6.118 on 22 of 23 types (whatif/bom.md)
SETUP, LOAD, LOAD_CAP, JOINT = 50.0, 20.0, 800.0, 0.01
XRAY = [(10, 10.0), (50, 5.0), (200, 3.0), (500, 2.0), (1000, 1.5), (3000, 1.0), (10 ** 9, 0.5)]   # up to n pieces: CNY each
PCB_ENG, PCB_RATE = 20.0, 410.0  # CNY per order, CNY per m2: 2-layer 1.6 mm. 410 = jlc.com news notice of 2026-09-21 (read 2026-11-12 15:56 UTC)
PCB_RATE_V1 = 370.0              # version 1 (whatif/bom.md) used the price after the 2026-09-14 cut; the 2026-09-21 notice raised it by 40
BOARD_MM = (100.0, 62.34)        # the outline as built: the overhang is 4.5 mm on both long edges (was 100 x 58.34, 100 x 53.34 before)
PER_ORDER_MAX = 50               # Economic PCBA takes 2-50 boards per order
BLOCKS = [("opamps", "Op-amps (ICs)"), ("precres", "Precision resistors"), ("switches", "Switches"),
          ("adc_ref", "Precision ADC and reference (ICs)"), ("ladder", "Calibration ladder"), ("rails", "Rails (LM27762, with its X-ray)"),
          ("midrail", "Scope mid-rail network"), ("other", "Everything else (decoupling, clamps, pulls, scope passives, AWG passives)"),
          ("setup", "Per-order setup fee"), ("pcb", "PCB"), ("owner", "Owner-fitted (BNCs, headers, standoff)")]
STREAMS = [("scope", "../sim/scope/parts.csv"), ("awg", "../sim/awg/parts.csv"), ("powercal", "../sim/powercal/parts.csv")]


def rd(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def ladder(s):
    out = []
    for t in (s or "").split(";"):
        if t:
            a, b = t.split(":")
            out.append((int(a), float(b)))
    return sorted(out)


def tier(lad, pieces):
    p = lad[0][1]
    for q, pr in lad:
        if q <= pieces: p = pr
    return p


def xray(k, graduated):
    if k <= 0: return 0.0
    if not graduated:
        return k * next(c for n, c in XRAY if k <= n)
    tot, lo = 0.0, 0
    for n, c in XRAY:
        tot += max(0, min(k, n) - lo) * c
        lo = n
        if k <= n: break
    return tot


class Data:
    """Everything read from disk; paths can be redirected for the self test."""
    def __init__(self, root=HERE, paths=None):
        self.root = root
        self.paths = dict(paths or {})
        g = lambda k, d: self.paths.get(k, os.path.join(root, d))
        self.catalog = {r["lcsc"]: r for r in rd(g("catalog", "catalog.csv"))}
        self.intl = {r["lcsc"]: r for r in rd(g("intl", "intl.csv"))}
        self.basic = {r["lcsc"]: r for r in rd(g("basic", "../jlc-basic.csv"))}
        self.rules = rd(g("blocks", "blocks.csv"))
        self.extra = rd(g("extra", "extra.csv"))
        self.v1 = rd(g("v1", "v1.csv"))
        self.streams = {}
        for name, rel in STREAMS:
            p = self.paths.get(name, os.path.join(root, rel))
            self.streams[name] = rd(p) if os.path.exists(p) else None


def block_of(data, stream, lcsc):
    for r in data.rules:
        if r["lcsc"] == lcsc and r["stream"] in (stream, "*"): return r["block"]
    return "other"


def lines(data, flags):
    """The consolidated per-line list for version 2: dicts with stream, ref, value, lcsc, role, qty, block, include, fixed_usd."""
    out, seen = [], set()
    for name, rows in data.streams.items():
        if rows is None: continue
        for r in rows:
            q = r.get("qty_per_board") or r.get("qty") or ""
            ref = r.get("refdes_per_channel") or r.get("refs") or r.get("ref") or ""
            L = dict(stream=name, ref=ref, value=r.get("value", ""), lcsc=(r.get("lcsc") or "").strip(), role=r.get("role", ""),
                     qty=int(q) if q.strip().isdigit() else None, include=True, fixed_usd=None, replaces="")
            key = (name, ref, L["value"], L["lcsc"], L["role"], q)
            if key in seen: flags.append("DUPLICATE LINE in %s: %s %s %s qty %s (counted twice)" % (name, ref, L["value"], L["lcsc"], q))
            seen.add(key)
            if L["qty"] is None: flags.append("BAD QUANTITY in %s: %s %r" % (name, ref, q)); L["qty"] = 0
            L["block"] = block_of(data, name, L["lcsc"])
            out.append(L)
    for r in data.extra:
        ph = r["placeholder_for"]
        if ph and data.streams.get(ph) is not None:
            flags.append("note: extra.csv row %s (%s x%s) dropped: %s/parts.csv exists and lists its own parts" % (r["ref"], r["value"], r["qty"], ph))
            continue
        q = r["qty"]
        out.append(dict(stream="extra" + ("(" + ph + " placeholder)" if ph else ""), ref=r["ref"], value=r["value"], lcsc=r["lcsc"].strip(),
                        role=r["role"], qty=int(q) if q.isdigit() else 0, block=r["block"], include=r["include"] == "yes",
                        fixed_usd=float(r["fixed_usd"]) if r["fixed_usd"] else None, replaces=r["replaces"]))
    return out


def v1_lines(data):
    return [dict(stream="v1", ref=r["ref"], value=r["value"], lcsc=r["lcsc"].strip(), role=r["role"], qty=int(r["qty"]), block=r["block"],
                 include=True, fixed_usd=float(r["fixed_usd"]) if r.get("fixed_usd") else None, replaces="") for r in data.v1]


class Part:
    """Price facts of one LCSC number."""
    def __init__(self, data, c, flags):
        self.c = c
        cat, il, bs = data.catalog.get(c), data.intl.get(c), data.basic.get(c)
        self.pkg = cat["package"] if cat else ""
        self.joints = int(cat["joints"]) if cat and cat["joints"] != "" else None
        self.leadless = bool(cat and cat["leadless"] == "1")
        self.intl_lib = il["library"] if il else None
        self.mfr = (il or {}).get("mfr", "")
        self.stock = (il or {}).get("stock", "")
        dom = (cat or {}).get("class_dom", "")
        self.in_basic_csv = bs is not None and bs.get("basic") == "yes"
        if not dom and bs is not None: dom = "base" if bs["domestic_library"] == "base" and bs["basic"] == "yes" else "expand"
        if not dom:
            dom = "expand"; flags.append("%s: domestic class not read; taken as Extended" % c)
        self.cls = dom
        if dom == "base" and not self.in_basic_csv:
            flags.append("%s is marked Basic but is not a Basic row of jlc-basic.csv (JLC's own pages)" % c)
        if self.intl_lib in ("base", "expand") and self.intl_lib != dom:
            flags.append("%s: class %s here but %s on jlcpcb.com (international API)" % (c, dom, self.intl_lib))
        if cat and cat["ladder_cny"]:
            self.lad, self.derived = ladder(cat["ladder_cny"]), "derived" in cat["ladder_cny_src"]
        elif il and il["ladder_usd"]:
            self.lad, self.derived = [(q, p * D_RATIO) for q, p in ladder(il["ladder_usd"])], True
        else:
            self.lad, self.derived = None, False
            flags.append("%s: NO PRICE (no domestic ladder, no international ladder)" % c)
        if self.joints is None and cat is None:
            flags.append("%s: not in catalog.csv (package and joints unknown)" % c)


def cost(data, L, boards, flags=None, graduated=False, pcb_rate=None):
    """Per-board cost in CNY, by block, for `boards` boards (one order up to 50, else orders of 50)."""
    flags = [] if flags is None else flags
    per = min(boards, PER_ORDER_MAX)
    parts = {}
    n = {}
    for x in L:
        if not x["include"] or not x["lcsc"]: continue
        n[x["lcsc"]] = n.get(x["lcsc"], 0) + x["qty"]
    for c in n: parts[c] = Part(data, c, flags)
    # class per type: Extended if any use is JLC-assembled
    jlc = {c: sum(x["qty"] for x in L if x["include"] and x["lcsc"] == c and x["block"] != "owner") for c in n}
    ext = sorted(c for c in n if jlc[c] > 0 and parts[c].cls == "expand")
    blk = {b: dict(parts=0.0, load=0.0, joints=0.0, xray=0.0, fixed=0.0) for b, _ in BLOCKS}
    unpriced = []
    for x in L:
        if not x["include"]: continue
        if not x["lcsc"]:
            if x["fixed_usd"] is not None: blk["owner"]["fixed"] += x["fixed_usd"] * FX * x["qty"]
            elif x["qty"] == 0 or x["block"] == "owner": unpriced.append(x)
            else: unpriced.append(x)
            continue
        p = parts[x["lcsc"]]
        if p.lad is None: unpriced.append(x); continue
        owner = x["block"] == "owner"
        pieces = (boards if owner else per) * n[x["lcsc"]]
        blk[x["block"]]["parts"] += x["qty"] * tier(p.lad, pieces)
        if not owner:
            if p.joints is not None: blk[x["block"]]["joints"] += JOINT * p.joints * x["qty"]
            if p.cls == "expand": blk[x["block"]]["load"] += LOAD * x["qty"] / jlc[x["lcsc"]] / per
            if p.leadless: blk[x["block"]]["xray"] += xray(per * x["qty"], graduated) / per
    loadcap = min(LOAD * len(ext), LOAD_CAP)
    if LOAD * len(ext) > LOAD_CAP:
        for b in blk: blk[b]["load"] *= LOAD_CAP / (LOAD * len(ext))
    blk["setup"]["fixed"] = SETUP / per
    blk["pcb"]["fixed"] = (PCB_ENG + (PCB_RATE if pcb_rate is None else pcb_rate) * per * BOARD_MM[0] * BOARD_MM[1] / 1e6) / per
    pl = sum(x["qty"] * (parts[x["lcsc"]].joints or 0) for x in L if x["include"] and x["lcsc"] and x["block"] != "owner")
    pcs = sum(x["qty"] for x in L if x["include"] and x["lcsc"] and x["block"] != "owner")
    xr = sum(per * x["qty"] for x in L if x["include"] and x["lcsc"] and x["block"] != "owner" and parts[x["lcsc"]].leadless)
    return dict(blk=blk, per=per, ext=ext, parts=parts, n=n, unpriced=unpriced, joints=pl, placements=pcs,
                loadcap=loadcap, xray_pieces=xr, graduated=graduated,
                total=sum(sum(v.values()) for v in blk.values()))


def block_total(c, b):
    return sum(c["blk"][b].values())


def derived_used(c, L):
    return sorted(k for k in c["parts"] if c["parts"][k].derived and k in c["n"] and any(x["lcsc"] == k and x["include"] for x in L))


def attrition(c, per):
    """JLC China's attrition (jlc-smt.com help 42767) for the Extended parts: extra pieces by pin count and unit price."""
    tot = 0.0
    for k in c["ext"]:
        p = c["parts"][k]
        if p.lad is None or p.joints is None or p.joints > 8: continue
        u = tier(p.lad, per * c["n"][k])
        if p.joints <= 2: ex = 10 if u < .1 else 8 if u < .2 else 4 if u < .5 else 2 if u < 1 else 0
        else: ex = 5 if u < .2 else 4 if u < .5 else 2 if u < 1 else 0
        tot += ex * u
    return tot


def usd(cny): return cny / FX


def run(data):
    flags = []
    L = lines(data, flags)
    res = {}
    for B in (20, 100):
        f = []
        res[B] = dict(lo=cost(data, L, B, f, False), hi=cost(data, L, B, None, True))
        flags.extend(x for x in f if x not in flags)
    # not-included rows: delta of switching them on (and their `replaces` off)
    deltas = []
    for x in L:
        if x["include"]: continue
        L2 = [dict(y, include=True) if y is x else (dict(y, include=False) if x["replaces"] and y["ref"] == x["replaces"] else y) for y in L]
        d = {B: cost(data, L2, B, [], False)["total"] - res[B]["lo"]["total"] for B in (20, 100)}
        deltas.append((x, d))
    return L, res, deltas, flags


def run_board(data, board=None):
    """Same shape as run(), for the lines of the final board (order.py's source): the footprints Fitted by JLC and not DNP, the owner-fitted footprints, and
    extra.csv's include = no alternatives as switch-on deltas."""
    import order
    fps = order.read_board(board or order.BOARD_V2)
    L = order.lines_from_rows(order.smt_rows(fps)) + order.owner_lines(data, [p for p in fps if p["fitted"] == "owner"])
    for r in data.extra:
        if r["include"] != "yes" and r["lcsc"] and not r["placeholder_for"]:
            L.append(dict(stream="extra", ref=r["ref"], value=r["value"], lcsc=r["lcsc"].strip(), role=r["role"], qty=int(r["qty"]), block=r["block"], include=False,
                          fixed_usd=None, replaces=r["replaces"]))
    flags, res = [], {}
    for B in (20, 100):
        f = []
        res[B] = dict(lo=cost(data, L, B, f, False), hi=cost(data, L, B, None, True))
        flags.extend(x for x in f if x not in flags)
    deltas = []
    for x in L:
        if x["include"]: continue
        L2 = [dict(y, include=True) if y is x else (dict(y, include=False) if x["replaces"] and y["ref"] == x["replaces"] else y) for y in L]
        deltas.append((x, {B: cost(data, L2, B, [], False)["total"] - res[B]["lo"]["total"] for B in (20, 100)}))
    return L, res, deltas, flags


def v1_run(data):
    L = v1_lines(data)
    return L, {B: dict(lo=cost(data, L, B, [], False, pcb_rate=PCB_RATE_V1), hi=cost(data, L, B, None, True, pcb_rate=PCB_RATE_V1)) for B in (20, 100)}


# ------------------------------------------------------------------------------------------------ report
def fmt(x, n=2): return ("%." + str(n) + "f") % x


def block_rows(res1, res2, B):
    rows = []
    for b, name in BLOCKS:
        a, c = block_total(res1[B]["lo"], b), block_total(res2[B]["lo"], b)
        rows.append((b, name, usd(a), usd(c), usd(c - a)))
    return rows


def consolidated(L, c):
    """One row per LCSC: n, placements, function summary."""
    agg = {}
    for x in L:
        if not x["include"] or not x["lcsc"]: continue
        a = agg.setdefault(x["lcsc"], dict(n=0, refs=[], value=x["value"], blocks=set()))
        a["n"] += x["qty"]
        a["refs"].append("%s %s x%d" % (x["stream"], x["ref"], x["qty"]))
        a["blocks"].add(x["block"])
    return agg


def report(data, L, res, deltas, flags, args):
    o = []
    w = o.append
    r20, r100 = res[20], res[100]
    lo20, hi20, lo100, hi100 = r20["lo"], r20["hi"], r100["lo"], r100["hi"]
    own = lambda c: usd(block_total(c, "owner"))
    jlc = lambda c: usd(c["total"] - block_total(c, "owner"))
    w("# AFE version 2 bill of materials and cost, per board and per order (domestic order)\n")
    w("Generated by `v2/bom/bom.py` (`python3 -I bom.py --md bom.md`) from **the final board's footprints** (`v2/layout/integrated/afe-v2-integrated.kicad_pcb`: Fitted by JLC, not DNP, "
      "grouped by the LCSC field; the same lines as `order-5-100.md`, which is the purchasable table at 5 and 100 boards with the JLC BOM/CPL uploads) and `extra.csv`, `catalog.csv`, `intl.csv` and "
      "`../jlc-basic.csv`; rerun the script rather than editing this file. The method is `whatif/bom.md`'s domestic model "
      "(JLC China Economic SMT, PCB included, owner-fitted parts separate); "
      "version 2 only.\n")
    w("**Part list:** %d JLC-assembled footprints per board in the board's own designators (%d distinct LCSC numbers); the schematic-era stream lists (`parts.csv`) are not used here.\n" % (
        sum(x["qty"] for x in L if x["include"] and x["lcsc"] and x["block"] != "owner"), len({x["lcsc"] for x in L if x["include"] and x["lcsc"] and x["block"] != "owner"})))
    w("What is still a placeholder: the owner-fitted header set (a retail listing, tail length *(check)*), the M2.5 standoffs and screws and the CAL pin strip (unpriced), "
      "every price marked D, the PCB (published rule, no quote), and the `include = no` rows in \"Not included\".\n")
    w("## Cost summary\n")
    w("Exchange rate **%.4f CNY per USD** (Bank of China spot selling rate, 2026-11-12 05:30 Beijing, the rate `whatif/bom.md` used; "
      "it moves daily *(check)*). Fees per order: setup %g CNY, %g CNY per distinct Extended type (cap %g), %g CNY per SMT joint, "
      "X-ray 10 CNY per leadless piece for 1-10 pieces and 5 CNY for 11-50; PCB %g CNY + %g CNY/m2 over %g x %g mm. 100 boards are two "
      "orders of 50. Where two figures are given the X-ray is priced wholly at its tier / tier by tier (neither price page says which "
      "*(check)*).\n" % (FX, SETUP, LOAD, LOAD_CAP, JOINT, PCB_ENG, PCB_RATE, BOARD_MM[0], BOARD_MM[1]))
    w("| per board | 20 boards (1 order) | 100 boards (2 x 50) |\n|---|---|---|")
    pb = lambda r, k: sum(v[k] for b, v in r["blk"].items() if b != "owner")
    w("| parts | %.2f CNY = $%.2f | %.2f CNY = $%.2f |" % (pb(lo20, "parts"), usd(pb(lo20, "parts")), pb(lo100, "parts"), usd(pb(lo100, "parts"))))
    fee = lambda r: (r["total"] - block_total(r, "owner") - pb(r, "parts") - block_total(r, "pcb")) * r["per"]
    w("| JLC fees per order | %.2f / %.2f CNY | %.2f / %.2f CNY |" % (fee(lo20), fee(hi20), fee(lo100), fee(hi100)))
    w("| PCB per order | %.2f CNY | %.2f CNY |" % (block_total(lo20, "pcb") * 20, block_total(lo100, "pcb") * 50))
    w("| **JLC + PCB per board** | **$%.2f / $%.2f** | **$%.2f / $%.2f** |" % (jlc(lo20), jlc(hi20), jlc(lo100), jlc(hi100)))
    w("| owner-fitted per board (BNC and retail headers; M2.5 hardware and the CAL strip unpriced *(check)*) | $%.2f | $%.2f |" % (own(lo20), own(lo100)))
    w("| **TOTAL per board, PCB and owner-fitted included** | **$%.2f / $%.2f** | **$%.2f / $%.2f** |" % (usd(lo20["total"]), usd(hi20["total"]), usd(lo100["total"]), usd(hi100["total"])))
    w("| total per batch | $%.2f / $%.2f | $%.2f / $%.2f |" % (usd(lo20["total"]) * 20, usd(hi20["total"]) * 20, usd(lo100["total"]) * 100, usd(hi100["total"]) * 100))
    w("| JLC placements / SMT joints per board | %d / %d | same |" % (lo20["placements"], lo20["joints"]))
    w("| distinct Extended types (loading fee each) | %d | same |" % len(lo20["ext"]))
    unp = lo20["unpriced"]
    w("\nUnpriced lines are NOT in these totals: %s.\n" % ("; ".join("%s %s (%s)" % (x["ref"], x["value"], x["role"][:50]) for x in unp) or "none"))
    dep = derived_used(lo20, L)
    w("Prices marked **D** have no domestic ladder read, so they are the international USD ladder times %.3f (%d part(s) this run). All other JLC-assembled parts use a "
      "domestic ladder read from `jlc-smt.com` (`read_dom.py`; dates in the sources table).\n" % (D_RATIO, len(dep)))
    # bound: price D parts at +-1 % ? simply report the share of parts cost that is D
    dshare = sum(x["qty"] * tier(lo20["parts"][x["lcsc"]].lad, 20 * lo20["n"][x["lcsc"]]) for x in L if x["include"] and x["lcsc"] and x["block"] != "owner" and x["lcsc"] in dep)
    w("Parts cost per board at 20 boards resting on D prices: %.2f CNY of %.2f CNY (%.0f %%).\n" % (dshare, pb(lo20, "parts"), 100 * dshare / pb(lo20, "parts")))

    agg = consolidated(L, lo20)
    # ---- sections the BOM gate asks for
    def split(c, B):
        per, rd_, dv, intl = c["per"], 0.0, 0.0, 0.0
        for x in L:
            if not x["include"] or not x["lcsc"] or x["block"] == "owner" or c["parts"][x["lcsc"]].lad is None: continue
            p = c["parts"][x["lcsc"]]; u = tier(p.lad, per * c["n"][x["lcsc"]])
            if p.derived: dv += x["qty"] * u
            else: rd_ += x["qty"] * u
            il = data.intl.get(x["lcsc"], {}).get("ladder_usd")
            if il: intl += x["qty"] * tier(ladder(il), per * c["n"][x["lcsc"]])
        return rd_, dv, intl
    w("## Price basis: domestic-read against international-based (parts bought by JLC, per board)\n")
    w("*Domestic-read* parts have a CNY ladder read from the domestic part page (`whatif/bom.md`, 2026-11-11). *Derived* parts have only the international USD ladder "
      "(read from jlcpcb.com on 2026-11-12, 14:54-15:55 UTC) times %.3f. *International price* is the same parts at the international USD tiers with no conversion, for comparison.\n" % D_RATIO)
    w("| per board | 20 boards | 100 boards |\n|---|---|---|")
    s20, s100 = split(lo20, 20), split(lo100, 100)
    w("| parts, domestic ladder read | %.2f CNY = $%.2f | %.2f CNY = $%.2f |" % (s20[0], usd(s20[0]), s100[0], usd(s100[0])))
    w("| parts, derived (international x %.3f) | %.2f CNY = $%.2f | %.2f CNY = $%.2f |" % (D_RATIO, s20[1], usd(s20[1]), s100[1], usd(s100[1])))
    w("| **parts, total (what the totals use)** | **%.2f CNY = $%.2f** | **%.2f CNY = $%.2f** |" % (s20[0] + s20[1], usd(s20[0] + s20[1]), s100[0] + s100[1], usd(s100[0] + s100[1])))
    w("| the same parts at international USD prices | $%.2f | $%.2f |" % (s20[2], s100[2]))
    dread = sorted(k for k in agg if not lo20["parts"][k].derived and any(x["lcsc"] == k and x["block"] != "owner" for x in L if x["include"]))
    ddev = sorted(k for k in agg if lo20["parts"][k].derived and any(x["lcsc"] == k and x["block"] != "owner" for x in L if x["include"]))
    w("\nDomestic-read parts: %s.\n\nDerived (D) parts: %s.\n" % (", ".join(dread), ", ".join(ddev)))
    w("## PCB, as its own line\n")
    ar = BOARD_MM[0] * BOARD_MM[1] / 1e6
    w("| | 20 boards | 100 boards (2 x 50) |\n|---|---|---|")
    w("| per order | %.2f CNY = $%.2f | %.2f CNY = $%.2f each |" % (PCB_ENG + PCB_RATE * 20 * ar, usd(PCB_ENG + PCB_RATE * 20 * ar), PCB_ENG + PCB_RATE * 50 * ar, usd(PCB_ENG + PCB_RATE * 50 * ar)))
    w("| per board | $%.2f | $%.2f |" % (usd(block_total(lo20, "pcb")), usd(block_total(lo100, "pcb"))))
    w("\n**A published rule, not a quote.** Engineering fee %g CNY + %g CNY/m2 over %g x %g mm (%.2f cm2 a board), 2-layer, 1.6 mm. The %g CNY/m2 is the jlc.com news notice "
      "of 2026-09-21 (<https://www.jlc.com/portal/q33i63612.html>, its \"latest news\" column: single and double-sided boards raised 40 CNY/m2 to 410 CNY/m2, A1 board, 1.6 mm, "
      "\"final price per the system's live quote\"), read 2026-11-12 15:56 UTC; the page loaded normally, no bot challenge. The 20 CNY engineering fee is `whatif/bom.md`'s "
      "reading of `server_guide_4114` (2026-11-11) and was not re-read. The live quote page computes in the browser and was not read.\n" % (PCB_ENG, PCB_RATE, BOARD_MM[0], BOARD_MM[1], ar * 1e4, PCB_RATE))
    w("## Hand-soldered parts, as their own line\n")
    w("Not assembled by JLC: no loading fee, no joint fee. Bought as loose parts; tier for (boards x quantity) pieces.\n")
    w("**The 86 pass-through header joints are the owner's largest assembly task** (the BNCs and the CAL header come on top). The header price is a retail listing and its tail length is *(check)*: a set whose tails are too short will not stack into the Due's sockets, and that is the one way this line goes wrong.\n")
    w("| ref | part | LCSC | qty | $ per board @20 | $ per board @100 | price basis |\n|---|---|---|---|---|---|---|")
    to20 = to100 = 0.0
    for x in L:
        if x["block"] != "owner" or not x["include"]: continue
        if x["lcsc"]:
            p = lo20["parts"][x["lcsc"]]
            n_ = lo20["n"][x["lcsc"]]
            u20, u100 = tier(p.lad, 20 * n_), tier(p.lad, 100 * n_)
            b20, b100 = usd(x["qty"] * u20), usd(x["qty"] * u100)
            basis = "domestic ladder read 2026-11-11 (whatif/bom.md)" if not p.derived else "D"
        elif x["fixed_usd"] is not None:
            b20 = b100 = x["fixed_usd"] * x["qty"]; basis = x.get("note") or "fixed price"
        else:
            b20 = b100 = 0.0; basis = "UNPRICED"
        to20 += b20; to100 += b100
        w("| %s | %s | %s | %d | %.4f | %.4f | %s |" % (x["ref"], x["value"], x["lcsc"] or "-", x["qty"], b20, b100, basis))
    w("| **total** | | | | **%.2f** | **%.2f** | |\n" % (to20, to100))
    w("## Part-type count and loading fees\n")
    nb = len([k for k in lo20["n"] if lo20["parts"][k].cls == "base" and any(x["lcsc"] == k and x["block"] != "owner" for x in L if x["include"])])
    w("JLC-assembled part types: **%d** (%d Extended, %d Basic). Hand-fitted types: %d. Each Extended type costs %g CNY per order (cap %g):\n" % (
        len(lo20["ext"]) + nb, len(lo20["ext"]), nb, len([k for k in lo20["n"] if any(x["lcsc"] == k and x["block"] == "owner" for x in L if x["include"])]), LOAD, LOAD_CAP))
    w("| LCSC | part | package | n | fee per order | per board @20 | per board @100 |\n|---|---|---|---|---|---|---|")
    for k in lo20["ext"]:
        p = lo20["parts"][k]
        w("| %s | %s | %s | %d | %g CNY | $%.3f | $%.3f |" % (k, p.mfr, p.pkg, lo20["n"][k], LOAD, usd(LOAD / 20), usd(LOAD / 50)))
    w("| **total** | | | | **%g CNY** | **$%.2f** | **$%.2f** |\n" % (LOAD * len(lo20["ext"]), usd(LOAD * len(lo20["ext"]) / 20), usd(LOAD * len(lo20["ext"]) / 50)))

    w("## Cost target (D-V2-1)\n")
    w("The target is the owner's and is left blank here. Version 2 is **$%.2f / $%.2f at 20 boards and $%.2f / $%.2f at 100**.\n\n"
      "| D-V2-1 | owner's per-board target | _owner to set_ |\n|---|---|---|\n" % (usd(lo20["total"]), usd(hi20["total"]), usd(lo100["total"]), usd(hi100["total"])))

    w("## Part types (consolidated, one row per LCSC number)\n")
    w("`n` = placements per board; unit prices are the tier holding 20 x n pieces (boards) or 50 x n pieces (100 boards: two orders) "
      "for JLC-assembled parts and 20 x n / 100 x n for owner-fitted parts, in CNY; **D** = derived from the international ladder. "
      "Class is the domestic class (E = Extended, B = Basic), Basic only when `jlc-basic.csv` (JLC's own part pages) says so.\n")
    w("| LCSC | part | pkg | class | n | joints | function: lines | unit @20 | unit @100 | CNY/board @20 | CNY/board @100 | stock (intl, 2026-11-12) |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    agg = consolidated(L, lo20)
    order = sorted(agg, key=lambda k: (lo20["parts"][k].cls != "base", -agg[k]["n"] * (tier(lo20["parts"][k].lad, 20 * agg[k]["n"]) if lo20["parts"][k].lad else 0)))
    for k in order:
        p, a = lo20["parts"][k], agg[k]
        owner = a["blocks"] == {"owner"}
        u20 = tier(p.lad, (20 if owner else 20) * a["n"]) if p.lad else None
        u100 = tier(p.lad, (100 if owner else 50) * a["n"]) if p.lad else None
        d = " D" if p.derived else ""
        fn = "; ".join(a["refs"])
        w("| %s | %s | %s | %s | %d | %s | %s | %s%s | %s%s | %s | %s | %s |" % (
            k, p.mfr or a["value"], p.pkg, "B" if p.cls == "base" else "E", a["n"], p.joints if p.joints is not None else "",
            fn[:150], fmt(u20, 4) if u20 else "", d if u20 else "", fmt(u100, 4) if u100 else "", d if u100 else "",
            fmt(a["n"] * u20, 4) if u20 else "", fmt(a["n"] * u100, 4) if u100 else "", p.stock))
    w("\nExtended types (a loading fee each, per order): " + ", ".join(lo20["ext"]) + ".\n")

    w("## Not included (rows with include = no in `extra.csv`)\n")
    w("Version 1 parts the version 2 lists do not carry, and an alternative; switching one on changes the total per board by:\n")
    w("| ref | part | LCSC | qty | what | delta @20 | delta @100 |\n|---|---|---|---|---|---|---|")
    for x, d in deltas:
        w("| %s | %s | %s | %d | %s | $%+.2f | $%+.2f |" % (x["ref"], x["value"], x["lcsc"], x["qty"], x["role"], usd(d[20]), usd(d[100])))
    w("")

    w("## Flags (the tool's own checks)\n")
    if flags:
        for f in flags: w("- " + f)
    else: w("- none")
    w("")

    w("## Sources: what each price is and when it was read\n")
    w("| LCSC | part | domestic price | read from | international ladder read (UTC) from |\n|---|---|---|---|---|")
    for k in sorted(agg, key=lambda c: int(c[1:])):
        p = lo20["parts"][k]
        cat, il = data.catalog.get(k, {}), data.intl.get(k, {})
        src = cat.get("ladder_cny_src", "") if cat.get("ladder_cny") else "**D**: international ladder x %.3f, no domestic ladder read" % D_RATIO
        w("| %s | %s | %s | %s | %s %s |" % (k, p.mfr, "read" if cat.get("ladder_cny") and not p.derived else "derived", src, il.get("read_utc", ""), il.get("url", "")))
    w("")
    w("## What could not be read\n")
    w("- **Domestic JLC part pages** (`https://www.jlc-smt.com/lcsc/detail/<C>.html`) answered with an anti-bot page to four plain requests at 2026-11-12 14:50 UTC "
      "(not worked around). At about 16:04 UTC the same plain request returned the record, and `read_dom.py` then read the ladder and library class of every "
      "catalog part that had no domestic ladder, 3 s apart, stopping at the first challenge. Parts whose ladder was read on 2026-11-11 (version 1's list) keep those.\n")
    w("- **TPH2502 (C118223)** and **ADS1115 (C37593)** are now domestic-read: both Extended on `jlc-smt.com`.\n")
    w("- **Stock** is the international API's `stockCount` at 2026-11-12 14:55 UTC; the domestic record carries none: ADS1115 16,705, TPH2502 3,263, "
      "REF3030E 975, LM27762 40,693 against 100 of each needed for 100 boards *(check before ordering)*.\n")
    w("- **PCB**: no quote was read; see the PCB section (published rule, 410 CNY/m2 + 20 CNY) *(check in the live quote)*. "
      "Shipping and any coupon are excluded, as in version 1. Attrition by JLC China's rule (`jlc-smt.com` help 42767) for the Extended parts of 8 pins or fewer: "
      "%.2f CNY per order at 20 boards and %.2f at 50, not in the totals *(check the rule)*.\n" % (attrition(lo20, 20), attrition(lo100, 50)))
    w("- **Headers**: a retail listing in EUR (no quantity break, shipping excluded). **CAL pin strip J501, M2.5 standoffs and screws**: no priced part; unpriced.\n")
    w("## Assumptions (all in `extra.csv`, each changeable there)\n")
    for r in data.extra:
        if r["placeholder_for"] or r["include"] == "yes": continue
        if r["note"] and ("assumed" in r["note"] or "value" in r["note"] or "design's" in r["note"]):
            w("- `%s` %s x%s: %s" % (r["ref"], r["value"], r["qty"], r["note"]))
    w("- Values of the ladder, feedback, sense divider and bleed are `sim/powercal/parts.csv`'s own; `blocks.csv` assigns by LCSC number, so the 10k C25804 (sense bottom, sense series and the bleed) stays in Everything else.")
    w("- The part list is the board's: anything the board does not carry (version 1's supply-branch network, the sense-input clamp, the I2C pull-ups of earlier lists) is not here; `extra.csv` rows with include = no are in the not-included table with their cost.")
    w("- Blocks follow `blocks.csv`; a part not listed there is in Everything else.")
    w("- Totals are per board in USD at %.4f CNY/USD; the per-order fees are divided over the boards of the order (20, or 50 for each of two orders at 100)." % FX)
    return "\n".join(o) + "\n"


def summary(res, flags, unp):
    lo20, hi20, lo100, hi100 = (res[20]["lo"], res[20]["hi"], res[100]["lo"], res[100]["hi"])
    print("version 2 total per board: 20 boards $%.2f / $%.2f   100 boards $%.2f / $%.2f   (whole / graduated X-ray)" % (usd(lo20["total"]), usd(hi20["total"]), usd(lo100["total"]), usd(hi100["total"])))
    print("Extended types %d, placements %d, joints %d; unpriced lines %d; flags %d" % (len(lo20["ext"]), lo20["placements"], lo20["joints"], len(unp), len(flags)))
    for f in flags: print("  FLAG", f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=None, help="write the report here")
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--model", choices=("board", "streams"), default="board", help="part list: the final board (default; what bom.md and the order files use) or the schematic-era stream lists (the model the self test mutates)")
    ap.add_argument("--order", action="store_true", help="write the purchasable order tables at 5 and 100 boards for v2 (order-5-100.md/.csv here) and v1 (../../bom/v1/order-5-100.md/.csv)")
    ap.add_argument("--refresh-v1-design", metavar="DIR", help="rewrite v1-input/design-parts.csv from DIR/design.py (a version 1 kicad/ folder; read-only)")
    ap.add_argument("--path", action="append", default=[], help="override an input: name=path (catalog, intl, basic, blocks, extra, v1, scope, awg, powercal)")
    a = ap.parse_args(argv)
    paths = dict(p.split("=", 1) for p in a.path)
    if a.refresh_v1_design:
        import order
        print("wrote", order.refresh_v1_design(a.refresh_v1_design)); return None, []
    data = Data(a.root, paths)
    L, res, deltas, flags = (run_board if a.model == "board" else run)(data)
    summary(res, flags, res[20]["lo"]["unpriced"])
    if a.md:
        open(a.md, "w").write(report(data, L, res, deltas, flags, a))
    if a.order:
        import order
        o = order.write_all(data)
        for d in ("v2", "v1"):
            print("%s order: 5 boards $%.2f per board ($%.2f the order), 100 boards $%.2f per board ($%.2f the order)" % (
                d, usd(o[d][5]["grand"] / 5), usd(o[d][5]["grand"]), usd(o[d][100]["grand"] / 100), usd(o[d][100]["grand"])))
    return res, flags


if __name__ == "__main__":
    main()
