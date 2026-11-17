# Moving the general tools out of afe-proto/pcbtools

One module per step. A step lands only when the AFE quick tier passes unchanged with the AFE code importing the moved module
from here, and the module's own tests in `hardware/pcbkit/tests` pass on synthetic boards. The AFE's figures (gate-3 rows,
the fab manifests, silkread counts) do not move in any step; a step that moves one is a behaviour change, not a move.

| step | from (afe-proto) | to (pcbkit) | what changes on the way | status |
|---|---|---|---|---|
| 1 | `pcbtools/boardio.py`, `geom.py`, `shapes.py` | `board`, `geom` | the Due frame (`OX, OY`) becomes `FRAME` in the configuration | to do |
| 2 | `pcbtools/rules.py`: `lr1`, `bottom_runs`, `bottom_crossings` | `rules.ground_plane`, `rules.bottom_hops` | fences and sensitive nets come from the configuration by name | to do |
| 3 | `rules.py`: `lr3`, `lr4`'s via and length terms, `pour_gaps`, `lr5`, `lr12` | `rules.sensitive_nets`, `rules.pour_gap`, `rules.keepout_ring`, `rules.decoupling` | the AFE's channel tables stay in the AFE layer and are turned into these lists there | to do |
| 4 | `rules.py`: `lr11`'s outline, designator, test-point and legibility terms, `designator_findings`, `one_label_pairs`, `foreign_labels` | `rules.blocks`, `rules.designators`, `rules.test_points`, `outlines` | the two-way test joins `designators` (today it lives only in the team scripts) | to do |
| 5 | `kicad/labels/place3.py` (afe1-labels), `silk_labels/place_silk.py` and `stackcheck.py` (silk-labels-afe2) | `labels` | one placer for both boards, the better of the two where they differ, with both boards' approved silk as its regression fixtures | to do |
| 6 | `pcbtools/pinlabels.py`, `fab.py`, `docker/pcb/ibom.sh`, `kicad/topfill/render.py`, `kicad/labels/prove.py`, `silk_labels/movehash.py` | `pinlabels`, `fab`, `ibom`, `render`, `proof` | the two proof scripts become one | to do |

What stays in `afe-proto/pcbtools`: `lr2` (signal flow through the channels), `lr4`'s inverting-node and isolation-resistor terms,
`lr6` (the supply stars), `lr7`, `lr8` (the VREF Kelvin branches), `lr9`, the board configurations and their arms, the gate-3
tables, the schematic and SPICE tools, and `cap.py` and `planar.py`.
