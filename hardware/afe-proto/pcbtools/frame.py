"""The AFE's coordinate frame, the one value every reader and transform of the AFE tools passes to pcbkit.board.

KiCad's board_x = OX + x and board_y = OY - y, i.e. Due mm (y up, origin at the Due's lower-left corner): the Due's shield sits
at (50, 150) on the KiCad page. pcbkit.board has no default frame: a caller names it, and for the AFE this is the name
(`pcbkit.board.read_board(path, FRAME)`, `to_frame(x, y, FRAME)`). tests/pcbtools/test_frame.py holds it equal to the board
configurations' own FRAME.
"""
FRAME = (50.0, 150.0)
