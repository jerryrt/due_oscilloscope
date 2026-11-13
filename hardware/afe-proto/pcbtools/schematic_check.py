"""The generic checks of a generated project (the old check.py), on a board config, with their mutation arms.

Rows (each is `Row(id, ok, detail)`; `tag` is appended to the id, as the arms do):

    S1  ERC through kicad-cli: nothing live left, exactly cfg.ERC_EXCLUDED documented exclusions
    S2  the exported netlist's connectivity equals design.PARTS, net for net and pin for pin
    S3  every symbol's value, footprint and LCSC field equal PARTS
    S4  every designator, LCSC code and count equals cfg.BOM_PATH (known deltas in cfg.BOM_DELTAS)
    P1  every board pad's net equals the schematic netlist                       (arrays, pure)
    P2  DRC through kicad-cli with schematic parity: nothing but unrouted items  (a file)
    P3  every footprint inside the outline, the Due headers on their V03 pins     (arrays, pure)

Entry points
    schematic_rows(sch_path, parts, cfg, tag='')  -> (rows, nets)        S1..S4; nets = {kicad net: [(ref, pin)]}
    board_rows(board, nets, cfg, tag='', drc_path=None) -> (rows, drc)   P1, P3 on `board` (BoardArrays) and, when drc_path
                                                                         is a .kicad_pcb, P2 on it
    arms(cfg, nets, board, board_path, work) -> [Arm]                    the generic mutation arms (below)
    run_arms(arm_list) -> rows                                           one row per arm plus the 'M*' summary row

What a board config provides (module-level names, a types.SimpleNamespace with the same names works):
    PARTS            list of part dicts: ref, value, fp, lcsc, pins {pin: net}, dnp, fitted_by
    BOM_PATH, BOM_DELTAS, ERC_EXCLUDED, MIN_NETS, MIN_COMPS, MIN_BOM, MIN_PADS
    BOARD_RECT       (x0, y0, x1, y1) in Due mm;  HEADER_PINS {(ref, pin): (x, y)};  HEADER_TOL_MM
    SILK_EDGE_ALLOWED refs whose silk_edge_clearance DRC reports are by design
    sch_cfg(**over)  the namespace schematic.write_all takes (the schematic arms regenerate the project with one field changed)
    ARM_*            names the arms break: ARM_SWAP_PINS (a two-pin part), ARM_LCSC (ref, other code), ARM_BOM_DROP (ref),
                     ARM_NO_FLAG (a PWR_FLAG net), ARM_NET_SWAP (a two-pad part), ARM_OVERLAP (ref, ref), ARM_HEADER (ref, pin)
An Arm is Arm(id, text, run) where run() -> True when the check CAUGHT the break: a board declares its own the same way.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable

import numpy as np

from . import mutate
from . import schematic as sch
from . import sexpr as sx
from .editor import edit


@dataclasses.dataclass
class Row:
    id: str
    ok: bool
    detail: str

    def line(self):
        return f"{'PASS' if self.ok else 'FAIL'} {self.id}: {self.detail}"


@dataclasses.dataclass
class Arm:
    id: str
    text: str
    run: Callable[[], bool]


def cli(*args):
    r = subprocess.run(['kicad-cli', *args], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        raise RuntimeError(f'kicad-cli {args}: {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r


# ------------------------------------------------------------------------------------------------ KiCad's own reading
def erc(sch_path):
    """-> (live violations, excluded violations) as text lines"""
    out = os.path.join(tempfile.mkdtemp(prefix='pcbtools-erc-'), 'erc.json')
    cli('sch', 'erc', '--format', 'json', '--severity-all', '-o', out, str(sch_path))
    d = json.load(open(out))
    live, excl = [], []
    for s in d['sheets']:
        for v in s['violations']:
            (excl if v.get('excluded') else live).append(f"{v['type']}: " + '; '.join(i['description'] for i in v['items']))
    return live, excl


def netlist(sch_path):
    """-> (comps {ref: {value, footprint, fields}}, nets {name: [(ref, pin)]}) from kicad-cli's netlist export"""
    out = os.path.join(tempfile.mkdtemp(prefix='pcbtools-net-'), 'net.net')
    cli('sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out, str(sch_path))
    n = sx.parse(open(out).read())
    comps = {}
    for c in sx.find(sx.first(n, 'components'), 'comp'):
        ref = sx.first(c, 'ref')[1]
        f = {sx.first(x, 'name')[1]: x[2] for x in sx.find(sx.first(c, 'fields') or [], 'field') if len(x) > 2}
        comps[ref] = dict(value=sx.first(c, 'value')[1], footprint=(sx.first(c, 'footprint') or [None, ''])[1], fields=f)
    nets = {}
    for e in sx.find(sx.first(n, 'nets'), 'net'):
        nets[sx.first(e, 'name')[1]] = sorted((sx.first(x, 'ref')[1], sx.first(x, 'pin')[1]) for x in sx.find(e, 'node'))
    return comps, nets


# ------------------------------------------------------------------------------------------------ pure comparators
def strip_flags(nets):
    """KiCad's net dict without its own single-pin no-connect nets and without the PWR_FLAG symbols, leading '/' removed"""
    out = {}
    for k, v in nets.items():
        if k.startswith('unconnected-') and len(v) == 1:
            continue          # KiCad's own net for a no-connect pin; a design net on that pin then fails S2
        v = [x for x in v if not x[0].startswith('#')]
        if v:
            out[k.lstrip('/')] = v
    return out


def design_nets(parts):
    want = {}
    for p in parts:
        for pin, net in p['pins'].items():
            want.setdefault(net, []).append((p['ref'], pin))
    return want


def compare_nets(want, got):
    """both net -> [(ref, pin)]; a list of differences (empty = equal). Nets are compared by their pin sets, then by name"""
    diff = []
    ws = {frozenset(v): k for k, v in want.items()}
    gs = {frozenset(v): k for k, v in got.items()}
    for s, k in ws.items():
        if s not in gs:
            diff.append(f'design net {k} {sorted(s)} not in KiCad')
        elif gs[s] != k:
            diff.append(f'net {k} is named {gs[s]} in KiCad')
    for s, k in gs.items():
        if s not in ws:
            diff.append(f'KiCad net {k} {sorted(s)} not in the design')
    return diff


def compare_parts(parts, comps):
    diff = []
    want = {p['ref']: p for p in parts}
    for ref in sorted(set(want) | {r for r in comps if not r.startswith('#')}):
        if ref not in comps:
            diff.append(f'{ref} missing from the netlist')
            continue
        if ref not in want:
            diff.append(f'{ref} not in the design')
            continue
        p, c = want[ref], comps[ref]
        if c['value'] != p['value']:
            diff.append(f"{ref} value {c['value']!r} != {p['value']!r}")
        if c['footprint'] != p['fp']:
            diff.append(f"{ref} footprint {c['footprint']!r} != {p['fp']!r}")
        if c['fields'].get('LCSC', '') != p['lcsc']:
            diff.append(f"{ref} LCSC {c['fields'].get('LCSC')!r} != {p['lcsc']!r}")
    return diff


def bom_txt(path):
    """designator -> LCSC code, from the numbered part lines of a bom.txt and their designator lines"""
    out, lcsc = {}, None
    for line in open(path):
        if re.match(r'^\s*\d+\s+\S', line) and not line.startswith(' ' * 6):
            m = re.search(r'\s(C\d{3,})\s', line)
            lcsc = m.group(1) if m else ''
            continue
        m = re.match(r'^\s{6}([A-Z]+)(\d+)(?:-[A-Z]+(\d+))?\s+x(\d+)\s', line)
        if m and lcsc is not None:
            pre, a, b, n = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), int(m.group(4))
            refs = [f'{pre}{k}' for k in range(a, b + 1)]
            if pre == 'MH':
                continue               # the standoff and its screws: mechanical, no symbol carries their codes
            if len(refs) != n:
                raise ValueError(f'bom.txt count mismatch: {line!r}')
            for r in refs:
                out[r] = lcsc
    return out


def compare_bom(parts, bom, deltas):
    diff = []
    have = {p['ref']: p for p in parts if not p['dnp'] and p['fitted_by'] != 'none'}
    for ref, lc in bom.items():
        if ref not in have:
            diff.append(f'bom.txt {ref} ({lc}) not fitted in the design')
        elif have[ref]['lcsc'] != lc:
            diff.append(f"{ref}: design {have[ref]['lcsc']} != bom.txt {lc}")
    for ref, p in have.items():
        if ref not in bom and p['lcsc'] and ref not in deltas:
            diff.append(f"{ref} ({p['lcsc']}) fitted but not in bom.txt")
    for ref in deltas:
        if ref in bom:
            diff.append(f'{ref} is listed as a delta but bom.txt now carries it: drop the delta')
    return diff


def _tail(d):
    return ': ' + ' | '.join(d[:4]) if d else ''


# ------------------------------------------------------------------------------------------------ schematic rows
def schematic_rows(sch_path, parts, cfg, tag=''):
    rows = []
    live, excl = erc(sch_path)
    rows.append(Row('S1' + tag, not live and len(excl) == cfg.ERC_EXCLUDED,
                    f'ERC {len(live)} live, {len(excl)} excluded' + (': ' + ' | '.join(live[:4]) if live else '')))
    comps, nets = netlist(sch_path)
    want, got = design_nets(parts), strip_flags(nets)
    d = compare_nets(want, got)
    rows.append(Row('S2' + tag, not d and len(want) >= cfg.MIN_NETS, f'{len(want)} design nets, {len(got)} KiCad nets{_tail(d)}'))
    d = compare_parts(parts, comps)
    rows.append(Row('S3' + tag, not d and len(comps) >= cfg.MIN_COMPS, f'{len(comps)} symbols{_tail(d)}'))
    bom = bom_txt(cfg.BOM_PATH)
    d = compare_bom(parts, bom, cfg.BOM_DELTAS)
    rows.append(Row('S4' + tag, not d and len(bom) >= cfg.MIN_BOM,
                    f'{len(bom)} bom.txt designators, deltas {sorted(cfg.BOM_DELTAS)}{_tail(d)}'))
    return rows, nets


# ------------------------------------------------------------------------------------------------ board rows
def _pad_nets(b):
    refs = np.array(b.fp_ref, dtype=object)[b.p_fp]
    names = np.array(b.nets, dtype=object)[b.p_net]
    return list(zip(refs.tolist(), b.p_pin, names.tolist()))


def p1_rows(b, nets, cfg, tag=''):
    """pad nets against the schematic netlist (every net, KiCad's no-connect nets included)"""
    want = {(ref, pin): net.lstrip('/') for net, nodes in nets.items() for ref, pin in nodes if not ref.startswith('#')}
    diff, seen, n = [], set(), 0
    for ref, pin, net in _pad_nets(b):
        n += 1                # the count is every pad, as the old row printed it
        if not pin:
            continue          # mounting-hole and shield-tab pads with no number
        seen.add((ref, pin))
        w = want.get((ref, pin), '')
        if net.lstrip('/') != w:
            diff.append(f'{ref}.{pin} on {net.lstrip("/")!r}, schematic {w!r}')
    for k in want:
        if k not in seen:
            diff.append(f'{k[0]}.{k[1]} has no pad')
    return Row('P1' + tag, not diff and n > cfg.MIN_PADS, f'{n} pads{_tail(diff)}')


def p3_rows(b, cfg, tag=''):
    x0, y0, x1, y1 = cfg.BOARD_RECT
    out = (b.p_x < x0) | (b.p_x > x1) | (b.p_y < y0) | (b.p_y > y1)
    bad = sorted({b.fp_ref[i] for i in b.p_fp[out]})
    err, found = 0.0, 0
    key = {(b.fp_ref[f], p): i for i, (f, p) in enumerate(zip(b.p_fp.tolist(), b.p_pin))}     # the last pad of a pin wins
    for k, (wx, wy) in cfg.HEADER_PINS.items():
        i = key.get(k)
        if i is not None:
            err = max(err, math.hypot(float(b.p_x[i]) - wx, float(b.p_y[i]) - wy))
            found += 1
    if found != len(cfg.HEADER_PINS):
        err = math.inf       # a header pad missing is a failure, not a pass on fewer pads
    return Row('P3' + tag, not bad and err < cfg.HEADER_TOL_MM,
               f'{len(b.fp_ref)} footprints, {len(bad)} outside the outline {bad[:6]}; worst header pad off V03 by {err:.4f} mm')


def drc_project(pcb_path, cfg, work=None):
    """kicad-cli DRC with schematic parity on a COPY of the project (never in place: it writes next to its input).
    The project is the folder of the board: its .kicad_sch, .kicad_pro, library tables and lib/."""
    src = os.path.dirname(os.path.abspath(pcb_path))
    d = tempfile.mkdtemp(prefix='pcbtools-drc-', dir=work)
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if f == 'lib' and os.path.isdir(p):
            shutil.copytree(p, os.path.join(d, f))
        elif os.path.isfile(p) and f.endswith(('.kicad_pcb', '.kicad_sch', '.kicad_pro', '-lib-table')) and \
                (not f.endswith('.kicad_pcb') or f == os.path.basename(pcb_path)):
            shutil.copy(p, d)
    out = os.path.join(d, 'drc.json')
    cli('pcb', 'drc', '--format', 'json', '--severity-all', '--schematic-parity', '-o', out, os.path.join(d, os.path.basename(pcb_path)))
    return json.load(open(out))


def p2_row(d, cfg, tag=''):
    vio = [v for v in d.get('violations', []) if not v.get('excluded')]
    kinds = {}
    for v in vio:
        kinds[v['type']] = kinds.get(v['type'], 0) + 1
    allowed_re = re.compile(r'of (' + '|'.join(map(re.escape, cfg.SILK_EDGE_ALLOWED)) + r') on') if cfg.SILK_EDGE_ALLOWED else None

    def allowed(v):
        return v['type'] == 'silk_edge_clearance' and allowed_re and any(allowed_re.search(i['description']) for i in v['items'])
    hard = {}
    for v in vio:
        if v['type'] != 'unconnected_items' and not allowed(v):
            hard[v['type']] = hard.get(v['type'], 0) + 1
    par = d.get('schematic_parity', [])
    return Row('P2' + tag, not hard and not par,
               f"DRC {kinds or 'clean'}; unrouted {len(d.get('unconnected_items', []))}; parity {len(par)}"
               + (': ' + ' | '.join(f"{p['type']}: {p['description']}" for p in par[:3]) if par else ''))


def board_rows(b, nets, cfg, tag='', drc_path=None):
    rows = [p1_rows(b, nets, cfg, tag), p3_rows(b, cfg, tag)]
    d = None
    if drc_path is not None:
        d = drc_project(drc_path, cfg)
        rows.insert(1, p2_row(d, cfg, tag))
    return rows, d


# ------------------------------------------------------------------------------------------------ mutation arms
def _rotate_symbols(path, out):
    """a copy of the written schematic whose rotated (90 degree) symbols are all instantiated at 0: the wire stubs stay where
    the drawing put them, so the pins no longer meet them and KiCad must read different connectivity"""
    t = sx.parse(open(path).read())
    n = 0
    for e in t:
        if isinstance(e, list) and e and e[0] == 'symbol' and any(isinstance(x, list) and x[:1] == ['lib_id'] for x in e):
            at = sx.first(e, 'at')
            if at and len(at) > 3 and float(at[3]) == 90:
                at[3] = 0
                n += 1
    assert n, 'no rotated symbol to break'
    open(out, 'w').write(sx.dump(t) + '\n')


def arms(cfg, nets, board, board_path, work):
    """the generic mutation arms; every one breaks one input and the matching row must fail"""
    parts = cfg.PARTS

    def m1():
        p2 = copy.deepcopy(parts)
        pr = next(p for p in p2 if p['ref'] == cfg.ARM_SWAP_PINS)
        pr['pins']['1'], pr['pins']['2'] = pr['pins']['2'], pr['pins']['1']
        return bool(compare_nets(design_nets(p2), strip_flags(nets)))

    def m2():
        p2 = copy.deepcopy(parts)
        ref, code = cfg.ARM_LCSC
        next(p for p in p2 if p['ref'] == ref)['lcsc'] = code
        return bool(compare_bom(p2, bom_txt(cfg.BOM_PATH), cfg.BOM_DELTAS))

    def m2b():
        bom = bom_txt(cfg.BOM_PATH)
        bom.pop(cfg.ARM_BOM_DROP)
        return bool(compare_bom(parts, bom, cfg.BOM_DELTAS))

    def regenerate(**over):
        d = tempfile.mkdtemp(prefix='pcbtools-mut-', dir=work)
        sch.write_all(parts, cfg.sch_cfg(**over), d)
        return d, os.path.join(d, f'{cfg.PROJECT}.kicad_sch')

    def m3():
        d, s = regenerate()
        _rotate_symbols(s, s)
        return bool(compare_nets(design_nets(parts), strip_flags(netlist(s)[1])))

    def m4():
        d, s = regenerate(PWR_FLAG_NETS=[n for n in cfg.sch_cfg().PWR_FLAG_NETS if n != cfg.ARM_NO_FLAG])
        return bool(erc(s)[0])

    def mp1():
        a, c = cfg.ARM_NET_SWAP, None
        pins = [i for i in range(len(board.p_pin)) if board.fp_ref[board.p_fp[i]] == a]
        assert len(pins) == 2, pins
        b2 = mutate.set_pad_net(board, a, board.p_pin[pins[0]], board.nets[board.p_net[pins[1]]])
        b2 = mutate.set_pad_net(b2, a, board.p_pin[pins[1]], board.nets[board.p_net[pins[0]]])
        return not p1_rows(b2, nets, cfg).ok

    def mp2():
        r1, r2 = cfg.ARM_OVERLAP
        out = os.path.join(tempfile.mkdtemp(prefix='pcbtools-mut-', dir=work), os.path.basename(board_path))
        i2 = board.ref_index(r2)
        with edit(board_path, out=out) as e:
            e.move(r1, float(board.fp_x[i2]), float(board.fp_y[i2]))
        shutil.copy(board_path.replace('.kicad_pcb', '.kicad_sch'), os.path.dirname(out))
        pro = board_path.replace('.kicad_pcb', '.kicad_pro')
        if os.path.exists(pro):
            shutil.copy(pro, os.path.dirname(out))
        base = p2_row(drc_project(board_path, cfg, work), cfg)
        broken = p2_row(drc_project(out, cfg, work), cfg)
        return broken.detail != base.detail

    def mp3():
        ref, pin = cfg.ARM_HEADER
        return not p3_rows(mutate.shift_pad(board, ref, pin, dx=0.2), cfg).ok
    return [Arm('M1', f'S2 sees {cfg.ARM_SWAP_PINS} reversed', m1),
            Arm('M2', f'S4 sees {cfg.ARM_LCSC[0]} with another code', m2),
            Arm('M2b', f'S4 sees {cfg.ARM_BOM_DROP} fitted but missing from bom.txt', m2b),
            Arm('M3', 'S2 sees passives drawn at the wrong rotation', m3),
            Arm('M4', f'S1 sees {cfg.ARM_NO_FLAG} without its flag', m4),
            Arm('MP1', 'P1 fails on the net mutation', mp1),
            Arm('MP2', 'P2 fails on the overlap mutation', mp2),
            Arm('MP3', 'P3 fails on the header mutation', mp3)]


def run_arms(arm_list):
    rows = [Row(a.id, bool(a.run()), a.text) for a in arm_list]
    n = sum(r.ok for r in rows)
    rows.append(Row('M*', n == len(rows), f'{n} of {len(rows)} mutation arms failed the check as they must'))
    return rows


def main(argv=None):
    """python -m pcbtools.schematic_check --board v1 --project DIR [--pcb] [--arms]
    DIR holds <PROJECT>.kicad_sch (and .kicad_pcb with --pcb); it is read on a copy. Prints the rows the old check.py printed.
    Exit 0 only if every row passed, 1 otherwise, 2 on bad input."""
    import argparse
    import importlib
    import sys
    ap = argparse.ArgumentParser(prog='python -m pcbtools.schematic_check')
    ap.add_argument('--board', required=True)
    ap.add_argument('--project', required=True)
    ap.add_argument('--pcb', action='store_true')
    ap.add_argument('--arms', action='store_true')
    a = ap.parse_args(argv)
    cfg = importlib.import_module(f'pcbtools.boards.{a.board}')
    work = tempfile.mkdtemp(prefix='pcbtools-check-')
    proj = os.path.join(work, 'project')
    shutil.copytree(a.project, proj, ignore=shutil.ignore_patterns('3d', '__pycache__', 'render', '*.kicad_prl', '~*'))
    s = os.path.join(proj, f'{cfg.PROJECT}.kicad_sch')
    if not os.path.exists(s):
        print(f'no {s}', file=sys.stderr)
        return 2
    rows, nets = schematic_rows(s, cfg.PARTS, cfg)
    board = path = None
    if a.pcb:
        from . import boardio
        path = os.path.join(proj, f'{cfg.PROJECT}.kicad_pcb')
        board = boardio.read_board(path)
        more, _ = board_rows(board, nets, cfg, drc_path=path)
        rows += more
    if a.arms:
        rows += run_arms([x for x in arms(cfg, nets, board, path, work) if board is not None or not x.id.startswith('MP')])
    print('\n'.join(r.line() for r in rows))
    ok = all(r.ok for r in rows)
    print('ALL PASS' if ok else 'FAIL: ' + ', '.join(r.id for r in rows if not r.ok))
    return 0 if ok else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
