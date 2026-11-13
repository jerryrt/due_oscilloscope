"""The rest of the old v2 check.py that is not v2's: rows any generated schematic project can be held to, and the mutation-arm
runner that refuses to call an arm caught unless its row flipped from PASS to FAIL.

schematic_check.py (S1..S4, P1..P3 and their arms) is the shared module of the first port; this one adds, on the same `Row`,
the rows the v2 project needed and the v1 one did not run:

    S1  ERC: nothing live left, exactly cfg.ERC_EXCLUDED documented exclusions            s1_row
    S2  the exported netlist equals the part list, net for net and pin for pin             s2_row
    S3  every symbol's value, footprint and the fields in cfg.COMPARE_FIELDS equal it      s3_row
    E1  every pin connected or declared NC, a declared NC unconnected                      e1_row
    E2  no net with a single pin                                                           e2_row
    E3  every fitted part has a value, a footprint that exists in a library, an LCSC code  e3_row
    E4  the pin names of the parts in cfg.DATASHEET_PINS equal an independent table        e4_row
    numbering   every designator's hundreds digit is its block's, and each block holds exactly its key part list (two rows)
                d_rows
    bridge      the bridges join what they must, and the named parts sit on the named sides      bridge_row
    H1  the connector parts named in cfg.HEADER_TABLE carry exactly the table's pins        header_row
    N*  the netlist comparison with a study's SPICE netlist (spicecmp.py)                   spice_row

Details are written the way the old check.py wrote them, so a verdict AND its text can be compared with the old output.

What a board config provides (module-level names, a types.SimpleNamespace with the same names works), beyond schematic_check's:
    ERC_EXCLUDED, MIN_NETS, MIN_COMPS     the counts and floors (a check that examined fewer items than the floor did not run)
    COMPARE_FIELDS    ((netlist field, part key)) compared by S3 besides value, footprint and LCSC
    FOOTPRINT_DIR, PROJECT_LIB_NAME        where E3 looks a footprint up; the project's own library is <project>/lib/<name>.pretty
    FITTED_BY_BOARD_HOUSE                  the 'Fitted by' field value that must carry an LCSC code
    DATASHEET_PINS    {library part: {pin: name}}
    BLOCKDIGIT        {block: hundreds digit};  KEY_PARTS {block: set of refs}
    ROW_IDS           {'numbering': (id, id), 'bridge': id}: the ids of the rows above that have no fixed one
    BRIDGE_JOINS      {bridge ref: (end, end)}, BRIDGE_SIDES [(end, end)], BRIDGE_TEXT; an end is ('pin', ref, pin) or ('fn', ref, name)
    HEADER_TABLE      {header value: {pin: net}}, HEADER_BLOCK, HEADER_PART_PREFIX, HEADER_LABEL
"""
from __future__ import annotations

import dataclasses
import os
import re
import tempfile
from typing import Callable

from . import schematic_check as sc
from . import spicecmp
from . import sexpr as sx
from .schematic_check import Row, cli


# ------------------------------------------------------------------------------------------------ KiCad's own reading
def netlist_full(sch_path):
    """-> (comps {ref: {value, footprint, fields, part}}, nets {name: [(ref, pin, pin function)]}) from kicad-cli's export;
    `part` is the library symbol's name, the pin function has its '_<pin>' suffix removed"""
    out = os.path.join(tempfile.mkdtemp(prefix='pcbtools-net-'), 'net.net')
    cli('sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out, str(sch_path))
    n = sx.parse(open(out).read())
    comps = {}
    for c in sx.find(sx.first(n, 'components'), 'comp'):
        ref = sx.first(c, 'ref')[1]
        f = {sx.first(x, 'name')[1]: x[2] for x in sx.find(sx.first(c, 'fields') or [], 'field') if len(x) > 2}
        comps[ref] = dict(value=sx.first(c, 'value')[1], footprint=(sx.first(c, 'footprint') or [None, ''])[1], fields=f,
                          part=sx.first(sx.first(c, 'libsource'), 'part')[1])
    nets = {}
    for e in sx.find(sx.first(n, 'nets'), 'net'):
        nodes = []
        for x in sx.find(e, 'node'):
            pin = sx.first(x, 'pin')[1]
            fn = (sx.first(x, 'pinfunction') or [None, ''])[1]
            if fn.endswith('_' + pin):
                fn = fn[:-len(pin) - 1]
            nodes.append((sx.first(x, 'ref')[1], pin, fn))
        nets[sx.first(e, 'name')[1]] = sorted(nodes)
    return comps, nets


def real_nets(nets):
    """design nets only: KiCad's own 'unconnected-' nets and the PWR_FLAG symbols dropped, the leading '/' removed"""
    out = {}
    for k, v in nets.items():
        if k.startswith('unconnected-'):
            continue
        v = [x for x in v if not x[0].startswith('#')]
        if v:
            out[k.lstrip('/')] = v
    return out


def unconnected(nets):
    return {(r, p) for k, v in nets.items() if k.startswith('unconnected-') for (r, p, _) in v if not r.startswith('#')}


def pin_net(nets):
    return {(r, p): k for k, v in real_nets(nets).items() for (r, p, _) in v}


def pin_fn_net(nets):
    return {(r, fn): k for k, v in real_nets(nets).items() for (r, _, fn) in v if fn}


@dataclasses.dataclass
class Project:
    """one generated project as KiCad reads it: what every row after S1 looks at"""
    sch_path: str
    parts: list
    comps: dict
    nets: dict
    dir: str

    @classmethod
    def read(cls, sch_path, parts):
        comps, nets = netlist_full(sch_path)
        return cls(str(sch_path), parts, comps, nets, os.path.dirname(os.path.abspath(sch_path)))

    @property
    def real(self):
        return real_nets(self.nets)

    @property
    def pn(self):
        return pin_net(self.nets)

    @property
    def pf(self):
        return pin_fn_net(self.nets)


def tail(d, n=3):
    return ': ' + ' | '.join(d[:n]) if d else ''


# ------------------------------------------------------------------------------------------------ S and E rows
def s1_row(sch_path, cfg, tag=''):
    live, excl = sc.erc(sch_path)
    return Row('S1' + tag, not live and len(excl) == cfg.ERC_EXCLUDED,
               f'ERC {len(live)} live, {len(excl)} excluded' + (': ' + ' | '.join(live[:3]) if live else ''))


def s2_row(p, cfg, tag=''):
    got = {k: [(r, n) for (r, n, _) in v] for k, v in p.real.items()}
    want = sc.design_nets(p.parts)
    d = sc.compare_nets(want, got)
    return Row('S2' + tag, not d and len(want) >= cfg.MIN_NETS, f'{len(want)} design nets, {len(got)} KiCad nets{tail(d)}')


def s3_row(p, cfg, tag=''):
    dp = []
    byref = {q['ref']: q for q in p.parts}
    for ref in sorted(set(byref) | {r for r in p.comps if not r.startswith('#')}):
        if ref not in p.comps or ref not in byref:
            dp.append(f'{ref} in only one of design / KiCad')
            continue
        q, c = byref[ref], p.comps[ref]
        fields = [('value', c['value'], q['value']), ('footprint', c['footprint'], q['fp']),
                  ('LCSC', c['fields'].get('LCSC', ''), q['lcsc'])]
        fields += [(name, c['fields'].get(name, ''), q[key]) for name, key in cfg.COMPARE_FIELDS]
        for k, a, b in fields:
            if a != b:
                dp.append(f'{ref} {k} {a!r} != {b!r}')
    return Row('S3' + tag, not dp and len(p.comps) >= cfg.MIN_COMPS, f'{len(p.comps)} symbols{tail(dp)}')


def e1_row(p, cfg, tag=''):
    unc = unconnected(p.nets)
    bad = []
    for q in p.parts:
        declared = {(q['ref'], n) for n in (q['nc'] if q['nc'] != 'rest' else ())}
        have = {(r, n) for (r, n) in unc if r == q['ref']}
        if q['nc'] == 'rest':
            if any(pin in q['pins'] for (_, pin) in have):
                bad.append(f"{q['ref']}: a connected pin is NC in KiCad")
        elif have != declared:
            bad.append(f"{q['ref']}: KiCad NC pins {sorted(x[1] for x in have)} != declared {sorted(x[1] for x in declared)}")
    return Row('E1' + tag, not bad, f'{len(unc)} NC pins, every one declared; every other pin connected{tail(bad)}')


def e2_row(p, cfg, tag=''):
    got = {k: [(r, n) for (r, n, _) in v] for k, v in p.real.items()}
    single = sorted(k for k, v in got.items() if len(v) < 2)
    return Row('E2' + tag, not single, f'{len(got)} nets, none with a single pin' + (': ' + ', '.join(single[:6]) if single else ''))


def footprint_exists(fp, project_dir, cfg):
    lib, name = fp.split(':')
    d = os.path.join(project_dir, 'lib', lib + '.pretty') if lib == cfg.PROJECT_LIB_NAME else os.path.join(cfg.FOOTPRINT_DIR, lib + '.pretty')
    return os.path.exists(os.path.join(d, name + '.kicad_mod'))


def e3_row(p, cfg, tag=''):
    miss = []
    for ref, c in p.comps.items():
        if ref.startswith('#'):
            continue
        f = c['fields']
        if not c['value'] or not c['footprint']:
            miss.append(f'{ref} lacks value or footprint')
        elif not footprint_exists(c['footprint'], p.dir, cfg):
            miss.append(f"{ref} footprint {c['footprint']} not in any library")
        if f.get('Fitted by') == cfg.FITTED_BY_BOARD_HOUSE and not f.get('LCSC'):
            miss.append(f'{ref} is fitted by the board house with no LCSC number')
        if f.get('Fitted by') == cfg.FITTED_BY_BOARD_HOUSE and not re.match(r'^C\d{3,}$', f.get('LCSC', '')):
            miss.append(f"{ref} LCSC {f.get('LCSC')!r} is not a Cnnn code")
    return Row('E3' + tag, not miss, f'{len(p.comps)} symbols carry value, footprint, LCSC{tail(miss)}')


def e4_row(p, cfg, tag=''):
    d4 = []
    for ref, c in p.comps.items():
        tbl = cfg.DATASHEET_PINS.get(c['part'])
        if not tbl:
            continue
        seen = {pin: fn for k, v in p.nets.items() for (r, pin, fn) in v if r == ref}
        if seen != tbl:
            d4.append(f'{ref} ({c["part"]}): pins {sorted(set(seen.items()) ^ set(tbl.items()))[:4]}')
    return Row('E4' + tag, not d4 and any(c['part'] in cfg.DATASHEET_PINS for c in p.comps.values()),
               ', '.join(cfg.DATASHEET_PINS) + f' pin names equal the datasheet tables{tail(d4)}')


# ------------------------------------------------------------------------------------------------ numbering, bridges, headers
def d_rows(p, cfg, tag=''):
    got = {r: c['fields'].get('Block', '') for r, c in p.comps.items() if not r.startswith('#')}
    bad = [f'{r} ({b or "no block"})' for r, b in sorted(got.items())
           if b not in cfg.BLOCKDIGIT or int(re.sub(r'\D', '', r)) // 100 != cfg.BLOCKDIGIT[b]]
    r1 = Row(cfg.ROW_IDS['numbering'][0] + tag, not bad and len(got) >= cfg.MIN_COMPS, f'{len(got)} designators: hundreds digit = block'
             + (': ' + ', '.join(bad[:4]) if bad else ''))
    have = {b: {r for r, bb in got.items() if bb == b} for b in cfg.BLOCKDIGIT}
    d = [f'{b}: missing {sorted(cfg.KEY_PARTS[b] - have[b])[:3]} extra {sorted(have[b] - cfg.KEY_PARTS[b])[:3]}'
         for b in cfg.BLOCKDIGIT if have[b] != cfg.KEY_PARTS[b]]
    r2 = Row(cfg.ROW_IDS['numbering'][1] + tag, not d, 'each block holds exactly its key part list: '
             + ', '.join(f'{b} {len(cfg.KEY_PARTS[b])}' for b in cfg.BLOCKDIGIT) + (' | ' + ' | '.join(d) if d else ''))
    return [r1, r2]


def end_net(p, end):
    kind, ref, key = end
    return (p.pn if kind == 'pin' else p.pf).get((ref, key))


def bridge_row(p, cfg, tag=''):
    want = {ref: {end_net(p, a), end_net(p, b)} for ref, (a, b) in cfg.BRIDGE_JOINS.items()}
    have = {ref: {p.pn.get((ref, '1')), p.pn.get((ref, '2'))} for ref in cfg.BRIDGE_JOINS}
    sides = all(end_net(p, a) is not None and end_net(p, a) == end_net(p, b) for a, b in cfg.BRIDGE_SIDES)
    return Row(cfg.ROW_IDS['bridge'] + tag, have == want and sides,
               ', '.join(f'{ref} joins {sorted(have[ref], key=str)}' for ref in cfg.BRIDGE_JOINS) + '; ' + cfg.BRIDGE_TEXT)


def header_row(p, cfg, tag=''):
    d = []
    byname = {c['value']: r for r, c in p.comps.items()
              if c['fields'].get('Block') == cfg.HEADER_BLOCK and c['part'].startswith(cfg.HEADER_PART_PREFIX)}
    for hname, tbl in cfg.HEADER_TABLE.items():
        ref = byname.get(hname)
        if ref is None:
            d.append(f'{hname} missing')
            continue
        have = {pin: net for (r, pin), net in p.pn.items() if r == ref}
        if have != tbl:
            d.append(f'{hname}: {sorted(set(have.items()) ^ set(tbl.items()))[:4]}')
    return Row('H1' + tag, not d, f'{len(cfg.HEADER_TABLE)} {cfg.HEADER_LABEL} headers carry exactly the header-pin table{tail(d)}')


def spice_row(p, cfg, row_id, block, text, tag=''):
    try:
        d, ns, nc_ = spicecmp.compare(block, text, p.comps, p.nets, cfg)
    except Exception as e:      # a stale rule, an unclassified element, a part with no counterpart
        d, ns, nc_ = [f'{type(e).__name__}: {e}'], 0, 0
    return Row(row_id + tag, not d and ns >= cfg.MIN_SPICE_ELEMENTS,
               f'{block}: {ns} SPICE elements after reduction, {nc_} schematic elements{tail(d)}')


# ------------------------------------------------------------------------------------------------ resistor networks (arithmetic rows)
def rmap(p):
    """ref -> (ohms, net of pin 1, net of pin 2) for every resistor symbol, from KiCad's netlist"""
    pn = p.pn
    return {r: (spicecmp.parse_value(c['value']), pn.get((r, '1')), pn.get((r, '2'))) for r, c in p.comps.items() if c['part'] == 'R'}


def chain(R, a, b, nets_nodes):
    """resistance of the series path from net a to net b whose intermediate nets carry exactly two pins; None if there is none"""
    total, cur, seen = 0.0, a, set()
    while cur != b:
        step = [(r, v) for r, v in R.items() if cur in v[1:] and r not in seen]
        nxt = None
        for want_b in (True, False):       # a resistor straight to b wins over one into an intermediate net
            for r, (ohm, n1, n2) in step:
                other = n2 if n1 == cur else n1
                if (want_b and other == b) or (not want_b and len(nets_nodes.get(other, [])) == 2 and other != a):
                    nxt = (r, ohm, other)
                    break
            if nxt:
                break
        if nxt is None:
            return None
        seen.add(nxt[0])
        total += nxt[1]
        cur = nxt[2]
    return total


def by_field(p, name, value):
    """refs whose netlist field `name` equals value"""
    return [r for r, c in p.comps.items() if c['fields'].get(name) == value]


# ------------------------------------------------------------------------------------------------ mutation arms that must FLIP
@dataclasses.dataclass
class FlipArm:
    """one arm of the variant kind: a changed copy of the project, every row run on it, the named rows required to FAIL.
    The arm only counts as caught when each named row PASSES on the unchanged project and FAILS on the changed one: a row that
    already fails on the clean board cannot be caught by anything, and that is NOT TESTABLE, not a pass."""
    why: str
    expect: tuple
    mut_parts: Callable | None = None
    mut_spice: Callable | None = None
    flag_nets: list | None = None


def flip_row(why, expect, clean, failed):
    """-> Row for the arm 'M-<why>': clean {row id: ok} on the unchanged regenerated project, failed = ids failing on the variant"""
    bad_base = [e for e in expect if not clean.get(e, False)]
    if bad_base:
        return Row('M-' + why, False, f'NOT TESTABLE: {bad_base} already FAIL on the clean board')
    return Row('M-' + why, set(expect) <= set(failed), f'{sorted(failed)} failed; wanted {list(expect)}')


def finish_arms(rows):
    n = sum(r.ok for r in rows)
    return rows + [Row('M*', n == len(rows), f'{n} of {len(rows)} mutation arms failed the way they must')]
