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

## Rules: how they read a configuration (`pcbkit.config`)

Every rule declares its names in a table (`GROUND_PLANE_NAMES`, `BOTTOM_HOPS_NAMES` in `pcbkit/rules.py`): a **project** name (a net, a part, a
table, a rectangle, a prefix) is required and a missing one raises `ConfigError` naming the rule and the key, never a pass; a **tunable** (a
margin, a limit, a tolerance) has the default shown below and is reported as `default` when the project does not set it. `rules.effective_config(cfg, rule)`
returns the effective configuration as text (name, `project` or `default`, value; the layout of `labels.effective_config`), and every rule function
takes `report=[]` to receive the same rows. A rule never reads a name it does not list.

**One `ConfigError` for the package** is `pcbkit.config.ConfigError`. **The typo guard:** `pcbkit.config.DECLARED` is the registry of every name any module
declares (`config.declare(rule, names)`, called at import). Each rule checks the names of the configuration it is given: a name no module declares is
*unrecognised*, listed by `effective_config` and otherwise ignored (an AFE configuration carries many names of its own); a name that is not declared but
is a likely typo of a declared one raises `ConfigError` naming both (edit distance 2 when the shorter name has at least 6 characters, 1 when it has 4 or 5,
never for shorter names). A declared name never raises, even when it is near another declared name (`config.declared_pairs_near()` lists such pairs: none
today). The registry holds the modules imported so far; `import pcbkit` imports them all. On the AFE's configurations (`v2_layout`, `v2`, `v1`, `v1r`,
`v1_frozen`) nothing raises (`tests/afe_effective_config.py`).

### rules.ground_plane

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `GND` | project | net name | required | the ground net |
| `PLANE_LAYER` | project | `'F'` or `'B'` (or 0, 1) | required | the copper layer that carries the plane |
| `COPPER_LAYERS` | tunable | count | 2 | the board has exactly this many copper layers |
| `GND_VIA_REACH` | tunable | mm | 3.0 | every SMD ground pad has a via of its own within this distance (greedy in (ref, pin) order, each via used once) |

### rules.bottom_hops

Signal copper on `PLANE_LAYER` (the plane's own net excluded) is judged as hops: a connected run (segments of one net touching within `HOP_JOIN_TOL`)
may be at most `HOP_MAX` long with at most `HOP_MAX_VIAS` vias at its ends, may not lie under a keep-out part, inside a fence or under a sensitive track or pad.

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `GND`, `PLANE_LAYER` | project | as above | required | as above |
| `HOP_FENCES` | project | list of (x0, y0, x1, y1), frame mm | required | areas no hop may enter (half the track width is added) |
| `HOP_SENSITIVE` | project | list of net-name prefixes | required | nets whose tracks (on the other layer) and pads no hop may pass under |
| `HOP_KEEPOUT_PARTS` | project | list of designators | required | parts whose courtyards no hop may lie under; a part with no courtyard is skipped |
| `HOP_MAX` | tunable | mm | 3.0 | longest run |
| `HOP_MAX_VIAS` | tunable | count | 2 | most vias at the ends of one run |
| `HOP_KEEPOUT_PAD` | tunable | mm | 0.0 | margin around a keep-out courtyard, besides half the track width |
| `HOP_JOIN_TOL` | tunable | mm | 0.01 | segments of one net closer than this are one run (end to end, end on a segment's interior, crossing) |
| `HOP_VIA_TOL` | tunable | mm | 0.05 | a via this close to a run's end belongs to it (same net only) |
| `HOP_SENSITIVE_CLEAR` | tunable | mm | 0.1 | clearance beyond half the two widths kept from a sensitive track, and (plus half the track width) from a sensitive pad |

The AFE's `pcbtools.rules.lr1` builds these names from its own tables (`GND`, `ANALOG_FENCE` and `OUTLINE`, `XSENS`, `ANALOG_REFS`, `ZONE_PAD`, `HOP_MAX`,
`HOP_MAX_VIAS`) in `kit_cfg_lr1` and keeps every tunable not named there at the default above, which is the value LR-1 always used.

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
