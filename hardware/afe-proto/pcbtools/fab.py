"""The JLC fabrication set of a board: Gerbers, Excellon drills, the BOM and CPL, in one deterministic zip, and the checks on it.

    python3 -m pcbtools.fab build BOARD OUTDIR [--bom F --cpl F] [--design v1|v2]
                                                                      write OUTDIR/<IDENT>-fab.zip (needs kicad-cli: run in the image); --design picks the identity,
                                                                      the kicad-cli file stem and the default BOM/CPL of version 1 or 2 (default v2)
    python3 -m pcbtools.fab manifest ZIP                              the manifest (member names, sizes, sha256) as JSON

Options follow docs/jlcpcb.md section 1 ("Files for KiCad"): Gerber with Protel extensions, 4.6 format, F/B.Cu, F/B.Mask, F/B.Silkscreen,
Edge.Cuts and F.Paste, extended X2 and netlist attributes on, no drill marks, scale 1:1; Excellon in mm, absolute origin, decimal zeros,
PTH and NPTH in separate files, alternate mode for ovals. The zip is flat (JLC reads the Gerbers and drills from the zip root); the BOM and
CPL are the bom engine's files (`v2/bom/<IDENT>-bom.csv`, `-cpl.csv`), which JLC takes in its own upload step, so they are in the zip under
their own names and a customer may leave them out of the Gerber upload. Reproducibility: kicad-cli writes the plot time into the Gerber and
drill headers, so it is replaced by a fixed stamp, members are sorted, and the zip entries carry a fixed date and mode.
"""
import json, os, sys
from pcbkit import fab as _kit
from pcbkit.fab import (LAYERS, GERBERS, DRILLS, ASSEMBLY, STAMP, _norm, manifest, check_outline, outline_size, drill_hits, board_holes, check_drills)   # noqa: F401  (the kit's own)

STEM = 'afe-v2-integrated'       # kicad-cli's own file stem (the board's name)


def _ident():
    import importlib.util
    sp = importlib.util.spec_from_file_location('_fab_v2cfg', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards', 'v2.py'))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return f'{m.NAME}-{m.MODEL}-REV{m.REV}'


def design_ident(design):
    """(IDENT, kicad-cli file stem, directory of the BOM and CPL) of a design: v2 as above; v1 from the literals NAME, MODEL and REV of boards/v1.py (read with ast:
    that config imports the design data, and the name is written once, there)"""
    if design == 'v2':
        return IDENT, STEM, 'v2/bom'
    import ast
    lit = {}
    for n in ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boards', 'v1.py')).read()).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('NAME', 'MODEL', 'REV'):
            lit[n.targets[0].id] = ast.literal_eval(n.value)
    return f"{lit['NAME']}-{lit['MODEL']}-REV{lit['REV']}", 'afe-proto', 'bom/v1'


IDENT = _ident()                  # the member and zip prefix, from the config: COPPIA-AFE-2-REVA
GERBERS = {'F_Cu.gtl': 'top copper', 'B_Cu.gbl': 'bottom copper', 'F_Mask.gts': 'top mask', 'B_Mask.gbs': 'bottom mask',
           'F_Silkscreen.gto': 'top silk', 'B_Silkscreen.gbo': 'bottom silk', 'Edge_Cuts.gm1': 'outline', 'F_Paste.gtp': 'top paste'}
DRILLS = {'PTH.drl': 'plated holes', 'NPTH.drl': 'non-plated holes'}
ASSEMBLY = {'bom.csv': 'JLC BOM', 'cpl.csv': 'JLC CPL'}
ZIP_NAME = IDENT + '-fab.zip'
STAMP = '2000-01-01T00:00:00+00:00'


def expected_members(ident=None):
    return _kit.expected_members(ident or IDENT)


def build(board, outdir, bom, cpl, ident=None, stem=None):
    return _kit.build(board, outdir, bom, cpl, ident or IDENT, stem or STEM)


def check_members(names, ident=None):
    return _kit.check_members(names, ident or IDENT)


def verify(zp, board, width, height, ident=None):
    return _kit.verify(zp, board, width, height, ident or IDENT)


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        a = sys.argv[2:]
        ident, stem, bomdir = design_ident(a[a.index('--design') + 1] if '--design' in a else 'v2')
        bom = a[a.index('--bom') + 1] if '--bom' in a else f'{bomdir}/{ident}-bom.csv'
        cpl = a[a.index('--cpl') + 1] if '--cpl' in a else f'{bomdir}/{ident}-cpl.csv'
        print(build(a[0], a[1], bom, cpl, ident, stem))
    elif sys.argv[1] == 'manifest':
        print(json.dumps(manifest(sys.argv[2]), indent=1))
