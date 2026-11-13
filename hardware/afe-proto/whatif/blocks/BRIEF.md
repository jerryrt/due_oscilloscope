# Block agent brief (AFE v1 restart, tools = pcbtools in the pinned image)

You place and route ONE block of the AFE v1 board inside your own fence on a private copy of the baseline board. Nobody else touches
your copy. The integrator merges the blocks later (pcbtools.merge) and judges the merged board with `pcbtools.check --config v1`.
Do not commit, do not push, do not look at /home/jerry/DA.Projects/20261103_due_afe_001. CLAUDE.md applies: no invented numbers
(mark unverified figures *(check)*), break a new check once on purpose.

## Where things are (repo worktree R = /home/jerry/EE.Projects/due_oscilloscope_kvm01, project dir P = R/hardware/afe-proto)
- Your board: P/whatif/blocks/<BLOCK>/<BLOCK>.kicad_pcb (the 34b2e51 baseline: every part legally placed, unrouted). Work on that file
  and on copies beside it. The baseline P/whatif/blocks/base.kicad_pcb is read-only. Project/library tables sit in P/whatif/blocks/.
- Earlier work you may start from or mine for ideas (read-only): SCOPE: prev.kicad_pcb (routed, to be re-placed); REFCAL:
  REFCAL3.kicad_pcb, REFCAL3_checkpoint0.kicad_pcb, orig.kicad_pcb; POWER: prev.kicad_pcb (pass 3, unfinished). The old helper scripts
  are in /tmp/claude-1000/-home-jerry-EE-Projects-due-oscilloscope/03688616-436c-475d-a0e7-d8a9b1032ed0/scratchpad/blocks/<BLOCK>*/ (they
  used the deleted blocktools.py; port ideas, not code). Hill-climbing is allowed ONLY as a bounded loop in ONE process (no
  multiprocessing, no pools); an earlier REFCAL job of 11 workers ran the shared machine out of memory.
- Contract: P/whatif/blocks/ref/floorplan_table.md (rows = nets crossing a fence: edge point, layer/width, bridge, owner) and P/kicad/floorplan.py
  FENCES. Your copper for those nets must END at the row's edge point on your fence edge, top copper, at the width named.
- Rules: P/whatif/blocks/ref/afe.md section 11.1 and ref/jlcpcb.md (silk, clearances). Read both first.
- Data: P/kicad/design.py (PARTS, nets, blocks), P/pcbtools/boards/v1.py (the config the checker reads: fences, outlines, CHANNELS...).

## Tools (all through the image, from P; docker is the ONLY way to run python with pcbnew)
Command: `cd R && docker/pcb/run.sh -m 3G -c 2 -t 600 bash -c 'cd /work/hardware/afe-proto && python3 ...'` (/work = R; the image runs as you,
--network none; `python3 -I` ignores cwd, so use plain `python3`). ONE container at a time per agent, never more, never outside
run.sh, no pools or multiprocessing, every loop bounded. The summary line `capped: peak_rss_kb=...` shows what you used.
- Write path: `from pcbtools.editor import edit` then `with edit(path, out) as e:` with `e.move(ref,x,y,rot=None,side=None)`,
  `e.set_ref(ref,x,y,h=1.0)` / `e.set_ref_pose`, `e.add_text(text,x,y,h=1.0)`, `e.add_tracks(net,'F',x0,y0,x1,y1,w)` and
  `e.add_vias(net,x,y,dia=0.6,drill=0.3)` (array arguments allowed), `e.remove_tracks(idx)/remove_vias(idx)` by the `*_idx` of the
  BoardArrays, `e.pad_xy(ref,pin)`, `e.stub_via(...)`. See pcbtools/editor.py and pcbtools/README.md ("Write path", "Things that bite"):
  a via that lands on a pad takes that pad's net; each pcbnew load writes a .kicad_prl beside the board (fine here, never in tests/).
  Coordinates are Due mm, x right, y up. Do many edits in one `edit()` call, not one process per edit.
- Read path: `from pcbtools import boardio; b = boardio.read_board(path)` -> numpy BoardArrays (see pcbtools/ARRAYS.md).
- Fence: `python3 -m pcbtools.fence`-style check through `pcbtools.fence.check_fence(base, blk, block, cfg)` with cfg = pcbtools.boards.v1
  (`FenceResult.ok`, `.violations`); it must be clean after every batch of edits (a track crossing the fence edge counts as outside;
  parts of other blocks must not move).
- Rules: `python3 -m pcbtools.check BOARD --config v1 --no-drc [--rows LR-1 LR-2 ...]` (add `--drc` for kicad-cli DRC on a board that
  has the project/library tables beside it). The rows that look at other blocks' copper fail until the merge: say which failures are yours.
  v1's LR notes: LR-12 decoupling is per named cap (C103/U101.8, C302/U301.8, C303/U301.4, C502/U502.8, C501/U501.1, max 3 mm).
- Pictures: `kicad-cli pcb export svg ...` then `magick` to PNG inside the container; look at your own fence often.

## Rules in short (your block's rows must pass; do not weaken a check)
Top copper only for signals; the bottom is one unbroken GND plane (no bottom signal track, no hop, no cut). Every SMD GND pad has its own
via within 3 mm. No top GND track or pour next to inverting nodes (LR-4: 0.5 mm). Track 0.2 (0.25-0.3 supply), clearance 0.2, via 0.6/0.3.
Every part inside your fence; the six bridges R109 R110 R309 R310 R515 R516 stay in the wall corridor as in the baseline. 1.0 mm
designator on F.SilkS for every part of the block, the block words ('CH1' 'CH2' 'AWG' 'POWER' 'REF/CAL', 'ON' at the CAL shunt-on position),
silk 1.0 mm height, 0.15 line, clean silk DRC.

## Report (under 50 lines)
What you moved and why; per-row status of `pcbtools.check` for your block's rules; DRC kinds open and where; each edge point reached (net, x, y,
layer, width); each rule you could not satisfy (numbers); every *(check)*. Final board = your <BLOCK>.kicad_pcb plus a PNG of your fence beside it.
