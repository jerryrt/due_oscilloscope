# tools/

86 scripts, one shell shim, no shared entry point. Most are one-off
bench instruments written to answer a single question and then left in
place - `toolchain.py` and `flash.py`/`flash.sh` are the exceptions
everything else depends on. 43 are named after the issue they were
built for (`issueNN_*.py`); the rest describe what they do.

This file is an index, not a curation pass. Nothing here is deleted -
CLAUDE.md's own rule is that a one-off bench tool with a hardcoded path
is invisible to every other check, so marking a script's status is the
only leverage this file has, and it is reversible in a way deletion is
not.

## Reading the status column

| status | meaning |
|---|---|
| **live** | in current use: referenced by `docs/`, `CLAUDE.md`, the test suite, or another live tool, or its owning issue is still open |
| **archived** | its owning issue is closed and its finding is recorded in `docs/` - kept for provenance, not for re-running |
| **unknown** | no issue, doc, or test reference could be found; classification is a guess and the table says so rather than picking one |

Status was determined by evidence, not by reading the docstring alone:
`gh issue view <n>` for the issue's state, then a grep of `docs/` for
whether the finding it produced was actually written down. A script
citing an **open** issue is `live` even with no `docs/` citation yet,
because `docs/` only carries what is settled and an open issue is by
definition not settled. A script citing a **closed** issue is `archived`
only where the finding shows up in `docs/`; where it does not, that is
`unknown` rather than an assumption either way.

## Two things this table does not fix

**Nine of these hardcode `track="b"`**, so a Track A run gets recorded
as if it were Track B - issue #53's own subject, tracked there rather
than duplicated here.

**A handful hardcode one bench's absolute repo path or serial port**
(`COM7` and similar) instead of discovering either. The repo-path form
is a straightforward bug and was fixed on sight where found; a
hardcoded port is a bench-specific convenience left for whoever owns
that bench to generalise, not a defect this pass corrects.

## The scripts

| script | purpose | status |
|---|---|---|
| `ab.py` | Compare firmware conditions against a control arm that must reproduce. | live - docs/testing.md |
| `acr_issue5.py` | Does the DAC output-stage bias move issue #5's artifact? | live - docs/awg.md, docs/noise.md |
| `acr_noise.py` | Does DACC_ACR's bias setting move the noise floor? | live - docs/noise.md |
| `acr_rise.py` | Does DACC_ACR's bias setting move the settling edge? | unknown - no issue, doc or test reference found |
| `bench.py` | Measure this board against the design's figures, on any host. | live - docs/usb.md, docs/status.md, docs/linux.md, docs/windows.md |
| `bleed_cadence.py` | Is the A1-arm excursion random, or on a cadence? | live - docs/noise.md |
| `clock_calib.py` | Measure the device's clock against the host's, free of host overhead. | archived - docs/hardware.md (issue #52 closed; topic match, not cited by number in-file) |
| `console_pairs.py` | Which paired console bodies are one logic, and which only share a name? | live - tests/test_shared_source.py |
| `dso_metrics.py` | Device metrics for the DAC, measured with an instrument that is not the board. | live - docs/awg.md, docs/measurement-suite.md |
| `dso_sweep.py` | Drive every supported waveform at every supported rate, and watch. | live - docs/awg.md |
| `enum_probe.py` | Does Track A's command port fail to come up after a flash on Windows? | live - tests/test_clean_build.py |
| `flash.py` | Flash a bare-metal .bin to the Due, on any host. | live - docs/linux.md, docs/windows.md, docs/toolchain.md |
| `flash.sh` | Shell shim that runs flash.py from the repo venv. | live - docs/frontend.md, docs/daemon-api.md, docs/linux.md, docs/toolchain.md |
| `gallery.py` | Capture the wiki's screenshot gallery, reproducibly, from a live board. | live - tests/test_daemon_api.py, tests/test_startup_frames.py |
| `image_fingerprint.py` | What is actually on the board, in a form two benches can compare. | live - CLAUDE.md |
| `image_mnemonics.py` | Per-function mnemonic hashes: what the compiler generated, not where it put it. | live - CLAUDE.md |
| `issue18_soak.py` | Is there a room signal left once build and activity are fixed? | live - issue #18 open |
| `issue18_transfer.py` | Does the calibration follow the sensor excursion? | live - issue #18 open |
| `issue24_draws.py` | Which lattice did each capture draw? Board-free, over the records. | live - docs/awg.md |
| `issue24_drift.py` | Are the sites fixed, or is one event marching through the fold? | live - issue #24 open |
| `issue24_drive_path.py` | Is the site instability the drive path or something else? | live - issue #24 open |
| `issue24_fold.py` | #24's displacement, measured with #5's instrument, in the same units. | live - docs/awg.md |
| `issue24_hold.py` | #24's ratio axis, with a fold that survives a held level. | live - docs/awg.md |
| `issue24_holdavg.py` | The host path read without discarding a phase, at any hold. | live - issue #24 open |
| `issue24_outliers.py` | The big-fold outliers, as a class rather than four accidents. | live - issue #24 open |
| `issue24_period.py` | Which period does #24's artifact actually belong to? | live - issue #24 open |
| `issue24_phase.py` | What the "bidirectional jitter storm" actually is. | live - docs/awg.md |
| `issue24_ratio.py` | Is the comb of 21 counted in DAC updates, or is it a beat? | live - issue #24 open |
| `issue24_runs.py` | Is the comb's gate drawn per stream, or does it drift on a slower clock? | live - issue #24 open |
| `issue24_taginterleave.py` | Is the TAG interleave what makes the two paths disagree? | live - issue #24 open |
| `issue24_two_readings.py` | #24 vs #5: both site readings over the same captures. | live - issue #24 open |
| `issue24_us.py` | #24's gap census, in microseconds as well as in updates. | live - issue #24 open |
| `issue24_visible.py` | Which lattices can a given #24 arm actually tell apart? | live - issue #24 open |
| `issue24_wrap_rate.py` | Are the host-fed events per wrap or per second? | live - issue #24 open |
| `issue24_wrap_vs_time.py` | #24 per-wrap or per-second, with step height and pair count as controls. | live - issue #24 open |
| `issue35_touch_arms.py` | Re-run the four arms that put a platform branch in flash.py. | archived - issue #35 closed; docs/linux.md |
| `issue44_daemon_start.py` | #44 through the daemon, which is where the start-race fix actually is. | archived - issue #44 closed; docs/daemon-api.md |
| `issue44_gaps.py` | Did the device keep cadence while the lost frames vanished? | archived - issue #44 closed; docs/daemon-api.md |
| `issue45_ctlgap.py` | Track C control link: does the failure need idleness, not calls? | live - issue #45 open |
| `issue47_cooccur.py` | Does the short feed co-occur with the byte deficit? | archived - issue #47 closed; docs/awg.md |
| `issue47_oversupply.py` | Is the RC 32 loss the host discarding, or the converter running slow? | archived - issue #47 closed; docs/awg.md |
| `issue47_ratio.py` | Is the 15/16 rate specific to RC 32, or does every rate have one? | live - docs/awg.md, docs/daemon-api.md |
| `issue47_tail.py` | Is the ~450 kB deficit a loss, or a tail? | archived - issue #47 closed; docs/awg.md |
| `issue48_droop.py` | What does DACC_MR_REFRESH(2) cost, measured with the ADC? | live - issue #48 open |
| `issue48_dwell.py` | Is #48's mode fixed for a whole playback, or re-decided inside one? | live - issue #48 open |
| `issue48_hostfeed.py` | #48 from the host's side, on a bench whose host tells the truth. | live - issue #48 open |
| `issue48_lattice.py` | #48's n/256 lattice, on whichever bench runs it. | live - issue #48 open |
| `issue48_nousb.py` | Does the rate deficit need the USB feed, or is it the DACC alone? | live - issue #48 open |
| `issue48_withinrun.py` | Does #48's mode incidence drift within a single run? | live - docs/measurement-suite.md |
| `issue50_track_diff.py` | Does the Track A suite tell us anything the Track B one does not? | live - issue #50 open |
| `issue52_threeclock.py` | Separate the board's crystal from the host controller's. | archived - issue #52 closed; docs/hardware.md |
| `issue58_reset_distance.py` | Does distance from the last board reset gate the contention lever? | archived - issue #58 closed; docs/testing.md |
| `issue5_a1.py` | Does the comb of 21 land on DAC1 as well, or only on DAC0? | live - docs/awg.md |
| `issue5_absphase.py` | Where are #5's sites in the table, not in the fold? | live - docs/awg.md |
| `issue5_amp.py` | Does #5's displacement scale with the signal, or sit on top of it? | live - issue #5 open |
| `issue5_perboot_block.py` | One block of #5's per-boot test: n=12 at a fixed FWS and rate. | live - issue #5 open |
| `issue5_powercycle.py` | #5's last untried draw-event candidate, with a human doing the cycle. | live - issue #5 open |
| `issue5_sites.py` | How many samples per wrap are displaced, and which of them flips? | live - docs/awg.md, docs/measurement-suite.md |
| `issue5_solo.py` | Does removing the DAC1 write change what the comb counts? | live - issue #5 open |
| `kfixed.py` | Phase against elapsed time at a fixed start gap. | live - issue #5 open |
| `kpass.py` | Is the residue class a function of K, or of when the run started? | live - issue #5 open |
| `loadwatch.py` | Poll main-loop load over the control channel and log every sample. | live - docs/control-protocol.md |
| `loop.py` | Capture and full-loop validation, on any host. | live - docs/status.md, docs/windows.md |
| `metrics.py` | Run the metric set as one command, and emit a report that can be quoted. | live - docs/measurement-suite.md |
| `noise_metrics.py` | The noise measurements, in the shape Phase 0 can repeat. | live - imported by tools/phase0.py |
| `noisetool.py` | What the digital side costs the analog side, measured on this board. | live - docs/noise.md, docs/measurement-suite.md |
| `phase0.py` | Run one metric N times and record what it actually did. | live - docs/noise.md, docs/measurement-suite.md |
| `phase_k.py` | Does the artifact's landing phase move with M's ADC-to-DAC start gap? | live - issue #5 open |
| `powercycle.py` | Power-cycle the board from software - if the hub really cuts power. | live - issue #5 open |
| `report.py` | Generate the figure tables that documentation would otherwise hand-copy. | live - docs/status.md |
| `serial_probe.py` | Minimal serial probe for bring-up. | live - CLAUDE.md |
| `settletime.py` | Settle to one code, by equivalent-time sampling with the ADC. | live - docs/metric-baseline-windows-track-a.md |
| `soak0c.py` | Soak port open/close cycles, which is the thing objective 0c hangs in. | archived - docs/usb.md, docs/windows.md (objective 0c, diagnosed) |
| `soak0c_portable.py` | Objective 0c, reproduced without any POSIX-only code. | live - docs/windows.md |
| `soak_close_stream.py` | Close the native port mid-capture, without stopping the stream. | live - tests/test_framer_close.py |
| `splices.py` | Count the splices in a device-generated capture, run after run. | live - docs/awg.md |
| `stream_seam.py` | The seam list for issue #14, extracted rather than curated. | live - docs/shared-source.md |
| `temp_bands.py` | Judge a temperature soak against issue #18's adopted bands. | live - issue #18 open |
| `temp_soak.py` | Is there a room-temperature signal left once build and activity are fixed? | live - issue #18 open |
| `temp_track_parity.py` | Do the two tracks now read the die sensor the same? | archived - issue #15 closed; docs/noise.md |
| `temp_workload.py` | Does the die sensor read the workload rather than the room? | archived - issue #15 closed; docs/measurement-suite.md |
| `toolchain.py` | Resolve build tools from toolchains.json. | live - docs/toolchain.md |
| `track_parity.py` | Compare the tracks' console tables and main() init, as lists. | live - tests/test_track_parity.py |
| `uptime_reset_probe.py` | Does opening the control port reset the board? Ask the board. | live - docs/usb.md, docs/measurement-suite.md |
| `verify_track_parity_history.py` | Would track_parity.py have caught the five main() divergences? | unknown - no issue, doc or test reference found |
| `wikigen.py` | Build the wiki's gallery pages from the capture's own index. | live - consumes tools/gallery.py's index.json (live) |
| `writepolicy.py` | Is Feeder.WRITE_SIZE still a rule, or a stale workaround? | live - docs/usb.md, docs/linux.md |
