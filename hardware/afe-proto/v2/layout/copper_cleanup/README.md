# AFE-2 copper cleanup

`build.sh` rebuilds `v2/layout/integrated/afe-v2-integrated.kicad_pcb` from the board of record, `afe-v2-integrated.before.kicad_pcb` (the integrated board as it was before the cleanup),
in the pinned PCB image, from the repository root:

    docker/pcb/run.sh -m 4G -t 1800 bash hardware/afe-proto/v2/layout/copper_cleanup/build.sh

The same input gives the same bytes (two builds, one sha256: the board's own sha256 is printed last). The passes, in order:

| step | file | what |
|---|---|---|
| 1 | `cc_reroute.py` | the automatic track pass, answering to the five kinds `track_geometry` had when the cleanup was written (angle, jog, entry, over_pad, arc): only the runs it flags are rebuilt, from the nearest good vertex on each side, as an octilinear path of at most 4 legs (legs of 0.62 mm or more, 0.3 mm at a fine-pitch pad), the last leg perpendicular to the pad edge, 0.2 mm clear of other copper (more round the sensitive nets, never less than the old gap under 0.15 mm), nothing over a foreign pad, the net's pad connectivity kept with and without the LR-6 / LR-8 cuts, and the protected nets (AWG_FB, CH1_OUT, CH2_OUT, A0, A1, CH1_N, CH2_N) never longer; a track wider than the pad it enters is narrowed. GND is skipped (`--skip-nets /GND`): its tracks are step 6's |
| 2 | `cc_edits.py` | the hand edits, as data (`OPS` and the via lists): per net the segments to remove and the polylines to add. It refuses an edit that removes a segment that is not there |
| 3 | `cc_edits.py ... cc_fix_data` | round 2 of the hand edits, same machinery, data in `cc_fix_data.py`: what the detour, dangling, T-spur and wide checks found (the AWG_VO hooks, the CH2_IN V kink, the D201.2 '<', free ends, T junctions at a bend, the AWG_BNC S) |
| 4 | `cc_reroute.py --kinds detour --grid` | the detours (a run that turns 180 degrees or more within 3 mm, or is 1.5 times its octilinear shortest path): the whole run is re-routed end to end, first by `grid_path`, a least-bent octilinear search on a 0.05 mm grid (legs of 0.62 mm or more, bends of 45 or 90 degrees made outside the pads, the track starting and ending where it likes on its pads, across an edge and within its span), then by the enumerated paths of step 1 |
| 5 | `cc_gndedge.py` | every GND track and via is removed and every SMD GND pad gets a via at its edge, no track between (annulus overlapping the pad's box by 0.01 mm or more, straight out of an edge, 0.2 mm clear; the DRC floor of 0.15 mm in a second look); U401's pins 1 and 4 are tied straight into the exposed pad, one via at the exposed pad's end completes its four pads, and a pad with no place keeps a legal stub (the exceptions of `v2_layout`) |
| 6 | `pcbtools.fill_clean` | LAST: keep-outs, thermal reliefs, minimum widths, stitching; it keeps connector GND pins and SMD GND pads in the pour or gives them a via at the edge |
| 7 | `cc_check.py` | the no-margin rule: every protected net is no longer than on the board of record, unrounded, to 1e-9 mm of float noise and nothing larger; the build fails otherwise. `cc_reroute.py` enforces the same per candidate |
| 8 | `cc_normalize.py` | uuids of the vias and rule areas pcbnew made are derived from their content, they are put in uuid order, and everything but the copper is the board of record's own text, so the bytes repeat |

`cc_state.py` is the shared part (the net graph, the clearance model, the writer), `cc_router.py` the candidate paths. Nothing here moves a footprint; `pcbkit.proof` says so.
`tests/pcbtools/test_copper_cleanup.py` holds the board of record by hash, the edit data to the angle step, the protected net lengths, and the findings that are left (the named exceptions of `boards/v2_layout.py`, each matching exactly one finding; a stale row fails) to the rule.
