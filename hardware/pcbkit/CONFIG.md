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

## pinlabels (`pcbkit.pinlabels`)

| name | type | default | meaning |
|---|---|---|---|
| `FRAME` | (OX, OY) | required | board x = OX + x, board y = OY - y |
| `EDGE_SOCKETS` | dict | required | socket reference on the board -> header reference in the pin table |
| `PIN_TABLE`, `PIN_TABLE_ROOT` | path | required, cwd | the markdown pin table; `PIN_TABLE_ROOT` is what a relative path is relative to |
| `BASE_RECT` | box | required (or `DUE_RECT`) | the base board's outline, where the sockets' pad edge is measured from |
| `BOARD_RECT`, `KEEPOUTS` | box, [(name, box)] | required | the shield's outline and the overhang bands the labels sit in |
| `PIN_LABEL_H`, `_W`, `_THICK`, `_EDGE_MARGIN`, `_PAD_GAP`, `_POS_TOL`, `_INK_H` | float | required | label text size, stroke, distance to the board edge and to pads, position tolerance, ink height |
| `PIN_LABEL_INK` | dict name -> mm | required | measured ink length of each name (`--measure` in the PCB image writes the file) |
| `PIN_LABEL_INK_FILE` | path | None | the json `--measure` reads and writes |
| `PIN_LABEL_ALIASES`, `PIN_LABEL_FUNCTION_HEADERS` | dict, tuple | `{}`, `()` | table cell -> label mapping; headers whose label is the word that is not the Dnn number |
| `PIN_LABEL_UUID_NAMESPACE` | str | 'pinlabel' | the namespace of the labels' uuids (a project that already has labels keeps its own) |
| `DESIGNATOR_GAP_ONE_LABEL`, `DESIGNATOR_ADVANCE`, `DESIGNATOR_INK_H` | float | required | spacing between labels and the designators' box size |

## fab, ibom, render, proof

These take their identity as arguments, not configuration: `fab.build(board, outdir, bom, cpl, ident, stem)` (`ident` the member prefix, `stem` kicad-cli's file stem), `render.render(board, out, side, width,
height, quality)`, `ibom.run(board, extra, home)` (`IBOM_HOME` in the environment), `proof.digest(path)`, `proof.compare`, `proof.netdiff`. Environment: `IBOM_HOME`, `KICAD_FOOTPRINT_DIR` (tests),
`PCBKIT_ROOT`, `PCBKIT_REQUIRE_PCBNEW`.

Policy for the pin-label tools (the same as the label tools): the project's own names (`FRAME`, `EDGE_SOCKETS`, `PIN_TABLE`, `KEEPOUTS`, `BOARD_RECT`, `PIN_LABEL_INK`, `PIN_LABEL_INK_H`, and one of
`BASE_RECT` / `DUE_RECT`) raise `ValueError` when missing. Tunables (label size, stroke, margins, tolerance, spacing, uuid namespace) fall back to a default. `pinlabels.effective_config(cfg)`
returns every name with its value and `project` or `default`; the command line prints it at the start of every run and a report carries it.
