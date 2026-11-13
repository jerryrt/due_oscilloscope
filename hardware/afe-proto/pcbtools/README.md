# pcbtools (stage 1: I/O, geometry kernels, fixtures)

Interface: `ARRAYS.md`. Stage 1 delivers `boardio.py` (BoardArrays, `read_board`, `to_due`/`from_due`, npz cache), `geom.py`
(numpy/scipy kernels) and the frozen fixtures and goldens the rules (stage 2) are checked against.

## Environment

One interpreter with pcbnew (KiCad 10), numpy, scipy and pytest. Nothing in the package names a host path. Variables:

| variable | used by | meaning |
|---|---|---|
| `PCB_PYTHON` | `tests/run_pcbnew_tests.sh` | that interpreter (default `python3`) |
| `CAPPED` | the runner, `tests/golden_capture/*.py` | optional memory-cap wrapper (`capped.sh -m MEM -t SEC cmd`); empty = uncapped |
| `OLD_TOOLS_DIR` | `tests/golden_capture/capture_old.py`, `old_counts.py` | the reference tools; default: the frozen copy in `tests/fixtures/v2-8a1f7ac/tools` |
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
    tests/golden/MANIFEST.sha256 (hash of every golden), update_manifest.py, *_mutation_result.txt
    tests/golden_capture/        the scripts that WRITE goldens (capture_old, run_old_tools, bench_*, reparse_figures); never collected
    # regenerate arrays:  python -m pcbtools.boardio BOARD.kicad_pcb OUT.npz   (run from hardware/afe-proto)

## Conventions that bite

* `s_idx`/`a_idx`/`v_idx` index the whole `board.GetTracks()` enumeration (segments, arcs and vias together).
* `p_pin` can repeat within a footprint (shield or thermal pads): `pad_index` returns the first, `pad_indices` all.
  The old loader keyed pads by (ref, pin), last wins; the equivalence tests reproduce that.
* Zones export filled outlines and their holes as rings (`z_ring_off`, `z_vert_off`, `z_ring_hole`); a pour as KiCad 10 returns it on these boards is already fractured (HoleCount 0 on every fixture zone: a cut-out is a slit in the outline), so even-odd on the outline ring is complete; real hole rings are exported when KiCad returns them; layer codes 0 F.Cu, 1 B.Cu, 2 inner.
* `seg_seg_dist` refuses a matrix over 256 MB; use `within` / `min_dist` for large inputs.

# Stage 2: the rules, the fence rule, the command line

    pcbtools/boards/v2.py        BoardConfig of the v2 board (module-level names); the ONE loader `_load_sources()` imports design.py,
                                 floorplan.py, layout.py from tests/fixtures/v2-8a1f7ac/ by path relative to the package
    pcbtools/boards/v2_arms.py   ARMS = [(name, rule, arm(b, cfg) -> BoardArrays)]: 28 numpy mutation arms
    pcbtools/rules.py            lr1 lr2 lr3 lr4 lr4_inv lr12 lr5 lr6 lr7 lr8 lr9 lr11, `ROWS` in the old print order
    pcbtools/drc.py              LR-10: kicad-cli DRC wrapper (the only KiCad-dependent rule), and its arm
    pcbtools/fence.py            owner_of, inside_masks, violations, check_fence (the old fence_check on arrays)
    pcbtools/mutate.py           the numpy edits the arms are written in (add_segment, add_via, move_footprint, ...)
    pcbtools/check.py            python -m pcbtools.check BOARD.kicad_pcb|CACHE.npz --config v2 [--mutate] [--rows LR-1 ...] [--drc]

## Rules

`rule(b: BoardArrays, cfg) -> Result(ok, detail, figures)`. `cfg` is a config module (`pcbtools.boards.v2`) or any object with
the same upper-case names, so a test builds a config from plain values (`tests/pcbtools/synth.py: cfg(**overrides)`).
`detail` reproduces the old tool's printed line; `figures` holds floats (lengths, distances, counts) under stable keys.
No rule loops over segments: segment tests are `geom` kernels, connectivity is `geom.connected_components`.

What the old tool treated as "touching", kept exactly (`rules.pieces`, used by LR-6 and LR-8): two top tracks touch when an end
of one is within 0.05 mm of the other's centre line; a track and a via when the via centre is within 0.05 mm of the centre
line; a track and a pad when the centre line enters the pad's box grown by 0.02 mm; two vias within 0.05 mm; a via and a pad
when the via centre is in the pad's box grown by 0.02 mm; two pads never, except the `BRIDGE_PADS` pairs; widths are not used;
the star pads (LR-6) and source pads (LR-8) are removed before connecting. A pad is identified by (ref, pin) and the last pad of
a repeated pin wins, as in the old loader. The top pour test of LR-4 is a point-in-ring test of the zone arrays, hole-aware
(`geom.points_in_polys(..., hole=z_ring_hole)`); the old HitTestFilledArea's 0.02 mm accuracy is not reproduced and no verdict
depends on it. KiCad returns these pours already fractured (a cut-out is a slit in the outline, `HoleCount` 0 on every fixture
zone), so even-odd on the outline ring is complete; real hole rings are exported and honoured when KiCad returns them.

LR-8 needs `route.KELVIN['VREF']`, which lives in a module that imports pcbnew; its two lists are in `boards/v2.py`
(`VREF_SOURCE`, `VREF_BRANCHES`, from commit 8a1f7ac) and are the one copy of that data outside route.py.

## Differences from the old tool (each tested in tests/pcbtools/test_rules_equivalence.py)

| where | old | new | effect |
|---|---|---|---|
| segment-in-box, segment-near-segment (LR-1, 3, 9, pieces) | any sample point every 0.05-0.5 mm | exact test | none on the 7 fixtures |
| LR-5 distance figure | nearest sample point (0.5 mm step) | exact distance to the box | figure can only be smaller; verdicts equal |
| printed 0.1 mm figures sitting on x.x5 | float sum of nm integers | float sum of 1e-6 rounded coordinates | 5 rows print 1.4 for 1.5 or 1.8 for 1.9 (CH2_OUT 1.45 on four boards, DAC0 1.85 on awg): the value is the same, the rounding of an exact half differs |
| LR-4 pour-near-FB arm | a point list `extra_top_gnd` | a top GND track (and an added zone arm for the pour test) | arm detail says `GND track`, not `added ground copper` |
| LR-4 pour test | HitTestFilledArea(accuracy 0.02) | even-odd, hole-aware, no accuracy | none |
| LR-6 missing star pads message | set iteration order | config list order | order only (never printed on a passing board) |
| arcs | read as chords | not on any fixture; `a_*` arrays are ignored by the rules (fence compares arc ends) | none |

## Fence rule (pcbtools/fence.py)

    owner_of(ref, cfg) -> str | None
    inside_masks(b, block, cfg) -> (seg_mask, arc_mask, via_mask)        wholly inside ONE fence of the block (closed, 1e-6 mm)
    violations(base, blk, block, cfg) -> list[str]                       the old tool's lines
    check_fence(base, blk, block, cfg) -> FenceResult(violations, foreign_moved, outside_changed_idx, ok)

`outside_changed_idx` is `{'base': {'s_idx','a_idx','v_idx'}, 'blk': {...}}`: the KiCad track enumeration indices of the items
outside the block's fences that exist in one board and not in the other (what an editor removes or restores). `cfg` names:
`FENCES`, `HUNDREDS`, `OWNER_OVERRIDE`, `TOL_MM`. Item keys print as the old tool printed them (F.Cu 0, B.Cu 2; part sides 0 / 31).

## Tests

    python -m pytest -c tests/pytest.ini -m "not pcbnew and not ngspice" tests     # numpy tier
    PCB_PYTHON=python tests/run_pcbnew_tests.sh                                     # pcbnew tier, prints 'attempt N of 3'
    python tests/pcbtools/mutate_rules.py                                           # mutation proof of the rules and fence

`test_rules_synthetic.py` (hand-built boards, exact figures, both sides of every limit), `test_fence.py`, `test_rules_equivalence.py`
(every rule x every board against the old tool's golden; arms against the old `--mutate` output; fence against fence_check),
`test_rules_live.py` (pcbnew: the live read gives the same rows; LR-10 through kicad-cli against the old DRC rows).
The pcbnew tier prints every start-up retry; a retry is a finding, not a cost.
Under a memory cap: `capped.sh -m 3G -t 300 <command>`; never more than two heavy jobs at once.

# Stage 3: golden protection, the frozen old tools, the capacitance solver

## Goldens cannot change silently

`tests/golden/MANIFEST.sha256` (sha256sum format) lists every file under `tests/golden/` except itself, and
`tests/pcbtools/test_golden_manifest.py` fails when a golden differs, is missing, or is on disk without being listed. To change a
golden on purpose: `python tests/golden/update_manifest.py --i-changed-a-golden`, and commit the manifest with it (the script refuses
without the flag). Scripts that write goldens live in `tests/golden_capture/`, outside the collected tree: each has `main()` behind
`__main__`, writes only to `--out DIR` (default `pcbtools/.scratch/golden_out/`), and writes into `tests/golden/v2-8a1f7ac/` only
with `--into-golden`, printing the manifest reminder. `test_golden_capture.py` imports every script in its own subprocess and
checks the golden folder is untouched (and that a script which writes at import would be caught).

## The old tools, frozen

`tests/fixtures/v2-8a1f7ac/tools/` holds lr_check, fence_check, cap and what they import, byte for byte from v2-layout-wip 8a1f7ac
(SOURCE.md). `python tests/golden_capture/run_old_tools.py --out DIR` runs them on the fixture boards and writes the raw text
(`<fixture>.<tool>.raw.txt`); this is what the container run uses to re-take the goldens of record. Run them with `-I -B`.
Checked against the committed goldens on this host: 11 of 12 raw outputs are byte-identical; the twelfth (awg `lr_check`) differs
only in the order of two keys of the LR-10 dict, which the old tool does not fix (kicad-cli's report order).

## pcbtools/cap.py

3-D finite-difference capacitance on a window of the board, numpy/scipy only (arrays in, floats out; see the module docstring for
the model). `pair_caps`, `self_cap`, `report(b, cfg)` (the old tool's whole output; `cfg.CAP_PAIRS`, `cfg.CAP_SELF` in
`boards/v2.py`), `python -m pcbtools.cap BOARD|NPZ|selftest`. Rasterisation is ragged vectorised arithmetic, the operator is one CSR
matrix per scenario, solved by scipy CG with a Jacobi preconditioner (relative residual 1e-6, the old tool's). Chosen by measurement (host,
scratch scripts): Jacobi halves the iterations (557 -> 278 on the 1 M-cell NP window, 6 s -> 3-4 s per solve); on the N-N window a
direct solve (SuperLU) took 0.48 s at 19 k unknowns against 0.1 s for plain CG and had not finished after the 100 s cap at 158 k
(CG 1.1 s); an ILU preconditioner (spilu) made CG take 23 000 iterations on 2 k unknowns and was dropped. Coordinates are
rounded to a nanometre in KiCad mm before rasterising so every cell decision equals the old tool's (a 0.2 mm track on a 0.1 mm grid
puts cell centres exactly on its edge). `python tests/pcbtools/mutate_cap.py` is the mutation proof.


# Write path and generators (kvm_01): editor, sexpr, schematic, build, renumber, floorplan, merge

Every module reads from or writes to plain Python values; none names a host path, and none keeps module-level state (a
board object kept alive in a module is what ran the shared machine out of memory once).

| module | what it does | checked against |
|---|---|---|
| `editor.py` | `with edit(path, out=None) as e:` the ONE place a board is changed: `move`, `set_ref`, `set_ref_pose`, `add_text`, `add_footprint_from`, `remove_footprint`, `add_tracks(net, layer, x0, y0, x1, y1, w)` and `add_vias(net, x, y, dia, drill)` (array arguments, grouped by the caller), `remove_tracks`/`remove_vias(idx)` by the `*_idx` of `BoardArrays`, `fill_zones`, `pour`. Saved once on exit | read-back with `boardio` after each edit; repeated edits in one process (the SWIG ownership traps below) |
| `sexpr.py` | tokenizer and iterative reader/writer of KiCad s-expressions (`parse`, `dump`, `find`, `first`, `Q`), symmetric escapes | round trip on every fixture file; atom count; a slow budget step |
| `schematic.py` | `write_all(parts, cfg, out_dir)`: the symbol library, the sheets and the project from `design.PARTS` | byte-identical to the old `build_sch.py` on v1 |
| `build.py` | `build_board(parts, cfg, place, nets, out, legalise_overlaps, anchors)`; `legalise` pushes overlapping courtyards apart (anchors never move); `overlaps` is one array pass | same parts, pads, nets, outline and positions as the old `build_pcb.py` on v1; two builds are byte-identical |
| `renumber.py` | `build_map`, `rewrite` (whole-word, single pass), `unmapped` | the v1 renumber map |
| `floorplan.py` | `table_md`, `svg`, `validate` from the floorplan data | the v1 contract table |
| `merge.py` | `merge(base, {block: board}, out, cfg)`; `python -m pcbtools.merge --board v1 --base B --out O BLOCK=PATH ...` (exit 0 all merged, 1 a block refused, 2 usage) | the old `merge_blocks.py`: same merged board, same refusals |

`boards/v1.py` is the v1 BoardConfig (fences, hundreds map, tolerance) and `boards/v1_build.py` the one place that turns the frozen
old design, layout and build constants into the `cfg` objects of `schematic.write_all` and `build_board`; the equivalence tests
and the bench steps both use it.

## Things that bite in the write path

- **pcbnew SWIG ownership.** `board.Remove(item)` hands the item to Python, which frees it without its destructor and a later
  `LoadBoard` then returns a bare `SwigPyObject`: the editor uses `RemoveNative`, and every item it `Add`s gets `thisown = False`.
- **A via that lands on a pad takes that pad's net** when the board is saved and read back, whatever net was asked for.
- **pcbnew writes `<board>.kicad_prl` (and a lock) beside any board it loads**: run it on a copy, never on a fixture. A test fails
  if one appears in `tests/fixtures`.
- **The old tools write next to themselves**, so they run on a throw-away copy of the frozen fixture
  (`tests/golden/v1-34b2e51-image/run_old.sh`).

## Goldens of record, v1

`tests/golden/v1-34b2e51-image/`: each old v1 tool's output, taken inside the pinned PCB image and stamped with its digest in
`STAMP.json`; every output was produced twice and compared byte for byte. The figures in `STAMP.json` are single runs; the bench
takes the medians. The five old tools and the two new build steps are in `tests/bench_steps.json`.
