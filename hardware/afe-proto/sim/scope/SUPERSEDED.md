# SUPERSEDED (2026-11-13)

This directory's default study (`run.py`, variant `hz`: the 1 Mohm compensated divider with R1 = R3 = 760k, R2 = 330k, an OPA354 follower,
BAT54S pin clamp, Vmid sense filter; golden `tests/golden_sim/v1-scope-hz`) is NOT the scope channel on the v1 board. The board has the
TPH2502 dual with 770k / 800k / 330k to the REF3030E, Rnp 680, Cnp 10p, Riso 22 and a BAV99 clamp (kicad/design.py).

The v1 study is `v1/sim/` (README there): v2's scope and AWG harnesses with the v1 board's values and the extracted strays, with a
spicecmp proof against v1's schematic. Quote its figures, not this directory's, for v1. The old study stays reproducible and its golden
still guards the shared netlib plumbing; nothing here is deleted.
