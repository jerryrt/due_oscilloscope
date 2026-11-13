# v2 layout WIP (not for main)

power/        power4_step_<cap>.kicad_pcb (one per moved cap, in the order C403 C402 C401 C404 C407 C408 C406), power4_final, power3_final (baseline)
v2-blocks/    inputs copied from the v2 worktree (BASE, AWG/REFCAL/SCOPE-east finals) and power/ tooling; power/scratch/try.sh = move + reroute + check
v2-integration/  integrate.sh (merge, corridors, DRC, verify) with POWER_BOARD=...; figs.py, fence4.py
integrated/   afe-v2-integrated.kicad_pcb (power4), ref_power3/ (same pipeline with power3_final), render/, drc_full.json
Run everything in the image: docker/pcb/run.sh -m 3G -t 600 bash /work/hardware/afe-proto/v2/layout/v2-integration/integrate.sh

LR-11 on the integrated board (`--config v2_layout`, `pcbtools/boards/v2_layout.py`):
outlines.py            the one table of block outlines (Due mm) the silk is drawn from and the config reads, with SHARED_PARTS (U101 is held to CH1)
outlines_from_silk.py  recovers the outlines actually drawn on a board's F.Silkscreen (dashed or broken sides included); `--check` compares them with the table
draw_outlines.py       adds the table's rectangles the silk lacks (the AWG BNC outline); silk only
place_designators.py   silk-only designator placement (moves each Reference text; copper, parts, pads untouched); run it in the image
refine_designators.py  second silk-only pass: turns/moves labels so none reads as one (cfg.DESIGNATOR_GAP_ONE_LABEL, same baseline) and none sits in a foreign outline; run in the image
refill_zones.py        refills every zone with pcbnew so the fills honour the project's min_copper_edge_clearance (0.45); splices only the filled_polygon blocks into the board text; idempotent; run in the image
pinlabels (pcbtools/pinlabels.py)  the Due's own pin names beside each edge-row socket, on top silk in the bands (LR-11): python3 -m pcbtools.pinlabels BOARD --config v2_layout --write; --check and --list too. Names come from docs/due-header-table.md, sockets from EDGE_SOCKETS in boards/v2_layout.py
Both tools above are pure text editing except place_designators.py, which reads the board with pcbnew.
