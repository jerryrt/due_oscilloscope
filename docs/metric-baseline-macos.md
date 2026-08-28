# Metric baseline: macOS - 2026-08-27T20:31:01-0400

**The tracked baseline for the macOS bench.** Regenerate with
`python3 tools/metrics.py --out docs/metric-baseline-macos.md`, and
commit the change so a moved figure shows up as a diff rather than as a
memory. The machine-readable run of every generation is appended to
`records/metrics.jsonl`; this file is the latest one, rendered.

Every figure below is qualified by the conditions in the next block; a
figure quoted without them is not a figure. **No instrument is
required** - the ADC is the instrument - so this is reproducible on any
bench that has a board, which is the point of tracking it per platform.
The Windows counterpart is issue #12.

## Exact versions

| | |
|---|---|
| **firmware track** | b |
| **fw_version** | 0.2.0 *(bumped by hand; not an identifier on its own)* |
| **firmware commit** | `fc00c39-dirty` |
| **firmware sha256** | `acbb472708f4e163...` |
| **build stamp** | Aug 27 2026 16:14:27 |
| flashed at | 2026-08-27T20:30:40-0400 |
| build/commit match | **matched** |
| firmware source since flashed | **unchanged** - the board runs current firmware however far the host tree has moved |
| ctl / frame version | 3 / 3 |
| scope | **firmware only** - the board is opened directly and no daemon is in the path |
| instrument | **none required** - the ADC is the instrument, so this report is reproducible on any bench with a board |
| host tree | `fc00c39-dirty` |
| host | Darwin 21.6.0 (x86_64), python 3.14.6 |
| bench | **macos-dso** |
| wiring | DAC0->A0, DAC1->scope EXT TRIG (x1), A1 free, A2 bare *(declared)* |


## Effective resolution and noise

| metric | value | n | spread |
|---|---|---|---|
| effective_bits | 9.40302 | 3 | 0.06045 |
| noise_rms_codes | 1.74654 | 3 | 0.0719 |
| spectral_lines | 0 | 3 | 0 |
| advref_mv | 3270 | - | - |
| advref_source | measured | - | - |

*units: bits of 12; codes rms; count*

## The DAC to ADC loop

| metric | value | n | spread |
|---|---|---|---|
| tone_amplitude_codes | 1368.29 | 3 | 4.134 |
| windows_at_or_above_1340 | 0.993197 | 3 | 0 |
| overrun_frames_per_run | 8 | 3 | 3 |
| rate_measured_over_declared | 0.999998 | 3 | 1.668e-06 |

*units: codes; fraction; frames; ratio*

## Host-fed playback ladder

| RC | sps | underruns | host wrote | device got | deficit |
|---|---|---|---|---|---|
| 195 | 200,000 | 0 | 1,222,656 | 1,222,656 | 0 B (0.000%) |
| 98 | 397,959 | 0 | 2,412,544 | 2,412,544 | 0 B (0.000%) |
| 65 | 600,000 | 0 | 3,628,032 | 3,628,032 | 0 B (0.000%) |
| 44 | 886,363 | 0 | 5,348,352 | 5,271,552 | 76,800 B (1.436%) |
| 39 | 1,000,000 | 0 | 6,032,896 | 5,898,240 | 134,656 B (2.232%) |
| 32 | 1,218,750 | 0 | 7,349,760 | 7,349,760 | 0 B (0.000%) |
| 28 | 1,392,857 | 0 | 8,395,264 | 8,394,880 | 384 B (0.005%) |

## Settling, equivalent-time

| metric | value | n | spread |
|---|---|---|---|
| rise_10_90_ns | 923.077 | 1 | - |
| agrees_with_stored_dso_range | True | - | - |
| fold_margin | 22.91945381097661 | - | - |

*units: -*

---

A median with no spread beside it is a claim nobody can check. Where `n` is 1,
the figure is one observation and is not a result - this project has had four
false positives caught by taking a second one.
