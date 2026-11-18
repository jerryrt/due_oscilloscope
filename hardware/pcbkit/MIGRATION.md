# Moving the general tools out of afe-proto/pcbtools

One module per step. A step lands only when the AFE quick tier passes unchanged with the AFE code importing the moved module
from here, and the module's own tests in `hardware/pcbkit/tests` pass on synthetic boards. The AFE's figures (gate-3 rows,
the fab manifests, silkread counts) do not move in any step; a step that moves one is a behaviour change, not a move.

| step | from (afe-proto) | to (pcbkit) | what changes on the way | status |
|---|---|---|---|---|
| 1 | `pcbtools/boardio.py`, `geom.py`, `shapes.py` | `board`, `geom` | the Due frame (`OX, OY`) becomes `FRAME` in the configuration; `shapes` joins `geom` | moved (branch `pcbkit-step1`) |
| 1b | (new reads in `board`, from the label and silk tools' own parsing of the file text) | `board` | F.Fab body boxes, footprint and board silk graphics, text angle, justification, stroke, box, hide flag: the arrays in `ARRAYS.md`. No AFE figure moves | moved (branch `pcbkit-step1b`) |
| 2 | `pcbtools/rules.py`: `lr1`, `bottom_runs`, `bottom_crossings` | `rules.ground_plane`, `rules.bottom_hops` | fences and sensitive nets come from the configuration by name | moved (branch `pcbkit-step2`) |
| 3 | `rules.py`: `lr3`, `lr4`'s via and length terms, `pour_gaps`, `lr5`, `lr12` | `rules.sensitive_nets`, `rules.pour_gap`, `rules.keepout_ring`, `rules.decoupling` | the AFE's channel tables stay in the AFE layer and are turned into these lists there | moved (branch `pcbkit-step3`, stacked on `pcbkit-step2`) |
| 4 | `rules.py`: `lr11`'s outline, designator, test-point and legibility terms, `designator_findings`, `one_label_pairs`, `foreign_labels` | `rules.blocks`, `rules.designators`, `rules.test_points`, `outlines` | the two-way test joins `designators` (today it lives only in the team scripts) | moved (branch `pcbkit-step4`) |
| 5 | `kicad/labels/place3.py` (afe1-labels), `silk_labels/place_silk.py` and `stackcheck.py` (silk-labels-afe2) | `labels` | one placer for both boards, the better of the two where they differ, with both boards' approved silk as its regression fixtures | moved |
| 6 | `pcbtools/pinlabels.py`, `fab.py`, `docker/pcb/ibom.sh`, `kicad/topfill/render.py`, `kicad/labels/prove.py`, `silk_labels/movehash.py` | `pinlabels`, `fab`, `ibom`, `render`, `proof` | the two proof scripts become one | moved |
| 7 | the AFE's importers of `pcbtools.boardio`, `geom`, `shapes` | `pcbkit` directly | every importer reads with `pcbkit.board` and passes `pcbtools.frame.FRAME` (50, 150) to `read_board`, `read_board_retry`, `to_frame` and `from_frame`; `pcbtools/boardio.py`, `geom.py` and `shapes.py` are deleted, and so are the AFE copies of `test_geom.py`, `mutate_geom.py` and their golden (`pcbkit/tests/test_geom.py` is the same file, and every one of `mutate_geom.py`'s 22 mutants is in `mutate_kit.py`). The AFE's arrays are now the full ones, later fields read; its recorded caches stay the first release's. Kept, because they carry AFE constants: `pcbtools/frame.py` (`FRAME`), `pcbtools/pinlabels.py` (the frame default, `PIN_TABLE_ROOT`, the ink file, the label UUID namespace) and `pcbtools/fab.py` (`STEM`, `IDENT`, `design_ident`, `ZIP_NAME`) | moved |

What stays in `afe-proto/pcbtools`: `lr2` (signal flow through the channels), `lr4`'s inverting-node and isolation-resistor terms,
`lr6` (the supply stars), `lr7`, `lr8` (the VREF Kelvin branches), `lr9`, the board configurations and their arms, the gate-3
tables, the schematic and SPICE tools, and `cap.py` and `planar.py`.
