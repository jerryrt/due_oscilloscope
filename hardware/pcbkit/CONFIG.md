# Configuration names

A configuration is a Python module or a mapping of upper-case names. Each pcbkit function that needs a name reads it from the
configuration it is given; a configuration that is given but lacks a name the function needs makes it raise `ValueError`
naming the field (or, for a rule, return a result that says it was not run). Nothing falls back to a value of its own that a
project could mistake for its own.

| name | type | unit | read by | when missing |
|---|---|---|---|---|
| `FRAME` | `(OX, OY)`, two floats | mm | `board.read_board`, `board.read_board_retry`, `board.frame_of` | raises `ValueError` naming `FRAME`, for a configuration without it and for no configuration at all; there is no default frame |

`FRAME` is the one place the coordinate frame is written, and a project name (it raises when missing). A project that wants KiCad's own axes passes `board.KICAD_FRAME = (0.0, 0.0)` explicitly, which means x as KiCad has it and y flipped to point up (`board_y = 0 - y`). The transform is KiCad `board_x = OX + x`, `board_y = OY - y`, so the arrays hold
`x = board_x - OX` and `y = OY - board_y` (y up). `board.to_frame(x, y, frame)` and `board.from_frame(x, y, frame)` are the
transform and its inverse. `board.frame_of(cfg)` accepts a 2-sequence, a mapping with `FRAME`, or an object with a
`FRAME` attribute. Lengths in the arrays are millimetres in this frame; angles are degrees counter-clockwise.

Names for the rules are added here as each rule moves in (`MIGRATION.md`).
