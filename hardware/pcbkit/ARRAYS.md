# Arrays added to `board` after the first release (step 1b)

Frame. Every array is in the frame the configuration's `FRAME = (OX, OY)` names: `board_x = OX + x`, `board_y = OY - y`, so y points up. `FRAME` is required: `read_board` raises, naming it, when it is missing. `board.KICAD_FRAME = (0.0, 0.0)` is KiCad's own origin with y flipped up; a project that wants it passes it explicitly.

All in the configured frame (`FRAME`), mm, y up; boxes are `x0 <= x1`, `y0 <= y1`. Read from pcbnew, never from the file text. A
field that was not read RAISES. `board.require(b, *fields)` raises `FieldNotRead`, naming the field, unless the read that made `b` filled
it; `b.read_fields` is the set of added fields a read filled, and an empty array never means "not read". Every pcbkit consumer of an added
field calls `require` first (`fab_boxes`, `footprint_silk`, `board_silk_graphics` and `text_boxes` do; so must each later rule).
What fills them:

| reader | fills the added fields? |
|---|---|
| `pcbkit.board.read_board(path, cfg)`, `read_board_retry`, and an npz cache written from one | yes: `read_fields == LATER_FIELDS`, a field with zero rows is still read |
| a board built by hand (`from_arrays`), an npz cache written before this step | no, unless the caller names the fields it filled in `read_fields=` |

`fp_fab_*` is NaN for a footprint with no F.Fab shape. **`fp_fab_*` is the box of the F.Fab SHAPES only; text on F.Fab is not part of it.** F.Fab text is not printed and is not the part: since D30 (1c) it is just the designators moved off the silk, and a label that touches another part's F.Fab reference text is not touching that part. A part with no F.Fab shape (the test points) has NaN, and the two-way nearest test then uses its pads as the solid, which it always includes. (An earlier version included the text: it made four of AFE-1's approved labels and one of AFE-2's block names fail the two-way test by touching other parts' F.Fab designators.) No configuration name is read beyond `FRAME`.

| fields | one row per | what |
|---|---|---|
| `fp_fab_x0/y0/x1/y1` | footprint (same rows as `fp_*`) | the box of all the footprint's F.Fab SHAPES (the body); F.Fab text is not part of it. NaN when it has none |
| `fs_fp`, `fs_x0/y0/x1/y1`, `fs_kind` | F.SilkS graphic of a footprint | owner footprint row; pcbnew's bounding box, stroke width included; kind `segment`, `rect`, `arc`, `circle`, `poly`, `text`, `other` |
| `g_x0/y0/x1/y1`, `g_kind` | board-level F.SilkS shape | pcbnew's bounding box with the stroke; kind `line`, `rect`, `poly`, `arc`, `circle`, `other` |
| `t_ang`, `t_stroke`, `t_just`, `t_hide`, `t_layer`, `t_x0/y0/x1/y1` | board-level F.SilkS text (the existing `t_*` rows) | angle (degrees), stroke width, horizontal justification `left`/`center`/`right`, hide flag, layer code (0 = F.SilkS: only F.SilkS texts are rows), pcbnew's box of the rendered text |
| `r_hide`, `r_just` | reference text (the existing `r_*` rows) | hide flag (not visible), horizontal justification. The stroke is the existing `r_t`; there is no `r_stroke` |

Notes. KiCad 10 keeps no hide flag on a board-level text, so `t_hide` is always False. `t_just` is the horizontal justification only. The
existing `p_bx0/by0/bx1/by1` are pcbnew's `GetBoundingBox` of the pad (checked in `tests/test_board_silk.py`): the axis-aligned box of the pad
as turned on the board. `LATER_FIELDS` names every field added in this step; a project that must keep its recorded set filters by it.
