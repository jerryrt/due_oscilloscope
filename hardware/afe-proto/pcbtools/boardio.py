"""Board I/O for the AFE: pcbkit.board with this project's coordinate frame.

The reader, the BoardArrays container and the npz cache live in hardware/pcbkit/pcbkit/board.py and are the same objects here
(every public and private name of that module is re-exported). What this file adds is the project's FRAME, the Due's: KiCad
board_x = OX + x, board_y = OY - y, i.e. Due mm, y up, origin at the Due's lower-left corner (x - 50, 150 - y), which the kit
no longer knows. `read_board(path)`, `read_board_retry(path)`, `to_due` and `from_due` keep their old signatures and bind it.
"""
from pcbkit import board as _kit
from pcbkit.board import *      # noqa: F401,F403  (public names)

globals().update({k: v for k, v in vars(_kit).items() if not k.startswith('__')})     # and the private ones (_ALL, _r, ...)

FRAME = (50.0, 150.0)           # the same as boards/v2.py's FRAME (tests/pcbtools/test_frame.py holds them equal)
OX, OY = FRAME


def to_due(x, y):
    """KiCad mm -> Due mm (arrays or scalars)"""
    return _kit.to_frame(x, y, FRAME)


def from_due(x, y):
    """Due mm -> KiCad mm; the inverse of to_due"""
    return _kit.from_frame(x, y, FRAME)


def read_board(path):
    """Load `path` with pcbnew once, copy everything into BoardArrays in Due mm, return."""
    return _kit.read_board(path, FRAME)


def read_board_retry(path, tries=3, timeout=120):
    """pcbkit.board.read_board_retry in the AFE frame"""
    return _kit.read_board_retry(path, FRAME, tries=tries, timeout=timeout)


if __name__ == '__main__':       # python -m pcbtools.boardio BOARD.kicad_pcb OUT.npz
    import sys
    save_npz(read_board(sys.argv[1]), sys.argv[2])
