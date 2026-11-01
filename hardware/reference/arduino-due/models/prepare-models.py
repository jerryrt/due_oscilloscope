#!/usr/bin/env python3
"""Extract matching STEP bodies in footprint-local coordinates; requires OCP.

Run with cadquery-ocp-novtk==7.9.3.1.1. Original assembly geometry is retained.
Only selected component bodies are exported; PCB, oversized LEDs and generic
capacitors are deliberately excluded. No electrical CAD is modified here.
"""
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import (XCAFDoc_DocumentTool, XCAFDoc_ColorGen,
                         XCAFDoc_ColorSurf)
from OCP.gp import gp_Trsf

ROOT = Path(__file__).resolve().parent
V03 = ROOT.parent / 'v03'
ARCHIVE = ROOT / 'source/arduino-due-1.snapshot.12.zip'
ASSEMBLY = ROOT / 'assembly/Arduino-Due.step'
# Occurrences in this particular STEP assembly, verified by product name and
# assembly coordinates. Multiple two-pin strips form one native header.
GROUPS = {
    'J3': [2], 'USB1': [3], 'X2': [4], 'U1': [9],
    'DEBUG0': [10, 11], 'ICSP1': [12, 13, 14], 'SPI0': [15, 16, 17],
    'JTAG0': [18], 'PWML0': [19], 'COMMUNICATION0': [20],
    'POWER0': [21], 'ADCL0': [22], 'ADCH0': [23], 'PWMH0': [24],
    'XIO0': [25], 'PC1': [35], 'PC2': [36], 'RESET0': [37],
}
EXPECTED_NAMES = {
    'J3': 'MicroUSB B', 'USB1': 'MicroUSB AB', 'X2': 'Power Jack',
    'U1': 'SAM3X8EAU', 'PC1': 'Nichicon', 'PC2': 'Nichicon',
    'RESET0': 'Switch',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return list(box.Get())


def members(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def named(label):
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ''


def document():
    return TDocStd_Document(TCollection_ExtendedString('XmlXCAF'))


def visual_color(ref, face):
    """Generic display materials; the supplied STEP has one pale-blue color."""
    b = bounds(face)
    black, silver, red = (0.035,0.04,0.045), (0.55,0.58,0.62), (0.55,0.025,0.02)
    if ref == 'U1':
        return black if b[5] > 0.9 else silver
    if ref in {'POWER0','PWML0','PWMH0','ADCL0','ADCH0','COMMUNICATION0','XIO0'}:
        return black if b[5] > 0.1 else silver
    if ref in {'SPI0','ICSP1','DEBUG0','JTAG0'}:
        return black if b[2] > -0.1 and b[5] < 2.8 else silver
    if ref == 'X2':
        surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
        metal = (surface.GetType() == GeomAbs_Cylinder and surface.Cylinder().Radius() < 1.2)
        return silver if b[5] < 0.1 or metal else black
    if ref in {'PC1','PC2'}:
        return black if b[5] < 0.7 else silver
    if ref == 'RESET0':
        cap = b[2] > 2.5 and max(b[3]-b[0], b[4]-b[1]) < 3.5
        return red if cap else (black if b[5] < 0.9 else silver)
    return silver


def main():
    ROOT.joinpath('assembly').mkdir(exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        original = archive.read('STEP and IGES/ARDUINO DUE.STEP')
        ASSEMBLY.write_bytes(original)
        (ROOT / 'assembly/supplied-rendering.jpg').write_bytes(
            archive.read('Renderings/Arduino Duo.JPG'))
    doc = document()
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    assert reader.ReadFile(str(ASSEMBLY)) == IFSelect_RetDone
    assert reader.Transfer(doc)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shapes.GetFreeShapes(roots)
    assert roots.Length() == 1
    instances = TDF_LabelSequence()
    assert shapes.GetComponents_s(roots.Value(1), instances)
    assert instances.Length() == 37

    pcb_shape = shapes.GetShape_s(instances.Value(1))
    pcb_bounds = bounds(pcb_shape)
    assert abs(pcb_bounds[3] - pcb_bounds[0] - 101.6) < 0.02
    assert abs(pcb_bounds[5] - pcb_bounds[2] - 53.34) < 0.02
    eagle = ET.parse(V03 / 'source/Arduino-DUE-V03.brd')
    cylinders = []
    for face in members(pcb_shape, TopAbs_FACE):
        surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
        if surface.GetType() != GeomAbs_Cylinder:
            continue
        cylinder = surface.Cylinder()
        axis = cylinder.Axis().Direction()
        if abs(abs(axis.Y()) - 1) < 1e-6:
            center = cylinder.Location()
            cylinders.append((center.X(), -center.Z(), cylinder.Radius()))
    hole_matches = []
    for hole in eagle.findall('.//board/plain/hole'):
        x, y = float(hole.get('x')), float(hole.get('y'))
        radius = float(hole.get('drill')) / 2
        possible = [c for c in cylinders if abs(c[2] - radius) < 0.02]
        assert possible, (x, y, radius)
        closest = min(possible, key=lambda c: math.hypot(c[0]-x, c[1]-y))
        delta = math.hypot(closest[0]-x, closest[1]-y)
        assert delta < 0.02, (x, y, closest, delta)
        hole_matches.append(dict(eagle_xy_mm=[x, y], step_xy_mm=list(closest[:2]),
                                 center_delta_mm=delta, radius_mm=closest[2]))
    assert len(hole_matches) == 6

    validation = json.loads((V03 / 'validation.json').read_text())
    renames = validation['reference_renames']
    elements = {renames.get(e.get('name'), e.get('name')): e
                for e in eagle.findall('.//board/elements/element')}
    destination = ROOT / 'components'
    destination.mkdir(exist_ok=True)
    # SolidWorks assembly lies in X/Z, with the board top at Y=+0.8 mm.
    # KiCad model coordinates have X/Y in the PCB plane, Z up, top at Z=0.
    global_transform = gp_Trsf()
    global_transform.SetValues(1,0,0,0, 0,0,-1,0, 0,1,0,-0.8)
    result = []
    for ref, occurrence_ids in GROUPS.items():
        element = elements[ref]
        x, y = float(element.get('x')), float(element.get('y'))
        angle = float(element.get('rot', 'R0').removeprefix('R'))
        theta = math.radians(angle)
        c, s = math.cos(theta), math.sin(theta)
        local_transform = gp_Trsf()
        local_transform.SetValues(c,s,0,-c*x-s*y, -s,c,0,s*x-c*y, 0,0,1,0)
        out_doc = document()
        out_shapes = XCAFDoc_DocumentTool.ShapeTool_s(out_doc.Main())
        out_colors = XCAFDoc_DocumentTool.ColorTool_s(out_doc.Main())
        products = []
        color_count = 0
        for occurrence_id in occurrence_ids:
            instance = instances.Value(occurrence_id)
            definition = TDF_Label()
            assert shapes.GetReferredShape_s(instance, definition)
            product = named(definition)
            expected = EXPECTED_NAMES.get(ref, 'Berg Header')
            assert expected in product, (ref, product)
            original_shape = shapes.GetShape_s(definition)
            placement = shapes.GetLocation_s(instance).Transformation()
            # Keep original assembly placement; do not snap approximate bodies
            # to fabricated coordinates. Localize it around the actual footprint.
            transform = local_transform.Multiplied(global_transform).Multiplied(placement)
            builder = BRepBuilderAPI_Transform(original_shape, transform, True)
            converted = builder.Shape()
            label = out_shapes.AddShape(converted, False)
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(ref + ': ' + product))
            for kind in (TopAbs_SOLID, TopAbs_FACE):
                for subshape in members(original_shape, kind):
                    for color_kind in (XCAFDoc_ColorGen, XCAFDoc_ColorSurf):
                        color = Quantity_Color()
                        if colors.GetColor(subshape, color_kind, color):
                            converted_subshape = builder.ModifiedShape(subshape)
                            sublabel = (label if converted_subshape.IsSame(converted)
                                        else out_shapes.AddSubShape(label, converted_subshape))
                            assert not sublabel.IsNull(), (ref, occurrence_id, kind)
                            out_colors.SetColor(sublabel, color, color_kind)
                            color_count += 1
            # Keep geometry, but give the otherwise uniformly pale-blue STEP
            # generic plastic/metal materials so the KiCad view is legible.
            for face in members(converted, TopAbs_FACE):
                sublabel = out_shapes.AddSubShape(label, face)
                assert not sublabel.IsNull()
                out_colors.SetColor(sublabel, Quantity_Color(*visual_color(ref, face), Quantity_TOC_RGB),
                                    XCAFDoc_ColorSurf)
            products.append(dict(occurrence=occurrence_id, product=product,
                                 assembly_bounds_mm=bounds(shapes.GetShape_s(instance)),
                                 local_bounds_mm=bounds(converted)))
        path = destination / (ref + '.step')
        writer = STEPCAFControl_Writer()
        writer.SetColorMode(True)
        writer.SetNameMode(True)
        assert writer.Transfer(out_doc)
        assert writer.Write(str(path)) == IFSelect_RetDone
        result.append(dict(reference=ref, file=str(path.relative_to(ROOT)),
                           sha256=digest(path), bytes=path.stat().st_size,
                           footprint_xy_mm=[x, y], footprint_rotation_degrees=angle,
                           colored_subshapes=color_count, source_products=products,
                           model_offset_mm=[0,0,0], model_rotation_degrees=[0,0,0]))
        print('Prepared',ref,flush=True)
    evidence = dict(
        tool='cadquery-ocp-novtk', tool_version=importlib.metadata.version('cadquery-ocp-novtk'),
        source_step='assembly/Arduino-Due.step', source_step_sha256=digest(ASSEMBLY),
        source_archive='source/'+ARCHIVE.name, source_archive_sha256=digest(ARCHIVE),
        source_board_bounds_xyz_mm=pcb_bounds,
        mounting_hole_comparison=hole_matches,
        alignment='(STEP X, -STEP Z, STEP Y - 0.8 mm), then inverse of each native footprint placement/rotation; unit scale.',
        display_materials='Generic black plastic, silver metal and red switch cap assigned by face geometry. Supplied STEP contains only a uniform pale-blue material; colors are display approximations, not original vendor material or polarity evidence.',
        qualification='Mechanical visualization only. Mounting holes and board size match V03; connector heights, pin details, IC pin-1 orientation and physical fit are not measured qualifications. Small original placement offsets are retained.',
        excluded_occurrences=dict(pcb=[1],leds=[5,6,7,8],generic_capacitors=list(range(26,35))),
        exclusions='No duplicate PCB slab. Source 3.2x1.6 mm LED bodies do not match the 0805 footprints; generic capacitor bodies do not establish the SMC_B polarized package. Other unmodeled source parts are left bare.',
        assignments=result,
    )
    (ROOT / 'alignment.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Prepared',len(result),'component models; six mounting holes match.',flush=True)


if __name__ == '__main__':
    main()
