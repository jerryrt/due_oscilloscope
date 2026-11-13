# TPH2502 behavioural small-signal model (project's own)

`tph2502_beh.lib`, sha256 e5d30338104d9389b942d8c1b708f02e8850c0f4a7a8caba0815ce47856e8d4e (1386 bytes). Written for this project and
fitted to the 3PEAK TPH2501/2/3/4 datasheet Rev. A (GBW, the open-loop gain and phase curve, AVOL, open-loop output impedance, input
capacitances: every number and its source is in the file's header); licence CC-BY-SA 4.0 (models-open/LICENSE terms). Small-signal
only: AC and .op, no rails, slew, current limit or noise. The v2 scope study (v2/sim/scope, `beh_sha()`) reads it; it was kept
untracked in whatif/tph2502/beh/ until now, which is why the study could not be rerun anywhere else. The datasheet's own 3PEAK
vendor model is a different file (TPH2501.mdl, fetched, models/manifest.json).
