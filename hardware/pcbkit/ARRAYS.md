# Arrays added to `board` after the first release (step 1b)

All in the configured frame (`FRAME`), mm, y up; boxes are `x0 <= x1`, `y0 <= y1`. Read from pcbnew, never from the file text. A
board built by hand, or an npz cache that predates them, leaves them empty (length 0 = not read; a consumer that needs one checks `len`). `fp_fab_*` is NaN for a footprint with no F.Fab shape. No configuration name is read.

| fields | one row per | what |
|---|---|---|
| `fp_fab_x0/y0/x1/y1` | footprint (same rows as `fp_*`) | the box of all the footprint's F.Fab shapes (the body); text on that layer is not part of it. NaN when it has none |
| `fs_fp`, `fs_x0/y0/x1/y1`, `fs_kind` | F.SilkS graphic of a footprint | owner footprint row; pcbnew's bounding box, stroke width included; kind `segment`, `rect`, `arc`, `circle`, `poly`, `text`, `other` |
| `g_x0/y0/x1/y1`, `g_kind` | board-level F.SilkS shape | pcbnew's bounding box with the stroke; kind `line`, `rect`, `poly`, `arc`, `circle`, `other` |
| `t_ang`, `t_stroke`, `t_just`, `t_hide`, `t_layer`, `t_x0/y0/x1/y1` | board-level F.SilkS text (the existing `t_*` rows) | angle (degrees), stroke width, horizontal justification `left`/`center`/`right`, hide flag, layer code (0 = F.SilkS: only F.SilkS texts are rows), pcbnew's box of the rendered text |
| `r_hide`, `r_just` | reference text (the existing `r_*` rows) | hide flag (not visible), horizontal justification. The stroke is the existing `r_t`; there is no `r_stroke` |

Notes. KiCad 10 keeps no hide flag on a board-level text, so `t_hide` is always False. `t_just` is the horizontal justification only. The
existing `p_bx0/by0/bx1/by1` are pcbnew's `GetBoundingBox` of the pad (checked in `tests/test_board_silk.py`): the axis-aligned box of the pad
as turned on the board. `LATER_FIELDS` names every field added in this step; a project that must keep its recorded set filters by it.
