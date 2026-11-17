"""The AFE's coordinate frame is one value: pcbtools.boardio (which binds it for pcbkit.board) and the v2 configuration agree,
and a to_due / from_due round trip and the Due's corner come out of it."""
from pcbtools import boardio
from pcbtools.boards import v2


def test_frame_is_one_value():
    assert tuple(v2.FRAME) == tuple(boardio.FRAME) == (50.0, 150.0)


def test_due_corner_and_roundtrip():
    x, y = boardio.to_due(50.0, 150.0)
    assert (float(x), float(y)) == (0.0, 0.0)
    assert [float(v) for v in boardio.from_due(*boardio.to_due(60.0, 140.0))] == [60.0, 140.0]
