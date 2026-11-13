"""One-shot steps for the bench (tests/bench_steps.json), each a fresh process that does one thing to one board and exits:

    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py sexpr  BOARD.kicad_pcb      parse the board text
    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py editor BOARD.kicad_pcb      edit() it: move one part, add a via, save a copy
    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py schematic                   write the v1 schematic project from design.py
    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py board                       build the v1 placement board from design.py
    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py fence  BOARD BASE BLOCK     fence.check_fence of a block board against BASE

The bench measures wall time and peak memory of the whole process, so each step is the smallest honest unit of work.
"""
import os
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def sexpr(path):
    from pcbtools import sexpr as sx
    sx.parse(pathlib.Path(path).read_text())


def editor(path):
    from pcbtools import boardio
    from pcbtools.editor import edit
    b = boardio.read_board(path)
    out = os.path.join(tempfile.mkdtemp(prefix='pcbtools-bench-'), 'out.kicad_pcb')
    with edit(path, out=out) as e:
        e.move(b.fp_ref[0], float(b.fp_x[0]), float(b.fp_y[0]), float(b.fp_rot[0]))
        e.add_vias('GND', 1.0, 1.0)


def _work():
    return tempfile.mkdtemp(prefix='pcbtools-bench-')


def schematic(_=None):
    from pcbtools import schematic as sch
    from pcbtools.boards import v1_build as v1b
    w = _work()
    parts, cfg = v1b.sch_inputs(v1b.prepare(w))
    sch.write_all(parts, cfg, os.path.join(w, 'new'))


def board(_=None):
    from pcbtools import build as bd
    from pcbtools.boards import v1_build as v1b
    w = _work()
    old = v1b.prepare(w)
    inp = v1b.pcb_inputs(old)
    nets = bd.schematic_nets(os.path.join(old, 'afe-proto.kicad_sch'))
    bd.build_board(inp['parts'], inp['cfg'], inp['place'], nets, os.path.join(w, 'new.kicad_pcb'),
                   legalise_overlaps=True, anchors=inp['anchors'])


def fence(path, base, block):
    from pcbtools import boardio, fence as F
    from pcbtools.boards import v2
    F.check_fence(boardio.read_board(base), boardio.read_board(path), block, v2)


if __name__ == '__main__':
    {'sexpr': sexpr, 'editor': editor, 'schematic': schematic, 'board': board, 'fence': fence}[sys.argv[1]](*sys.argv[2:])
