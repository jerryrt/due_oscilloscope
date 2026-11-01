#!/usr/bin/env python3
"""Prepare portable package bodies for the V03 reference; requires pinned OCP.

Only mechanical files/records are written. Original KiCad library assets are
copied with their headers; derived assets are rigidly aligned to EAGLE pads.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf
from OCP.gp import gp_Trsf, gp_Pnt, gp_Ax2, gp_Dir

ROOT = Path(__file__).resolve().parent
V03 = ROOT.parent / 'v03'
spec = importlib.util.spec_from_file_location('assembly_models', ROOT / 'prepare-models.py')
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)
spec = importlib.util.spec_from_file_location('model_clauses', V03 / 'attach-models.py')
clauses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clauses)

# EAGLE package -> KiCad footprint; model pin numbers are mapped explicitly
# where EAGLE uses different names. No electrical pin numbering is changed.
MATCHES = {
    'R0402': ('Resistor_SMD/R_0402_1005Metric', {}),
    'C0402': ('Capacitor_SMD/C_0402_1005Metric', {}),
    'R0603-ROUND': ('Resistor_SMD/R_0603_1608Metric', {}),
    'C0603-ROUND': ('Capacitor_SMD/C_0603_1608Metric', {}),
    '0805': ('Inductor_SMD/L_0805_2012Metric', {}),
    'CHIP-LED0805': ('LED_SMD/LED_0805_2012Metric', {'1':'C', '2':'A'}),
    'SMC_B': ('Capacitor_Tantalum_SMD/CP_EIA-3528-21_Kemet-B', {'1':'+', '2':'-'}),
    'CAT16': ('Resistor_SMD/R_Array_Concave_4x0603', {}),
    'CAY16': ('Resistor_SMD/R_Array_Convex_4x0603', {}),
    'MINIMELF': ('Diode_SMD/D_MiniMELF', {'1':'C', '2':'A'}),
    'DO220AAL': ('Diode_SMD/D_SMP_DO-220AA', {'1':'P$1', '2':'P$2'}),
    'SOT223': ('Package_TO_SOT_SMD/SOT-223', {}),
    'MSOP08': ('Package_SO/MSOP-8_3x3mm_P0.65mm', {}),
    'MLF32': ('Package_DFN_QFN/QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm', {}),
    'SC70-5': ('Package_TO_SOT_SMD/SOT-353_SC-70-5', {}),
    'SOT23-6': ('Package_TO_SOT_SMD/SOT-23-6', {}),
    'SOT23': ('Package_TO_SOT_SMD/SOT-23', {}),
    # In this EAGLE MOSFET package pad 1 is the single lead, and pads 2/3
    # form the opposite row. Generic KiCad SOT-23 calls the single lead 3.
    'SOT-23': ('Package_TO_SOT_SMD/SOT-23', {'1':'3', '2':'2', '3':'1'}),
    'CRYSTAL-3.2-2.5': ('Crystal/Crystal_SMD_3225-4Pin_3.2x2.5mm', {}),
}
SPECIAL = {'L1812', 'SRR0604', 'RESONATOR_EPSON_FC_145', 'SMD_157SW', 'CT/CN0603'}
SOURCES = {
    'L1812': 'https://www.bourns.com/data/global/pdfs/MF-MSMF.pdf',
    'SRR0604': 'https://bourns.com/docs/product-datasheets/srr0604.pdf',
    'RESONATOR_EPSON_FC_145': 'https://www.epsondevice.com/crystal/en/support/product-no/pdf/pcs.pdf',
    'CT/CN0603': 'https://www.bourns.com/docs/Product-Datasheets/cg0603mlc-05e_cg0603mlc-12e.pdf',
    'SMD_157SW': '../v03/source/Arduino-DUE-V03.brd: SMD_157SW outline and pads; height estimated',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pad_points(text):
    result = {}
    for _, _, block in clauses.children(text):
        match = re.match(r'\(pad "([^"]+)"', block)
        if match:
            pos = re.search(r'\(at ([\d.eE+-]+) ([\d.eE+-]+)', block)
            result[match[1]] = [float(pos[1]), -float(pos[2])]
    return result


def align(source, standard, rename):
    pairs = [(point, source[rename.get(number, number)])
             for number, point in standard.items()]
    assert len(pairs) == len(source) and len(pairs) >= 2
    trials = []
    for degrees in (0, 90, 180, 270):
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        rotated = [[c*p[0]-s*p[1], s*p[0]+c*p[1]] for p, _ in pairs]
        offset = [sum(q[i]-p[i] for p, (_, q) in zip(rotated, pairs))/len(pairs)
                  for i in (0, 1)]
        errors = [math.dist([p[i]+offset[i] for i in (0,1)], q)
                  for p, (_,q) in zip(rotated, pairs)]
        trials.append((max(errors), degrees, offset, sum(e*e for e in errors)))
    maximum, degrees, offset, _ = min(trials, key=lambda t:t[3])
    # Pad centers vary with solder-land length, but lead-row pitch and
    # handedness must match. This rejects mismatched pin patterns.
    assert maximum < 0.25, (maximum, degrees, offset)
    transform = gp_Trsf()
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    transform.SetValues(c,-s,0,offset[0], s,c,0,offset[1], 0,0,1,0)
    return transform, dict(rotation_z_degrees=degrees, translation_xy_mm=offset,
                          maximum_land_center_difference_mm=maximum,
                          standard_to_eagle_pad_names=rename,
                          note='Land-center differences reflect solder-pad dimensions; bodies are not scaled.')


def save(doc, path, header=''):
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    assert writer.Transfer(doc)
    assert writer.Write(str(path)) == IFSelect_RetDone
    if header:
        text = path.read_text()
        path.write_text(text.replace('HEADER;', 'HEADER;\n' + header, 1))


def library_body(source, destination, transform):
    doc = assembly.document()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    assert reader.ReadFile(str(source)) == IFSelect_RetDone and reader.Transfer(doc)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    out = assembly.document()
    out_shapes = XCAFDoc_DocumentTool.ShapeTool_s(out.Main())
    out_colors = XCAFDoc_DocumentTool.ColorTool_s(out.Main())

    def convert(label, placement):
        if shapes.IsAssembly_s(label):
            instances = TDF_LabelSequence()
            shapes.GetComponents_s(label, instances)
            for index in range(1, instances.Length()+1):
                instance = instances.Value(index)
                definition = TDF_Label()
                assert shapes.GetReferredShape_s(instance, definition)
                convert(definition, placement.Multiplied(shapes.GetLocation_s(instance).Transformation()))
            return
        original = shapes.GetShape_s(label)
        builder = BRepBuilderAPI_Transform(original, transform.Multiplied(placement), True)
        converted = builder.Shape()
        target = out_shapes.AddShape(converted, False)
        TDataStd_Name.Set_s(target, TCollection_ExtendedString(destination.stem))
        fallback = Quantity_Color(0.12,0.12,0.12,Quantity_TOC_RGB)
        colors.GetColor(original, XCAFDoc_ColorGen, fallback)
        out_colors.SetColor(target, fallback, XCAFDoc_ColorGen)
        for kind in (assembly.TopAbs_SOLID, assembly.TopAbs_FACE):
            for subshape in assembly.members(original, kind):
                for color_kind in (XCAFDoc_ColorGen, XCAFDoc_ColorSurf):
                    color = Quantity_Color()
                    if colors.GetColor(subshape, color_kind, color):
                        changed = builder.ModifiedShape(subshape)
                        sublabel = target if changed.IsSame(converted) else out_shapes.AddSubShape(target, changed)
                        assert not sublabel.IsNull()
                        out_colors.SetColor(sublabel, color, color_kind)
        return assembly.bounds(converted)

    roots = TDF_LabelSequence()
    shapes.GetFreeShapes(roots)
    for index in range(1, roots.Length()+1):
        convert(roots.Value(index), gp_Trsf())
    # Preserve the complete upstream copyright/license comment in derivatives.
    header = re.search(r'/\*.*?\*/', source.read_text(), re.S)
    save(out, destination, (header[0] if header else '') +
         '\n/* Local derivative: rigid alignment to Arduino Due V03 EAGLE package; no scaling. */\n')


def custom_body(package, path):
    """Simple colored solids; envelopes are documented, details approximated."""
    doc = assembly.document()
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    black, silver, gold = (0.055,0.06,0.065), (0.6,0.63,0.66), (0.55,0.4,0.12)
    extents = []

    def part(shape, color, name):
        label = shapes.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
        colors.SetColor(label, Quantity_Color(*color,Quantity_TOC_RGB), XCAFDoc_ColorGen)
        extents.append(assembly.bounds(shape))

    def box(x,y,z,dx,dy,dz,color,name):
        part(BRepPrimAPI_MakeBox(gp_Pnt(x,y,z),dx,dy,dz).Shape(),color,name)

    def chip(length,width,height,color,terminal):
        box(-length/2,-width/2,0.04,length,width,height-0.04,color,'Approximate body')
        for x in (-length/2,length/2-terminal):
            box(x,-width/2,0,terminal,width,0.12,silver,'Terminal')

    if package == 'L1812':
        chip(4.6,3.24,0.85,gold,0.7)
        note = 'MF-MSMF050 generic PPTC envelope 4.6 x 3.24 x 0.85 mm, within published limits; no printed marking.'
    elif package == 'CT/CN0603':
        chip(1.6,0.85,0.51,(0.24,0.22,0.19),0.3)
        note = 'CG0603MLC nominal 1.60 x 0.85 x 0.51 mm; simple body/terminals.'
    elif package == 'RESONATOR_EPSON_FC_145':
        chip(4.1,1.5,0.9,black,0.9)
        box(-1.95,-0.65,0.75,3.9,1.3,0.15,silver,'Approximate metal lid')
        note = 'FC-145 4.1 x 1.5 x 0.9 mm package envelope from Epson configuration guide; simplified lid and terminals.'
    elif package == 'SRR0604':
        box(-3.25,-3.25,0.15,6.5,6.5,0.7,black,'Inductor base')
        part(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0,0,0.85),gp_Dir(0,0,1)),3.25,3.95).Shape(),
             (0.16,0.17,0.18),'Simplified ferrite shield')
        for x in (-3.25,2.25):
            box(x,-1.25,0,1,2.5,0.2,silver,'Terminal')
        note = 'SRR0604 6.5 x 6.5 x 4.8 mm envelope; shield contours and internal winding omitted.'
    elif package == 'SMD_157SW':
        box(-1.6,-1.27,0.1,3.2,2.54,0.65,black,'Switch base')
        box(-1.6,-1.27,0.75,3.2,2.54,0.3,silver,'Switch lid')
        for x in (-2.3,1.6):
            box(x,-0.8,0,0.7,1.6,0.2,silver,'Contact')
        part(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0,0,1.05),gp_Dir(0,0,1)),0.81,0.55).Shape(),black,'Actuator')
        note = 'ERASE switch approximate visualization from source 4.064 x 2.54 mm package outline and two contacts; 1.6 mm height estimated, exact switch part unknown.'
    else:
        raise ValueError(package)
    save(doc, path, '/* Project-generated simplified visualization; see population.json for dimensions and sources. */\n')
    return note, [min(b[i] for b in extents) if i<3 else max(b[i] for b in extents) for i in range(6)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kicad-support', type=Path,
        default=Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport'))
    args = parser.parse_args()
    source = ET.parse(V03 / 'source/Arduino-DUE-V03.brd')
    packages = {(lib.get('name'),p.get('name')):p
                for lib in source.findall('.//board/libraries/library')
                for p in lib.findall('./packages/package')}
    renames = json.loads((V03/'validation.json').read_text())['reference_renames']
    existing = {a['reference'] for a in json.loads((ROOT/'alignment.json').read_text())['assignments']}
    for directory in ('library', 'library/footprints', 'packages', 'generated'):
        (ROOT/directory).mkdir(exist_ok=True)
    assignments, exclusions, assets = [], [], {}
    for element in source.findall('.//board/elements/element'):
        ref = renames.get(element.get('name'),element.get('name'))
        package, value = element.get('package'), element.get('value','')
        if ref in existing:
            continue
        if 'NM' in value or package == 'FIDUCIA-MOUNT':
            exclusions.append(dict(reference=ref, package=package, value=value,
                                   reason='Source marks not mounted' if 'NM' in value else 'Bare copper fiducial'))
            continue
        key = element.get('library') + ':' + package
        if key not in assets:
            p = packages[element.get('library'),package]
            if package in MATCHES:
                identity, rename = MATCHES[package]
                lib, stem = identity.split('/')
                fp_path = args.kicad_support/'footprints'/(lib+'.pretty')/(stem+'.kicad_mod')
                fp_text = fp_path.read_text()
                assert re.search(r'\(offset\s*\(xyz 0 0 0\)',fp_text)
                assert re.search(r'\(rotate\s*\(xyz 0 0 0\)',fp_text)
                assert re.search(r'\(scale\s*\(xyz 1 1 1\)',fp_text)
                original = args.kicad_support/'3dmodels'/(lib+'.3dshapes')/(stem+'.step')
                copy = ROOT/'library'/(stem+'.step')
                fp_copy = ROOT/'library/footprints'/(stem+'.kicad_mod')
                shutil.copyfile(original,copy)
                shutil.copyfile(fp_path,fp_copy)
                source_pads = {pad.get('name'):[float(pad.get('x')),float(pad.get('y'))]
                               for pad in p.findall('smd')}
                transform, alignment = align(source_pads,pad_points(fp_text),rename)
                output = ROOT/'packages'/(key.replace(':','_').replace('/','_')+'.step')
                library_body(copy,output,transform)
                note = 'Generic KiCad package body; actual manufacturer, height and markings not qualified.'
                if package == 'SMC_B':
                    note = 'Polar tantalum B-case approximation, 3.5 x 2.8 x 2.1 mm; EAGLE drawing 3.2 x 2.7 mm and land centers +/-1.5 mm. Actual installed height/type not identified. Positive end aligned to + pad.'
                asset = dict(file=str(output.relative_to(ROOT)), sha256=sha(output),
                    kind='kicad_library_package', library_footprint=identity,
                    upstream_model='https://gitlab.com/kicad/libraries/kicad-packages3D/-/blob/master/'+lib+'.3dshapes/'+stem+'.step',
                    original_file=str(copy.relative_to(ROOT)), original_sha256=sha(copy),
                    footprint_file=str(fp_copy.relative_to(ROOT)), footprint_sha256=sha(fp_copy),
                    license='CC-BY-SA-4.0 with KiCad library exception; upstream header retained',
                    alignment=alignment, qualification=note)
            elif package in SPECIAL:
                output = ROOT/'generated'/(package.replace('/','_')+'.step')
                note, bounds = custom_body(package,output)
                asset = dict(file=str(output.relative_to(ROOT)),sha256=sha(output),
                             kind='project_generated_simplified', dimensions_source=SOURCES[package],
                             local_bounds_mm=bounds, qualification=note)
            else:
                raise ValueError(('Unhandled populated component',ref,package,value))
            assets[key] = asset
            print('Prepared',package,flush=True)
        asset = assets[key]
        assignments.append(dict(reference=ref,package=key,value=value,file=asset['file'],
                                sha256=asset['sha256'],model_offset_mm=[0,0,0],
                                model_rotation_degrees=[0,0,0]))
    assert len(existing)+len(assignments)+len(exclusions) == 129
    result = dict(kicad_library_source='Installed KiCad 10.0.6 library; original model and footprint hashes retained',
                  scope='V03 visualization only. Generic packages and simplified special parts; original EAGLE electrical CAD preserved. No new owner inspection of this expanded population yet.',
                  assets=assets, assignments=assignments, exclusions=exclusions,
                  existing_assembly_models=len(existing), additional_models=len(assignments),
                  total_models=len(existing)+len(assignments))
    (ROOT/'population.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Additional:',len(assignments),'Total:',result['total_models'],'Bare:',len(exclusions),flush=True)


if __name__ == '__main__':
    main()
