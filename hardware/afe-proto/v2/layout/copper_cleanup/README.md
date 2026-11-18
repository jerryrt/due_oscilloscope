# AFE-2 copper cleanup

`build.sh` rebuilds `v2/layout/integrated/afe-v2-integrated.kicad_pcb` from the board of record, `afe-v2-integrated.before.kicad_pcb` (the integrated board as it was before the cleanup),
in the pinned PCB image, from the repository root:

    docker/pcb/run.sh -m 4G -t 1800 bash hardware/afe-proto/v2/layout/copper_cleanup/build.sh

The same input gives the same bytes (two builds, one sha256: the board's own sha256 is printed last). The passes, in order:

| step | file | what |
|---|---|---|
| 1 | `cc_reroute.py` | the automatic track pass: only the runs of segments `track_geometry` flags are rebuilt, from the nearest good vertex on each side, as an octilinear path of at most 4 legs (legs of 0.62 mm or more, 0.3 mm at a fine-pitch pad), the last leg perpendicular to the pad edge, 0.2 mm clear of other copper (more round the sensitive nets, never less than the old gap under 0.15 mm), nothing over a foreign pad, the net's pad connectivity kept with and without the LR-6 / LR-8 cuts and the INV_MAX nets no longer by more than 0.1 mm; a track wider than the pad it enters is narrowed; GND stubs that cannot be made legal go |
| 2 | `cc_edits.py` | the hand edits, as data: per net the segments to remove and the polylines to add, vias moved, deleted or added (the U401 fan-out, the VREF cluster at U501.2 / C501.1, ...). It refuses an edit that removes a segment that is not there |
| 3 | `cc_gndvias.py` | a via of its own, on a legal stub, for the SMD GND pads the edits left without one (LR-1) |
| 4 | `pcbtools.fill_clean` | LAST: keep-outs, thermal reliefs, minimum widths, stitching |
| 4b | `cc_check.py` | the no-margin rule: every protected net (AWG_FB, CH1_OUT, CH2_OUT, A0, A1, CH1_N, CH2_N: the nets whose track length an LR row reads or limits) is no longer than on the board of record, unrounded, to 1e-9 mm of float noise and nothing larger; the build fails otherwise. `cc_reroute.py` enforces the same per candidate |
| 5 | `cc_normalize.py` | uuids of the vias and rule areas pcbnew made are derived from their content, and they are put in uuid order, so the bytes repeat |

`cc_state.py` is the shared part (the net graph, the clearance model, the writer), `cc_router.py` the candidate paths. Nothing here moves a footprint; `pcbkit.proof` says so.
`tests/pcbtools/test_copper_cleanup.py` holds the board of record by hash, the edit data to the angle step, the protected net lengths, and the findings that are left (the named exceptions of `boards/v2_layout.py`, each matching exactly one finding; a stale row fails) to the rule.
