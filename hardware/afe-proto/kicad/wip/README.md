WIP, not main: v1 layout restart, merge 1 (SCOPE + POWER + AWG; REFCAL not merged, still on its own board).
- v1_merge1.kicad_pcb: base (R520, VNEG_O) + the three blocks + a bottom GND pour; v1_merge1.rows.txt: `pcbtools.check --config v1 --drc` (rows, then the --mutate arms).
- Made with whatif/blocks scripts (add_r520.py, vneg_o.py, port_awg.py) and `python -m pcbtools.merge --board v1 --carry-text`, PCBTOOLS_V1_SOURCE=kicad/.
- gate3-notes.md: the standing rules, the recorded deviations and the open items.
- v1_merge3 (current): merge 2 with R109 moved north out of REFCAL's fence (62.8, 36.7) and the copper-to-edge setting 0.45 mm (v1_merge3.kicad_pro; the three edge items of merge 2 are gone). Its rows file shows `lib_footprint_issues: 4`: that is the check's DRC copying the board to a temp folder without the library tables; `kicad-cli pcb drc` run beside fp-lib-table here reports none.
- fp-lib-table / sym-lib-table here point to ../lib (kicad/lib).
- v1_merge4 (current): merge 3 with the 5 mm south overhang and the keep-out band (outline from boards/v1.py: BOARD_RECT, KEEPOUTS); its rows: the 2 silk_edge_clearance items are gone, nothing else changed.
