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

* **One numeric tolerance.** `EPS` (tunable, mm, default 0.005) is declared once, in `pcbkit.config` (`config.EPS_NAME`, `config.EPS_DEFAULT`), and every rule that compares a distance with a threshold lists it in its names table and applies it the same way: a distance passes a threshold when it is within `EPS` of it. It is coordinate and text-box resolution (KiCad's nm grid and pcbnew's stroke boxes, a few micrometres), not a loosened margin: it is the rounding allowance, and it is what lets a label that is 1.25 micrometres short of the margin pass. `pcbkit.labels` reads this same declared value (`from pcbkit.config import EPS_NAME, EPS_DEFAULT`), not a copy of its own.

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

### rules.blocks (and `outlines`)

Each block's rectangles hold exactly the parts of that block (a part is judged by its origin, rectangles closed), named strays excepted. `blocks_parts` returns the findings as text
(`BLOCK: outline holds [extra] extra, lacks [missing]`); `block_of_parts` is each footprint's block (its configured block, else the first outline holding its origin).
The lines of an outline (breaks at pads and silk) are drawn by `pcbkit.labels`, not here.

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `BLOCK` | project | dict ref -> block | required | |
| `OUTLINE` | project | dict block -> list of (x0, y0, x1, y1), frame mm | required | |
| `OUTLINE_STRAYS` | tunable | list of designators | `()` | allowed outside their own block's rectangles, never inside another's |
| `EDGE_BLOCK` | tunable | block name or None | None | its parts are in no outline, unless listed in `BLOCK_OVERRIDE` |
| `BLOCK_OVERRIDE` | tunable | list of designators | `()` | edge-block parts that are judged anyway |
| `SHARED_PARTS` | tunable | dict ref -> home block | `{}` | a part straddling two rectangles: held to its home outline within `SHARED_MARGIN`, counted in no other |
| `SHARED_MARGIN` | tunable | mm | 0.0 | |

### rules.test_points

Each of `TEST_BLOCKS` has a test point (a part whose designator starts with `TP_PREFIX` and which has pad `TP_PIN`; a part without a block of its own takes the outline holding it), and each test point
in `TP_NETS` is on its net. Findings: `block X has no test point` (sorted), then `TPn: missing or not on NET`.

| name | kind | type | default |
|---|---|---|---|
| `BLOCK`, `OUTLINE` | project | as blocks | required |
| `TEST_BLOCKS` | project | list of block names | required |
| `TP_NETS` | project | dict ref -> net | required |
| `TP_PREFIX`, `TP_PIN` | project | designator prefix, pin number | required |

### rules.designators

`designators` = the silk requirement + the two-way nearest test; `silk_required_parts`, `designator_findings`, `one_label_pairs` and `foreign_labels` are the pieces a project words itself (the AFE's LR-11 does).

* **Silk requirement** (`silk_required_parts`): a part whose designator prefix is in `SILK_REQUIRED_PREFIXES` (None: every part) must have its reference text on F.SilkS at `DESIGNATOR_MIN_H` or more; any other part may have moved it to F.Fab.
* **Legibility terms** (`designator_findings`, `one_label_pairs`, `foreign_labels`): designator boxes (length per character x `DESIGNATOR_ADVANCE`, width `DESIGNATOR_INK_H`, both times the text height) closer than `DESIGNATOR_GAP_MIN`,
  over another part's pad, farther than `DESIGNATOR_DIST_MAX` from every pad of their own part, two on one baseline closer than `DESIGNATOR_GAP_ONE_LABEL`, or a centre inside another block's outline.
* **The two-way nearest test** (`two_way_test`, ported unchanged from the AFE-2 label job): measured from the boxes of the part's solid (the F.Fab body box of every graphic, text included, and each pad box) and of its label (its designator, plus any `LABEL_TEXTS` text);
  (1) from the label, its own part is nearer than any other part by `READ_MARGIN`; (2) from the part, its own label is nearer than any other label by `READ_MARGIN`; an anchor (longest matching prefix in `SILK_REQUIRED_PREFIXES`) is compared only with its own kind, a passive with all.
  It reads `fp_fab_*` and the board text boxes through `board.require`, so a board that did not come from `pcbkit.board.read_board` raises `FieldNotRead`. On the AFE-2 integrated board it reproduces the original script's result: 60 labelled parts, only J605 failing, all own distances equal.

| name | kind | type, unit | default | meaning |
|---|---|---|---|---|
| `SILK_REQUIRED_PREFIXES` | project | tuple of prefixes, or None | required | |
| `DESIGNATOR_MIN_H` | project | mm | required | |
| `DESIGNATOR_GAP_MIN`, `DESIGNATOR_DIST_MAX` | project | mm | required | legibility terms |
| `DESIGNATOR_ADVANCE`, `DESIGNATOR_INK_H` | tunable | fraction of text height | 0.95, 1.2 | the box. **One meaning across the package: fractions of the text height** (a box is the fraction times the text's height in mm; `pcbkit.labels` follows this) |
| `DESIGNATOR_GAP_ONE_LABEL` | tunable | mm | 0.6 | |
| `DESIGNATOR_FOREIGN_WAIVED` | tunable | dict ref -> block | `{}` | |
| `READ_MARGIN` | tunable | mm | 0.15 | the owner's margin (round 5 of the label job) |
| `EPS` | tunable | mm | 0.005 | **the package's one numeric tolerance** (see Policy): a distance passes the two-way test when `own + READ_MARGIN <= other + EPS` |
| `LABEL_TEXTS` | tunable | dict text -> designator | `{}` | board silk texts that are part of a part's label (a BNC's function text) |
| `BLOCK`, `OUTLINE`, `EDGE_BLOCK`, `BLOCK_OVERRIDE`, `SHARED_PARTS` | as blocks | | | foreign labels |

The AFE's `lr11` builds these names from its own tables in `kit_cfg_lr11` and keeps what is its own: the designator-number rule (`LR_HUNDREDS`), the recorded waivers of close pairs (`DESIGNATOR_GAP_WAIVED`), the pin labels, the identity silk, the silk words and the D30 wording. It does not run the two-way test (the AFE's two-way
test is the label job's `stackcheck.py`, now `pcbkit.rules.two_way_test`).

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

## labels (`pcbkit.labels.place`, `check_two_way`)

| name | type | default | meaning |
|---|---|---|---|
| `SILK_REQUIRED_PREFIXES` | tuple of str | required | reference prefixes of the anchors; an anchor goes through `ANCHOR_TIERS`, is placed before passives and is compared only with parts and labels of its own kind (longest matching prefix) |
| `NO_LABEL_PREFIXES` | tuple of str | required | parts that carry no designator |
| `DESIGNATOR_ADVANCE` | float | 0.95 | label box length per character, per character (box length = characters x this) |
| `DESIGNATOR_INK_H` | float | 1.2 | label box width across the text, a fraction of the text height |
| `DESIGNATOR_H` | float (mm) | 1.0 | the designators' text height |
| `SILK_CHAR_ADV`, `SILK_TEXT_H` | float | 0.9, 1.0 | the text box the silk readers use (own-part test) |
| `READ_MARGIN` | float | 0.15 | two-way nearest test: own part (or own label) nearer than any other by this, measured to bodies and pads |
| `OWN_MARGIN` | float | 0.25 | search preference of the placer (not part of `validate`): the silk text box nearer its own part's courtyard (body in the relaxed tiers) than any other's by this |
| `LABEL_GAP` | float | 0.2 | clearance between two labels |
| `DESIGNATOR_GAP_ONE_LABEL` | float | 0.6 | clearance between two labels on one baseline |
| `PAD_CLEAR` | float | 0.10 | label box to any pad, via or silk |
| `ANCHOR_PAD_CLEAR` | float | 0.05 | label box to a pad, for an anchor (an IC, connector or test point with little room); a passive uses `PAD_CLEAR` |
| `OUTLINE_CLEAR` | float | 0.05 | label box to a block-outline line (board-level silk line) |
| `VIA_CLEAR` | float or None | None | label box to a via; None = a label may lie over a via (the board tents its vias, DRC allows it, both approved boards have labels over them) |
| `EPS` | float | `pcbkit.config.EPS_DEFAULT` | the package's one resolution allowance (declared once in `pcbkit.config`), applied in `validate` |
| `OUTLINE_STRAYS` | tuple of ref | `()` | parts that may sit outside their block's rectangle and in no other; their labels are inside their block's rectangle or at least in no other block's |
| `TEXT_CLEAR` | float | 0.4 | label box to a board text |
| `EDGE_CLEAR` | float | 0.4 | label box to `LABEL_AREA` edge |
| `OWN_SOLID_CLEAR` | float | 0.05 | label box to its own part's body and pads |
| `GAPS` | tuple | `(0.15,0.25,0.35,0.5,0.7,0.9,-0.1,-0.2,-0.3,-0.4)` | gaps from the courtyard in search order; negative = over the courtyard's edge |
| `GAPS_OUTSIDE` | tuple | `(1.2,1.6,2.0,2.5,3.0)` | extra gaps for the `out` tiers |
| `SLIDE` | float | 0.1 | step of the sliding coordinate |
| `REGION_MARGIN` | float | 0.1 | a label inside a block's rectangle keeps this from its lines |
| `LABEL_AREA` | box or None | board outline box | where labels may sit (before `EDGE_CLEAR`) |
| `BLOCK` | dict or callable | required | reference -> block name |
| `OUTLINE` | dict | required | block -> list of rectangles (x0, y0, x1, y1); a part whose origin is inside its block's rectangles keeps its label inside; any other label stays out of every block's rectangles |
| `PRIORITY` | tuple of ref | `()` | anchors placed first, in this order |
| `FORCE` | dict ref -> (x, y, angle) | `{}` | a label at a stated place, tier `forced`, not tested (the owner's call) |
| `FIXED_LABELS` | dict ref -> (x, y, angle) | `{}` | labels that stay as they are (a BNC's vertical designator), placed first as obstacles |
| `PASSIVE_TEST` | `'courtyard'` or `'body'` | `'courtyard'` | the strict test for a passive: against other courtyards (AFE-1, D30) or other bodies (AFE-2) |
| `ANCHOR_TIERS` | tuple of (test, where) | strict/in, relaxed/in, strict/out, relaxed/out, samekind/in, samekind/out | tests an anchor goes through; `relaxed` judges bodies, `samekind` compares only same-kind bodies, `out` = outside every rectangle with the longer gaps |

`validate(labelboard, plan, cfg, skip)` checks a finished board with the hard tests only (label area, own part, pads, footprint silk, outline lines, board texts, label spacing, the two-way test in
three directions, the region rules); the owner's reading standard is the two-way test with `READ_MARGIN`, so `OWN_MARGIN` and the courtyard tests only steer the search.

## labels: connector boxes (`bnc_layout`), block names (`place_names`), outline lines (`outline_segments`)

| name | type | default | meaning |
|---|---|---|---|
| `BNC` | dict ref -> text | required by `bnc_layout` | the connectors that get a box and a turned designator plus function text; the text is the function label |
| `BNC_MARGIN` | float or None | None | box margin on all four sides of each connector's silk; None = (pitch - silk height) / 2 so neighbouring boxes share a line |
| `BNC_DES_DY`, `BNC_FN_DY` | float | -3.35, -0.45 | designator centre and function-text bottom, from each connector's origin (same for all) |
| `BNC_LINE` | float | 0.075 | half the outline line width, used to centre the labels in the left margin |
| `BLOCK_NAMES` | dict block -> text | required by `place_names` | the block names to place, one size, at a rectangle corner |
| `NAME_SIZE` | float | 1.2 | text height of a block name |
| `NAME_AREA` | box or None | `LABEL_AREA` | where names may sit |
| `NAME_CLEAR_BODY`, `NAME_CLEAR_PAD`, `NAME_CLEAR_SILK` | float | 0.05, 0.10, 0.08 | clearances of a name |
| `NAME_REACH`, `NAME_STEP` | float | 12.0, 0.25 | search distance from the corner and step |
| `OUTLINE_BREAK_CLEAR` | float | 0.2 | an outline line is broken this far each side of a pad, footprint silk or forced label |
| `OUTLINE_IGNORE` | list of boxes | `()` | boxes holding other drawn lines (not outline lines) that `validate_outline` skips |
| `NAME_OUTSIDE_GAPS` | tuple | (0.3, 0.5) | gaps of the outside tier of a block name (flush with a rectangle corner, just outside its side) |
| `NAME_CORNER_MAX` | float | 12.0 | how far (manhattan, box corner to rectangle corner) a name inside its rectangle may be from the nearest corner |
| `OUTLINE_LINE_HALF` | float | 0.075 | half the outline line width |

`validate_names(labelboard, boxes, cfg, others)` and `validate_outline(labelboard, drawn_segments, cfg)` check the block names (one size, at a corner inside the rectangle or flush
with a corner just outside, clear of bodies, pads, silk and labels) and the outline lines (every edge closed except at pad, footprint-silk or forced-label breaks, each break 0.2 mm
clear, a shared line drawn once, no line across anything, none off the rectangles). A forced label may touch a line; only crossing it counts.

Where the checks live: `pcbkit.rules` owns the two-way nearest test (`two_way_all` on boxes lists every offender, `two_way_core` keeps the nearest of each step, `two_way_test` reads a board; `too_near` is the one comparison of both steps) and the one-label rule (`shares_baseline`); `pcbkit.outlines` owns the region rule for a label
(`label_region_findings`), the block-name check (`check_name_boxes`) and the outline-line check (`check_outline_lines`). `pcbkit.labels` places labels and calls them: `validate`, `validate_names`, `validate_outline` and
`check_two_way` are thin callers, so the placer and the rules can never disagree about what reads. The placer's search calls `too_near` with the same `READ_MARGIN` and `EPS` for its own-part-nearer test (step 1) and for a new label crowding a placed part (step 2 from the other part); only the test of the new label against the labels already placed, as seen from its own part (step 2), is deliberately stricter (full margin, no allowance, equality rejects), because it is a search preference. `validate` reports a label that crowds a fixed or forced part under the judged label's owner.
