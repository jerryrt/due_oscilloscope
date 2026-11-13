# pcbtools: the array interface (proposal v0, for review before anything is built on it)

One package for both AFE boards (v1 and v2). Nothing board-specific in the code: a board is a small config
(`BoardConfig`, below) plus its `.kicad_pcb`. This file fixes the interface between the I/O adapter and every check or
editor, so the checking side (kvm_02) and the building side (kvm_01) can work in parallel.

## Rules

1. **pcbnew is loaded exactly once per board**, by `pcbtools.boardio.read_board(path) -> BoardArrays`, which copies what the
   tools need into plain numpy arrays and then **releases pcbnew** (the `BOARD` object is deleted inside the call; nothing
   in `BoardArrays` refers to pcbnew). Peak memory of a read is about one board load (160 MB measured on the v2 integrated
   board) and the returned arrays are a few MB.
   Deleting the `BOARD` frees the Python wrapper, not pcbnew's C++ memory: in the gate the pytest process kept about 1.3 GB
   after the pcbnew tests (`gc.collect()` and `malloc_trim` returned nothing), so a long-lived process that loads many boards
   must be split into processes (`docker/pcb/run-gate.sh` does).
2. **Every check works on `BoardArrays`**, vectorised. No per-segment Python loops. A computation that a numpy
   expression reproduces replaces the loop it came from (the loop is deleted, not kept as a fallback).
3. **Edits go through one write path** (`pcbtools.boardio.edit(path)`: a context manager that loads, yields a thin
   editor, saves, and frees the board in one place; owned by the building side). The checking side never writes a board.
4. **Order and rounding**: every item array keeps KiCad's own enumeration order (`board.GetTracks()` split into segments and vias, `GetFootprints()`), and `s_idx`, `v_idx`, `fp_idx` are the position in that enumeration so an editor can delete or move an item from a mask computed on the arrays without re-searching. Positions and sizes are rounded to 1e-6 mm at read time, so golden figures compare with a 1e-6 tolerance.
5. **Coordinates**: every array is in *Due mm*: x right, y **up**, origin the Due's lower-left corner (KiCad x - 50,
   150 - KiCad y). float64. Angles are degrees, counter-clockwise, KiCad's convention. The transform lives in ONE function in `boardio` (`to_due`/`from_due`), tested against two known pads (J601 pin 5 at (38.1, 2.54) on the v2 board).
6. **pcbtools imports pcbnew only inside `boardio.py`** (and the building side's editor). The core (`geom`, `rules`,
   `cap`) imports numpy/scipy only, so it is testable without KiCad, on boards the tests build as arrays with known answers.

## `BoardArrays` (frozen dataclass; every field is a numpy array or a tuple of str)

| group | fields (all length N of the group unless noted) |
|---|---|
| meta | `path: str`, `copper_layers: int`, `nets: tuple[str]` (index = net id; `nets[0] == ""` for no net; names as KiCad writes them, e.g. `/GND`) |
| outline | `outline: float64 (K,2)` board outline polygon (Edge.Cuts), closed implicitly |
| segments (tracks) | `s_idx: int32`, `s_x0 s_y0 s_x1 s_y1 s_w: float64`, `s_layer: int8` (0 = F.Cu, 1 = B.Cu), `s_net: int32` |
| arcs (PCB_ARC tracks) | `a_idx: int32`, `a_x0 a_y0 a_xm a_ym a_x1 a_y1 a_w: float64` (start, mid, end), `a_layer: int8`, `a_net: int32`. `read_board` never drops an arc silently: it returns them here (a check that cannot handle arcs must say so, not skip them) |
| vias | `v_idx: int32`, `v_x v_y v_dia v_drill: float64`, `v_net: int32` |
| footprints | `fp_idx: int32`, `fp_ref: tuple[str]`, `fp_x fp_y fp_rot: float64`, `fp_side: int8` (0 = F, 1 = B), `fp_cx0 fp_cy0 fp_cx1 fp_cy1: float64` courtyard bbox (NaN if none), `fp_kind: tuple[str]` (library footprint name) |
| pads | `p_fp: int32` (index into footprints), `p_pin: tuple[str]`, `p_x p_y: float64` centre, `p_bx0 p_by0 p_bx1 p_by1: float64` bbox, `p_net: int32`, `p_smd: bool`, `p_rot: float64` (degrees, absolute), `p_shape: int8` (0 circle, 1 rect, 2 oval, 3 roundrect, 4 other), `p_sx p_sy: float64` (pad size before rotation; a rotated pad's bbox overstates clearance, so geometry uses size and rotation; the arrays carry no corner radius, so a rounded-rect pad is treated as its circumscribed rectangle, conservative by about 0.08 mm at the corners, the safe direction for every clearance check), `p_layer_mask: uint8` (bit0 F, bit1 B) |
| reference text | `r_x r_y r_h r_w r_t: float64`, `r_ang: float64`, `r_layer: int8` (0 = F.SilkS, 1 = B.SilkS, 2 = F.Fab, 3 = other), `r_on_silk: bool` (visible on F.SilkS), `r_fp: int32` |
| silk texts (board-level) | `t_text: tuple[str]`, `t_x t_y t_h: float64` |
| zones | per zone: `z_layer: int8`, `z_net: int32`, `z_filled: bool`. Filled copper as ONE vertex array `z_xy: float64 (V,2)` plus int64 offsets per level: `z_ring_off` (zone -> ring: zone i owns rings `z_ring_off[i]:z_ring_off[i+1]`) and `z_vert_off` (ring -> vertex: ring j owns `z_xy[z_vert_off[j]:z_vert_off[j+1]]`), and `z_ring_hole: int8` per ring (0 = outline, 1 = hole; a hole cuts the nearest outline ring before it). `geom.points_in_polys(..., hole=z_ring_hole)` respects holes KiCad fractures the fills it returns (`HoleCount` 0 on every fixture zone), so a recorded board has no hole ring: the hole path is proven by the synthetic tests only |

A `BoardArrays` also carries two derived lookups (built once, plain numpy):

* `net_id(name) -> int` (raises KeyError), `ref_index(ref) -> int`, `pad_index(ref, pin) -> int`.
* `seg_mask(net=..., layer=...)`, `pad_mask(net=...)` returning boolean arrays (boolean selection only; no loops).

## `pcbtools.geom` (numpy only, vectorised; the shared kernels)

All take arrays, return arrays, and chunk internally so memory stays bounded (peak < 200 MB for 10 000 x 10 000 pairs).

* `seg_len(S)`, `seg_seg_dist(A, B)` -> `(len(A), len(B))` minimum distance between segments (exact: endpoint to segment
  and crossing test), with `within(A, B, d)` returning index pairs `(i, j)` closer than `d` without materialising the matrix.
* `point_seg_dist(P, S)`, `seg_in_box(S, box)`, `box_overlap(A, B)`, `box_dist(A, B)`, `points_in_polys(P, polys)`.
* `connected_components(items, joins)`: union-find over item indices given pairs that touch, for LR-6/LR-8 (copper
  connectivity of a net through tracks, vias and pads).

## `BoardConfig` (per board, plain data, one module each: `pcbtools/boards/v2.py`, `v1.py`)

Everything a rule needs that is not geometry, as tables at the top of one file:

* `NAME`, `BOARD` (default path), `FENCES = {block: [(x0, y0, x1, y1), ...]}`, `HUNDREDS = {digit: block}`, `OWNER_OVERRIDE`.
* net tables: `SENSITIVE`, `XSENS` (bottom-copper-forbidden), `INV_LEN_NODES`, `INV_NODES`, `IN_NODES` (divider nodes),
  `VREF_BRANCH_GROUPS`, `STAR` (named star pads per rail: `{net: [(ref, pin), ...]}`), `GROUPS` (LR-6 consumer groups), `AREF`.
* `DECOUP = {cap_ref: (ic_ref, supply_pin)}`, `INV_MAX`, `DECOUP_MAX`, `HOP_MAX`, `KEEPOUT_REFS`, `KEEPOUT_MM`.
* `CONTRACT_ROWS` (the floorplan table as data: net, edge point, layer, width) and `BRIDGES` (ref, nets).
* thresholds from the rule text (LR-1..LR-12) as named constants, each with the rule number in a comment.

Config values come from `design.py` / `floorplan.py` where they already exist (import them, do not copy).

## Rule results

`pcbtools.rules.<rule>(b: BoardArrays, cfg) -> Result(ok: bool, detail: str, figures: dict)`. `figures` holds the numbers
(lengths, distances, clearances) so golden files can compare figures, not only pass/fail. The CLI `python -m pcbtools.check
BOARD --config v2 [--mutate]` prints the same lines as today's `lr_check.py`.

## Mutation arms

Every rule keeps its mutation arm. An arm is a function `BoardArrays -> BoardArrays` (a copy with a numpy edit, e.g. append a
segment) and the test requires the rule to flip from pass to fail. Arms are pure numpy: no pcbnew, nothing to leak, so they run
in-process (one subprocess per arm is only for the `pcbnew`-marked tests that load a real board).

## What changes for the building side (kvm_01)

* Reads use `read_board`. Writes use `boardio.edit(path)`; the editor API (move footprint, set text, add/remove track/via,
  add footprint, refill zones) is the building side's to define; the checking side only needs the file on disk.
* `layout.py`, `merge_blocks.py`, `fence_check.py` (the latter is a checking-side rule, built on arrays) share the same config.

## Settled in review (kvm_01, montreal5, kvm_02)

1. Field list as above: plus the `*_idx` fields, `r_layer`, arcs, pad rotation/shape/size and the 1e-6 rounding. Not needed: 3D, footprint properties, silk graphics beyond text. LR-10 stays KiCad's DRC.
2. Zones: one flat vertex array plus int64 offsets per level (zone -> ring -> vertex) and a per-ring outline/hole flag (holes are kept in the arrays, but KiCad's fractured fills carry none, so the keep-back round an inverting node is a slit in the outline and the hole path rests on the synthetic tests).
3. Config is Python modules (they import `design.py` / `floorplan.py`: one source, no second home for a table); every constant a module-level name so a test can build a config from plain values.
4. Base: this branch is cut from `origin/main`; the old tools stay on `v1-layout-wip` / `v2-layout-wip` as the reference (goldens are captured from there) and are ported only into `pcbtools/`. Board files used as fixtures go in `tests/fixtures/` as copies named after their source commit.

## Write path (kvm_01's)

`with pcbtools.boardio.edit(path) as e:` loads once, yields an Editor, saves and frees on exit (no module-level keep list; the objects
pcbnew's SWIG must not free are held by the editor instance until exit). Editor methods: `move(ref, x, y, rot=None, side=None)`,
`set_ref(ref, x, y, h, w, t, on_silk)`, `add_text(text, x, y, h, layer='F.SilkS')`, `add_tracks(net, layer, X0, Y0, X1, Y1, w)` (arrays),
`add_vias(net, x, y, dia, drill)` (arrays), `remove_tracks(idx)`, `remove_vias(idx)` (index arrays from `BoardArrays`),
`add_footprint_from(base_path, ref)`, `fill_zones()`.
