"""Generate the KiCad 10 schematic of the AFE shield from design.py.

    python3 -I hardware/afe-proto/kicad/build_sch.py

Writes afe-proto.kicad_sch, the project file, sym-lib-table and the
project symbol library lib/afe.kicad_sym (the three symbols KiCad's
libraries lack).  Every pin gets a short wire and a net label, so the
drawing is a connection list laid out by block; check.py holds the result
to design.py through KiCad's own netlist export.  Then run
`kicad-cli sch upgrade` (check.py does) so the file is in KiCad 10's
format exactly as eeschema writes it.

Own work, CC BY-SA 4.0.
"""
import copy
import json
import math
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design                                     # noqa: E402
from sexpr import Q, parse, dump, find, first     # noqa: E402

KILIB = os.environ.get('KICAD_SYMBOL_DIR', '/usr/share/kicad/symbols')
PROJECT = 'afe-proto'
NS = uuid.UUID('6f1f0d3e-4a52-4c1b-9a4e-0ad5e0a1f001')
ROOT_UUID = str(uuid.uuid5(NS, 'root'))
G = 2.54
PIN_AT = {}
PWR_FLAG_NETS = ['GND', '+5V_DUE', '+5V_F', 'SC_VCC']


def uid(*k):
    return str(uuid.uuid5(NS, '/'.join(map(str, k))))


# ----------------------------------------------------------------------------- library symbols
_libs = {}


def lib(name):
    if name not in _libs:
        if name == 'afe':
            _libs[name] = parse(open(os.path.join(HERE, 'lib', 'afe.kicad_sym')).read())
        else:
            _libs[name] = parse(open(os.path.join(KILIB, name + '.kicad_sym')).read())
    return _libs[name]


def raw_symbol(libname, name):
    for s in find(lib(libname), 'symbol'):
        if s[1] == name:
            return s
    raise KeyError(f'{libname}:{name}')


def rename_sub(sub, old, new):
    s = list(sub)
    assert s[1].startswith(old + '_'), (s[1], old)
    s[1] = Q(new + s[1][len(old):])
    return s


def flat_symbol(libname, name):
    """The symbol with any 'extends' resolved, its sub-symbols named after it."""
    s = raw_symbol(libname, name)
    ext = first(s, 'extends')
    if not ext:
        return [x for x in s]
    parent = flat_symbol(libname, ext[1])
    own_props = {p[1]: p for p in find(s, 'property')}
    own_flags = {x[0]: x for x in s[2:] if isinstance(x, list) and x[0] not in ('property', 'extends', 'symbol')}
    out = ['symbol', Q(name)]
    for x in parent[2:]:
        if isinstance(x, list) and x[0] == 'property':
            out.append(own_props.pop(x[1], x))
        elif isinstance(x, list) and x[0] == 'symbol':
            out.append(rename_sub(x, ext[1], name))
        elif isinstance(x, list) and x[0] in own_flags:
            out.append(own_flags.pop(x[0]))
        else:
            out.append(x)
    out[2:2] = list(own_flags.values())
    for k, p in own_props.items():
        out.append(p)
    return out


def embedded(lib_id):
    libname, name = lib_id.split(':')
    s = copy.deepcopy(flat_symbol(libname, name))
    s[1] = Q(lib_id)
    return s


def pins_of(lib_id):
    """{(unit, number): (x, y, angle, name, type)} in library coordinates; unit 0 = all units."""
    libname, name = lib_id.split(':')
    s = flat_symbol(libname, name)
    out = {}
    for sub in find(s, 'symbol'):
        tail = sub[1][len(name) + 1:].split('_')
        unit, style = int(tail[0]), int(tail[1])
        if style not in (0, 1):
            continue
        for p in find(sub, 'pin'):
            at = first(p, 'at')
            num = first(p, 'number')[1]
            nm = first(p, 'name')[1]
            out[(unit, num)] = (float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0, nm, p[1])
    return out


def units_of(lib_id):
    return sorted({u for (u, _) in pins_of(lib_id)} - {0}) or [1]


# ----------------------------------------------------------------------------- the project's own symbols
def box_symbol(name, pins, width, ref='U', value=None, fp='', ds='', desc=''):
    """pins: list of (number, name, type, side, slot); side L/R/T/B, slot = position along the side (grid units)."""
    nl = [p for p in pins if p[3] == 'L']; nr = [p for p in pins if p[3] == 'R']
    ht = max([p[4] for p in pins if p[3] in 'LR'] + [0]) + 1
    top, bot = ht * G / 2 + G / 2, -(ht * G / 2 + G / 2)
    top = round(top / G) * G; bot = -top
    hw = width / 2
    body = ['symbol', Q(f'{name}_0_1'), ['rectangle', ['start', -hw, top], ['end', hw, bot],
                                          ['stroke', ['width', 0.254], ['type', 'default']], ['fill', ['type', 'background']]]]
    pl = ['symbol', Q(f'{name}_1_1')]
    for num, nm, typ, side, slot in pins:
        y = top - (slot + 1) * G
        if side == 'L':
            at = ['at', -hw - 2 * G, y, 0]
        elif side == 'R':
            at = ['at', hw + 2 * G, y, 180]
        elif side == 'T':
            at = ['at', -hw + (slot + 1) * G, top + 2 * G, 270]
        else:
            at = ['at', -hw + (slot + 1) * G, bot - 2 * G, 90]
        pl.append(['pin', typ, 'line', at, ['length', 2 * G],
                   ['name', Q(nm), ['effects', ['font', ['size', 1.27, 1.27]]]],
                   ['number', Q(num), ['effects', ['font', ['size', 1.27, 1.27]]]]])

    def prop(k, v, y, hide=False):
        e = ['effects', ['font', ['size', 1.27, 1.27]]] + ([['hide', 'yes']] if hide else [])
        return ['property', Q(k), Q(v), ['at', 0, y, 0], e]
    return ['symbol', Q(name), ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes'],
            prop('Reference', ref, top + 3 * G), prop('Value', value or name, top + 2 * G),
            prop('Footprint', fp, 0, True), prop('Datasheet', ds, 0, True), prop('Description', desc, 0, True),
            body, pl]


def write_afe_lib():
    tmux = box_symbol('TMUX1119', [
        ('4', 'S1', 'passive', 'L', 0), ('6', 'S2', 'passive', 'L', 2), ('1', 'SEL', 'input', 'L', 4),
        ('5', 'D', 'passive', 'R', 1), ('2', 'VDD', 'power_in', 'T', 1), ('3', 'GND', 'power_in', 'B', 1)],
        width=10.16, fp=design.SC706, ds='https://www.ti.com/lit/ds/symlink/tmux1119.pdf',
        desc='SPDT 5 V analog switch, SC70-6 (SCDS401C table 4-1): SEL low = S1-D')
    os.makedirs(os.path.join(HERE, 'lib'), exist_ok=True)
    # own work, CC BY-SA 4.0: generated by build_sch.py (edit the generator, not the library)
    text = dump(['kicad_symbol_lib', ['version', '20241209'], ['generator', Q('afe_build_sch')],
                 ['generator_version', Q('10.0')], tmux])
    with open(os.path.join(HERE, 'lib', 'afe.kicad_sym'), 'w') as f:
        f.write(text + '\n')
    _libs.pop('afe', None)


# ----------------------------------------------------------------------------- geometry
def rot(x, y, r):
    """library (x up) -> schematic offset (y down), symbol rotated r degrees counter-clockwise on screen."""
    X, Y = x, -y
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return X * c + Y * s, -X * s + Y * c


def out_dir(angle, r):
    """unit vector from the pin's connection point away from the body, in schematic coordinates."""
    a = math.radians(angle)
    dx, dy = -round(math.cos(a)), round(math.sin(a))     # library outward (-cos, -sin) -> screen (-cos, +sin)
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return dx * c + dy * s, -dx * s + dy * c


def label_len(net):
    return len(net) * 1.0 + 2.0


class Cell:
    def __init__(self, p):
        self.p = p
        self.lib_id = p['sym']
        pins = pins_of(self.lib_id)
        self.units = units_of(self.lib_id)
        self.r = 90 if self.lib_id in ('Device:R', 'Device:C') else 0
        # each unit side by side; per unit its pins (incl. unit 0 on the first unit)
        self.items = []     # (unit, dx, [(num, px, py, ox, oy, net)])
        x0 = 0.0
        self.minx = self.miny = 1e9; self.maxx = self.maxy = -1e9
        for k, u in enumerate(self.units):
            pl = []
            for (uu, num), (x, y, a, nm, typ) in pins.items():
                if uu == u or (uu == 0 and k == 0):
                    px, py = rot(x, y, self.r)
                    ox, oy = out_dir(a, self.r)
                    pl.append((num, px, py, ox, oy, p['pins'].get(num), typ))
            xs = [q[1] for q in pl]
            w0 = min(xs) if xs else 0
            dx = x0 - w0 + 4 * G if k else 0.0
            if k:
                dx = round((x0 + (-w0) + 3 * G) / G) * G
            ext = []
            for (num, px, py, ox, oy, net, typ) in pl:
                L = G + (label_len(net) if net else 0)
                ext += [(dx + px, py), (dx + px + ox * L, py + oy * L)]
            ext += [(dx - 2 * G, -2 * G), (dx + 2 * G, 2 * G)]
            self.minx = min(self.minx, *[e[0] for e in ext]); self.maxx = max(self.maxx, *[e[0] for e in ext])
            self.miny = min(self.miny, *[e[1] for e in ext]); self.maxy = max(self.maxy, *[e[1] for e in ext])
            x0 = max(e[0] for e in ext)
            self.items.append((u, dx, pl))
        self.miny -= 2.5 * G          # room for reference / value
        self.w = self.maxx - self.minx + 2 * G
        self.h = self.maxy - self.miny + G


def snap(v):
    return round(v / G) * G


# ----------------------------------------------------------------------------- the sheet
BLOCK_TITLE = {
    'power': 'POWER: 5 V feed (take only), LM27762 +3.3 V_A / -2.07 V, bleed',
    'ch1': 'SCOPE CH1 (A1): 1 Mohm compensated divider centred from the REF3030E, TPH2502 follower (shared dual), ADC-pin clamp',
    'ch2': 'SCOPE CH2 (A0): as CH1, on the dual\'s half B',
    'awg': 'AWG: TPH2502 (DAC0 buffer + gain stage), attenuator, own Vmid (TLV9062), 50 ohm out',
    'cal': 'CALIBRATION: REF3030E, ladder (A2..A7), ADS1115 on I2C, AWG-sense divider and ratio switch',
    'due': 'DUE HEADERS (V03 positions), mounting, test points',
}
ORDER = ['power', 'ch1', 'ch2', 'awg', 'cal', 'due']


def build():
    write_afe_lib()
    cells = {b: [Cell(p) for p in design.PARTS if p['block'] == b] for b in ORDER}
    flags = [dict(ref=f'#FLG{i + 1:02d}', sym='power:PWR_FLAG', value='PWR_FLAG', fp='', lcsc='', mpn='',
                  pins={'1': n}, block='power', dnp=False, fitted_by='none', note='ERC: net driven from outside / '
                  'through a part') for i, n in enumerate(PWR_FLAG_NETS)]
    cells['power'] += [Cell(f) for f in flags]

    body = []
    placed = []   # (cell, x, y)
    W = 400.0
    col_x = [20.0, 20.0 + W + 20.0]
    col_y = [30.0, 30.0]
    for b in ORDER:
        cs = cells[b]
        c = 0 if col_y[0] <= col_y[1] else 1
        x0, y0 = col_x[c], col_y[c]
        body.append(['text', Q(BLOCK_TITLE[b]), ['exclude_from_sim', 'no'], ['at', x0, y0, 0],
                     ['effects', ['font', ['size', 2.54, 2.54], ['bold', 'yes']], ['justify', 'left', 'bottom']],
                     ['uuid', Q(uid('title', b))]])
        x, y, rowh = x0, y0 + 2 * G, 0.0
        for cell in cs:
            if x + cell.w > x0 + W and x > x0:
                x, y, rowh = x0, y + rowh, 0.0
            sx, sy = snap(x - cell.minx), snap(y - cell.miny)
            placed.append((cell, sx, sy))
            x += cell.w; rowh = max(rowh, cell.h)
        col_y[c] = y + rowh + 6 * G
    width = snap(col_x[1] + W + 20); height = snap(max(col_y) + 10)

    lib_ids = sorted({cell.lib_id for cell, _, _ in placed})
    libsyms = ['lib_symbols'] + [embedded(i) for i in lib_ids]

    for cell, sx, sy in placed:
        p = cell.p
        is_flag = p['ref'].startswith('#')
        for (u, dx, pl) in cell.items:
            ux = sx + dx
            props = []

            def prop(k, v, at, hide=False, size=1.27):
                e = ['effects', ['font', ['size', size, size]]] + ([['hide', 'yes']] if hide else [])
                return ['property', Q(k), Q(v), ['at', at[0], at[1], 0], e]
            top = sy + cell.miny + 2.5 * G
            props.append(prop('Reference', p['ref'], (ux, top - 2.2 * G), is_flag))
            props.append(prop('Value', p['value'], (ux, top - 1.2 * G)))
            props.append(prop('Footprint', p['fp'], (ux, sy), True))
            props.append(prop('Datasheet', '~', (ux, sy), True))
            if not is_flag:
                for k in ('lcsc', 'mpn', 'fitted_by', 'note'):
                    props.append(prop({'lcsc': 'LCSC', 'mpn': 'MPN', 'fitted_by': 'Fitted by', 'note': 'Note'}[k],
                                      p[k], (ux, sy), True))
            inst = ['symbol', ['lib_id', Q(cell.lib_id)], ['at', ux, sy, cell.r], ['unit', u],
                    ['exclude_from_sim', 'no'], ['in_bom', 'no' if (is_flag or p['fitted_by'] == 'none') else 'yes'],
                    ['on_board', 'no' if is_flag else 'yes'], ['dnp', 'yes' if p['dnp'] else 'no'],
                    ['uuid', Q(uid('sym', p['ref'], u))]] + props
            # every pin of the symbol, not only this unit's: KiCad gives any pin left out a random uuid
            for num in sorted({n for (_, n) in pins_of(cell.lib_id)}, key=lambda n: (len(n), n)):
                inst.append(['pin', Q(num), ['uuid', Q(uid('pin', p['ref'], u, num))]])
            inst.append(['instances', ['project', Q(PROJECT), ['path', Q('/' + ROOT_UUID), ['reference', Q(p['ref'])],
                                                                 ['unit', u]]]])
            body.append(inst)
            for (num, px, py, ox, oy, net, typ) in pl:
                X, Y = ux + px, sy + py
                PIN_AT[(p['ref'], num)] = (X, Y)
                if net is None:
                    if typ != 'no_connect':
                        body.append(['no_connect', ['at', X, Y], ['uuid', Q(uid('nc', p['ref'], u, num))]])
                    continue
                X2, Y2 = X + ox * G, Y + oy * G
                body.append(['wire', ['pts', ['xy', X, Y], ['xy', X2, Y2]], ['stroke', ['width', 0], ['type', 'default']],
                             ['uuid', Q(uid('w', p['ref'], u, num))]])
                ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(ox, oy)]
                just = ['justify', 'left' if ang in (0, 90) else 'right', 'bottom']
                body.append(['label', Q(net), ['at', X2, Y2, ang], ['effects', ['font', ['size', 1.0, 1.0]], just],
                             ['uuid', Q(uid('l', p['ref'], u, num))]])

    sch = ['kicad_sch', ['version', '20250114'], ['generator', Q('eeschema')], ['generator_version', Q('9.0')],
           ['uuid', Q(ROOT_UUID)], ['paper', Q('User'), width, height],
           ['title_block', ['title', Q('AFE full range design 01: AFE shield for the Arduino Due')], ['rev', Q('FR-01')],
            ['comment', 1, Q('Generated by hardware/afe-proto/kicad/build_sch.py from design.py: edit those, not this file')],
            ['comment', 2, Q('Values and parts: whatif/bom.txt. Connectivity: the simulated circuit (docs/architecture.md)')],
            ['comment', 3, Q('Own work, CC BY-SA 4.0')]],
           libsyms] + body + [['sheet_instances', ['path', Q('/'), ['page', Q('1')]]], ['embedded_fonts', 'no']]
    with open(os.path.join(HERE, PROJECT + '.kicad_sch'), 'w') as f:
        f.write(dump(sch) + '\n')
    with open(os.path.join(HERE, 'sym-lib-table'), 'w') as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "afe")(type "KiCad")(uri "${KIPRJMOD}/lib/afe.kicad_sym")'
                '(options "")(descr "AFE project symbols, generated by build_sch.py"))\n)\n')
    # ERC exclusion, one, with its reason: the LM27762's PGOOD is open drain and tied to GND as its datasheet asks when
    # unused (SNVSAF7C table 4-1); GND carries a PWR_FLAG (a power output), and an open collector on a power output is
    # an ERC error by pin type, not by circuit.  Keyed by the two pins' UUIDs and the first pin's position (100 nm units), then
    # the sheet path of the marker and of each item (the format read out of eeschema: key|x|y|id|id|path|path|path).
    pg = PIN_AT[('U401', '1')]
    excl = [[f"pin_to_pin|{round(pg[0] * 1e4)}|{round(pg[1] * 1e4)}|{uid('pin', 'U401', 1, '1')}|{uid('pin', '#FLG01', 1, '1')}"
             f"|/{ROOT_UUID}|/{ROOT_UUID}|/{ROOT_UUID}",
             'PGOOD unused, tied to GND per SNVSAF7C; GND carries the PWR_FLAG']]
    with open(os.path.join(HERE, 'fp-lib-table'), 'w') as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "afe")(type "KiCad")(uri "${KIPRJMOD}/lib/afe.pretty")'
                '(options "")(descr "AFE project footprints, generated by build_pcb.py"))\n)\n')
    pro = {'meta': {'filename': PROJECT + '.kicad_pro', 'version': 3},
           'erc': {'erc_exclusions': excl},
           'schematic': {'legacy_lib_dir': '', 'legacy_lib_list': []},
           'sheets': [[ROOT_UUID, 'Root']]}
    with open(os.path.join(HERE, PROJECT + '.kicad_pro'), 'w') as f:
        json.dump(pro, f, indent=2); f.write('\n')
    print(f'{len(placed)} cells, {len(lib_ids)} library symbols, sheet {width:.0f} x {height:.0f} mm')


if __name__ == '__main__':
    build()
