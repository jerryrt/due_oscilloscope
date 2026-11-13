"""The gate-3 package engine: every number is regenerated from a board and the repo, none is typed in, and nothing here names a board.

    python3 -B -m pcbtools.gate3 --config <board config> --table <gate-3 table> --out <dir>

Two inputs say everything board-specific. The BOARD CONFIG (`pcbtools/boards/<cfg>.py`, fields in `pcbtools/CONFIG_FIELDS.md`) is what
the layout rules read. The GATE-3 TABLE (`pcbtools/boards/gate3_<board>.py`, fields in `pcbtools/gate3/README.md`) is plain data: which
files, which parts and nets, which cited sentences, which prose. This module holds (a) pure helpers on numpy arrays (`bridge_table`,
`hop_table`, `classify_net`, `margin_rows`, ...: tested on synthetic boards) and (b) `generate()`, which reads the board with pcbtools
(pcbnew, in the image only), runs the layout rules and kicad-cli DRC, reads the study result files and the BOM engine the table names,
and assembles GATE3.md and data/*. It writes only under the output folder it is given.

The only clock input is the generated-at line, and `stamp` replaces it. Nothing reads a file modification time: a checkout does not keep
them. The renders' freshness is by content (`rendersum`: the board hash the renders were made from, and each image's own hash).
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import importlib
import importlib.util
import json
import os
import re
import string
import subprocess

import numpy as np

from . import connectivity as CONN
from . import rendersum

AFE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))      # hardware/afe-proto
REPO = os.path.abspath(os.path.join(AFE, '..', '..'))
LAYER_NAMES = ('F.Cu', 'B.Cu')
RULING = ('adc', 'divider', 'vref')       # rule (a): a bridge inside a block over one of these needed a ruling


# ============================================================================================ pure helpers (numpy only)
def _pt_seg(P, x0, y0, x1, y1):
    """distance of each point of P (n,2) to each segment (m,): (n, m)"""
    P = np.asarray(P, float)
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    px, py = P[:, 0:1] - x0[None, :], P[:, 1:2] - y0[None, :]
    t = np.where(L2[None, :] > 0, (px * dx[None, :] + py * dy[None, :]) / np.where(L2 > 0, L2, 1)[None, :], 0.0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(px - t * dx[None, :], py - t * dy[None, :])


def classify_net(name, classes):
    """which class of net a name falls in: 'adc' (a net that reaches a Due ADC pin), 'divider' (the scope's high-impedance
    side), 'vref' (the reference and its branches, by prefix), 'other-sensitive' (rest of XSENS), or None"""
    if name in classes['adc']:
        return 'adc'
    if name in classes['divider']:
        return 'divider'
    if any(name == p or name.startswith(p + '_') for p in classes['vref_prefix']):
        return 'vref'
    if name in classes.get('other', ()):
        return 'other-sensitive'
    return None


def _pads_of(b, ref):
    i = b.ref_index(ref)
    return [j for j in range(len(b.p_fp)) if b.p_fp[j] == i]


def bridge_table(b, bridges, classes, half_w=0.4, span=(0.3, 0.7)):
    """one row per 0R bridge part of `bridges` ((ref, na, nb, block, why) tuples): position (Due mm), the two pad nets, and the
    foreign-net tracks under its body. The body is the pad-to-pad axis, `half_w` either side (a 0603 is 0.8 mm wide), the middle
    `span` of the way between the pad centres (clear of the pads themselves). A track counts when the nearest sample on the axis
    is within half_w + half the track width of its centre line; its own two nets (and no-net copper) never count."""
    rows = []
    seg = dict(x0=b.s_x0, y0=b.s_y0, x1=b.s_x1, y1=b.s_y1, w=b.s_w, net=b.s_net, layer=b.s_layer)
    for ref, na, nb_, blk, why in bridges:
        ps = _pads_of(b, ref)
        pads = {b.p_pin[j]: j for j in ps}
        j1, j2 = pads['1'], pads['2']
        a = np.array([b.p_x[j1], b.p_y[j1]])
        c = np.array([b.p_x[j2], b.p_y[j2]])
        own = {int(b.p_net[j1]), int(b.p_net[j2]), 0}
        ts = np.linspace(span[0], span[1], 13)
        P = a[None, :] + ts[:, None] * (c - a)[None, :]
        crossed = []
        if len(seg['net']):
            d = _pt_seg(P, seg['x0'], seg['y0'], seg['x1'], seg['y1']).min(axis=0)
            hit = np.flatnonzero((d - seg['w'] / 2 <= half_w) & ~np.isin(seg['net'], list(own)))
            by = {}
            for k in hit:
                key = (b.nets[seg['net'][k]], 'F.Cu' if seg['layer'][k] == 0 else 'B.Cu')
                by[key] = min(by.get(key, 9e9), float(d[k] - seg['w'][k] / 2))
            crossed = [dict(net=n, layer=ly, edge_gap_mm=round(g, 3), cls=classify_net(n, classes)) for (n, ly), g in sorted(by.items())]
        i = b.ref_index(ref)
        flagged = sorted({x['cls'] for x in crossed if x['cls'] in RULING})
        rows.append(dict(ref=ref, x=float(b.fp_x[i]), y=float(b.fp_y[i]), rot=float(b.fp_rot[i]),
                         net_a=b.nets[b.p_net[j1]], net_b=b.nets[b.p_net[j2]], design_a='/' + na, design_b='/' + nb_,
                         pad_pitch_mm=float(np.hypot(*(c - a))), block=blk, why=why, crossed=crossed,
                         needs_ruling=bool(flagged), ruling_classes=flagged))
    return rows


def hop_table(b, classes, tol=1e-3):
    """every bottom-layer track run (B.Cu segments, joined where their ends meet on one net): net, ends, length, the vias on that
    net at its ends, and the foreign-net top tracks it passes under (the nets the hop jumps)"""
    bot = np.flatnonzero(b.s_layer == 1)
    if not len(bot):
        return []
    parent = list(range(len(bot)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ends = [((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k])) for k in bot]
    for i in range(len(bot)):
        for j in range(i):
            if b.s_net[bot[i]] != b.s_net[bot[j]]:
                continue
            if any(np.hypot(p[0] - q[0], p[1] - q[1]) < tol for p in ends[i] for q in ends[j]):
                parent[find(i)] = find(j)
    runs = {}
    for i in range(len(bot)):
        runs.setdefault(find(i), []).append(bot[i])
    top = np.flatnonzero(b.s_layer == 0)
    out = []
    for ks in runs.values():
        net = int(b.s_net[ks[0]])
        pts = np.array([e for k in ks for e in ((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k]))])
        length = float(sum(np.hypot(b.s_x1[k] - b.s_x0[k], b.s_y1[k] - b.s_y0[k]) for k in ks))
        nv = 0
        if len(b.v_idx):
            for q in np.flatnonzero(b.v_net == net):
                if np.min(np.hypot(pts[:, 0] - b.v_x[q], pts[:, 1] - b.v_y[q])) < max(0.05, 0.5 * b.v_dia[q] * 0.5):
                    nv += 1
        crossed = []
        if len(top):
            by = {}
            for k in ks:
                ts = np.linspace(0, 1, 41)
                P = np.stack([b.s_x0[k] + ts * (b.s_x1[k] - b.s_x0[k]), b.s_y0[k] + ts * (b.s_y1[k] - b.s_y0[k])], 1)
                d = _pt_seg(P, b.s_x0[top], b.s_y0[top], b.s_x1[top], b.s_y1[top]).min(axis=0) - b.s_w[top] / 2 - b.s_w[k] / 2
                for t_ in np.flatnonzero((d <= 0.0) & (b.s_net[top] != net) & (b.s_net[top] != 0)):
                    n = b.nets[b.s_net[top[t_]]]
                    by[n] = min(by.get(n, 9e9), float(d[t_]))
            crossed = [dict(net=n, cls=classify_net(n, classes)) for n in sorted(by)]
        out.append(dict(net=b.nets[net], segments=len(ks), length_mm=length, vias=nv, width_mm=float(b.s_w[ks[0]]),
                        ends=[[round(float(x), 3), round(float(y), 3)] for x, y in pts[[0, -1]]], crosses=crossed))
    return out


def margin_rows(items):
    """items: (rule, what, value, limit, kind) with kind 'max' (value must stay <= limit) or 'min'; returns rows with the
    margin and a flag 'marginal' when under 10 % of the limit"""
    out = []
    for rule, what, v, lim, kind in items:
        m = (lim - v) if kind == 'max' else (v - lim)
        out.append(dict(rule=rule, what=what, value=float(v), limit=float(lim), kind=kind, margin=float(m),
                        marginal=bool(m < 0.1 * abs(lim))))
    return out


def md_table(head, rows):
    esc = lambda x: str(x).replace('|', '\\|').replace('\n', ' ')
    return '\n'.join(['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)] + ['| ' + ' | '.join(esc(c) for c in r) + ' |' for r in rows])


def fnum(x, n=3):
    if x is None:
        return '-'
    if isinstance(x, (int, np.integer)):
        return str(x)
    return f'{x:.{n}g}' if abs(x) < 1e-3 or abs(x) >= 1e4 else f'{x:.{n}f}'.rstrip('0').rstrip('.')


def figs_str(f):
    return ', '.join(f'{k}={fnum(v)}' for k, v in f.items())


# ---------------------------------------------------------------------------------------------------- templates
class _Fmt(string.Formatter):
    """str.format with one extra format spec: `n<k>` is `fnum(value, k)` (the document's own number style)"""

    def format_field(self, value, spec):
        if spec[:1] == 'n' and spec[1:].isdigit():
            return fnum(value, int(spec[1:]))
        return super().format_field(value, spec)


def tpl(text, **kw):
    """fill a table template: {name}, {name[key]}, {name:n3}"""
    return _Fmt().vformat(text, (), kw)


def dotted(obj, path):
    """obj['a']['b'][0] from 'a.b.0' (a segment that is all digits indexes a list)"""
    for seg in path.split('.'):
        obj = obj[int(seg)] if seg.isdigit() and isinstance(obj, (list, tuple)) else obj[seg]
    return obj


def _flat(cfg, spec):
    """names from config fields: 'FIELD' (a net, or a collection of nets, or of collections: flattened) or 'FIELD.key' (the key of every
    dict of a collection of dicts)"""
    if '.' in spec:
        field, key = spec.split('.', 1)
        out = []
        for d in getattr(cfg, field):
            v = d[key]
            out.extend([v] if isinstance(v, str) else v)
        return out
    v = getattr(cfg, spec)
    if isinstance(v, str):
        return [v]
    out = []
    for x in v:
        out.extend([x] if isinstance(x, str) else x)
    return out


# ============================================================================================ board-bound parts
def read_json(p):
    with open(p) as f:
        return json.load(f)


def read_text(p):
    with open(p) as f:
        return f.read()


def sh(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw).stdout.strip()
    except Exception as e:       # noqa: BLE001
        return f'unavailable ({e.__class__.__name__})'


def footprint_props(board):
    """ref -> dict(value, lcsc, fp) parsed from the board text (the arrays carry no properties)"""
    t = read_text(board)
    out = {}
    for f in re.split(r'\n\t\(footprint ', t)[1:]:
        ref = re.search(r'\(property "Reference" "([^"]*)"', f).group(1)
        val = re.search(r'\(property "Value" "([^"]*)"', f).group(1)
        l = re.search(r'\(property "LCSC" "([^"]*)"', f)
        at = re.search(r'\(attr ([^)]*)\)', f)
        out[ref] = dict(value=val, lcsc=l.group(1) if l else '', fp=f.split('"')[1], dnp=bool(at and 'dnp' in at.group(1).split()))
    return out


def apply_setup(pro, setup):
    """the project file's rules block and default net class replaced by the design's (BOARD_SETUP)"""
    out = json.loads(json.dumps(pro))
    out.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {}).update(setup['board']['design_settings']['rules'])
    ns = out.setdefault('net_settings', {'classes': []})
    for c in setup['net_settings']['classes']:
        old = [o for o in ns.setdefault('classes', []) if o.get('name') == c['name']]
        if old:
            old[0].update(c)
        else:
            ns['classes'].append(c)
    return out


def lib_mismatch_text(pro):
    """what the committed project file says about `lib_footprint_mismatch`, read from it (never assumed): its severity if it sets one, else KiCad's default"""
    sev = ((pro or {}).get('board', {}).get('design_settings', {}).get('rule_severities', {}) or {}).get('lib_footprint_mismatch')
    if sev == 'ignore':
        return 'the committed project file sets mismatch to ignore'
    if sev:
        return f'the committed project file sets the mismatch severity to `{sev}`'
    return 'the committed project file sets no severity for it, so KiCad\'s default (a warning) applies and the warning is reported'


def rule_diff(pro, setup):
    have = pro.get('board', {}).get('design_settings', {}).get('rules', {})
    want = setup['board']['design_settings']['rules']
    return [dict(rule=k, project=have.get(k), design=v) for k, v in want.items() if have.get(k) != v]


def run_drc(board, setup=None, board_text=None):
    """kicad-cli DRC on a work copy (as pcbtools.drc does) at the project file's own rules, or, with `setup`, at the design's rules
    (the work copy's project file gets BOARD_SETUP applied; the board and the real project file are never touched)"""
    import tempfile
    from pcbtools import drc
    d = tempfile.mkdtemp(prefix='gate3-drc-')
    work = drc._work_copy(board, d)
    if board_text is not None:
        with open(work, 'w') as fh:
            fh.write(board_text)
    if setup is not None:
        pp = work.replace('.kicad_pcb', '.kicad_pro')
        with open(pp) as fh:
            pro = json.load(fh)
        with open(pp, 'w') as fh:
            json.dump(apply_setup(pro, setup), fh, indent=2)
    out = os.path.join(d, 'drc.json')
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, work], capture_output=True, text=True, timeout=300)
    return read_json(out)


def to_due(p, origin):
    return (round(p['x'] - origin[0], 3), round(origin[1] - p['y'], 3))


def lr_texts(path):
    t = read_text(path)
    out = {}
    for m in re.finditer(r'^\| (LR-\d+) \| (.*) \|\s*$', t, re.M):
        out[m.group(1)] = m.group(2)
    return out


# ============================================================================================ sections
def sec_info(b, T):
    board = os.path.join(REPO, T.BOARD)
    h = hashlib.sha256(open(board, 'rb').read()).hexdigest()
    return dict(board=os.path.relpath(board, REPO), sha256=h,
                git_head=sh(['git', '-c', 'safe.directory=*', '-C', REPO, 'rev-parse', '--short', 'HEAD']),
                git_branch=sh(['git', '-c', 'safe.directory=*', '-C', REPO, 'rev-parse', '--abbrev-ref', 'HEAD']),
                git_dirty_files=sh(['git', '-c', 'safe.directory=*', '-C', REPO, 'status', '--porcelain', '--', os.path.relpath(AFE, REPO)]).count('\n') + 1,
                footprints=int(len(b.fp_ref)), nets=int(len(b.nets)),
                segments=int(len(b.s_idx)), vias=int(len(b.v_idx)))


def sec_renders(T):
    board = os.path.join(REPO, T.BOARD)
    rows = []
    for key, name in T.RENDERS:
        p = os.path.join(REPO, T.RENDER_DIR, name)
        if os.path.exists(p):
            cur, why = rendersum.status(board, os.path.join(REPO, T.RENDER_DIR), name)
            rows.append(dict(view=key, file=os.path.relpath(p, REPO), link=T.RENDER_LINK_PREFIX + name, exists=True, current=cur, why=why,
                             sha256=rendersum.sha256_file(p)[:16]))
        else:
            rows.append(dict(view=key, file=name, link='', exists=False, current=False, why='missing', sha256=''))
    return rows


def _rename_for(T, checker_row):
    for row, label, field in T.LR_RENAMES:
        if row == checker_row:
            return label, field
    return None


def sec_lr(b, cfg, drc_report, T):
    from pcbtools import rules
    out = []
    for name, fn in rules.ROWS:
        r = fn(b, cfg)
        ren = _rename_for(T, name)
        label = ren[0].format(getattr(cfg, ren[1])) if ren else name
        out.append(dict(rule=label, checker_row=name, ok=bool(r.ok), detail=r.detail, figures={k: float(v) for k, v in r.figures.items()}))
    vio = [v for v in drc_report.get('violations', []) if not v.get('excluded')]
    kinds = {}
    for v in vio:
        kinds[v['type']] = kinds.get(v['type'], 0) + 1
    un = len(drc_report.get('unconnected_items', []))
    out.append(dict(rule=T.DRC_ROW, checker_row=T.DRC_ROW, ok=bool(not vio and not un), detail=f'DRC {kinds or "clean"}; unconnected {un}',
                    figures=dict(violations=float(len(vio)), unconnected=float(un), **{k: float(v) for k, v in kinds.items()})))
    return out


LIBRARY_TYPES = ('lib_footprint_mismatch', 'lib_footprint_issues')


def sec_drc(report, T):
    vio = [v for v in report.get('violations', []) if not v.get('excluded')]
    rows = []
    for v in vio:
        refs = [re.sub(r'^Footprint ', '', i['description']) for i in v['items']]
        documented = any(v['type'] == t and r in refs for t, r in T.DRC_DOCUMENTED)
        rows.append(dict(type=v['type'], severity=v['severity'], description=v['description'], items=[i['description'] for i in v['items']],
                         pos_due_mm=[to_due(i['pos'], T.DUE_ORIGIN) for i in v['items']], documented=documented,
                         library=v['type'] in LIBRARY_TYPES))
    kinds = {}
    for r in rows:
        kinds.setdefault((r['type'], r['severity']), []).append(r)
    return dict(counts=[dict(type=t, severity=s, n=len(v), documented=sum(x['documented'] for x in v)) for (t, s), v in sorted(kinds.items())],
                items=rows, unconnected=len(report.get('unconnected_items', [])), kicad=report.get('kicad_version'),
                schematic_parity=len(report.get('schematic_parity', [])), total=len(rows),
                undocumented=sum(not r['documented'] for r in rows),
                library=sum(r['library'] for r in rows), real_undocumented=sum(not r['documented'] and not r['library'] for r in rows))


def power_caps(b, cfg, T):
    """each generator capacitor to its nearest pad of the generator IC on the same (non-ground) net, pad centre to pad centre"""
    ic = T.POWER_CAPS['ic']
    iu = b.ref_index(ic)
    up = [(b.p_pin[j], int(b.p_net[j]), np.array([b.p_x[j], b.p_y[j]])) for j in range(len(b.p_fp)) if b.p_fp[j] == iu]
    out = []
    for c in T.POWER_CAPS['caps']:
        ic_ = b.ref_index(c)
        best = []
        for j in [j for j in range(len(b.p_fp)) if b.p_fp[j] == ic_]:
            n = int(b.p_net[j])
            if b.nets[n] == cfg.GND:
                continue
            cands = [(float(np.hypot(*(p - np.array([b.p_x[j], b.p_y[j]])))), pin) for pin, nn, p in up if nn == n]
            if cands:
                d, pin = min(cands)
                best.append((d, pin, b.nets[n], b.p_pin[j]))
        d, pin, net, cpin = max(best) if best else (np.nan, '', '', '')        # a capacitor with two pads: the farther one governs
        out.append({'cap': c, 'net': net, ic.lower() + '_pin': pin, 'dist_mm': float(d)})
    return out


def net_classes(cfg, T):
    spec = T.NET_CLASS_FIELDS
    return dict(adc=set(_flat(cfg, spec['adc'][0])) | set(_flat(cfg, spec['adc'][1])),
                divider=set(_flat(cfg, spec['divider'][0])) | set(_flat(cfg, spec['divider'][1])),
                vref_prefix=tuple(_flat(cfg, spec['vref_prefix'])),
                other=set(_flat(cfg, spec['other'][0])) - set(_flat(cfg, spec['other'][1])))


def sec_bridges(b, cfg, T):
    classes = net_classes(cfg, T)
    mod, attr = T.BRIDGES_SOURCE
    designs = list(dotted_attr(importlib.import_module(mod), attr))
    on_board = sorted(r for r in b.fp_ref if re.fullmatch(T.BRIDGE_REF_PATTERN, r))
    rows = bridge_table(b, [d for d in designs if d[0] in on_board], classes)
    hops = hop_table(b, classes)
    return dict(classes={k: (sorted(v) if not isinstance(v, tuple) else list(v)) for k, v in classes.items()},
                board_refs=on_board, design_refs=sorted(d[0] for d in designs), bridges=rows, hops=hops)


def dotted_attr(obj, path):
    for seg in path.split('.'):
        obj = getattr(obj, seg)
    return obj


# ---------------------------------------------------------------------------------------------------- BOM
def load_bom_engine(T):
    spec = importlib.util.spec_from_file_location('gate3_bom_engine', os.path.join(REPO, T.BOM_ENGINE))
    bom = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bom)
    return bom


def sec_bom(b, props, T, bom):
    data = bom.Data(os.path.join(REPO, T.BOM_DATA_DIR), {k: os.path.join(REPO, v) for k, v in getattr(T, 'BOM_PATHS', {}).items()})     # BOM_PATHS: optional, the engine's own override names
    counts = tuple(T.BOARD_COUNTS)
    rep = T.REPORT_BOARDS
    per_order = bom.PER_ORDER_MAX
    flags = []
    L = bom.lines(data, flags)
    props_by_lcsc = {}
    for ref, p in props.items():
        if p['lcsc']:
            props_by_lcsc.setdefault(p['lcsc'], p['fp'])
    eng_n = {}
    for x in L:
        if x['include'] and x['lcsc']:
            eng_n[x['lcsc']] = eng_n.get(x['lcsc'], 0) + x['qty']
    board = {}
    dnp = sorted(r for r, p in props.items() if p['dnp'])
    for ref, p in props.items():
        if p['lcsc'] and not p['dnp']:
            board.setdefault(p['lcsc'], []).append(ref)
    diffs = []
    L2 = list(L)
    for c, refs in sorted(board.items()):
        d = len(refs) - eng_n.get(c, 0)
        if d:
            diffs.append(dict(lcsc=c, board=len(refs), engine=eng_n.get(c, 0), diff=d, refs=sorted(refs)))
        if d > 0:
            L2.append(dict(stream='board', ref=','.join(sorted(refs)), value=props[refs[0]]['value'], lcsc=c, role='on the board, not in the engine lists',
                           qty=d, block='other', include=True, fixed_usd=None, replaces=''))
    unpriced = [c for c in board if bom.Part(data, c, []).lad is None]
    bp = {c: bom.Part(data, c, []) for c in props_by_lcsc if props_by_lcsc[c].startswith(T.BRIDGE_PART['footprint_prefix']) and c == T.BRIDGE_PART['lcsc']}
    bridge_part = {c: {'n': len(board.get(c, [])), 'cls': 'Extended' if p.cls == 'expand' else 'Basic', 'derived': bool(p.derived), 'mfr': p.mfr, 'stock': p.stock,
                       'read_utc': data.intl.get(c, {}).get('read_utc', ''),
                       f'unit_cny_{rep}': None if p.lad is None else bom.tier(p.lad, rep * sum(x['qty'] for x in L2 if x['include'] and x['lcsc'] == c))}
                   for c, p in bp.items()}
    results = {}
    for B in counts:
        for tag, LL in (('engine', L), ('board', L2)):
            lo = bom.cost(data, LL, B, [], False)
            hi = bom.cost(data, LL, B, None, True)
            blk = lo['blk']
            results[f'{tag}_{B}'] = dict(
                boards=B, orders=-(-B // per_order), total_cny_lo=lo['total'], total_cny_hi=hi['total'], total_usd_lo=lo['total'] / bom.FX,
                total_usd_hi=hi['total'] / bom.FX,
                parts_cny=sum(v['parts'] for k, v in blk.items() if k != 'owner'), owner_cny=sum(blk['owner'].values()),
                pcb_cny=sum(blk['pcb'].values()), setup_cny=sum(blk['setup'].values()),
                fees_cny=sum(v['load'] + v['joints'] + v['xray'] for v in blk.values()), placements=lo['placements'], joints=lo['joints'],
                extended_types=len(lo['ext']), unpriced=[u['ref'] for u in lo['unpriced']])
    lines_ = []
    parts = {c: bom.Part(data, c, []) for c in set(board) | set(eng_n)}
    for c in sorted(board, key=lambda c: (parts[c].cls != 'expand', c)):
        refs = sorted(board[c])
        n = len(refs)
        p = parts[c]
        owner = c in T.OWNER_FITTED_LCSC
        row = dict(lcsc=c, refs=refs, qty=n, value=props[refs[0]]['value'], footprint=props[refs[0]]['fp'], cls='Extended' if p.cls == 'expand' else 'Basic',
                   mfr=p.mfr, derived=bool(p.derived), stock=p.stock)
        for B in counts:
            if p.lad is None:
                row[f'unit_cny_{B}'] = None
                continue
            per = min(B, per_order)
            tot = sum(x['qty'] for x in L2 if x['include'] and x['lcsc'] == c)
            row[f'unit_cny_{B}'] = bom.tier(p.lad, (B if owner else per) * tot)
        u = row[f'unit_cny_{rep}']
        row[f'line_cny_{rep}'] = None if u is None else u * n
        row[f'line_usd_{rep}'] = None if u is None else u * n / bom.FX
        lines_.append(row)
    nolcsc = {}
    for ref, p in props.items():
        if not p['lcsc']:
            nolcsc.setdefault((p['value'], p['fp']), []).append(ref)
    owner_rows = [dict(ref=r['ref'], value=r['value'], qty=r['qty'], fixed_usd=r['fixed_usd'], note=r['note'], lcsc=r['lcsc'])
                  for r in data.extra if r['block'] == 'owner' and r['include'] == 'yes']
    pk = {}
    for ref, p in props.items():
        m = re.search(r'(R|C)_(\d{4})_', p['fp'])
        pk[ref] = m.group(2) if m else p['fp'].split(':')[-1]
    sizes = sorted({v for v in pk.values()})
    out = dict(fx=bom.FX, results=results, dnp=dnp, bridge_part=bridge_part, unpriced_board=unpriced, lines=lines_, diffs=diffs, flags=flags, owner_rows=owner_rows,
               nolcsc=[dict(value=k[0], footprint=k[1], refs=sorted(v)) for k, v in sorted(nolcsc.items())],
               packages=sizes)
    for pkg in T.WATCH_PACKAGES:
        out[f'no_{pkg}'] = not any(pkg in s for s in sizes)
    return out


# ---------------------------------------------------------------------------------------------------- the connectivity proof
_PAD_DESC = re.compile(r'Pad (\S+)(?: \[([^\]]*)\])? of (\S+)')


def drc_unconnected(report):
    """the DRC report's unconnected items as (net, 'REF.PIN' list, raw descriptions); the net is the one the pad descriptions name"""
    out = []
    for u in report.get('unconnected_items', []):
        pads, nets = [], set()
        for i in u.get('items', []):
            m = _PAD_DESC.search(i.get('description', ''))
            if m:
                pads.append(f'{m.group(3)}.{m.group(1)}')
                if m.group(2):
                    nets.add(m.group(2))
        out.append(dict(nets=sorted(nets), pads=pads, raw=[i.get('description', '') for i in u.get('items', [])]))
    return out


def lost_pads(g, src):
    """the pads of graph g that are not in the copper piece of pad `src`"""
    return sorted(k for k, c in g['pad_comp'].items() if c != g['pad_comp'][src])


def _piece_of(g, item, origin):
    """the copper piece (a component id of graph g) the DRC item `item` (description and pos, in KiCad's coordinates) belongs to: a pad by its
    name, a track or via by the one piece of g whose copper holds its position; None if it is on no piece or on more than one"""
    m = _PAD_DESC.search(item.get('description', ''))
    if m:
        k = f'{m.group(3)}.{m.group(1)}'
        return g['pad_comp'].get(k)
    pos = item.get('pos')
    if not pos:
        return None
    x, y = pos['x'] - origin[0], origin[1] - pos['y']
    found = set()
    for i, nd in enumerate(g['nodes']):
        if nd['kind'] == 'track':
            x0, y0, x1, y1, w = nd['detail']
            if CONN._pt_seg(x, y, x0, y0, x1, y1) <= w / 2 + CONN.TOL:
                found.add(int(g['comp'][i]))
        elif nd['kind'] == 'via':
            vx, vy, vd = nd['detail']
            if np.hypot(x - vx, y - vy) <= vd / 2 + CONN.TOL:
                found.add(int(g['comp'][i]))
    return found.pop() if len(found) == 1 else None


def straddles(g, report, src, pred, origin):
    """the exact condition of a broken-once arm. The cut splits the net into the piece of `src` (kept) and the pieces that lose it (lost). Every
    unconnected pair DRC reports must be two items, one on a lost piece and one on the kept piece, and the lost pieces the pairs name must be
    exactly the pieces of the predicted lost pads. An item on no piece, a pair with both items on one side, and a predicted piece no pair
    names all fail. Which item KiCad picks to represent a piece is its own business."""
    kept = g['pad_comp'][src]
    want = {g['pad_comp'][p] for p in pred}
    named = set()
    for u in report.get('unconnected_items', []):
        it = u.get('items', [])
        if len(it) != 2:
            return False
        a, c = (_piece_of(g, i, origin) for i in it)
        if a is None or c is None or (a == kept) == (c == kept):
            return False
        named.add(c if a == kept else a)
    return named == want


def cut_arm(b, text, net, seg, src, drc_fn, origin=(50.0, 150.0)):
    """broken-once arm: remove ONE track (index `seg` of the b.s_* arrays) from a scratch copy of the board text, predict from the graph which pads
    lose the source, and let KiCad's DRC say which pads it reports unconnected"""
    g = CONN.copper_graph(b, net, drop={seg})
    pred = lost_pads(g, src)
    new, n = CONN.cut_segment_text(text, (b.s_x0[seg], b.s_y0[seg], b.s_x1[seg], b.s_y1[seg]), ox=origin[0], oy=origin[1])
    rep_ = drc_fn(new) if n == 1 else {}
    un = drc_unconnected(rep_)
    named = sorted({p for u in un for p in u['pads']})
    return dict(track=f"{LAYER_NAMES[int(b.s_layer[seg])]} ({b.s_x0[seg]:.3f},{b.s_y0[seg]:.3f})-({b.s_x1[seg]:.3f},{b.s_y1[seg]:.3f})", removed_from_text=n,
                graph_lost_pads=pred, drc_unconnected=len(un), drc_named_pads=named, drc_items=un,
                agree=bool(n == 1 and bool(pred) == bool(un) and straddles(g, rep_, src, pred, origin)))


def _pin_key(pin):
    return pin.replace('.', '_').lower()


def prove_net(b, text, drc_fn, drc_baseline, spec, origin):
    """what joins the proved pins to the source, from the board's own copper (see connectivity.py), with the zone fills left out,
    against KiCad's DRC, and with one track cut at a time. `spec` is the table's PROOF."""
    net, src, pins = spec['net'], spec['source'], tuple(spec['pins'])
    g = CONN.copper_graph(b, net)
    g0 = CONN.copper_graph(b, net, zones=False)
    zones = CONN.board_zones(text)
    paths = {pin: CONN.join_path(g, pin, src) for pin in pins}
    up_net, up_a, up_b = spec['upstream']
    up = CONN.copper_graph(b, up_net)
    up_path = CONN.join_path(up, up_a, up_b)
    arms = []
    for label, pin, pick in spec['arms']:
        tr = [n for n in paths[pin] if n[0].startswith('track')]
        if not tr:
            continue
        k = tr[0] if pick == 'first' else tr[len(tr) // 2]
        a = cut_arm(b, text, net, g['nodes'][k[2]]['i'], src, drc_fn, origin)
        a['label'] = label
        arms.append(a)
    zn = [dict(z, on_net=bool(z['net'] == net)) for z in zones]
    P = dict(net=net, source=src, counts=g['counts'], arcs=g['arcs'], pads=sorted(g['pad_comp']), components=CONN.components(g),
             components_without_zones=CONN.components(g0), zones=zn, zones_on_net=sum(z['on_net'] for z in zn),
             length_mm=float(sum(np.hypot(b.s_x1[k] - b.s_x0[k], b.s_y1[k] - b.s_y0[k]) for k in np.flatnonzero(b.s_net == b.nets.index(net)))))
    for pin in pins:
        P['path_' + _pin_key(pin)] = [dict(item=a, link=l) for a, l, _ in paths[pin]]
    P.update(upstream_components=CONN.components(up), upstream_path=[dict(item=a, link=l) for a, l, _ in up_path] if up_path else None,
             upstream_counts=up['counts'], drc_unconnected_baseline=int(drc_baseline))
    for pin in pins:
        P['joined_' + pin.split('.')[1]] = g['pad_comp'][pin] == g['pad_comp'][src]
    P['joined_%s_without_zones' % pins[0].split('.')[1]] = g0['pad_comp'][pins[0]] == g0['pad_comp'][src]
    P['arms'] = arms
    return P


def proof_md(P, T):
    spec = T.PROOF
    pins = tuple(spec['pins'])
    o = []
    w = o.append
    comp = [c for c in P['components'] if c]
    one = len(comp) == 1 and set(pins) <= set(comp[0])
    status = 'PROVEN JOINED' if one and P['drc_unconnected_baseline'] == 0 else '**NOT PROVEN: SEE BELOW**'
    w(tpl(T.PROOF_HEADING, status=status))
    w(tpl(T.PROOF_INTRO, net=P['net']))
    w(tpl(T.PROOF_COPPER, tracks=P['counts']['tracks'], length=P['length_mm'], vias=P['counts']['vias'], npads=P['counts']['pads'],
          pads=', '.join(P['pads']), arcs=P['arcs'], zones_on_net=P['zones_on_net'], nzones=len(P['zones'])))
    w(md_table(['#', 'name', 'net', 'layers', 'kind', 'priority', spec['on_net_head']],
               [[i, z['name'] or '(unnamed)', z['net'] or '(none)', ' '.join(z['layers']), 'rule area (keep-out, not copper)' if z['keepout'] else 'copper pour', z['priority'], 'yes' if z['on_net'] else 'no'] for i, z in enumerate(P['zones'])]))
    w('')
    same = 'the same' if P['components_without_zones'] == P['components'] else '**different**: ' + str(P['components_without_zones'])
    jn = {pin: P['joined_' + pin.split('.')[1]] for pin in pins}
    w(tpl(T.PROOF_RESULT, ncomp=len(comp), net=P['net'], pieces='; '.join('{' + ', '.join(c) + '}' for c in comp), same=same,
          src=P['source'], j_a=('is' if jn[pins[0]] else '**is not**'), j_b=('yes' if jn[pins[1]] else '**no**')))
    for pin in T.PROOF_PATH_ORDER:
        ref, num = pin.split('.')
        w(tpl(T.PROOF_PATH_HEAD, ref=ref, pin=num, src=P['source']))
        w(md_table(['step', 'copper item', 'joined to the previous by'], [[i, s['item'], s['link']] for i, s in enumerate(P['path_' + _pin_key(pin)])]))
        w('')
    w(T.PROOF_HISTORY)
    if P['upstream_path']:
        w(tpl(T.PROOF_UPSTREAM, n=len(P['upstream_path']), tracks=P['upstream_counts']['tracks'], vias=P['upstream_counts']['vias'],
              fills=P['upstream_counts']['zone_fills'], chain=' -> '.join(s['item'] for s in P['upstream_path'])))
    else:
        w(T.PROOF_UPSTREAM_NONE)
    w(tpl(T.PROOF_DRC, n=P['drc_unconnected_baseline']))
    w(md_table(['arm', 'track cut', 'removed from the scratch text', 'graph: pads that lose the source', 'DRC unconnected items', 'DRC item(s)', 'agree'],
               [[a['label'], a['track'], a['removed_from_text'], ', '.join(a['graph_lost_pads']) or 'none', a['drc_unconnected'], ' | '.join(' / '.join(u['raw']) for u in a['drc_items']) or '-', 'yes' if a['agree'] else '**NO**'] for a in P['arms']]))
    w(T.PROOF_RULE)
    return '\n'.join(o)


# ---------------------------------------------------------------------------------------------------- evidence rows
def load_evidence(T):
    """read every evidence entry of the table: {name: values}; entries with `json` + `values` read named values by dotted path (and may be
    written to data/), entries with only `json` are the whole file. Then the derived values."""
    ctx, written = {}, {}
    for e in T.EVIDENCE_DATA:
        j = read_json(os.path.join(REPO, e['json']))
        if 'values' in e:
            vals = {k: dotted(j, p) for k, p in e['values'].items()}
            ctx[e['name']] = vals
            if e.get('write'):
                written[e['write']] = vals
        else:
            ctx[e['name']] = j
    for d in getattr(T, 'EVIDENCE_DERIVED', ()):
        ctx[d['name']] = _derive(d, ctx)
    return ctx, written


def _arg(a, ctx):
    return dotted(ctx, a) if isinstance(a, str) else a


def _derive_arith(d, ctx):
    if d['op'] == 'add':
        return sum(_arg(a, ctx) for a in d['args'])
    return _arg(d['a'], ctx) / _arg(d['b'], ctx)


def _derive(d, ctx):
    op = d['op']
    if op in ('add', 'div'):
        try:
            return _derive_arith(d, ctx)
        except (TypeError, KeyError):
            return None            # an input is absent (a `find` that found nothing): the value is absent too
    if op == 'find':
        return next((f for f in dotted(ctx, d['list']) if all(f[k] == v for k, v in d['match'].items())), None)
    if op == 'margins':
        res = dotted(ctx, d['data'])
        return d['sep'].join(tpl(d['fmt'], case=k.split(d['case_split'])[0], margin=d['limit'] - v[d['key']]) for k, v in res.items())
    if op == 'regex':
        m = re.search(d['pattern'], read_text(os.path.join(REPO, d['file'])), re.S)
        return tpl(d['found'], g=(m.group(0),) + m.groups()) if m else d['missing']
    raise ValueError(f'unknown derived op {op!r}')


def table_rows(blk, ctx):
    """the cells of a `table` evidence block, each template filled from ctx"""
    return [[tpl(c, **ctx) for c in row] for row in blk['rows']]


def render_block(blk, ctx):
    """one evidence block as a list of document chunks (each chunk is one `w` call of the builder)"""
    kind = blk['kind']
    if 'when' in blk and ctx.get(blk['when']) is None:
        return []
    if kind == 'text':
        return [tpl(blk['text'], **ctx)]
    if kind == 'table':
        return [md_table(blk['head'], table_rows(blk, ctx))]
    if kind == 'cap_table':
        rows = []
        for f in dotted(ctx, blk['data'])['figures']:
            unit = 'fF' if f['kind'] == 'pair' else 'pF'
            v = f['extrapolated'] * (1e3 if f['kind'] == 'pair' else 1)
            u = f['uncertainty'] * (1e3 if f['kind'] == 'pair' else 1)
            rows.append([f['figure'], f['kind'], 'pour' if f['pour'] else 'no pour', f"{fnum(v)} +- {fnum(u)} {unit}", f['status'][:60], f.get('pad_used'), f.get('window_limited')])
        return [md_table(['figure', 'kind', 'case', 'extrapolated +- spread', 'status', 'window pad used (mm)', 'window limited'], rows)]
    if kind == 'matrix':
        s = dotted(ctx, blk['data'])
        res = s['results']
        out = [md_table([blk['head0']] + list(res.keys()), [[lab] + [fnum(res[k][key], 4) for k in res] for key, lab in blk['rows']])]
        out.append('\n' + '\n'.join(f"- {k}: {v}" for k, v in s['cases'].items()))
        return out
    raise ValueError(f'unknown evidence block kind {kind!r}')


# ============================================================================================ document
def build_doc(D, T, config_name):
    o = []
    w = o.append
    info = D['info']
    w(f'# Gate 3 package: {T.TITLE}\n')
    w(f"Generated by {T.GENERATED_BY} at {D['generated']}. **Every number below is regenerated from the board "
      f"and the repo by that one command; rerun it when the board changes.** Nothing in this file is typed in; a figure that is not from a "
      f"repo file is marked *(check)*.\n")
    w(f"- Board: `{info['board']}`, sha256 `{info['sha256'][:16]}...`, {info['footprints']} footprints, "
      f"{info['segments']} track segments, {info['vias']} vias, {info['nets']} nets.")
    w('- Tree: git is not in the PCB image, so no commit is recorded; the board\'s sha256 above is the identity of what was checked.')
    w(f"- Checks: `pcbtools` rules (`--config {config_name}`), kicad-cli {D['drc']['kicad']} DRC, in the pinned PCB image.\n")
    w('## Where each section comes from\n')
    w(md_table(['section', 'source (regenerated unless marked)'], [list(r) for r in T.SECTION_SOURCES]) + '\n')

    # 1
    w('## 1. Renders\n')
    w(md_table(['view', 'file', 'exists', 'made from this board'],
               [[r['view'], f"[{os.path.basename(r['file'])}]({r['link']})" if r['exists'] else r['file'], 'yes' if r['exists'] else '**MISSING**',
                 ('yes' if r['current'] else f"**no (STALE: {r['why']})**") if r['exists'] else '-'] for r in D['renders']]))
    if not all(r['exists'] and r['current'] for r in D['renders']):
        w('\n**At least one render was not made from this board file: re-render before publishing** ' + T.RENDER_HINT)
    w('')
    # 2
    w(T.LR_HEADING + '\n')
    w(tpl(T.LR_INTRO, config=config_name))
    rows = []
    for r in D['lr']:
        key = r['rule'].split()[0]
        if r['rule'] in T.LR_DOC_ROWS:
            txt = D['lr_text'].get(key, '(no row in the rules document)')
        else:
            txt = next((t for sub, t in T.LR_SUBCHECKS if sub in r['rule']), '(see note above)')
        txt = re.sub(r'\*\*', '', txt)
        first = txt.split('. ')[0][:230]
        rows.append([r['rule'], 'PASS' if r['ok'] else '**FAIL**', first, r['detail'], figs_str(r['figures'])])
    w(md_table(['rule', 'verdict', 'rule text (start)', 'checker detail', 'figures'], rows))
    w('')
    nfail = [r['rule'] for r in D['lr'] if not r['ok']]
    w(f"Raw verdicts: {len(D['lr']) - len(nfail)} of {len(D['lr'])} rows pass; failing: {', '.join(nfail) or 'none'}. "
      + (f"{T.DRC_ROW} is judged at the project file as it stands: see section 3 for what is behind it ({D['drc']['total'] - D['drc']['undocumented']} documented, {D['drc']['undocumented']} not; run B at the design rules: {D['drc_design']['total']} violations, {D['drc_design']['real_undocumented']} beyond documented and library-copy ones)." if T.DRC_ROW in nfail else '') + '\n')
    # 3
    w('## 3. DRC (kicad-cli)\n')
    rd = D['rule_diff']
    if rd:
        w(tpl(T.RULE_DIFF_TEXT, n=len(rd)))
        w(md_table(['rule', 'project file now', 'design (BOARD_SETUP)'], [[x['rule'], x['project'], x['design']] for x in rd]))
        w('')
    else:
        w('The project file carries the design\'s rules (`BOARD_SETUP`); run A and run B are the same DRC.\n')
    lib_sev = lib_mismatch_text(D.get('_project'))
    for tag, key in (('A: project file as it stands', 'drc'), ('B: at the design rules (BOARD_SETUP applied to a scratch copy)', 'drc_design')):
        d = D[key]
        w(f"**Run {tag}:** {d['total']} violation(s), {d['unconnected']} unconnected, {d['schematic_parity']} schematic-parity. "
          f"{d['total'] - d['undocumented']} documented ({T.DRC_DOCUMENTED_LABEL}), {d['library']} library-copy warnings (`lib_footprint_*`: footprint differs from the stock library copy; {lib_sev}), "
          f"**{d['real_undocumented']} other.**\n")
        if d['counts']:
            w(md_table(['type', 'severity', 'count', 'of which documented'], [[c['type'], c['severity'], c['n'], c['documented']] for c in d['counts']]))
            w('')
    d = D['drc_design']
    items = [i for i in d['items'] if not i['library']]
    if items:
        w('Items of run B (library-copy warnings left out; all of them are in `data/drc_design.json`):\n')
        w(md_table(['type', 'items', 'positions (Due mm)', 'documented'], [[i['type'], '; '.join(i['items']), ' ; '.join(str(tuple(p)) for p in i['pos_due_mm']), 'yes' if i['documented'] else '**NO**'] for i in items]))
    w('\n' + T.DRC_DOCUMENTED_NOTE + '\n')
    # 4
    B = D['bridges']
    w('## 4. Bridge and hop table\n')
    nb = len(B['bridges'])
    w(f"**{nb} zero-ohm bridge parts** on the board ({', '.join(B['board_refs'])}); `design.py` lists {len(B['design_refs'])}"
      + ('; the two agree.' if B['board_refs'] == B['design_refs'] else '; **THEY DIFFER** (board only: ' + ', '.join(sorted(set(B['board_refs']) - set(B['design_refs']))) + '; design only: ' + ', '.join(sorted(set(B['design_refs']) - set(B['board_refs']))) + ').'))
    rul = [r for r in B['bridges'] if r['needs_ruling']]
    over = [r for r in rul if set(r['ruling_classes']) & {'adc', 'vref'}]
    div = [r for r in B['bridges'] if 'divider' in r['ruling_classes']]
    parts = D['bridge_parts']
    rules_txt = read_text(os.path.join(REPO, T.RULE_DOC))
    d24_m = re.search(T.D24_ROW_PATTERN, rules_txt)
    d24_q = re.search(T.D24_QUOTE_PATTERN, d24_m.group(0)) if d24_m else None
    cited = tpl(T.D24_FOUND, quote=d24_q.group(0).replace('**', '')) if d24_q else T.D24_MISSING
    if len(parts) == 1 and '0603' in parts[0][2]:
        parts_txt = 'All are one 0603 type (' + ', '.join(f'{c} {v}, {f}' for c, v, f in parts) + ')'
    else:
        parts_txt = f"**They are {len(parts)} part types or not all 0603: " + '; '.join(f'{c} {v} {f}' for c, v, f in parts) + '**'
    div_txt = 'none crosses a divider node' if not div else f"**{len(div)} cross a divider node ({', '.join(r['ref'] for r in div)})**"
    w("**Count and acceptance.** " + cited + tpl(T.BRIDGE_ACCEPT, nb=nb, nover=len(over), over=', '.join(r['ref'] for r in over) or 'none', parts=parts_txt, div=div_txt))
    brow = []
    for r in B['bridges']:
        cr = '; '.join(f"{c['net']} ({c['layer']}, edge gap {c['edge_gap_mm']} mm" + (f", {c['cls']}" if c['cls'] else '') + ')' for c in r['crossed']) or 'none found under the body'
        brow.append([r['ref'], f"({r['x']:.2f}, {r['y']:.2f})", 'F.Cu', f"{r['net_a']} / {r['net_b']}", cr, r['block'], r['why'], ('accepted: LR-1 method over ' + ','.join(r['ruling_classes'])) if r['needs_ruling'] else 'accepted (no ADC, divider or VREF line under it)'])
    w(md_table(['ref', 'position (Due mm)', 'layer', 'pad nets (1 / 2)', 'net crossed (track under the body)', 'block', 'justification (design.py)', 'class'], brow))
    w('\nCrossing method: the pad-to-pad axis, 0.4 mm either side (a 0603 body is 0.8 mm wide), middle 40 % of the way between pad centres, every other-net track of either layer whose centre line comes within 0.4 mm + half its width. '
      'Copper pours are not counted (a ground pour under a bridge is the plane\'s business, LR-1). A bridge with "none found" has no foreign track under it on this board; its justification is design.py\'s.\n')
    w(f"**Bridges over an ADC line, divider node or VREF branch ({len(rul)}), all accepted:** " + (', '.join(f"{r['ref']} ({', '.join(c['net'] for c in r['crossed'] if c['cls'] in RULING)})" for r in rul) or 'none') + '.\n')
    w('**Bottom-layer hops** (every B.Cu track; the ground plane is a zone, not a track):\n')
    if B['hops']:
        w(md_table(['net', 'length mm', 'width mm', 'segments', 'vias at its ends', 'ends (Due mm)', 'top nets it passes under'],
                   [[h['net'], fnum(h['length_mm']), h['width_mm'], h['segments'], h['vias'], ' to '.join(str(tuple(e)) for e in h['ends']), ', '.join(c['net'] + (f" ({c['cls']})" if c['cls'] else '') for c in h['crosses']) or 'none'] for h in B['hops']]))
    else:
        w('none')
    lr1 = next(r for r in D['lr'] if r['rule'] == 'LR-1')
    w(f"\nLR-1's limit is {D['cfg']['HOP_MAX']} mm and {D['cfg']['HOP_MAX_VIAS']} vias per hop; the checker reports {int(lr1['figures']['bottom_runs'])} bottom run(s), longest {lr1['figures']['max_run_mm']} mm with {int(lr1['figures']['max_run_vias'])} vias.\n")
    # 5
    w('## 5. Deviation list\n')
    dev = []
    for r in D['drc_design']['items']:
        if r['documented']:
            dev.append([T.DEV_COURT[0], tpl(T.DEV_COURT[1], items=' vs '.join(r['items'])), T.DEV_COURT[2]])
    pc = D['power_caps']
    pin_key = T.POWER_CAPS['ic'].lower() + '_pin'
    far_mm = T.POWER_CAPS['far_mm']
    far = [c for c in pc if c['dist_mm'] > far_mm]
    near = [c for c in pc if c['dist_mm'] <= far_mm]
    dev.append([T.DEV_POWER[0], tpl(T.DEV_POWER[1], far_mm=far_mm, ic=T.POWER_CAPS['ic'],
                                    far=', '.join(f"{c['cap']} {c['dist_mm']:.2f} mm (pin {c[pin_key]}, {c['net']})" for c in far) or 'none',
                                    near=', '.join(f"{c['cap']} {c['dist_mm']:.2f}" for c in near)), T.DEV_POWER[2]])
    cq = D['cfg']
    if T.DEV_FOREIGN is not None:                  # optional rows: a board whose config has no designator waivers sets them to None
        fw = cq[T.CFG_FOREIGN_WAIVED]
        dev.append([T.DEV_FOREIGN[0], tpl(T.DEV_FOREIGN[1], n=len(fw), detail=(': ' + ', '.join(f'{k} in {v}' for k, v in fw.items())) if fw else T.DEV_FOREIGN_EMPTY), T.DEV_FOREIGN[2]])
    if T.DEV_GAP is not None:
        gw = cq[T.CFG_GAP_WAIVED]
        dev.append([T.DEV_GAP[0], tpl(T.DEV_GAP[1], n=len(gw), gap_min=cq[T.CFG_GAP_MIN], pairs=', '.join(f'{a}/{b_} {f}' for (a, b_), f in gw.items())),
                    tpl(T.DEV_GAP[2], one_label=cq[T.CFG_GAP_ONE_LABEL])])
    ov = D['outline']
    mc1 = re.search(T.MC1_PATTERN, rules_txt)
    dev.append([T.DEV_OUTLINE[0], tpl(T.DEV_OUTLINE[1], overhang=ov['overhang'], w=ov['w'], h=ov['h'], max0=ov['max'][0], max1=ov['max'][1], band=ov['band']),
                T.MC1_FOUND if mc1 else T.MC1_MISSING])
    dev.append([T.DEV_EDGE[0], tpl(T.DEV_EDGE[1], edge_rule=ov['edge_rule'], edge_cfg=ov['edge_cfg']), T.DEV_EDGE[2]])
    r5 = D['proof5v']
    pins = tuple(T.PROOF['pins'])
    joined = all(r5['joined_' + p.split('.')[1]] for p in pins)
    dev.append([T.DEV_PROOF[0], tpl(T.DEV_PROOF[1], tracks=r5['counts']['tracks'], length=r5['length_mm'], vias=r5['counts']['vias'], zones=r5['zones_on_net'], pads=', '.join(r5['pads']),
                                    result=T.DEV_PROOF_JOINED if joined else T.DEV_PROOF_NOT), T.DEV_PROOF[2]])
    w(md_table(['rule / item', 'deviation (figures from this run)', 'status / authority'], dev))
    w(proof_md(D['proof5v'], T))
    w('\n' + T.POWER_CAPS_CAPTION + '\n')
    w(md_table(['cap', 'net', f"{T.POWER_CAPS['ic']} pin", 'distance mm'], [[c['cap'], c['net'], c[pin_key], fnum(c['dist_mm'], 3)] for c in pc]))
    w('\n**Margins of the passing rules** (checker figures against the config limits; "marginal" = under 10 % of the limit):\n')
    w(md_table(['rule', 'what', 'value', 'limit', 'margin', ''], [[m['rule'], m['what'], fnum(m['value']), ('<= ' if m['kind'] == 'max' else '>= ') + fnum(m['limit']), fnum(m['margin']), '**marginal**' if m['marginal'] else ''] for m in D['margins']]))
    w('')
    # 6
    w(T.EVIDENCE_HEADING + '\n')
    for blk in T.EVIDENCE:
        for chunk in render_block(blk, D['evidence']):
            w(chunk)
    # 7
    M = D['bom']
    counts = tuple(T.BOARD_COUNTS)
    rep = T.REPORT_BOARDS
    w('## 7. BOM and cost\n')
    w(tpl(T.BOM_INTRO, fx=M['fx']))
    head = ['LCSC', 'class', 'refs', 'qty', 'value', 'footprint', f'unit CNY @{counts[0]} boards'] + [f'@{k}' for k in counts[1:]] + [f'line USD per board @{rep}']
    w(md_table(head,
               [[l['lcsc'], l['cls'], ','.join(l['refs']) if len(l['refs']) <= 6 else ','.join(l['refs'][:5]) + f',... ({len(l["refs"])})', l['qty'], l['value'], l['footprint'].split(':')[-1],
                 *[('no price in repo' if l[f'unit_cny_{k}'] is None else fnum(l[f'unit_cny_{k}'], 4)) for k in counts],
                 'no price in repo' if l[f'line_usd_{rep}'] is None else fnum(l[f'line_usd_{rep}'], 4)] for l in M['lines']]))
    w('\n' + T.BOM_UNIT_NOTE + f"Derived-from-international prices (marked D in bom.md and order-5-100.md): {', '.join(l['lcsc'] for l in M['lines'] if l['derived']) or 'none'}.\n")
    w('**Parts on the board with no LCSC number** (not JLC-assembled; test-point pads, owner-fitted sockets and headers, mounting holes):\n')
    w(md_table(['value', 'footprint', 'refs'], [[n['value'], n['footprint'].split(':')[-1], ','.join(n['refs'])] for n in M['nolcsc']]))
    w('\n**Owner-fitted lines priced by the engine** (`' + T.BOM_EXTRA_CSV + '`, block owner):\n')
    w(md_table(['engine ref', 'part', 'LCSC', 'qty', 'price (USD each)', 'note'], [[r['ref'], r['value'], r['lcsc'] or '-', r['qty'], r['fixed_usd'] if r['fixed_usd'] else ('ladder' if r['lcsc'] else 'UNPRICED'), r['note'][:140]] for r in M['owner_rows']]))
    w('\n**Reconciliation, board against the engine\'s lists** (any LCSC whose count differs):\n')
    w(md_table(['LCSC', 'on board', 'in engine lists', 'diff', 'refs'], [[x['lcsc'], x['board'], x['engine'], x['diff'], ','.join(x['refs'])] for x in M['diffs']]) if M['diffs'] else 'none')
    w('\n' + T.BOM_RECONCILE_NOTE + '\n')
    rs = M['results']
    hdr = ['boards', 'orders', 'per-board total USD (X-ray wholly at its tier / tier by tier)', 'JLC parts CNY/board', 'fees+joints+X-ray CNY/board', 'setup CNY/board', 'PCB CNY/board', 'owner-fitted CNY/board', 'placements']
    for tag, title in (('board', 'Board-adjusted (the bridges and any other excess over the engine lists included)'), ('engine', 'Engine stream lists (schematic-era, no bridges; bom.md now reads the board)')):
        w(f'\n**{title}**\n')
        w(md_table(hdr, [[k.split('_')[1], rs[k]['orders'], f"${rs[k]['total_usd_lo']:.2f} / ${rs[k]['total_usd_hi']:.2f}", fnum(rs[k]['parts_cny'], 4), fnum(rs[k]['fees_cny'], 4), fnum(rs[k]['setup_cny'], 4), fnum(rs[k]['pcb_cny'], 4), fnum(rs[k]['owner_cny'], 4), rs[k]['placements']] for k in sorted((k for k in rs if k.startswith(tag)), key=lambda k: int(k.split('_')[1]))]))
    bp = M['bridge_part']
    for c, x in bp.items():
        u = x[f'unit_cny_{rep}']
        w(tpl(T.BRIDGE_PART_TEXT, n=x['n'], c=c, mfr=x['mfr'], cls=x['cls'], read_utc=x['read_utc'], ratio=D['bom_d_ratio'], u=u,
              stock='stock ' + str(x['stock']), unpriced=', '.join(M['unpriced_board']) or 'none', dnp=', '.join(M['dnp']) or 'none'))
    w(T.BOM_PCB_NOTE + '\n')
    ta, tb = T.TARGET_BOARDS
    tgt = T.COST_TARGET + tpl(T.COST_TARGET_RESULT, a=ta, b=tb, a_lo=rs[f'board_{ta}']['total_usd_lo'], a_hi=rs[f'board_{ta}']['total_usd_hi'],
                              b_lo=rs[f'board_{tb}']['total_usd_lo'], b_hi=rs[f'board_{tb}']['total_usd_hi'])
    w(f"**Cost target.** {tgt}\n")
    w(f"**Packages in use** (from the board's footprint names): {', '.join(M['packages'])}. " + '; '.join(f"{p} is " + ('not used' if M[f'no_{p}'] else '**USED**') for p in T.WATCH_PACKAGES) + '.\n')
    w('## Gaps (what this package could not source)\n')
    for g in T.GAPS:
        w('- ' + g)
    w('')
    return '\n'.join(o) + '\n'


# ============================================================================================ the run
def stamp_now():
    return datetime.datetime.now().isoformat(timespec='minutes')


def generate(cfg, T, out_dir, config_name, stamp=None):
    """build the whole package for board config `cfg` and table `T` into `out_dir` (GATE3.md and data/); returns the document text.
    stamp: the generated-at text (default: now)."""
    from pcbtools import boardio
    board = os.path.join(REPO, T.BOARD)
    project = os.path.join(REPO, T.PROJECT)
    data_dir = os.path.join(out_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    b = boardio.read_board_retry(board)
    props = footprint_props(board)
    D = dict(generated=stamp or stamp_now())
    D['info'] = sec_info(b, T)
    D['renders'] = sec_renders(T)
    rep = run_drc(board)
    D['drc'] = sec_drc(rep, T)
    D['drc_design'] = sec_drc(run_drc(board, cfg.BOARD_SETUP), T)
    D['_project'] = read_json(project)
    D['rule_diff'] = rule_diff(D['_project'], cfg.BOARD_SETUP)
    D['lr'] = sec_lr(b, cfg, rep, T)
    D['lr_text'] = lr_texts(os.path.join(REPO, T.RULE_DOC))
    D['bridges'] = sec_bridges(b, cfg, T)
    D['power_caps'] = power_caps(b, cfg, T)
    text = read_text(board)
    D['proof5v'] = prove_net(b, text, lambda s: run_drc(board, board_text=s), D['drc']['unconnected'], T.PROOF, T.DUE_ORIGIN)
    D['bridge_parts'] = sorted({(props[r]['lcsc'], props[r]['value'], props[r]['fp'].split(':')[-1]) for r in D['bridges']['board_refs']})
    D['cfg'] = {k: (dict(getattr(cfg, k)) if isinstance(getattr(cfg, k), dict) else getattr(cfg, k)) for k in T.CFG_QUOTED}
    o = b.outline
    pro = read_json(project)
    g = sh(['git', '-c', 'safe.directory=*', '-C', REPO, 'log', '--all', '--oneline', '-1', T.MC1_COMMIT])
    commit_found = None if g.startswith('unavailable') else (T.MC1_COMMIT in g)
    D['outline'] = dict(overhang=cfg.OVERHANG, w=float(o[:, 0].max() - o[:, 0].min()), h=float(o[:, 1].max() - o[:, 1].min()), max=list(cfg.BOARD_MAX_MM),
                        band='; '.join(f'{n}, y {r[1]} to {r[3]} Due mm' for n, r in cfg.KEEPOUTS), commit_found=commit_found,
                        edge_rule=pro['board']['design_settings']['rules']['min_copper_edge_clearance'],
                        edge_cfg=cfg.BOARD_SETUP['board']['design_settings']['rules']['min_copper_edge_clearance'])
    f = {r['checker_row']: r['figures'] for r in D['lr']}
    items = []
    for m in T.MARGINS:
        if 'each_of' in m:
            items.extend((m['rule'], k, v, getattr(cfg, m['limit']), m['kind']) for k, v in f[m['each_of']].items())
        else:
            items.append((m['rule'], m['what'], f[m['row']][m['key']], getattr(cfg, m['limit']), m['kind']))
    D['margins'] = margin_rows(items)
    D['evidence'], written = load_evidence(T)
    bom = load_bom_engine(T)
    D['bom_d_ratio'] = bom.D_RATIO
    D['bom'] = sec_bom(b, props, T, bom)
    for k in ('info', 'renders', 'drc', 'drc_design', 'rule_diff', 'lr', 'bridges', 'power_caps', 'proof5v', 'outline', 'margins'):
        _dump(D[k], os.path.join(data_dir, f'{k}.json'))
    for name, vals in written.items():
        _dump(vals, os.path.join(data_dir, name))
    _dump(D['bom'], os.path.join(data_dir, 'bom.json'))
    counts = tuple(T.BOARD_COUNTS)
    rp = T.REPORT_BOARDS
    with open(os.path.join(data_dir, 'bom_lines.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh, lineterminator='\n')
        wr.writerow(['lcsc', 'class', 'refs', 'qty', 'value', 'footprint'] + [f'unit_cny_{k}' for k in counts] + [f'line_usd_{rp}'])
        for l in D['bom']['lines']:
            wr.writerow([l['lcsc'], l['cls'], ' '.join(l['refs']), l['qty'], l['value'], l['footprint'], *[l[f'unit_cny_{k}'] for k in counts], l[f'line_usd_{rp}']])
    with open(os.path.join(data_dir, 'bridges.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh, lineterminator='\n')
        wr.writerow(['ref', 'x', 'y', 'net_a', 'net_b', 'crossed', 'needs_ruling', 'block', 'why'])
        for r in D['bridges']['bridges']:
            wr.writerow([r['ref'], r['x'], r['y'], r['net_a'], r['net_b'], ';'.join(c['net'] for c in r['crossed']), r['needs_ruling'], r['block'], r['why']])
    doc = build_doc(D, T, config_name)
    with open(os.path.join(out_dir, 'GATE3.md'), 'w') as fh:
        fh.write(doc)
    return doc


def _dump(obj, path):
    with open(path, 'w') as fh:
        json.dump(obj, fh, indent=1, default=float)
