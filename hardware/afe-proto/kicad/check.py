"""Validate the generated KiCad files against design.py and whatif/bom.txt.

    python3 -I hardware/afe-proto/kicad/check.py            # schematic checks
    python3 -I hardware/afe-proto/kicad/check.py --pcb      # also the board (after build_pcb.py)

Checks, each through KiCad's own reading of the file (kicad-cli), never
through the generator's idea of what it wrote:

  S1  ERC: no error or warning left after the project's one documented exclusion
  S2  the exported netlist's connectivity equals design.py, net for net and pin for pin
  S3  every symbol's value, footprint and LCSC field equal design.py
  S4  every designator, LCSC code and count equals whatif/bom.txt (known deltas listed with their reason)
  P1  every board pad's net equals the schematic netlist (no pad on a wrong or missing net)
  P2  DRC: no courtyard overlap, nothing off the board, no unconnected-item report beyond unrouted nets
  P3  every footprint sits inside the outline and the Due headers sit on the V03 pin positions
  R1  (--frozen) the committed schematic and board are exactly what the generators make from this tree

Each check is broken on purpose before it is believed (the M-arms below):
a mutated input must make it fail.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design                         # noqa: E402
from sexpr import parse, find, first  # noqa: E402

SCH = os.path.join(HERE, 'afe-proto.kicad_sch')
PCB = os.path.join(HERE, 'afe-proto.kicad_pcb')
BOM = os.path.join(HERE, '..', 'whatif', 'bom.txt')
RESULTS = []

# parts on the board that whatif/bom.txt does not list, each with its reason; anything else missing or extra fails S4
# (D7 / D8 were here until bom.txt carried them)
BOM_DELTAS = {}


def row(cid, ok, detail):
    RESULTS.append((cid, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {cid}: {detail}")
    return ok


def cli(*args):
    r = subprocess.run(['kicad-cli', *args], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        raise RuntimeError(f'kicad-cli {args}: {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r


# ----------------------------------------------------------------------------- schematic
def erc(sch):
    out = os.path.join(tempfile.mkdtemp(prefix='afe-erc-'), 'erc.json')
    cli('sch', 'erc', '--format', 'json', '--severity-all', '-o', out, sch)
    d = json.load(open(out))
    live, excl = [], []
    for s in d['sheets']:
        for v in s['violations']:
            (excl if v.get('excluded') else live).append(f"{v['type']}: " + '; '.join(i['description'] for i in v['items']))
    return live, excl


def netlist(sch):
    out = os.path.join(tempfile.mkdtemp(prefix='afe-net-'), 'net.net')
    cli('sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out, sch)
    n = parse(open(out).read())
    comps = {}
    for c in find(first(n, 'components'), 'comp'):
        ref = first(c, 'ref')[1]
        f = {first(x, 'name')[1]: x[2] for x in find(first(c, 'fields') or [], 'field') if len(x) > 2}
        comps[ref] = dict(value=first(c, 'value')[1], footprint=(first(c, 'footprint') or [None, ''])[1], fields=f)
    nets = {}
    for e in find(first(n, 'nets'), 'net'):
        name = first(e, 'name')[1]
        nodes = sorted((first(x, 'ref')[1], first(x, 'pin')[1]) for x in find(e, 'node'))
        nets[name] = nodes
    return comps, nets


def strip_flags(nets):
    out = {}
    for k, v in nets.items():
        if k.startswith('unconnected-') and len(v) == 1:
            continue          # KiCad's own net for a no-connect pin; a design net on that pin then fails S2
        v = [x for x in v if not x[0].startswith('#')]
        if v:
            out[k.lstrip('/')] = v
    return out


def compare_nets(want, got):
    """Both net -> [(ref, pin)].  Returns a list of differences (empty = equal)."""
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
            diff.append(f'{ref} missing from the netlist'); continue
        if ref not in want:
            diff.append(f'{ref} not in the design'); continue
        p, c = want[ref], comps[ref]
        if c['value'] != p['value']:
            diff.append(f"{ref} value {c['value']!r} != {p['value']!r}")
        if c['footprint'] != p['fp']:
            diff.append(f"{ref} footprint {c['footprint']!r} != {p['fp']!r}")
        if c['fields'].get('LCSC', '') != p['lcsc']:
            diff.append(f"{ref} LCSC {c['fields'].get('LCSC')!r} != {p['lcsc']!r}")
    return diff


# ----------------------------------------------------------------------------- bom.txt
def bom_txt():
    """designator -> LCSC, from the numbered part lines and their designator lines."""
    out, lcsc = {}, None
    for line in open(BOM):
        if re.match(r'^\s*\d+\s+\S', line) and not line.startswith(' ' * 6):
            m = re.search(r'\s(C\d{3,})\s', line)
            lcsc = m.group(1) if m else ''; continue
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


def schematic_checks(sch=SCH, parts=None, tag=''):
    parts = design.PARTS if parts is None else parts
    ok = True
    live, excl = erc(sch)
    ok &= row('S1' + tag, not live and len(excl) == 1,
              f'ERC {len(live)} live, {len(excl)} excluded' + (': ' + ' | '.join(live[:4]) if live else ''))
    comps, nets = netlist(sch)
    want = {}
    for p in parts:
        for pin, net in p['pins'].items():
            want.setdefault(net, []).append((p['ref'], pin))
    d = compare_nets(want, strip_flags(nets))
    ok &= row('S2' + tag, not d and len(want) >= 70,
              f'{len(want)} design nets, {len(strip_flags(nets))} KiCad nets' + (': ' + ' | '.join(d[:4]) if d else ''))
    d = compare_parts(parts, comps)
    ok &= row('S3' + tag, not d and len(comps) >= 150, f'{len(comps)} symbols' + (': ' + ' | '.join(d[:4]) if d else ''))
    bom = bom_txt()
    d = compare_bom(parts, bom, BOM_DELTAS)
    ok &= row('S4' + tag, not d and len(bom) >= 150,
              f'{len(bom)} bom.txt designators, deltas {sorted(BOM_DELTAS)}' + (': ' + ' | '.join(d[:4]) if d else ''))
    return ok, nets


# ----------------------------------------------------------------------------- mutation arms (each must FAIL)
def mutation_arms(nets):
    import build_sch
    bad = 0
    # M1: a design that swaps one pin's net must not match KiCad's netlist (S2's comparator can see one pin)
    parts = copy.deepcopy(design.PARTS)
    pr = next(p for p in parts if p['ref'] == 'R30'); pr['pins']['1'], pr['pins']['2'] = pr['pins']['2'], pr['pins']['1']
    want = {}
    for p in parts:
        for pin, net in p['pins'].items():
            want.setdefault(net, []).append((p['ref'], pin))
    bad += row('M1', bool(compare_nets(want, strip_flags(nets))), 'S2 sees RF (R30) reversed')
    # M2: an LCSC code changed must fail S4; a bom.txt designator dropped must fail S4
    parts = copy.deepcopy(design.PARTS)
    next(p for p in parts if p['ref'] == 'R43')['lcsc'] = 'C2984375'
    bom = bom_txt()
    bad += row('M2', bool(compare_bom(parts, bom, BOM_DELTAS)), 'S4 sees R43 with the 953 ohm code')
    bom2 = dict(bom); bom2.pop('C26')
    bad += row('M2b', bool(compare_bom(design.PARTS, bom2, BOM_DELTAS)), 'S4 sees C26 fitted but missing from bom.txt')
    # M3: geometry: a schematic generated with the passives' rotation wrong must not reproduce the design's nets in
    # KiCad (S2 reads connectivity from the drawing, not from the generator's intent)
    tmp = tempfile.mkdtemp(prefix='afe-mut-')
    for f in ('sexpr.py', 'design.py', 'build_sch.py'):
        shutil.copy(os.path.join(HERE, f), tmp)
    src = open(os.path.join(tmp, 'build_sch.py')).read()
    # keep the wire stubs where the correct rotation would put them: draw with r = 90 offsets, instantiate at r = 0
    src3 = src.replace("['at', ux, sy, cell.r]", "['at', ux, sy, 0 if cell.r == 90 else cell.r]")
    assert src3 != src
    open(os.path.join(tmp, 'build_sch.py'), 'w').write(src3)
    os.makedirs(os.path.join(tmp, 'lib'), exist_ok=True)
    subprocess.run([sys.executable, '-I', os.path.join(tmp, 'build_sch.py')], check=True, capture_output=True)
    _, nets3 = netlist(os.path.join(tmp, 'afe-proto.kicad_sch'))
    bad += row('M3', bool(compare_nets(design.nets(), strip_flags(nets3))), 'S2 sees passives drawn at the wrong rotation')
    # M4: ERC must fail when the GND PWR_FLAG is removed (S1 sees an undriven power net)
    src4 = src.replace("PWR_FLAG_NETS = ['GND', ", "PWR_FLAG_NETS = [")
    assert src4 != src
    open(os.path.join(tmp, 'build_sch.py'), 'w').write(src4)
    subprocess.run([sys.executable, '-I', os.path.join(tmp, 'build_sch.py')], check=True, capture_output=True)
    live, _ = erc(os.path.join(tmp, 'afe-proto.kicad_sch'))
    bad += row('M4', bool(live), f'S1 sees GND without its flag ({len(live)} live violations)')
    shutil.rmtree(tmp, ignore_errors=True)
    del build_sch
    return bad


# ----------------------------------------------------------------------------- board
def pcb_checks(nets, PCB=PCB, tag=''):
    ok = True
    py = '/usr/bin/python3.14'      # the interpreter KiCad's pcbnew module is built against
    r = subprocess.run([py, '-I', os.path.join(HERE, 'pcb_dump.py'), PCB], capture_output=True, text=True, check=True)
    dump = json.loads(r.stdout)
    want = {}
    for net, nodes in nets.items():          # every schematic net, KiCad's no-connect nets included
        for ref, pin in nodes:
            if not ref.startswith('#'):
                want[(ref, pin)] = net.lstrip('/')
    diff = []
    for (ref, pad, net) in dump['pads']:
        if not pad:
            continue          # mounting-hole and shield-tab pads with no number
        w = want.get((ref, pad), '')
        if net != w:
            diff.append(f'{ref}.{pad} on {net!r}, schematic {w!r}')
    seen = {(r, p) for r, p, _ in dump['pads']}
    for k in want:
        if k not in seen:
            diff.append(f'{k[0]}.{k[1]} has no pad')
    ok &= row('P1' + tag, not diff and len(dump['pads']) > 400, f"{len(dump['pads'])} pads" + (': ' + ' | '.join(diff[:4]) if diff else ''))
    out = os.path.join(tempfile.mkdtemp(prefix='afe-drc-'), 'drc.json')
    cli('pcb', 'drc', '--format', 'json', '--severity-all', '--schematic-parity', '-o', out, PCB)
    d = json.load(open(out))
    vio = [v for v in d.get('violations', []) if not v.get('excluded')]
    kinds = {}
    for v in vio:
        kinds[v['type']] = kinds.get(v['type'], 0) + 1
    # silk_edge_clearance is allowed on the three BNCs only: they overhang the right edge by design (bom.txt
    # BOARD OUTLINE; the KH-BNC50-3511 drawing is unread, so the stand-in footprint's depth is *(check)*)
    def allowed(v):
        return v['type'] == 'silk_edge_clearance' and any(re.search(r'of J[123] on', i['description']) for i in v['items'])
    hard = {}
    for v in vio:
        if v['type'] != 'unconnected_items' and not allowed(v):
            hard[v['type']] = hard.get(v['type'], 0) + 1
    par = d.get('schematic_parity', [])
    ok &= row('P2' + tag, not hard and not par,
              f"DRC {kinds or 'clean'}; unrouted {len(d.get('unconnected_items', []))}; parity {len(par)}"
              + (': ' + ' | '.join(f"{p['type']}: {p['description']}" for p in par[:3]) if par else ''))
    bad = [f for f in dump['footprints'] if not f['inside']]
    hd = dump['header_err_mm']
    ok &= row('P3' + tag, not bad and hd < 0.01, f"{len(dump['footprints'])} footprints, {len(bad)} outside the outline "
              f"{[f['ref'] for f in bad][:6]}; worst header pad off V03 by {hd:.4f} mm")
    return ok, d


def pcb_mutation_arms(nets):
    """Each arm breaks a copy of the project (board, schematic, project file) and the matching P-check must fail."""
    bad = 0
    for mode, cid in (('net', 'P1'), ('overlap', 'P2'), ('header', 'P3')):
        tmp = tempfile.mkdtemp(prefix='afe-pmut-')
        for f in ('afe-proto.kicad_pcb', 'afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table'):
            shutil.copy(os.path.join(HERE, f), tmp)
        shutil.copytree(os.path.join(HERE, 'lib'), os.path.join(tmp, 'lib'))
        brd = os.path.join(tmp, 'afe-proto.kicad_pcb')
        subprocess.run(['/usr/bin/python3.14', '-I', os.path.join(HERE, 'pcb_mutate.py'), brd, mode], check=True,
                       capture_output=True)
        print(f'  -- mutation {mode}: expect {cid} to FAIL')
        before = len(RESULTS)
        pcb_checks(nets, PCB=brd, tag='~' + mode)
        failed = {c for c, ok, _ in RESULTS[before:] if not ok}
        bad += row('M' + cid, f'{cid}~{mode}' in failed, f'{cid} fails on the {mode} mutation')
        del RESULTS[before:-1]
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def regenerate(mutate=None):
    """Build the schematic and board from this tree's sources in a scratch copy; return their sha256."""
    import hashlib
    tmp = tempfile.mkdtemp(prefix='afe-regen-')
    for f in ('sexpr.py', 'design.py', 'build_sch.py', 'build_pcb.py'):
        shutil.copy(os.path.join(HERE, f), tmp)
    shutil.copytree(os.path.join(HERE, '3d'), os.path.join(tmp, '3d'))
    shutil.copytree(os.path.join(HERE, 'lib'), os.path.join(tmp, 'lib'))
    if mutate:
        p = os.path.join(tmp, 'design.py'); s = open(p).read(); s2 = s.replace(*mutate); assert s2 != s
        open(p, 'w').write(s2)
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, cwd=tempfile.gettempdir())
    run(sys.executable, '-I', os.path.join(tmp, 'build_sch.py'))
    run('kicad-cli', 'sch', 'upgrade', os.path.join(tmp, 'afe-proto.kicad_sch'))
    run('/usr/bin/python3.14', '-I', os.path.join(tmp, 'build_pcb.py'))
    h = {f: hashlib.sha256(open(os.path.join(tmp, f), 'rb').read()).hexdigest()
         for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pcb')}
    shutil.rmtree(tmp, ignore_errors=True)
    return h


def frozen_checks():
    import hashlib
    have = {f: hashlib.sha256(open(os.path.join(HERE, f), 'rb').read()).hexdigest()
            for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pcb')}
    ok = row('R1', regenerate() == have, 'committed schematic and board regenerate byte for byte')
    # the arm: one value changed in design.py must change the regenerated files
    bad = row('MR1', regenerate(("'22 1%'", "'22R 1%'")) != have,
              'R1 sees one value changed in design.py')
    return ok and bad


if __name__ == '__main__':
    ok, nets = schematic_checks()
    bad = mutation_arms(nets)
    ok &= row('M*', bad == 5, f'{bad} of 5 mutation arms failed as they must')
    if '--pcb' in sys.argv:
        ok &= pcb_checks(nets)[0]
        pb = pcb_mutation_arms(nets)
        ok &= row('MP*', pb == 3, f'{pb} of 3 board mutation arms failed as they must')
    if '--frozen' in sys.argv:
        ok &= frozen_checks()
    print('ALL PASS' if ok else 'FAILED')
    sys.exit(0 if ok else 1)
