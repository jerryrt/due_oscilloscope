"""Designator placement: one search order, anchors first, the two-way nearest test, forced and fixed labels from the configuration.

    plan = place(labelboard, cfg)      # Plan: ref -> (x, y, angle) or None (no place: the label comes off the silk)

The search order for every label (merged from the AFE-1 and AFE-2 placers): candidate sides above, east, west, below, east90, west90; for each side the gaps
from the part's courtyard in `GAPS` order (negative gaps lie over the courtyard's own edge), sliding 0.1 mm. The first place that passes every test wins.
Order of work: fixed labels (FIXED_LABELS), the labels of parts with no block, the PRIORITY anchors, forced labels (FORCE), the remaining anchors, then
the rest, each group the most constrained part first. An anchor (a part whose reference starts with one of SILK_REQUIRED_PREFIXES) that finds no place
under the strict test goes through the tiers in `ANCHOR_TIERS`; a passive has only the first. Mounting holes (NO_LABEL_PREFIXES) carry no label.

Every configuration name is listed in CONFIG.md. A missing required name raises ConfigError; nothing is defaulted silently except the ones CONFIG.md
marks with a default."""
import collections
import re
from . import _g as G
from .. import outlines, rules


from ..config import ConfigError, declare, check_names, EPS_DEFAULT      # one error class and one typo guard for the package


DEFAULTS = dict(
    DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2, DESIGNATOR_H=1.0,      # ADVANCE and INK_H are fractions of the text height (LR-11's meaning); DESIGNATOR_H is that height in mm
    SILK_CHAR_ADV=0.9, SILK_TEXT_H=1.0,
    READ_MARGIN=0.15, OWN_MARGIN=0.25,
    LABEL_GAP=0.2, DESIGNATOR_GAP_ONE_LABEL=0.6,
    PAD_CLEAR=0.10, ANCHOR_PAD_CLEAR=0.05, OUTLINE_CLEAR=0.05, VIA_CLEAR=None, EPS=EPS_DEFAULT, TEXT_CLEAR=0.4, EDGE_CLEAR=0.4, OWN_SOLID_CLEAR=0.05,
    GAPS=(0.15, 0.25, 0.35, 0.5, 0.7, 0.9, -0.1, -0.2, -0.3, -0.4),
    GAPS_OUTSIDE=(1.2, 1.6, 2.0, 2.5, 3.0),
    LABEL_AREA=None, BNC_DES_DY=-3.35, BNC_FN_DY=-0.45, BNC_LINE=0.075, BNC_MARGIN=None,
    NAME_SIZE=1.2, NAME_AREA=None, NAME_CLEAR_BODY=0.05, NAME_CLEAR_PAD=0.10, NAME_CLEAR_SILK=0.08, NAME_REACH=12.0, NAME_STEP=0.25, NAME_OUTSIDE_GAPS=(0.3, 0.5), NAME_CORNER_MAX=12.0,
    OUTLINE_IGNORE=(), OUTLINE_BREAK_CLEAR=0.2, OUTLINE_LINE_HALF=0.075,
    SLIDE=0.1, REGION_MARGIN=0.1,
    OUTLINE_STRAYS=(), PRIORITY=(), FORCE={}, FIXED_LABELS={}, PASSIVE_TEST='courtyard',
    ANCHOR_TIERS=(('strict', 'in'), ('relaxed', 'in'), ('strict', 'out'), ('relaxed', 'out'), ('samekind', 'in'), ('samekind', 'out')),
)


ALL_NAMES = set(DEFAULTS) | {'SILK_REQUIRED_PREFIXES', 'NO_LABEL_PREFIXES', 'BLOCK', 'OUTLINE', 'BNC', 'BLOCK_NAMES'}
declare('labels', ALL_NAMES)
REQUIRED = ('SILK_REQUIRED_PREFIXES', 'NO_LABEL_PREFIXES', 'BLOCK', 'OUTLINE')     # the project's own tables: a missing one raises (never a default); everything else is a tunable with a default
NEEDS = dict(place=REQUIRED, validate=REQUIRED, check_two_way=('SILK_REQUIRED_PREFIXES',), bnc_layout=('BNC',), place_names=('OUTLINE', 'BLOCK_NAMES'),
             validate_names=('OUTLINE', 'BLOCK_NAMES'), outline_segments=('OUTLINE',), validate_outline=('OUTLINE',))


class Cfg:
    """the configuration as the placer sees it. `need` names the project's tables the call cannot run without: a missing one raises ConfigError naming it. Every other name falls back
    to DEFAULTS, and `effective()` says which came from the project and which from a default."""
    def __init__(self, cfg, need=()):
        get = cfg.get if isinstance(cfg, dict) else (lambda k, d=None: getattr(cfg, k, d))
        has = (lambda k: k in cfg) if isinstance(cfg, dict) else (lambda k: hasattr(cfg, k))
        check_names(cfg)                                # a name near a declared one (READ_MARGN) raises: a likely typo, never a silent default
        missing = [k for k in need if not has(k)]
        if missing:
            raise ConfigError('the configuration has no %s (project-specific: no default)' % ', '.join(missing))
        self.v, self.src = {}, {}
        for k, d in {**DEFAULTS, **{k: None for k in ALL_NAMES if has(k)}, **{k: None for k in need}}.items():
            self.src[k] = 'project' if has(k) else 'default'
            self.v[k] = get(k, DEFAULTS.get(k, d)) if k in DEFAULTS else get(k, d)

    def __getattr__(self, k):
        try:
            return self.__dict__['v'][k]
        except KeyError:
            raise ConfigError(k)

    def effective(self):
        """[(name, value, 'project' | 'default')] for every name the label tools read"""
        return [(k, self.v[k], self.src[k]) for k in sorted(self.v)]


def effective_config(cfg, call='place'):
    """the effective configuration of a call as text, one name per line with its value and where it came from: print it in every run and carry it in the report"""
    c = Cfg(cfg, NEEDS.get(call, ()))
    return '\n'.join('%-28s %-9s %r' % (k, s, v) for k, v, s in c.effective())


def block_of(cfg, ref):
    b = cfg.BLOCK
    return b(ref) if callable(b) else b.get(ref)


def kind_of(cfg, ref):
    """the anchor kind (the longest matching SILK_REQUIRED_PREFIXES entry) or 'P' for a passive"""
    return rules._kind(ref, cfg.SILK_REQUIRED_PREFIXES)


def lab_box(cfg, ref, x, y, ang):
    L = len(ref) * cfg.DESIGNATOR_ADVANCE * cfg.DESIGNATOR_H
    h = cfg.DESIGNATOR_INK_H * cfg.DESIGNATOR_H
    return (x - h / 2, y - L / 2, x + h / 2, y + L / 2) if round(ang) % 180 == 90 else (x - L / 2, y - h / 2, x + L / 2, y + h / 2)


def text_box(cfg, s, x, y, ang):
    tw = len(s) * cfg.SILK_CHAR_ADV * cfg.SILK_TEXT_H
    h = cfg.SILK_TEXT_H
    if round(ang) % 180 == 90:
        tw, h = h, tw
    return (x - tw / 2, y - h / 2, x + tw / 2, y + h / 2)


def clash(cfg, L, B, name=False):
    """spacing between two labels: DESIGNATOR_GAP_ONE_LABEL when they share a baseline (overlap in y > half the shorter), LABEL_GAP otherwise"""
    mx = cfg.DESIGNATOR_GAP_ONE_LABEL if (rules.shares_baseline(L[1], L[3], B[1], B[3]) and not name) else cfg.LABEL_GAP      # the one-label rule is about two designators reading as one; a block name is not one
    e = cfg.EPS
    return B[0] - mx + e < L[2] and L[0] < B[2] + mx - e and B[1] - cfg.LABEL_GAP + e < L[3] and L[1] < B[3] + cfg.LABEL_GAP - e


def owner_of(key):
    return key[3:] if key.startswith('fn_') else key


class Plan(dict):
    """ref -> (x, y, angle) or None; .tier[ref] says which test set placed it, .reasons counts the tests candidates failed"""
    def __init__(self):
        super().__init__()
        self.tier = {}
        self.reasons = collections.Counter()


class _P:
    def __init__(s, lb, cfg):
        s.lb, s.c = lb, Cfg(cfg, REQUIRED)
        c = s.c
        s.parts = {r: p for r, p in lb.parts.items() if p.top and p.cour is not None}
        s.refs = sorted(s.parts)
        s.placed = {}                                   # key -> label box (designators by ref, fixed texts by 'fn_REF')
        s.plan = Plan()
        s.pads = [b for p in lb.parts.values() for b in p.pads]
        s.bodies = {r: p.body for r, p in lb.parts.items() if p.body}
        s.solid = {r: (p.solid() or [p.cour]) for r, p in s.parts.items()}
        s.rects = {k: [tuple(q) for q in v] for k, v in c.OUTLINE.items()}
        s.late = True
        for k, b in lb.fixed.items():
            s.placed[k] = b

    # ---- measures
    def dsolid(s, ref, L):
        return min(G.gap(L, b) for b in s.solid[ref])

    def own_label_dist(s, ref):
        ds = [s.dsolid(ref, s.placed[k]) for k in (ref, 'fn_' + ref) if k in s.placed]
        return min(ds) if ds else None

    def anchor(s, ref):
        return kind_of(s.c, ref) != 'P'

    def comparable(s, a, b):
        """an anchor is compared only with parts of its own kind, a passive with all"""
        ka = kind_of(s.c, a)
        return ka == 'P' or kind_of(s.c, b) == ka

    def silk(s):
        return s.lb.silk + (s.lb.outline_silk if s.late else [])

    # ---- the tests
    def two_way(s, ref, L):
        """from the part: its own label is nearer than any other label by READ_MARGIN (to body and pads); a label never comes nearer to another part than that part's own label"""
        c = s.c
        m = c.READ_MARGIN
        d_r = s.dsolid(ref, L)
        for q, B in s.placed.items():
            o = owner_of(q)
            if o == ref:
                continue
            if s.comparable(ref, o) and s.dsolid(ref, B) <= d_r + m:
                return False
            if o in s.parts and s.comparable(o, ref):
                ds = s.own_label_dist(o)
                if ds is not None and rules.too_near(ds, s.dsolid(o, L), m, c.EPS):
                    return False
        return True

    def region(s, ref, L, where):
        rects, c = s.rects, s.c
        blk = block_of(c, ref)
        if not rects or blk not in rects:
            return True              # a part of no block (an edge part): its label may lie in any rectangle when the two-way test passes (owner's delegate, 2026-11-17)
        pt = s.parts[ref]
        if where == 'out' and ref not in c.OUTLINE_STRAYS:      # the outside tier: in no block's rectangle at all
            return not any(G.in_box(G.centre(L), q) for v in rects.values() for q in v)
        return outlines.label_region_ok(L, (pt.x, pt.y), blk, rects, c.OUTLINE_STRAYS, ref, c.REGION_MARGIN, c.EPS, s.anchor(ref), False)

    def static(s, ref, x, y, ang, test, where):
        c = s.c
        L = lab_box(c, ref, x, y, ang)
        E = c.LABEL_AREA or s.lb.edge
        if E and (L[0] < E[0] + c.EDGE_CLEAR or L[2] > E[2] - c.EDGE_CLEAR or L[1] < E[1] + c.EDGE_CLEAR or L[3] > E[3] - c.EDGE_CLEAR):
            return 'edge'
        own_pads = s.parts[ref].pads or s.solid[ref]
        sol = s.solid[ref]
        if min(G.gap(L, b) for b in own_pads) < c.OWN_SOLID_CLEAR - c.EPS or any(G.overlap(L, b) for b in own_pads):
            return 'body'
        t = text_box(c, ref, x, y, ang)
        own_body = s.bodies.get(ref) or s.parts[ref].cour
        if test in ('relaxed', 'samekind'):                    # the part's body (F.Fab) is what counts, not its courtyard
            others = [(q, b) for q, b in s.bodies.items() if q != ref]
            if any(G.overlap(t, b) for _, b in others):
                return 'otherbody'
            if test == 'samekind':
                others = [(q, b) for q, b in others if kind_of(c, q) == kind_of(c, ref)]
            if others and min(G.gap(t, b) for _, b in others) - G.gap(t, own_body) < c.OWN_MARGIN - c.EPS:
                return 'ownmargin'
        else:
            cours = {q: p.cour for q, p in s.parts.items() if q != ref}
            if any(G.overlap(t, b) for b in cours.values()):
                return 'othercourt'
            if cours and min(G.gap(t, b) for b in cours.values()) - G.gap(t, s.parts[ref].cour) < c.OWN_MARGIN - c.EPS:
                return 'ownmargin'
        m = c.ANCHOR_PAD_CLEAR if (test != 'strict' and s.anchor(ref)) else c.PAD_CLEAR      # the search keeps the full clearance; only validate allows EPS
        if any(G.near(L, b, m) for b in s.pads) or (c.VIA_CLEAR is not None and any(G.near(L, b, c.VIA_CLEAR) for b in s.lb.vias)):
            return 'padvia'
        if any(G.near(L, b, c.PAD_CLEAR) for b in s.lb.silk) or (s.late and any(G.near(L, b, c.OUTLINE_CLEAR) for b in s.lb.outline_silk)):
            return 'silk'
        if any(G.gap(L, b) < c.TEXT_CLEAR for b in s.lb.texts):
            return 'text'
        for q, B in s.placed.items():
            if owner_of(q) != ref and clash(c, L, B, q.startswith('name_')):
                return 'label'
        d_own = min(G.gap(L, b) for b in sol)                   # from the label: its own part nearer than any other comparable part by READ_MARGIN
        for o in s.refs:
            if o != ref and s.comparable(ref, o) and rules.too_near(d_own, min(G.gap(L, b) for b in s.solid[o]), c.READ_MARGIN, c.EPS):
                return 'ownnearer'
        if not s.two_way(ref, L):
            return 'twoway'
        if not s.region(ref, L, where):
            return 'region'
        return True

    # ---- candidates, in the one search order
    def cands(s, ref, gaps):
        c = s.c
        P = s.parts[ref].cour
        cx, cy = (P[0] + P[2]) / 2, (P[1] + P[3]) / 2
        w, h = P[2] - P[0], P[3] - P[1]
        L = len(ref) * c.DESIGNATOR_ADVANCE * c.DESIGNATOR_H
        I = c.DESIGNATOR_INK_H * c.DESIGNATOR_H
        st = c.SLIDE

        def sl(half):
            n = int(half / st) + 2
            return sorted([0.0] + [sg * k * st for k in range(1, n) for sg in (1, -1)], key=abs)
        out = []
        for g in gaps:
            for dx in sl(w / 2 + 1.0 + L / 2):
                if abs(dx) <= w / 2 + 1.0 + L / 2:
                    out.append((0, 'above', cx + dx, P[3] + g + I / 2, 0, g, abs(dx)))
        for g in gaps:
            for dy in sl(h / 2 + 1.0):
                if abs(dy) <= h / 2 + 0.5:
                    out.append((1, 'east', P[2] + g + L / 2, cy + dy, 0, g, abs(dy)))
                    out.append((1, 'west', P[0] - g - L / 2, cy + dy, 0, g, abs(dy)))
        for g in gaps:
            for dx in sl(w / 2 + 1.0 + L / 2):
                if abs(dx) <= w / 2 + 1.0 + L / 2:
                    out.append((1.5, 'below', cx + dx, P[1] - g - I / 2, 0, g, abs(dx)))
        for g in gaps:
            for dy in sl(h / 2 + 1.0 + L / 2):
                if abs(dy) <= h / 2 + 1.0 + L / 2:
                    out.append((2, 'east90', P[2] + g + I / 2, cy + dy, 90, g, abs(dy)))
                    out.append((2, 'west90', P[0] - g - I / 2, cy + dy, 90, g, abs(dy)))
        return sorted(out, key=lambda t: (t[0], t[5] if t[5] >= 0 else 5 + abs(t[5]), t[6]))

    def gaps_for(s, where):
        return s.c.GAPS + (s.c.GAPS_OUTSIDE if where == 'out' else ())

    def first_ok(s, ref, tiers):
        for test, where in tiers:
            eff = 'relaxed' if (test == 'strict' and not s.anchor(ref) and s.c.PASSIVE_TEST == 'body') else test
            for k in s.cands(ref, s.gaps_for(where)):
                v = s.static(ref, k[2], k[3], k[4], eff, where)
                if v is True:
                    return k, (test, where)
                s.plan.reasons[v] += 1
        return None, None

    def feas(s, ref):
        n = 0
        for k in s.cands(ref, s.c.GAPS):
            if s.static(ref, k[2], k[3], k[4], 'strict', 'in') is True:
                n += 1
        return n

    def put(s, ref, x, y, ang, tier):
        s.placed[ref] = lab_box(s.c, ref, x, y, ang)
        s.plan[ref] = (round(x, 3), round(y, 3), int(ang))
        s.plan.tier[ref] = tier

    def run(s, refs):
        for r in refs:
            if r in s.plan:
                continue
            tiers = s.c.ANCHOR_TIERS if s.anchor(r) else (('strict', 'in'),)
            k, tier = s.first_ok(r, tiers)
            if k:
                s.put(r, k[2], k[3], k[4], tier)
            else:
                s.plan[r] = None
                s.plan.tier[r] = 'off'


def place(lb, cfg):
    """the plan for every part on the top side; see the module text"""
    s = _P(lb, cfg)
    c = s.c
    nolabel = [r for r in s.refs if r.startswith(tuple(c.NO_LABEL_PREFIXES))]
    for r in nolabel:
        s.plan[r] = None
        s.plan.tier[r] = 'none'
    for r, (x, y, a) in c.FIXED_LABELS.items():
        s.put(r, x, y, a, 'fixed')
    rest = [r for r in s.refs if r not in s.plan]
    anchors = [r for r in rest if s.anchor(r)]
    edge = sorted([r for r in anchors if block_of(c, r) is None], key=s.feas)
    inblk = [r for r in anchors if r not in edge]
    for r, (x, y, a) in c.FORCE.items():
        if r in s.parts:
            s.put(r, x, y, a, 'forced')
    s.run(edge)
    s.late = True
    prio = [r for r in c.PRIORITY if r in inblk]
    s.run(prio)
    s.run(sorted([r for r in inblk if r not in prio], key=s.feas))
    s.run(sorted([r for r in rest if not s.anchor(r)], key=s.feas))
    return s.plan


def check_two_way(lb, labels, cfg, keys=None):
    """the readability test on a finished board (stackcheck): `labels` maps a part to its label boxes (a BNC's designator and function text are two boxes of one
    label). From the label: its own part is nearer than any other comparable part by READ_MARGIN. From the part: its own label is nearer than any other comparable
    label. Returns {ref: (step1 failure or None, step2 failure or None)} for failing parts only."""
    c = Cfg(cfg, NEEDS['check_two_way'])
    solid = {r: (pt.solid() or ([pt.cour] if pt.cour else [])) for r, pt in lb.parts.items()}
    res = rules.two_way_core(solid, {r: b for r, b in labels.items() if r in solid}, c.SILK_REQUIRED_PREFIXES, c.READ_MARGIN, c.EPS)      # the one implementation, pcbkit.rules
    return {r: ((s1[0], s1[1]) if s1 else None, (s2[0], s2[1]) if s2 else None) for r, (own, s1, s2) in res.items() if s1 or s2}


def validate(lb, plan, cfg, skip=()):
    """The placer's hard tests on a finished board: {ref: [failing terms with their numbers]} for every label that fails. `plan` maps a part to (x, y, angle) or None.
    Hard tests are the ones the owner's reading standard rests on: inside the label area, clear of the part's own body and pads, of every pad (PAD_CLEAR; ANCHOR_PAD_CLEAR for an
    anchor), of footprint silk and board text, of block-outline lines by OUTLINE_CLEAR, of other labels (LABEL_GAP, DESIGNATOR_GAP_ONE_LABEL between designators on one baseline),
    the two-way nearest test both ways (READ_MARGIN, EPS of rounding), and the region rules. The preference tests of the search tiers (OWN_MARGIN against courtyards or bodies) are
    not part of it. Labels in `skip` (fixed or forced by the configuration) are not judged but stay obstacles."""
    s = _P(lb, cfg)
    c = s.c
    for r, p in plan.items():
        if p and r in s.parts:
            s.placed[r] = lab_box(c, r, *p)
    out = {}
    e = c.EPS
    for r, p in sorted(plan.items()):
        if not p or r in skip or r not in s.parts:
            continue
        x, y, a = p
        L = lab_box(c, r, x, y, a)
        why = []
        E = c.LABEL_AREA or lb.edge
        if E and (L[0] < E[0] + c.EDGE_CLEAR - e or L[2] > E[2] - c.EDGE_CLEAR + e or L[1] < E[1] + c.EDGE_CLEAR - e or L[3] > E[3] - c.EDGE_CLEAR + e):
            why.append('outside the label area by %.3f mm' % max(E[0] + c.EDGE_CLEAR - L[0], L[2] - E[2] + c.EDGE_CLEAR, E[1] + c.EDGE_CLEAR - L[1], L[3] - E[3] + c.EDGE_CLEAR))
        d_own = s.dsolid(r, L)
        own_pads = lb.parts[r].pads or s.solid[r]
        d_pads = min(G.gap(L, b) for b in own_pads)
        if d_pads < c.OWN_SOLID_CLEAR - e or any(G.overlap(L, b) for b in own_pads):
            why.append('own part pads %.3f mm (needs %.2f)' % (d_pads, c.OWN_SOLID_CLEAR))
        pc = c.ANCHOR_PAD_CLEAR if s.anchor(r) else c.PAD_CLEAR
        for q, pt in lb.parts.items():
            for b in pt.pads:
                g = G.gap(L, b)
                if g < pc - e:
                    why.append('pad of %s %.3f mm (needs %.2f)' % (q, g, pc))
        if c.VIA_CLEAR is not None:
            for v in lb.vias:
                if G.gap(L, v) < c.VIA_CLEAR - e:
                    why.append('via %.3f mm' % G.gap(L, v))
        for b in lb.silk:
            if G.gap(L, b) < c.PAD_CLEAR - e:
                why.append('footprint silk %.3f mm (needs %.2f)' % (G.gap(L, b), c.PAD_CLEAR))
        for b in lb.outline_silk:
            if G.gap(L, b) < c.OUTLINE_CLEAR - e:
                why.append('outline line %.3f mm (needs %.2f)' % (G.gap(L, b), c.OUTLINE_CLEAR))
        for b in lb.texts:
            if G.gap(L, b) < c.TEXT_CLEAR - e:
                why.append('board text %.3f mm (needs %.2f)' % (G.gap(L, b), c.TEXT_CLEAR))
        for q, B in s.placed.items():
            if owner_of(q) != r and clash(c, L, B, q.startswith('name_')):
                why.append('label %s: %.3f mm' % (q, G.gap(L, B)))
        pt = s.parts[r]
        why += outlines.label_region_findings(L, (pt.x, pt.y), block_of(c, r), s.rects, c.OUTLINE_STRAYS, r, c.REGION_MARGIN, e, s.anchor(r), True)
        if why:
            out[r] = why
    labels = {r: [lab_box(c, r, *pl)] for r, pl in plan.items() if pl and r in s.parts}
    for key, box in lb.fixed.items():
        if key.startswith('fn_') and key[3:] in s.parts:
            labels.setdefault(key[3:], []).append(box)
    for p_, (own, f1, f2) in rules.two_way_all(s.solid, labels, c.SILK_REQUIRED_PREFIXES, c.READ_MARGIN, e).items():
        if p_ not in skip:
            for x in f1:
                out.setdefault(p_, []).append('two-way, from the label: part %s is %.3f mm from it, its own part %.3f (needs +%.2f)' % (x[1], x[3], x[2], c.READ_MARGIN))
        for x in f2:
            who = p_ if p_ not in skip else x[1]        # a fixed or forced part's reading is crowded by the label that is judged: report it under that label
            if who in skip:
                continue
            out.setdefault(who, []).append('two-way, from the part: label of %s is %.3f mm from it, its own label %.3f (needs +%.2f)' % (x[1], x[3], x[2], c.READ_MARGIN) if who == p_ else
                                           'two-way, from part %s: this label is %.3f mm from it, its own label %.3f (needs +%.2f)' % (p_, x[3], x[2], c.READ_MARGIN))
    return out
