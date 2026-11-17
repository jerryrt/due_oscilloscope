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

## Policy (one for the whole package)

* **Project names raise.** Anything specific to one project (a net, a part, a table, a rectangle, a prefix, the frame) has no default: a rule or tool that needs one and does not find it raises
  `pcbkit.config.ConfigError` naming the key (`ConfigError` is a `ValueError`, so a tool that still raises `ValueError` for a missing name is compatible), and never passes.
* **Tunables default.** A margin, a limit, a tolerance, a step has the default listed in its row of this document and is reported as `default` when the project does not set it. A design value
  (a distance from a design rule, such as `KEEPOUT_DIST`) is a project name, not a tunable.
* **The effective configuration is reported.** `rules.effective_config(cfg, rule)` (and `labels.effective_config`, `pinlabels.effective_config`) returns every name a call reads with its value and `project` or
  `default`; every rule function takes `report=[]` to receive the same rows; a run prints it and a report carries it.
* **The typo guard.** `pcbkit.config.DECLARED` is the registry of every name a module declares (`config.declare(rule, names)`, at import; `import pcbkit` imports the rule modules). Each rule checks the names of the configuration
  it is given: a name no module declares is *unrecognised*, listed by `effective_config` and otherwise ignored (an AFE configuration carries many names of its own); a name that is not declared but is a likely typo of a declared one
  raises `ConfigError` naming both. "Near" is edit distance 2 when the shorter name has at least 6 characters, 1 when it has 4 or 5, and never for shorter names: a short name is within 2 edits of half the alphabet (the AFE's
  `GEN` is within 2 of `GND`, and a flat distance of 2 would have raised on its configuration). A declared name never raises, even when it is near another declared name (`config.declared_pairs_near()` lists such pairs).
  On the AFE's configurations (`v2_layout`, `v2`, `v1`, `v1r`, `v1_frozen`) nothing raises (`tests/afe_effective_config.py`). A module that does not declare its names yet (`pinlabels`) is simply not guarded.

Each rule declares its names in a `*_NAMES` table in `pcbkit/rules.py`; a rule never reads a name it does not list. The sections below give every name, its kind, type, unit and default.

## Rules (`pcbkit.rules`)

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

### rules.sensitive_nets

For each listed net, in order: a via on it, copper on the other layer, top track over a length limit; then every top segment of a net that has a gap with another net's top
track (the plane net `GND` and the segment's own net excluded) nearer than `gap` plus half the two widths. Findings are `Finding(kind, net, value, other)`; `sensitive_nets_parts`
returns them so a caller can word them itself (the AFE's LR-3 and LR-4 do).

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `GND` | project | net name | required | never a foreign track |
| `SENSITIVE_NETS` | project | list of dicts | required | one per net: `net` (required), `no_via` (True), `no_bottom` (False: no copper on the other layer), `max_length` (None: mm of top track), `gap` (None: mm); a key not in this list raises `ConfigError` |

### rules.pour_gap

Exact copper-edge to copper-edge distance from each node's top copper (tracks as capsules, pads by size and rotation) to top ground tracks and to the edges of filled, hole-aware top ground fills
(a keep-out area is not a fill); 0 where the node lies on a fill, +inf when there is nothing to measure to. The judged nodes (`POUR_NODES`) fail when either gap is under `POUR_KEEP_BACK`.

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `GND` | project | net name | required | the ground net |
| `POUR_NODES` | project | list of net names | required | judged nodes |
| `POUR_KEEP_BACK` | project | mm | required | the design keep-back distance (no default: it is a design value, not a tolerance) |
| `POUR_INFO_NODES` | tunable | list of net names | `()` | measured and reported, not judged |

### rules.keepout_ring

Sensitive top copper keeps `KEEPOUT_DIST` from the courtyards of `KEEPOUT_PARTS`, measured from the copper's edge (a track as a capsule, a pad by size and rotation).

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `KEEPOUT_PARTS` | project | list of designators | required | their courtyards (a part without one raises `KeyError`) |
| `KEEPOUT_NETS` | project | list of net-name prefixes | required | the sensitive nets |
| `KEEPOUT_EXEMPT_PARTS` | project | list of designators | required | their pads are not judged (may be empty) |
| `KEEPOUT_DIST` | project | mm | required | the design distance |

### rules.decoupling

Each listed capacitor's pad on the pin's net (pad 1 when neither is) is within `DECOUPLING_MAX` of the IC pin.

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `DECOUPLING` | project | list of (capacitor, ic, pin) | required | |
| `DECOUPLING_MAX` | project | mm | required | the design distance (no default: a design value) |

The AFE's `lr3`, `lr4` (via, bottom copper, FB length and pour terms), `lr5` and `lr12` build these names from `HIZ`, `ADC_NETS`, `INV_NODES`, `AWG['fb_net']`/`FB_MAX`, `POUR_NODES`/`POUR_INFO_NODES`
(and the module constant `POUR_KEEP_BACK`), `GEN`/`SENSITIVE`/`GENERATOR_BLOCK`/`KEEPOUT`, `DECOUP`/`DECOUP_MAX`; LR-4's output-resistor and supply-capacitor terms stay in the AFE.

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
