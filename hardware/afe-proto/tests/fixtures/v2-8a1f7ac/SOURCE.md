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
