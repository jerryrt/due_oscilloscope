"""One-shot steps for the bench (tests/bench_steps.json), each a fresh process that does one thing to one board and exits:

    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py sexpr  BOARD.kicad_pcb      parse the board text
    python3 hardware/afe-proto/tests/pcbtools/bench_tools.py editor BOARD.kicad_pcb      edit() it: move one part, add a via, save a copy

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


if __name__ == '__main__':
    {'sexpr': sexpr, 'editor': editor}[sys.argv[1]](sys.argv[2])
