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
* Zones export filled outlines and their holes as rings (`z_ring_off`, `z_vert_off`, `z_ring_hole`); a pour as KiCad 10 returns it on these boards is already fractured (HoleCount 0 on every fixture zone: a cut-out is a slit in the outline), so on these boards even-odd on the outline ring is complete. **The hole path is therefore proven only by the synthetic test** (`test_lr4_pour_is_hole_aware`, `test_a_zone_fill_joins_what_lies_in_it_on_its_layer_hole_aware`): no recorded board has a hole ring, and the code that honours one has never met a KiCad export of it (`HoleCount` > 0). Layer codes 0 F.Cu, 1 B.Cu, 2 inner.
* `seg_seg_dist` refuses a matrix over 256 MB; use `within` / `min_dist` for large inputs.

# Stage 2: the rules, the fence rule, the command line

    pcbtools/boards/v2.py        BoardConfig of the v2 board (module-level names); the ONE loader `_load_sources()` imports design.py,
                                 floorplan.py, layout.py from tests/fixtures/v2-8a1f7ac/ by path relative to the package
    pcbtools/boards/v2_arms.py   ARMS = [(name, rule, arm(b, cfg) -> BoardArrays)]: 28 numpy mutation arms
    pcbtools/rules.py            lr1 lr2 lr3 lr4 lr4_inv lr12 lr5 lr6 lr7 lr8 lr9 lr11, `ROWS` in the old print order
    pcbtools/drc.py              LR-10: kicad-cli DRC wrapper (the only KiCad-dependent rule), and its arm
    pcbtools/fence.py            owner_of, inside_masks, violations, check_fence (the old fence_check on arrays)
    pcbtools/mutate.py           the numpy edits the arms are written in (add_segment, add_via, move_footprint, ...)
    pcbtools/CONFIG_FIELDS.md    every board-config field, its shape and a v2 example; rules.py & co. hold NO ref or net literal
                                 (tests/pcbtools/test_no_board_literals.py)
    pcbtools/check.py            python -m pcbtools.check BOARD.kicad_pcb|CACHE.npz --config v2 [--mutate] [--rows LR-1 ...] [--drc | --no-drc]

## Rules

`rule(b: BoardArrays, cfg) -> Result(ok, detail, figures)`. `cfg` is a config module (`pcbtools.boards.v2`) or any object with
the same upper-case names, so a test builds a config from plain values (`tests/pcbtools/synth.py: cfg(**overrides)`).
`detail` reproduces the old tool's printed line; `figures` holds floats (lengths, distances, counts) under stable keys.
No rule loops over segments: segment tests are `geom` kernels, connectivity is `geom.connected_components`.

Connectivity (`rules.pieces`, used by LR-6 and LR-8) is the old tool's touch rules, exact, over the copper of one ELECTRICAL net:
the nets joined by 0 ohm bridge parts (`cfg.BRIDGES`) are one net (`rules.family`), the two pads of every bridge part are joined, and
copper is tracks on BOTH layers, vias, pads and the filled zones of the net's family. Two tracks of one layer touch when an end of
one is within 0.05 mm of the other's centre line (or 0.02 of an end); a track and a via when the via centre is within 0.05 mm of the
centre line (a via spans both layers); a track and a pad when the centre line enters the pad's box grown by 0.02 mm AND the pad
has the track's layer; two vias within 0.05 mm; a via and a pad when the via centre is in the pad's box grown by 0.02 mm; two pads
never, except bridge pairs; a zone fill (one node per outline ring, even-odd, hole-aware) holds the items with a point in it on its
layer; widths are not used. LR-6 and LR-8 also require REACHABILITY: every present consumer group (LR-6) and every branch (LR-8)
reaches a star / source pad through that copper, so an unrouted net no longer passes; a group or branch none of whose parts is on
the board is "absent", not unreachable. A pad is identified by (ref, pin) and the last pad of a repeated pin wins, as in the old
loader. LR-4's top-pour test is the exact distance from the pour's polygon edges (outline and hole rings) to the node's copper:
tracks as capsules, pads by size and rotation (`pcbtools.shapes`; a rounded-rectangle pad is its circumscribed rectangle, which
overstates the pad by at most its corner radius: conservative), 0 where the node's copper lies on the fill; the figure
`pour_gap_<node>_mm` is that distance. **Which nodes** LR-4's pour sentence covers is a decision recorded in `boards/v2.py` and `CONFIG_FIELDS.md`: the inverting node is the
shortest trace of the stage and the top ground pour is kept back from it, which is an inverting input with gain resistors, `/AWG_FB`
(`POUR_NODES`). The first port judged `INV_NODES` (`/CH1_N`, `/CH2_N` too), the set of the old no-via rule, and that was wrong for the
pour rule: those are divider nodes, governed by LR-3 (guarded by grounded copper, so pour near them is wanted; LR-3's test is the
extracted capacitance, `cap.report`'s N self lines and N-N), and a follower's inverting pin is on its output `/CH1_OUT`, `/CH2_OUT`
(`POUR_INFO_NODES`), covered by the capacitance budget behind it: reported in the figures, not judged. LR-5 is measured from the copper EDGE (a track's half width, a pad's extent) to the
generator's courtyard.

LR-8 needs `route.KELVIN['VREF']`, which lives in a module that imports pcbnew; its two lists are in `boards/v2.py`
(`VREF_SOURCE`, `VREF_BRANCHES` as pad lists, from commit 8a1f7ac) and are the one copy of that data outside route.py.

## Differences from the old tool (each tested in tests/pcbtools/test_rules_equivalence.py)

| where | old | new | effect |
|---|---|---|---|
| segment-in-box, segment-near-segment (LR-1, 3, 9, pieces) | any sample point every 0.05-0.5 mm | exact test | none on the 7 fixtures |
| LR-5 distance figure | nearest sample point (0.5 mm step) | exact distance to the box | figure can only be smaller; verdicts equal |
| printed 0.1 mm figures sitting on x.x5 | float sum of nm integers | float sum of 1e-6 rounded coordinates | 5 rows print 1.4 for 1.5 or 1.8 for 1.9 (CH2_OUT 1.45 on four boards, DAC0 1.85 on awg): the value is the same, the rounding of an exact half differs |
| LR-4 pour-near-FB arm | a point list `extra_top_gnd` | a top GND track (and an added zone arm for the pour test) | arm detail says `GND track`, not `added ground copper` |
| LR-4 pour test | HitTestFilledArea(accuracy 0.02) at 4 axial probes 0.5 mm from pad centres | exact edge-to-edge distance, all pour edges | every fixture fails LR-4 now (finding 9, `tests/pcbtools/known_improvements.py`) |
| LR-6, LR-8 | nets taken one by one, top copper only; unrouted passed | bridge-joined nets, both layers and zones, reachability | vacuous passes become verdicts (findings 1-3) |
| LR-1 | first bottom GND zone only; runs joined end to end | every bottom zone; T and crossing joins | findings 4, 5 |
| `--mutate` | an arm on a rule that already failed counted as caught | NOT TESTABLE, exit 1 | finding 6 |
| `check` without LR-10 | ALL PASS | `LR-10 NOT RUN`, exit 1 (`--no-drc` to skip on purpose) | finding 8 |
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
`boards/v2.py`; the report's first five lines are the old tool's, followed by one self-capacitance line per further `CAP_SELF` net), `python -m pcbtools.cap BOARD|NPZ|selftest`. Rasterisation is ragged vectorised arithmetic, the operator is one CSR
matrix per scenario, solved by scipy CG with a Jacobi preconditioner (relative residual 1e-6, the old tool's). Chosen by measurement (host,
scratch scripts): Jacobi halves the iterations (557 -> 278 on the 1 M-cell NP window, 6 s -> 3-4 s per solve); on the N-N window a
direct solve (SuperLU) took 0.48 s at 19 k unknowns against 0.1 s for plain CG and had not finished after the 100 s cap at 158 k
(CG 1.1 s); an ILU preconditioner (spilu) made CG take 23 000 iterations on 2 k unknowns and was dropped. Coordinates are
rounded to a nanometre in KiCad mm before rasterising so every cell decision equals the old tool's (a 0.2 mm track on a 0.1 mm grid
puts cell centres exactly on its edge). `python tests/pcbtools/mutate_cap.py` is the mutation proof.

**Grid convergence** (`report(b, cfg, converge=True)`, `python -m pcbtools.cap BOARD|NPZ --converge`; `converge_pair`, `converge_self`,
`extrapolate`). The single-cell-size figures above are not converged (about 9 % apart between 0.2 and 0.1 mm for the pour figures), so
each figure can also be solved at 0.2, 0.1 and 0.05 mm and Richardson-extrapolated: the observed order is `p = log2((C1 - C2) /
(C2 - C3))`, and only a strictly monotone sequence with 0.5 <= p <= 2.5 is extrapolated (`C0 = C3 - (C2 - C3) / (2^p - 1)`,
uncertainty = how far that moved the finest value); otherwise the finest value stands, the full spread is its uncertainty and the status
reads "not converging monotonically". Three identical values are converged with uncertainty 0. The five old report lines are unchanged;
the converged lines are extra output, and self capacitance is marked *not validated against a field solver*. **The finest level does not
fit the window**: a 0.05 mm cell makes 114 cells in z, so MAX_CELLS = 3,000,000 (about 530 B per cell, 1.5-1.7 GB peak, measured)
allows 26 k cells in x-y. The step lowers the window pad in 0.25 mm steps until it fits (`pad_used` against `pad_requested`, the same
window at all three levels so that only the cell size varies), refuses with `GridTooLarge` if even pad 0 does not fit, and reports
`pad_effect` (C at the requested pad minus C at the used pad, at 0.2 mm) and `extrapolated_padcorrected`. On the v2 integrated
board the used pads are 0.5 (N-N), 1.0 (NP-NP, AWG_FB) and 2.25 mm (CH1_N, CH2_N) against 3.0 requested, and the pad effect is
not small (CH2_N with pour: -0.043 pF at 0.2 mm), so read the `extrapolated_padcorrected` figure, not the raw one, next to a
full-window number. The measured table is `cap_converged_v2_integrated.json` (image digest, wall time and peak RSS per run); most
sequences are *not* monotone, which is the finding: at these cell sizes a 0.2 mm track and the 0.3 mm pour keep-back (`round(0.3 / h)`
cells: 2 at 0.2 mm, i.e. 0.4 mm) change by whole cells between levels, so the figures carry a spread, not a converged limit.
`mutate_cap.py --converge-only` is the mutation proof of the extrapolation and the guard.


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
| `schematic_rows.py` | the rows the v2 schematic needed and v1 did not run (E1-E4 NC pins, single-pin nets, footprints and LCSC, datasheet pin names; the numbering, bridge and header rows; the netlist-comparison row) on a `Project` read from KiCad's netlist, the resistor-chain helpers, and `FlipArm`/`flip_row`: an arm is caught only when a row goes from PASS on the unchanged project to FAIL on the changed one, and a row that already fails on the clean board is `NOT TESTABLE` | the old v2 `check.py` rows, verdict and text, in `tests/golden/v2-kicad-276a116/check.raw.txt` |
| `spicecmp.py` | a block of the schematic against a study's SPICE netlist: both sides reduced by rules the board's config lists (each with its reason), then a colour refinement over the element/net graph | the old v2 `spicecmp.py` through the rows above |

`boards/v1.py` is the v1 BoardConfig: the fences and the hundreds map, the build data the old build scripts kept as constants (title,
block titles, headers, BNCs, model overrides, ...) with `sch_cfg()`, `pcb_cfg()` and `pcb_place()` that make the `cfg` objects of
`schematic.write_all` and `build_board`, and the names the checks and their arms read. The equivalence tests and the bench steps use it.
`boards/v2_sch.py` and `boards/v2_checks.py` are the v2 SCHEMATIC: the project's constants and `sch_cfg()` (`v2_sch`), and the
rows, arms and config the generic rows read (`v2_checks`, which is itself the config namespace). `design.py` stays in
`hardware/afe-proto/v2/kicad` as the board's source data; `v2_sch._load_design()` is the one place that knows where. Commands
(from `hardware/afe-proto`; `schematic_check`'s CLI takes a board by name and runs S/P rows, and v2 has no PCB yet, so v2's CLI is its own):

    python -m pcbtools.boards.v2_checks [--project DIR] [--arms]    the old check.py rows (and its 24 arms with --arms)
    python -m pcbtools.boards.v2_checks --build OUT                  write the project, then kicad-cli sch upgrade

`afe-v2.kicad_sch`, the tables and `lib/afe.kicad_sym` are byte-identical to the old `build_sch.py`'s output; the project file is
too, and the COMMITTED `afe-v2.kicad_pro` is stale (see the equivalence notes in `tests/golden/v2-kicad-276a116/STAMP.json`).
The footprint library `lib/afe.pretty` is hand-kept and is not generated.
`schematic_check.py` is the old `check.py`: rows S1-S4 (ERC, netlist, symbols, BOM) and P1-P3 (pad nets, DRC with parity,
outline and header pins) with their mutation arms, `python -m pcbtools.schematic_check --board v1 --project DIR --pcb --arms`; its
header lists what a board config provides. Verdicts and details equal the old rows in `tests/golden/v1-34b2e51-image/check_pcb.out`.

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

## `planar.py`: can this block be routed on one layer without a crossing?

**Status: an advisory screen, not a gate; nobody is required to run it.** What it showed: *non-planar is a reason to expect a
bridge; planar promises nothing.* It also **disagrees with the hand-found v1 REFCAL crossing** (under the guessed leg order it
suggests TAP3, not SNS_B). A geometric version is deliberately not built: the router flow is the better investment.

Crossings used to be found only while routing. `planar.check(block_nets, pads, rotation, boundary, protected)` answers before:
planar or not, the fewest nets that must be bridged (a 0R 0603 or a hop), which net to bridge (never one that matches
`protected`: ADC lines, divider nodes, VREF branches, `boards/planar_v2.PROTECTED_NETS`), and which nets it crosses. The planarity
test is **networkx** (`nx.check_planarity`, in `requirements-pcb.txt`; the r4 image carries it, the r3 image does not, so the tests
skip with a reason there and **fail** under `PCBTOOLS_REQUIRE_NETWORKX=1`). What `planar.py` owns is the graph:

- every net is a hub joined to its pads and to its fence edge points; GND is the bottom plane and is not a net;
- a part body is a wall (its pads in pin order as a cycle, plus a hub so nothing can be inside it), a row of pins a chain, a
  part in `passable` (the 0R bridges) nothing; `body='wall'` is the strict construction, `body='auto'` (what `from_board` uses)
  reads the pad geometry: two pads, or pads further apart than `pass_pitch` (1.5 mm), are passable, one or two rows are chains
  (a track runs under a SOIC and between 0603 pads), anything else a wall; `body_overrides` names parts by hand;
- the fence is a wheel: the edge points in order along the boundary, joined to an outer hub;
- optional `roots`/`branches`/`ordered_branches` star a net at a pad (LR-8's Kelvin legs) with its legs in a given order.

**Minimum crossings** = the fewest nets whose removal makes the graph planar, exact by a bounded search (a minimal conflict from
the Kuratowski certificate and a deletion filter; every solution removes one of its nets; iterative deepening to `max_k` 4; past
that, or past the node budget, a greedy bound and `Result.exact` False). `crossings` pairs a removed net with the nets of its
conflict (K3,3 gives all eight partners; a three-way conflict is not a pair). `bridge_plans[net]` is one split of that net's
terminals into two segments that makes the block planar, or None (more than one bridge, or a rooted net).

`from_board(b, cfg, block)` reads a BoardArrays: the block's pads (`fence.owner_of`), the edge points and, with no `edge_points`
given, **the as-built contract**: each net is split into the pieces of top copper it has inside the fence (a net that leaves and
re-enters through a corridor is two pieces: one hub joining them inside would claim copper that is outside) and the edge points
are where tracks cross the fence boundary (rectangles of one block nearer than 3.5 mm are one region, ordered by angle).
`merge_bridges=True` removes the bridge parts and joins their nets. With `edge_points=[(net, (x, y))]` a planned contract is used
instead and each net stays one hub.

### v2, integrated board 990d4b03 (host venv, seconds)

| block | bridges in design.py | as built, auto | bridges as wires, auto | as built, strict walls | as wires, strict walls |
|---|---|---|---|---|---|
| POWER | 1 (BR401) | planar | planar (0) | planar | planar |
| REFCAL | 10 | planar | planar (0) | not planar, 1 | not planar, 3 (+3V3A_R, ADS_B, SNS_T0, TAP4) |
| SCOPE | 2 | planar | planar (0) | planar | planar |
| AWG | 0 | planar | planar (0) | not planar, 1 (+3V3A) | not planar, 1 |

**The consistency test holds in `auto` and the strict model does not**: read as the spec's construction (every body a wall), two
routed blocks come out non-planar because tracks pass between the pads of 0603s and under SOICs, so `auto` is the default for a
board. **The bridges are not found, and that is a finding**: with the bridges as wires the model still says planar for all four
blocks. A planarity test lets a net go round the end of another's trunk; the v2 bridges exist because the geometry (corridors, the
A0/A1 wall, strip lanes, distances) forbids that, and a topological check cannot see geometry. So a *non-planar* verdict is a
sound reason to expect a bridge, and a *planar* one is not a promise that no bridge is needed.

### v1 REFCAL, the hand-found crossing (kvm_01, REFCAL_obstruction.md)

`boards/planar_v1.py` carries the inputs (frozen board `tests/pcbtools/planar_v1_34b2e51.npz`, the contract rows as edge points,
VREF as a Kelvin star at U501.2 with its four legs, R520 as `with R520`). What the tool finds, and it does **not** reproduce the
hand derivation:

- legs of VREF leaving U501.2 in the order A, C, B, D, ICs as walls: not planar, one net short, the pair VREF/TAP3 (suggestion
  TAP3), and **R520 does not cure it**;
- no order on the legs: planar, with or without R520, so the topology alone does not make the obstruction;
- J501, the clamps and the 0603s on the SNS path walls as well: two nets short, SNS_B in the minimum sets with TAP3 or VREF, still
  not cured by R520.

The hand derivation used placement facts the topology lacks (leg D running between the pads of R517-R519, which face each leg
borders), so `test_v1_refcal_finds_the_hand_found_crossing` is a strict xfail with that reason and the three findings above are
pinned as ordinary tests. `/SNS*` is in `PROTECTED_NETS` (the sense pair is precision copper), so the tool would now refuse to
suggest SNS_B as a bridge.

### What it cannot see

Pad shapes, track width and clearance (whether a gap passes a 0.2 mm track is `pass_pitch`, a proxy); via placement and the bottom
layer (a bottom hop is a crossing); keep-outs and courtyards; the extent of a body beyond its pads; the **mirror** of a part (a
planar embedding fixes pin order up to reflection, so handedness is not checked: the verdict is necessary, never sufficient); a fence
of several rectangles is one star-shaped ring; and routability, as above.
