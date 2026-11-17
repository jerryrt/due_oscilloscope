# Configuration names

A configuration is a Python module or a mapping of upper-case names. Each pcbkit function that needs a name reads it from the
configuration it is given; a configuration that is given but lacks a name the function needs makes it raise `ValueError`
naming the field (or, for a rule, return a result that says it was not run). Nothing falls back to a value of its own that a
project could mistake for its own.

| name | type | unit | read by | when missing |
|---|---|---|---|---|
| `FRAME` | `(OX, OY)`, two floats | mm | `board.read_board`, `board.read_board_retry`, `board.frame_of` | a configuration without it raises `ValueError`; no configuration at all (`cfg=None`) means `board.DEFAULT_FRAME = (0.0, 0.0)`, KiCad's origin with y pointing up |

`FRAME` is the one place the coordinate frame is written: KiCad `board_x = OX + x`, `board_y = OY - y`, so the arrays hold
`x = board_x - OX` and `y = OY - board_y` (y up). `board.to_frame(x, y, frame)` and `board.from_frame(x, y, frame)` are the
transform and its inverse. `board.frame_of(cfg)` accepts `None`, a 2-sequence, a mapping with `FRAME`, or an object with a
`FRAME` attribute. Lengths in the arrays are millimetres in this frame; angles are degrees counter-clockwise.

Names for the rules are added here as each rule moves in (`MIGRATION.md`).
