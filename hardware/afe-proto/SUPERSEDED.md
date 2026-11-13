# Files on main that the tooling now replaces

**Candidates for removal after review.** Nothing in this list has been
deleted: the landing adds the replacement and leaves the old file where
it is, so the review can compare them and the spec lead decides.

Every old tool is kept byte for byte as a frozen copy under
`tests/fixtures/` (the equivalence tests run it in the image and compare
its output with the new tool's), so removing the live copy loses
nothing the tests use. The equivalence is proved by the tests named in
the last column, which are in the same commit as this file (the tooling
commit, `hardware: land the AFE tools ...`); their goldens are under
`tests/golden/`.

| file on main | replaced by | proof |
|---|---|---|
| `kicad/build_sch.py` | `pcbtools/schematic.py` (`write_all`) | `tests/pcbtools/test_schematic.py`, frozen copy `tests/fixtures/v1-34b2e51/kicad/build_sch.py` |
| `kicad/build_pcb.py` | `pcbtools/build.py` + `pcbtools/boards/v1.py` | `tests/pcbtools/test_build.py`, `golden/v1-34b2e51-image/build_pcb.out` |
| `kicad/check.py` | `pcbtools/schematic_check.py` | `test_schematic_check.py`, `golden/v1-34b2e51-image/check_pcb.out` |
| `kicad/lr_check.py` | `pcbtools/rules.py` (`ROWS`) | `test_rules_equivalence.py`, `golden/v1-34b2e51-image/lr_check.out` |
| `kicad/pcb_dump.py` | `pcbtools/boardio.py` | `test_boardio.py` |
| `kicad/pcb_mutate.py` | `pcbtools/mutate.py`, `pcbtools/editor.py` | `test_editor.py` |
| `kicad/route.py` | `docker/pcb/freeroute.sh` + `pcbtools/editor.py` | `test_freerouting.py` (frozen copy `tests/fixtures/v2-8a1f7ac/tools/route.py`) |
| `kicad/sexpr.py` | `pcbtools/sexpr.py` | `test_sexpr.py` |
| `v2/kicad/build_sch.py` | `pcbtools/schematic.py` + `pcbtools/boards/v2_sch.py` | `test_v2_schematic.py`, `golden/v2-kicad-276a116/` |
| `v2/kicad/check.py` | `pcbtools/schematic_check.py` | `test_v2_schematic.py` |
| `v2/kicad/sexpr.py` | `pcbtools/sexpr.py` | `test_sexpr.py` |
| `v2/kicad/spicecmp.py` | `pcbtools/spicecmp.py` | `test_netlib_golden.py` |

Not superseded and left alone: `kicad/design.py`, `layout.py`,
`layout_view.py` and the v1 KiCad files (the v1 board is still being
finished), and everything under `whatif/` (frozen studies that the
simulation ports read).
