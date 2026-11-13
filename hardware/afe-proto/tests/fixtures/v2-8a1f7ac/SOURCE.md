# Frozen fixtures: v2-layout-wip 8a1f7ac

- source branch: v2-layout-wip, commit 8a1f7ac ("hardware: drop the unused ground-via exemption")
- source worktree: /home/jerry/EE.Projects/due_oscilloscope_v2/hardware/afe-proto
- copy date: 2026-11-12
- boards (the files are untracked working-tree files in that worktree, not committed there; the name carries sha256[:8] of content):
  - v2-integrated-990d4b03 <- whatif/v2-integration/afe-v2-integrated.kicad_pcb (+ .kicad_pro)
  - v2-power3-7c838703   <- whatif/v2-blocks/power/power3_final.kicad_pcb (+ .kicad_pro)
  - v2-power-a5605a04    <- whatif/v2-blocks/power/power_final.kicad_pcb (+ .kicad_pro)
  - v2-refcal-326f141b   <- whatif/v2-blocks/refcal/refcal_final.kicad_pcb (+ .kicad_pro)
  - v2-awg-bc96e334      <- whatif/v2-blocks/awg/awg_final.kicad_pcb (+ .kicad_pro)
  - v2-scope2east-05ee441f <- whatif/v2-blocks/scope2/scope2_east_final.kicad_pcb (+ scope2_final_east.kicad_pro)
  - v2-BASE-056e1d03     <- whatif/v2-blocks/BASE.kicad_pcb (no .kicad_pro)
- fp-lib-table, lib/ <- v2/kicad/fp-lib-table, v2/kicad/lib/ (afe.pretty, afe.kicad_sym)
- design.py, floorplan.py, layout.py <- v2/kicad/ (design.py and layout.py import nothing; floorplan.py imports subprocess and pathlib only)
- goldens: tests/golden/v2-8a1f7ac/ captured with the reference tools at that commit (v2/kicad/lr_check.py, fence_check.py, cap.py)

frozen: do not edit; refresh by a new folder named after a new commit

## tools/ (the old tools, frozen with the boards)

- source: v2-layout-wip commit 8a1f7ac, original paths hardware/afe-proto/v2/kicad/{lr_check,fence_check,cap,route,design,floorplan,layout}.py and afe-v2.kicad_pro, copied byte for byte (2026-11-12)
- lr_check.py, fence_check.py, cap.py are the three tools; route.py (imported by lr_check for `route.KELVIN`), design.py, floorplan.py, layout.py are what they import. Nothing else is imported (route.py's other imports are heapq, math, numpy, pcbnew)
- they run from this folder with the fixture boards, which are passed on the command line: `python -I -B tools/lr_check.py v2-integrated-990d4b03.kicad_pcb`; each tool finds its sibling modules through its own folder (`HERE`), so nothing refers to the v2 worktree. Their default board (`afe-v2.kicad_pcb`) is not here: always pass a fixture board. `tools/afe-v2.kicad_pro` (v2/kicad/afe-v2.kicad_pro at 8a1f7ac, byte for byte; it differs from the integrated board's own .kicad_pro) is the project file the LR-10 arm of `lr_check.py --mutate` copies next to its mutated board
- design.py, floorplan.py and layout.py in tools/ are identical to the three copies one level up (tests/pcbtools/test_old_tools_frozen.py holds that)
- run them with `-B` / PYTHONDONTWRITEBYTECODE=1: this folder must stay free of bytecode
