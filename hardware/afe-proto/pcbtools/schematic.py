"""schematic.py: generate a KiCad schematic from a board's part list: one cell per part, every pin a short wire and a net
label, the sheet laid out by block. The drawing is a connection list; the netlist KiCad exports from it is what the
board is built from and what the checks compare with the design.

Nothing here names a board. A board supplies:

    parts   [dict]  ref, sym ('lib:name'), value, fp, lcsc, mpn, fitted_by, note, dnp, pins {number: net}, block
    cfg     object  PROJECT, NS (uuid namespace string), BLOCK_ORDER, BLOCK_TITLE {block: str}, PWR_FLAG_NETS [net],
                    TITLE, REV, COMMENTS [str], PROJECT_SYMBOLS [symbol tree] (the project library's own symbols),
                    ERC_EXCLUSIONS(pin_at, uid, root) -> [[key, reason]], SYMBOL_DIR (KiCad's symbol libraries)
    optional cfg    PROPS [(part key, field name)] the hidden fields every real part carries (default LCSC, MPN, Fitted by,
                    Note), FLAG_BLOCK the block the PWR_FLAG cells go in (default 'power'), CHECK_NC (every pin of a symbol is
                    connected or declared in the part's 'nc'; a part's nc may be 'rest'), LIB_GENERATOR (the project symbol
                    library's generator string), FP_LIB_TABLE (the footprint library table's text)

`build_tree(parts, cfg, library)` is a pure function of its inputs (no files written); `write_all` writes the schematic, the
two library tables, the project file and the project symbol library. Output is byte-identical to the old build_sch.py.
"""
import copy
import json
import math
import os
import uuid

from .sexpr import Q, dump, find, first, parse

class SchematicError(ValueError):
    """the generator refuses a part list (a pin neither connected nor declared NC, a pin the symbol does not have)"""


DEFAULT_PROPS = (('lcsc', 'LCSC'), ('mpn', 'MPN'), ('fitted_by', 'Fitted by'), ('note', 'Note'))
G = 2.54          # schematic grid, mm
W = 400.0         # column width of the sheet, mm


def make_uid(ns, *k):
    return str(uuid.uuid5(uuid.UUID(ns), '/'.join(map(str, k))))


# ----------------------------------------------------------------------------- library symbols
class Library:
    """KiCad symbol libraries read on demand (an instance cache, not module state): 'afe' is the project's own."""

    def __init__(self, symbol_dir, project_lib):
        self.symbol_dir, self.project_lib = symbol_dir, project_lib
        self._libs = {}

    def lib(self, name):
        if name not in self._libs:
            path = self.project_lib if name == 'afe' else os.path.join(self.symbol_dir, name + '.kicad_sym')
            with open(path) as f:
                self._libs[name] = parse(f.read())
        return self._libs[name]

    def raw_symbol(self, libname, name):
        for s in find(self.lib(libname), 'symbol'):
            if s[1] == name:
                return s
        raise KeyError(f'{libname}:{name}')

    def flat_symbol(self, libname, name):
        """the symbol with any 'extends' resolved, its sub-symbols named after it"""
        s = self.raw_symbol(libname, name)
        ext = first(s, 'extends')
        if not ext:
            return list(s)
        parent = self.flat_symbol(libname, ext[1])
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
        for p in own_props.values():
            out.append(p)
        return out

    def embedded(self, lib_id):
        libname, name = lib_id.split(':')
        s = copy.deepcopy(self.flat_symbol(libname, name))
        s[1] = Q(lib_id)
        return s

    def pins_of(self, lib_id):
        """{(unit, number): (x, y, angle, name, type)} in library coordinates; unit 0 = all units"""
        libname, name = lib_id.split(':')
        out = {}
        for sub in find(self.flat_symbol(libname, name), 'symbol'):
            tail = sub[1][len(name) + 1:].split('_')
            unit, style = int(tail[0]), int(tail[1])
            if style not in (0, 1):
                continue
            for p in find(sub, 'pin'):
                at = first(p, 'at')
                out[(unit, first(p, 'number')[1])] = (float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0,
                                                      first(p, 'name')[1], p[1])
        return out

    def units_of(self, lib_id):
        return sorted({u for (u, _) in self.pins_of(lib_id)} - {0}) or [1]


def rename_sub(sub, old, new):
    s = list(sub)
    if not s[1].startswith(old + '_'):
        raise ValueError(f'sub-symbol {s[1]!r} does not start with {old}_')
    s[1] = Q(new + s[1][len(old):])
    return s


def box_symbol(name, pins, width, ref='U', value=None, fp='', ds='', desc=''):
    """a rectangular symbol; pins: list of (number, name, type, side, slot), side L/R/T/B, slot = grid units along the side"""
    ht = max([p[4] for p in pins if p[3] in 'LR'] + [0]) + 1
    top = round((ht * G / 2 + G / 2) / G) * G
    bot = -top
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


def project_lib_text(symbols, generator='afe_build_sch'):
    return dump(['kicad_symbol_lib', ['version', '20241209'], ['generator', Q(generator)],
                 ['generator_version', Q('10.0')]] + list(symbols)) + '\n'


# ----------------------------------------------------------------------------- geometry
def rot(x, y, r):
    """library (x up) -> schematic offset (y down), symbol rotated r degrees counter-clockwise on screen"""
    X, Y = x, -y
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return X * c + Y * s, -X * s + Y * c


def out_dir(angle, r):
    """unit vector from the pin's connection point away from the body, in schematic coordinates"""
    a = math.radians(angle)
    dx, dy = -round(math.cos(a)), round(math.sin(a))
    c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
    return dx * c + dy * s, -dx * s + dy * c


def label_len(net):
    return len(net) * 1.0 + 2.0


def snap(v):
    return round(v / G) * G


class Cell:
    def __init__(self, p, library):
        self.p = p
        self.lib_id = p['sym']
        pins = library.pins_of(self.lib_id)
        self.units = library.units_of(self.lib_id)
        self.r = 90 if self.lib_id in ('Device:R', 'Device:C') else 0
        self.items = []     # (unit, dx, [(num, px, py, ox, oy, net, type)])
        x0 = 0.0
        self.minx = self.miny = 1e9
        self.maxx = self.maxy = -1e9
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
            self.minx = min(self.minx, *[e[0] for e in ext])
            self.maxx = max(self.maxx, *[e[0] for e in ext])
            self.miny = min(self.miny, *[e[1] for e in ext])
            self.maxy = max(self.maxy, *[e[1] for e in ext])
            x0 = max(e[0] for e in ext)
            self.items.append((u, dx, pl))
        self.miny -= 2.5 * G          # room for reference / value
        self.w = self.maxx - self.minx + 2 * G
        self.h = self.maxy - self.miny + G


def check_nc(parts, library):
    """a pin the design does not connect must be declared NC (part['nc'], or 'rest' for a header whose unused pins pass
    through), and a declared NC must not be connected"""
    for p in parts:
        lib_pins = {n for (_, n) in library.pins_of(p['sym'])}
        unknown = set(p['pins']) - lib_pins
        if unknown:
            raise SchematicError(f"{p['ref']}: pins {sorted(unknown)} not in symbol {p['sym']}")
        if p['nc'] == 'rest':
            continue
        undeclared = (lib_pins - set(p['pins'])) - set(p['nc'])
        if undeclared:
            raise SchematicError(f"{p['ref']}: pins {sorted(undeclared)} neither connected nor declared NC")
        both = set(p['nc']) & set(p['pins'])
        if both:
            raise SchematicError(f"{p['ref']}: pins {sorted(both)} declared NC and connected")


# ----------------------------------------------------------------------------- the sheet
def build_tree(parts, cfg, library):
    """-> (schematic tree, info) with info = {'pin_at': {(ref, pin): (x, y)}, 'cells': n, 'lib_ids': [...], 'size': (w, h)}"""
    uid = lambda *k: make_uid(cfg.NS, *k)      # noqa: E731
    root = str(uuid.uuid5(uuid.UUID(cfg.NS), 'root'))
    if getattr(cfg, 'CHECK_NC', False):
        check_nc(parts, library)
    cells = {b: [Cell(p, library) for p in parts if p['block'] == b] for b in cfg.BLOCK_ORDER}
    flag_block = getattr(cfg, 'FLAG_BLOCK', 'power')
    flags = [dict(ref=f'#FLG{i + 1:02d}', sym='power:PWR_FLAG', value='PWR_FLAG', fp='', lcsc='', mpn='',
                  pins={'1': n}, block=flag_block, dnp=False, fitted_by='none',
                  note='ERC: net driven from outside / through a part') for i, n in enumerate(cfg.PWR_FLAG_NETS)]
    cells[flag_block] += [Cell(f, library) for f in flags]

    body, placed, pin_at = [], [], {}
    col_x = [20.0, 20.0 + W + 20.0]
    col_y = [30.0, 30.0]
    for b in cfg.BLOCK_ORDER:
        cs = cells[b]
        c = 0 if col_y[0] <= col_y[1] else 1
        x0, y0 = col_x[c], col_y[c]
        body.append(['text', Q(cfg.BLOCK_TITLE[b]), ['exclude_from_sim', 'no'], ['at', x0, y0, 0],
                     ['effects', ['font', ['size', 2.54, 2.54], ['bold', 'yes']], ['justify', 'left', 'bottom']],
                     ['uuid', Q(uid('title', b))]])
        x, y, rowh = x0, y0 + 2 * G, 0.0
        for cell in cs:
            if x + cell.w > x0 + W and x > x0:
                x, y, rowh = x0, y + rowh, 0.0
            placed.append((cell, snap(x - cell.minx), snap(y - cell.miny)))
            x += cell.w
            rowh = max(rowh, cell.h)
        col_y[c] = y + rowh + 6 * G
    width, height = snap(col_x[1] + W + 20), snap(max(col_y) + 10)

    lib_ids = sorted({cell.lib_id for cell, _, _ in placed})
    libsyms = ['lib_symbols'] + [library.embedded(i) for i in lib_ids]

    for cell, sx, sy in placed:
        p = cell.p
        is_flag = p['ref'].startswith('#')
        for (u, dx, pl) in cell.items:
            ux = sx + dx

            def prop(k, v, at, hide=False, size=1.27):
                e = ['effects', ['font', ['size', size, size]]] + ([['hide', 'yes']] if hide else [])
                return ['property', Q(k), Q(v), ['at', at[0], at[1], 0], e]
            top = sy + cell.miny + 2.5 * G
            props = [prop('Reference', p['ref'], (ux, top - 2.2 * G), is_flag), prop('Value', p['value'], (ux, top - 1.2 * G)),
                     prop('Footprint', p['fp'], (ux, sy), True), prop('Datasheet', '~', (ux, sy), True)]
            if not is_flag:
                for k, name in getattr(cfg, 'PROPS', DEFAULT_PROPS):
                    props.append(prop(name, p[k], (ux, sy), True))
            inst = ['symbol', ['lib_id', Q(cell.lib_id)], ['at', ux, sy, cell.r], ['unit', u],
                    ['exclude_from_sim', 'no'], ['in_bom', 'no' if (is_flag or p['fitted_by'] == 'none') else 'yes'],
                    ['on_board', 'no' if is_flag else 'yes'], ['dnp', 'yes' if p['dnp'] else 'no'],
                    ['uuid', Q(uid('sym', p['ref'], u))]] + props
            # every pin of the symbol, not only this unit's: KiCad gives any pin left out a random uuid
            for num in sorted({n for (_, n) in library.pins_of(cell.lib_id)}, key=lambda n: (len(n), n)):
                inst.append(['pin', Q(num), ['uuid', Q(uid('pin', p['ref'], u, num))]])
            inst.append(['instances', ['project', Q(cfg.PROJECT), ['path', Q('/' + root), ['reference', Q(p['ref'])],
                                                                    ['unit', u]]]])
            body.append(inst)
            for (num, px, py, ox, oy, net, typ) in pl:
                X, Y = ux + px, sy + py
                pin_at[(p['ref'], num)] = (X, Y)
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

    comments = [['comment', k, Q(c)] for k, c in enumerate(cfg.COMMENTS, 1)]
    sch = ['kicad_sch', ['version', '20250114'], ['generator', Q('eeschema')], ['generator_version', Q('9.0')],
           ['uuid', Q(root)], ['paper', Q('User'), width, height],
           ['title_block', ['title', Q(cfg.TITLE)], ['rev', Q(cfg.REV)]] + comments,
           libsyms] + body + [['sheet_instances', ['path', Q('/'), ['page', Q('1')]]], ['embedded_fonts', 'no']]
    return sch, dict(pin_at=pin_at, cells=len(placed), lib_ids=lib_ids, size=(width, height), root=root)


SYM_LIB_TABLE = ('(sym_lib_table\n\t(version 7)\n\t(lib (name "afe")(type "KiCad")(uri "${KIPRJMOD}/lib/afe.kicad_sym")'
                 '(options "")(descr "AFE project symbols, generated by build_sch.py"))\n)\n')
FP_LIB_TABLE = ('(fp_lib_table\n\t(version 7)\n\t(lib (name "afe")(type "KiCad")(uri "${KIPRJMOD}/lib/afe.pretty")'
                '(options "")(descr "AFE project footprints, generated by build_pcb.py"))\n)\n')


def project_json(cfg, info):
    uid = lambda *k: make_uid(cfg.NS, *k)      # noqa: E731
    return {'meta': {'filename': cfg.PROJECT + '.kicad_pro', 'version': 3},
            'erc': {'erc_exclusions': cfg.ERC_EXCLUSIONS(info['pin_at'], uid, info['root'])},
            'schematic': {'legacy_lib_dir': '', 'legacy_lib_list': []},
            'sheets': [[info['root'], 'Root']]}


def write_all(parts, cfg, out_dir):
    """write the project symbol library, the schematic, the two library tables and the project file into out_dir"""
    os.makedirs(os.path.join(out_dir, 'lib'), exist_ok=True)
    lib_path = os.path.join(out_dir, 'lib', 'afe.kicad_sym')
    with open(lib_path, 'w') as f:
        f.write(project_lib_text(cfg.PROJECT_SYMBOLS, getattr(cfg, 'LIB_GENERATOR', 'afe_build_sch')))
    library = Library(cfg.SYMBOL_DIR, lib_path)
    sch, info = build_tree(parts, cfg, library)
    with open(os.path.join(out_dir, cfg.PROJECT + '.kicad_sch'), 'w') as f:
        f.write(dump(sch) + '\n')
    with open(os.path.join(out_dir, 'sym-lib-table'), 'w') as f:
        f.write(SYM_LIB_TABLE)
    with open(os.path.join(out_dir, 'fp-lib-table'), 'w') as f:
        f.write(getattr(cfg, 'FP_LIB_TABLE', FP_LIB_TABLE))
    with open(os.path.join(out_dir, cfg.PROJECT + '.kicad_pro'), 'w') as f:
        json.dump(project_json(cfg, info), f, indent=2)
        f.write('\n')
    return info
