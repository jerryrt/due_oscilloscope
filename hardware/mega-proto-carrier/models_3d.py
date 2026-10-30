#!/usr/bin/env python3
"""Project-local visual bodies for the normal populated carrier, KiCad 10.

Only 3D assignments change. Existing copper, pads, references and project
preferences are preserved. Generic body dimensions are not measured fit data.
"""
import hashlib
import json
from pathlib import Path
import shutil

import pcbnew as pcb

ROOT = Path(__file__).resolve().parent
DEST = ROOT / 'models' / 'kicad'
SOURCE = Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels')
ASSETS = {
    'socket6': 'Connector_PinSocket_2.54mm.3dshapes/PinSocket_1x06_P2.54mm_Vertical.step',
    'socket8': 'Connector_PinSocket_2.54mm.3dshapes/PinSocket_1x08_P2.54mm_Vertical.step',
    'header6': 'Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x06_P2.54mm_Vertical.step',
    'header8': 'Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x08_P2.54mm_Vertical.step',
    'digital': 'Connector_PinHeader_2.54mm.3dshapes/PinHeader_2x18_P2.54mm_Vertical.step',
    'corner': 'Connector_PinHeader_2.54mm.3dshapes/PinHeader_2x03_P2.54mm_Vertical.step',
    'switch': 'Button_Switch_THT.3dshapes/SW_PUSH_6mm.step',
    'led': 'LED_SMD.3dshapes/LED_0805_2012Metric.step',
    'resistor': 'Resistor_SMD.3dshapes/R_0805_2012Metric.step',
}


def prepare_assets():
    DEST.mkdir(parents=True, exist_ok=True)
    for relative in ASSETS.values():
        dest = DEST / Path(relative).name
        if not dest.exists():
            source = SOURCE / relative
            if not source.exists():
                raise FileNotFoundError(f'Install KiCad 10 3D libraries or restore {dest}')
            shutil.copyfile(source, dest)


def assignments(thickness):
    result = {}
    for n in range(1, 7):
        count = 6 if n == 4 else 8
        result[f'J{n}'] = (f'socket{count}', (0, 0, 0), (0, 0, -90), 'front female socket')
        result[f'J{n+9}'] = (f'header{count}', (0, 0, -thickness), (0, 180, -90), 'reverse male pins')
    result.update({
        'J7': ('digital', (2.54, 0, -thickness), (0, 180, 0), 'reverse 2x18 male header'),
        'J9': ('corner', (0, -2.54, 0), (0, 0, -90), 'front six-pin header; generic straight body'),
        'SW1': ('switch', (-3.25, 2.25, 0), (0, 0, 0), 'front 6 mm tactile switch'),
        'D1': ('led', (0, 0, 0), (0, 0, 0), 'front LED; polarity remains unverified'),
        'D2': ('led', (0, 0, 0), (0, 0, 0), 'front LED; polarity remains unverified'),
    })
    for ref in ('R1', 'R2', 'R3'):
        result[ref] = ('resistor', (0, 0, 0), (0, 0, 0), 'front chip resistor')
    return result


def attach_models(board):
    prepare_assets()
    thickness = pcb.ToMM(board.GetDesignSettings().GetBoardThickness())
    config = assignments(thickness)
    records = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in config:
            continue
        key, offset, rotation, role = config[ref]
        # These assignments are owned by this script; no board geometry moves.
        fp.Models().clear()
        model = pcb.FP_3DMODEL()
        name = Path(ASSETS[key]).name
        model.m_Filename = '${KIPRJMOD}/models/kicad/' + name
        model.m_Offset = pcb.VECTOR3D(*offset)
        model.m_Rotation = pcb.VECTOR3D(*rotation)
        model.m_Scale = pcb.VECTOR3D(1, 1, 1)
        model.m_Show = True
        fp.Add3DModel(model)
        records.append(dict(reference=ref, file='models/kicad/'+name,
                            offset_mm=list(offset), rotation_degrees=list(rotation), role=role))
    assets = [dict(file='models/kicad/'+Path(s).name, source_library=s,
                   sha256=hashlib.sha256((DEST/Path(s).name).read_bytes()).hexdigest())
              for s in ASSETS.values()]
    (ROOT/'models-3d-evidence.json').write_text(json.dumps(dict(
        revision='3D1', assembly='normal populated carrier, not stripped photo specimen',
        board_thickness_mm=thickness, assignments=sorted(records,key=lambda x:x['reference']),
        assets=assets, source='Unmodified models from installed KiCad 10 libraries',
        qualification='Generic visual body dimensions, heights and pin lengths are approximate. LED polarity and exact corner-header body style are not established by these models.',
        intentionally_empty=['J8 bare breakout field', 'PG1 prototyping holes', 'TP1 empty SMD lands', 'H1/H2 holes'],
    ), indent=2)+'\n')
    return len(records)


def physical_fingerprint(board):
    def xy(p):
        return [p.x, p.y]
    tracks = sorted((isinstance(t,pcb.PCB_VIA), xy(t.GetStart()), xy(t.GetEnd()),
                     t.GetLayer(), t.GetNetname(),
                     t.GetWidth(pcb.F_Cu) if isinstance(t,pcb.PCB_VIA) else t.GetWidth())
                    for t in board.GetTracks())
    pads = sorted((f.GetReference(), p.GetNumber(), xy(p.GetPosition()),
                   xy(p.GetSize()), xy(p.GetDrillSize()), p.GetShape(), p.GetNetname())
                  for f in board.GetFootprints() for p in f.Pads())
    footprints = sorted((f.GetReference(), xy(f.GetPosition()), f.GetOrientationDegrees(),
                         f.IsDNP(), f.GetValue()) for f in board.GetFootprints())
    outline = sorted((xy(s.GetStart()),xy(s.GetEnd()),s.GetWidth())
                     for s in board.GetDrawings() if s.GetLayer()==pcb.Edge_Cuts)
    return dict(tracks=tracks,pads=pads,footprints=footprints,outline=outline)


if __name__ == '__main__':
    path = ROOT/'mega-proto-carrier.kicad_pcb'
    board = pcb.LoadBoard(str(path))
    before = physical_fingerprint(board)
    before_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    count = attach_models(board)
    assert physical_fingerprint(board) == before
    pcb.SaveBoard(str(path), board)
    assert physical_fingerprint(pcb.LoadBoard(str(path))) == before
    data = json.loads((ROOT/'models-3d-evidence.json').read_text())
    data.update(before_board_sha256=before_sha, after_board_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                copper_pads_nets_outline_and_placement='unchanged')
    (ROOT/'models-3d-evidence.json').write_text(json.dumps(data,indent=2)+'\n')
    print(f'Attached {count} project-local component bodies; copper, pads, nets and placement unchanged.')
