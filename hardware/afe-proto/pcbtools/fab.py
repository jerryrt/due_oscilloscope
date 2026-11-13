"""The JLC fabrication set of a board: Gerbers, Excellon drills, the BOM and CPL, in one deterministic zip, and the checks on it.

    python3 -m pcbtools.fab build BOARD OUTDIR [--bom F --cpl F]     write OUTDIR/<IDENT>-fab.zip and OUTDIR/files/ (needs kicad-cli: run in the image)
    python3 -m pcbtools.fab manifest ZIP                              the manifest (member names, sizes, sha256) as JSON

Options follow docs/jlcpcb.md section 1 ("Files for KiCad"): Gerber with Protel extensions, 4.6 format, F/B.Cu, F/B.Mask, F/B.Silkscreen,
Edge.Cuts and F.Paste, extended X2 and netlist attributes on, no drill marks, scale 1:1; Excellon in mm, absolute origin, decimal zeros,
PTH and NPTH in separate files, alternate mode for ovals. The zip is flat (JLC reads the Gerbers and drills from the zip root); the BOM and
CPL are the bom engine's files (`v2/bom/<IDENT>-bom.csv`, `-cpl.csv`), which JLC takes in its own upload step, so they are in the zip under
their own names and a customer may leave them out of the Gerber upload. Reproducibility: kicad-cli writes the plot time into the Gerber and
drill headers, so it is replaced by a fixed stamp, members are sorted, and the zip entries carry a fixed date and mode.
"""
import hashlib, json, os, re, subprocess, sys, tempfile, zipfile

LAYERS = 'F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts,F.Paste'
STEM = 'afe-v2-integrated'       # kicad-cli's own file stem (the board's name)


def _ident():
    import importlib.util
    sp = importlib.util.spec_from_file_location('_fab_v2cfg', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards', 'v2.py'))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return f'{m.NAME}-{m.MODEL}-REV{m.REV}'


IDENT = _ident()                  # the member and zip prefix, from the config: COPPIA-AFE-2-REVA
GERBERS = {'F_Cu.gtl': 'top copper', 'B_Cu.gbl': 'bottom copper', 'F_Mask.gts': 'top mask', 'B_Mask.gbs': 'bottom mask',
           'F_Silkscreen.gto': 'top silk', 'B_Silkscreen.gbo': 'bottom silk', 'Edge_Cuts.gm1': 'outline', 'F_Paste.gtp': 'top paste'}
DRILLS = {'PTH.drl': 'plated holes', 'NPTH.drl': 'non-plated holes'}
ASSEMBLY = {'bom.csv': 'JLC BOM', 'cpl.csv': 'JLC CPL'}
ZIP_NAME = IDENT + '-fab.zip'
STAMP = '2000-01-01T00:00:00+00:00'


def expected_members():
    return sorted(f'{IDENT}-{k}' for k in list(GERBERS) + list(DRILLS) + list(ASSEMBLY))


def _norm(data):
    t = data.decode('utf8', 'replace')
    t = re.sub(r'\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(\+00:00)?', lambda m: STAMP if 'T' in m.group(0) else STAMP.replace('T', ' ')[:19], t)
    return t.encode('utf8')


def build(board, outdir, bom, cpl):
    os.makedirs(outdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['kicad-cli', 'pcb', 'export', 'gerbers', '-o', tmp + '/', '-l', LAYERS, '--precision', '6', board],
                       check=True, capture_output=True)
        subprocess.run(['kicad-cli', 'pcb', 'export', 'drill', '-o', tmp + '/', '--format', 'excellon', '--drill-origin', 'absolute',
                        '--excellon-units', 'mm', '--excellon-zeros-format', 'decimal', '--excellon-oval-format', 'alternate',
                        '--excellon-separate-th', board], check=True, capture_output=True)
        members = {}
        for k in list(GERBERS):
            members[f'{IDENT}-{k}'] = _norm(open(f'{tmp}/{STEM}-{k}', 'rb').read())
        for k in DRILLS:
            members[f'{IDENT}-{k}'] = _norm(open(f'{tmp}/{STEM}-{k}', 'rb').read())
    members[f'{IDENT}-bom.csv'] = open(bom, 'rb').read()
    members[f'{IDENT}-cpl.csv'] = open(cpl, 'rb').read()
    zp = os.path.join(outdir, ZIP_NAME)
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(members):
            zi = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            zi.compress_type, zi.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(zi, members[name])
    return zp


def manifest(zp):
    z = zipfile.ZipFile(zp)
    return dict(zip_sha256=hashlib.sha256(open(zp, 'rb').read()).hexdigest(),
                members=[dict(name=i.filename, size=i.file_size, sha256=hashlib.sha256(z.read(i)).hexdigest()) for i in sorted(z.infolist(), key=lambda i: i.filename)])


# ---------------------------------------------------------------------------------------------- the checks (each returns a list of problems)
def check_members(names):
    want, got = set(expected_members()), set(names)
    return [f'missing {n}' for n in sorted(want - got)] + [f'unexpected {n}' for n in sorted(got - want)]


def outline_size(gerber_text):
    """(width, height) in mm of the bounding box of every coordinate in an Edge.Cuts Gerber, 4.6 format, absolute."""
    assert '%FSLAX46Y46*%' in gerber_text and '%MOMM*%' in gerber_text
    xs, ys = [], []
    for m in re.finditer(r'^X(-?\d+)Y(-?\d+)D0[123]\*$', gerber_text, re.M):
        xs.append(int(m.group(1)) / 1e6); ys.append(int(m.group(2)) / 1e6)
    return round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4)


def check_outline(gerber_text, width, height, tol=1e-3):
    w, h = outline_size(gerber_text)
    return [] if abs(w - width) <= tol and abs(h - height) <= tol else [f'outline {w} x {h} mm, expected {width} x {height}']


def drill_hits(text):
    """{(diameter mm, 'round'|'slot'): count} of an Excellon file in mm."""
    tool, size, out = None, {}, {}
    for line in text.splitlines():
        m = re.match(r'^T(\d+)C([\d.]+)', line)
        if m:
            size[m.group(1)] = float(m.group(2)); continue
        m = re.match(r'^T(\d+)$', line)
        if m:
            tool = m.group(1); continue
        if tool and re.match(r'^X-?[\d.]+Y-?[\d.]+(G85X-?[\d.]+Y-?[\d.]+)?$', line):
            kind = 'slot' if 'G85' in line else 'round'
            out[(size[tool], kind)] = out.get((size[tool], kind), 0) + 1
    return out


def board_holes(board_text):
    """The same counts, taken independently from the board file's own text: pads with a drill and vias. -> (pth, npth)."""
    pth, npth = {}, {}
    for blk in re.split(r'\n\t\(footprint ', board_text)[1:]:
        for m in re.finditer(r'\(pad "[^"]*" (thru_hole|np_thru_hole) \w+(.*?)\n\t\t\)', blk, re.S):
            d = re.search(r'\(drill (oval )?([\d.]+)( ([\d.]+))?\)', m.group(2))
            if not d: continue
            key = (max(float(d.group(2)), float(d.group(4) or 0)) if d.group(1) else float(d.group(2)), 'slot' if d.group(1) else 'round')
            tgt = pth if m.group(1) == 'thru_hole' else npth
            tgt[key] = tgt.get(key, 0) + 1
    for m in re.finditer(r'\n\t\(via\b(.*?)\n\t\)', board_text, re.S):
        d = re.search(r'\(drill ([\d.]+)\)', m.group(1))
        pth[(float(d.group(1)), 'round')] = pth.get((float(d.group(1)), 'round'), 0) + 1
    return pth, npth


def check_drills(pth_text, npth_text, board_text):
    bp, bn = board_holes(board_text)
    out = []
    for name, got, want in (('PTH', drill_hits(pth_text), bp), ('NPTH', drill_hits(npth_text), bn)):
        if got != want:
            out.append(f'{name} drill file {sorted(got.items())} != board file {sorted(want.items())}')
    return out


def verify(zp, board, width, height):
    z = zipfile.ZipFile(zp)
    names = z.namelist()
    probs = check_members(names)
    if probs: return probs
    t = lambda k: z.read(f'{IDENT}-{k}').decode('utf8')
    return check_outline(t('Edge_Cuts.gm1'), width, height) + check_drills(t('PTH.drl'), t('NPTH.drl'), open(board).read())


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        a = sys.argv[2:]
        bom = a[a.index('--bom') + 1] if '--bom' in a else f'v2/bom/{IDENT}-bom.csv'
        cpl = a[a.index('--cpl') + 1] if '--cpl' in a else f'v2/bom/{IDENT}-cpl.csv'
        print(build(a[0], a[1], bom, cpl))
    elif sys.argv[1] == 'manifest':
        print(json.dumps(manifest(sys.argv[2]), indent=1))
