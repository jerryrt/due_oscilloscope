"""The AFE's coordinate frame is one value, pcbtools.frame.FRAME, which every AFE caller passes to pcbkit.board (it has no default): the
v2 configuration agrees with it, the Due's corner comes out of it, and a to_frame / from_frame round trip returns the point."""
from pcbkit import board as KB
from pcbtools.boards import v2
from pcbtools.frame import FRAME


def test_frame_is_one_value():
    assert tuple(v2.FRAME) == tuple(FRAME) == (50.0, 150.0)


def test_due_corner_and_roundtrip():
    x, y = KB.to_frame(50.0, 150.0, FRAME)
    assert (float(x), float(y)) == (0.0, 0.0)
    assert [float(v) for v in KB.from_frame(*KB.to_frame(60.0, 140.0, FRAME), FRAME)] == [60.0, 140.0]
