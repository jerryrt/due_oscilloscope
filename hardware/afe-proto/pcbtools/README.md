# pcbtools (stage 1: I/O, geometry kernels, fixtures)

Interface: `ARRAYS.md`. Stage 1 delivers `boardio.py` (BoardArrays, `read_board`, `to_due`/`from_due`, npz cache), `geom.py`
(numpy/scipy kernels) and the frozen fixtures and goldens the rules (stage 2) are checked against.

## Environment

One interpreter with pcbnew (KiCad 10), numpy, scipy and pytest. Nothing in the package names a host path. Variables:

| variable | used by | meaning |
|---|---|---|
| `PCB_PYTHON` | `tests/run_pcbnew_tests.sh` | that interpreter (default `python3`) |
| `CAPPED` | the runner, `tests/golden/*.py` | optional memory-cap wrapper (`capped.sh -m MEM -t SEC cmd`); empty = uncapped |
| `OLD_TOOLS_DIR` | `tests/golden/capture_old.py`, `old_counts.py` | `v2/kicad` of the reference tools (v2-layout-wip 8a1f7ac) |
| `PCB_IMAGE_ID` | goldens and bench rows | container image id; null until the pinned image exists |
| `PCBTOOLS_EXPECT_PCBNEW=1` | `tests/conftest.py` | the environment claims pcbnew: missing pcbnew fails, the guard arms |

pcbtools reads no KiCad library or 3D path: a `.kicad_pcb` embeds its footprints. The fixture folder carries `fp-lib-table`
and `lib/` (`${KIPRJMOD}`-relative) for `kicad-cli` DRC, which is the reference tool's concern, not the package's.
Goldens recorded so far are labelled "working reference, host .venv-pcb"; they are to be re-taken in the image.

## Running the tests (from hardware/afe-proto)

    python -m pytest -m "not pcbnew" tests                 # pure numpy: geom, boardio containers, cached arrays vs goldens
    PCB_PYTHON=python tests/run_pcbnew_tests.sh            # pcbnew group + guard; retries a start-up segfault up to 3 times
    python tests/pcbtools/mutate_geom.py                   # mutation proof: each geom mutant must be caught

The pcbnew group skips with an explicit reason when pcbnew is missing, **fails** when `PCBTOOLS_EXPECT_PCBNEW=1`, and
`test_guard.py` (last) fails unless every pcbnew-marked test passed.

## Layout

    pcbtools/boardio.py  geom.py  boards/ (stage 2)
    tests/fixtures/v2-8a1f7ac/   frozen boards, design.py/floorplan.py/layout.py, SOURCE.md (do not edit)
    tests/fixtures/arrays/       cached BoardArrays (.npz) of each fixture, readable without pcbnew
    tests/golden/v2-8a1f7ac/     old-tool outputs (lr_check, --mutate, fence_check, cap, loader counts), old/new bench
    tests/golden/capture_old.py, bench_new.py, geom_mutation_result.txt
    # regenerate arrays:  python -m pcbtools.boardio BOARD.kicad_pcb OUT.npz   (run from hardware/afe-proto)

## Conventions that bite

* `s_idx`/`a_idx`/`v_idx` index the whole `board.GetTracks()` enumeration (segments, arcs and vias together).
* `p_pin` can repeat within a footprint (shield or thermal pads): `pad_index` returns the first, `pad_indices` all.
  The old loader keyed pads by (ref, pin), last wins; the equivalence tests reproduce that.
* Zones export filled outer rings only (no holes); layer codes 0 F.Cu, 1 B.Cu, 2 inner.
* `seg_seg_dist` refuses a matrix over 256 MB; use `within` / `min_dist` for large inputs.
