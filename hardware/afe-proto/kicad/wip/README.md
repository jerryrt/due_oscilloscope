WIP, not main: v1 layout restart, merge 1 (SCOPE + POWER + AWG; REFCAL not merged, still on its own board).
- v1_merge1.kicad_pcb: base (R520, VNEG_O) + the three blocks + a bottom GND pour; v1_merge1.rows.txt: `pcbtools.check --config v1 --drc` (rows, then the --mutate arms).
- Made with whatif/blocks scripts (add_r520.py, vneg_o.py, port_awg.py) and `python -m pcbtools.merge --board v1 --carry-text`, PCBTOOLS_V1_SOURCE=kicad/.
- gate3-notes.md: the standing rules, the recorded deviations and the open items.
