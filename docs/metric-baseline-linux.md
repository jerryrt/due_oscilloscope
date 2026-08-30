# Metric report - 2026-08-29T22:18:16-0400

**The tracked baseline for the `linux-x1` bench - the third host, and the
first that is neither macOS nor Windows.** Regenerate with

    python3 tools/flash.py --bin build/baremetal_bringup.bin
    python3 tools/metrics.py --repeats 9 --seconds 3 \
        --out docs/metric-baseline-linux.md

and commit the change, so a moved figure shows up as a diff rather than
as a memory. Every generation is appended to `records/metrics.jsonl`;
this file is the latest one, rendered. `--out` overwrites, so this block
is re-added by hand - true of the macOS and Windows baselines as well.

**Split per host on the same reasoning as the other two** (issue #12):
the USB stacks are not the same instrument. What this host adds is a
third reading of quantities that had two, and on the ones that matter it
**sides with Windows**.

| metric | macOS (n=3) | windows-desk (n=9) | **linux-x1 (n=9)** |
|---|---|---|---|
| `effective_bits` | 9.403 | 10.444 | **10.499** |
| `noise_rms_codes` | 1.747 | 0.849 | **0.817** |
| `overrun_frames_per_run` | 8 | 55 | **63** |
| `tone_amplitude_codes` | 1368.3 | 1369.2 | **1376.6** |
| ladder deficit, RC 44 / 39 | 1.4-2.2% | ~0.010% | **0.176% / 0.147%** |

`advref_mv` reads 3270 on all three because all three read the same
committed `calibration.json`, so that column says nothing about the
boards - see the amplitude note below.

**Replicated, and the amplitude reading is stable.** A second Track B
generation three minutes later (`records/metrics.jsonl`, 22:21) read
`effective_bits` 10.5038, `noise_rms_codes` 0.814361,
`tone_amplitude_codes` **1376.12** and `overrun_frames_per_run` 66,
against this report's 10.4989 / 0.817092 / 1376.61 / 63. It is not the
tracked baseline because its flash carried a `-dirty` tree stamp where
this one is clean, but as a replication it matters: **three independent
generations on this bench - two Track B, one Track A - read
1376.12, 1376.61 and 1376.69.** The excess below is stable, not a draw.

**Three things worth someone's attention, none of them claimed as
findings.**

- **Noise and effective bits agree with windows-desk to well inside
  either spread, and both differ hugely from macOS.** That corroborates
  the "3.1x quieter second board" of issue #10 as a property of the
  *board*, not of the host - now on a third host with a third board.
- **`overrun_frames_per_run` is 63 here against 55 on Windows and 8 on
  macOS.** Linux and Windows agree; macOS is the outlier, on n=3 against
  n=9. Whether that is the host's read scheduling or the macOS bench's
  own capture path is not something this bench can decide alone.
- **`tone_amplitude_codes` is 1376.6 here against ~1368-1369 on both
  others, and that is board-to-board gain, not an anomaly.** An earlier
  version of this file called it "about six codes above the theoretical
  maximum" and asked for an analog eye. That was wrong twice over and
  the correction is the useful part.

  The "theoretical 1370.5" is not a ceiling. `build_waveform()` sends a
  digital sine of amplitude **2047 DAC codes**, and `calibration.json`
  stores `loop_slope_adc_per_dac_code` = **0.67053**; 2047 x 0.67053 is
  1372.6, and the figure exists only in prose - nothing computes it at
  runtime. That slope is a measured property of **one board**, the one
  `calibration.json` describes, read from a committed file by every
  bench. A board with a slightly wider DAC swing reads higher and
  exceeds nothing.

  What this bench actually shows: an implied slope of 1376.61 / 2047 =
  **0.67251**, which is **+0.30%** on the stored figure. `calibration.json`
  records `span_tolerance_mv` 40 against a 2193 mV span, or **+/-1.8%**,
  so it is well inside the tolerance that file states for itself.

  It was also wrong to write "`advref_mv` is 3270 on all three, so the
  amplitude column is not a reference artefact". `advref_mv` comes from
  the same committed `calibration.json` on every bench, so it carries no
  information about the three boards at all. The conclusion survives for
  a different reason, which `host/calibration.py` gives: the loop is
  **ratiometric** - the DAC's reference is the ADC's - so a reference
  shift moves both ends and cancels in the code domain.

  The one thing worth keeping: it is **stable and track-independent**,
  1376.12 / 1376.61 / 1376.69 across three generations and both tracks,
  which is what a fixed board property should look like.

**The playback ladder disagrees with this bench's own `writepolicy`
runs, and the disagreement is recorded rather than resolved.** The table
below reads 0.176% at RC 44 and 0.147% at RC 39, while
`tools/writepolicy.py` on the same bench read **0 B in 16 of 16 runs at
those two rates** (`records/writepolicy-linux-rc44-39.jsonl`). Different
feeders, so it is not a contradiction in the device - but it does mean
"Linux conserves bytes at RC 44/39" is a statement about a feeder, and
the honest summary is that the two rates the documented slow converter
lives at are also the only two that show a deficit here.

**Two provenance notes.**

- The header says *"image built after newest fw commit: NO"*. That is a
  **cross-track false positive**, not a stale image.
  `host/provenance.py`'s `FW_SOURCE` is one tuple covering both tracks,
  `sketches` included, so a Track A commit (`a7ef102`, the issue #33
  fix) marks a Track B image as predating firmware. Track B's sources
  were unchanged - `firmware source since flashed` reads **unchanged** on
  the same run, and `cmake --build` correctly relinked nothing. Offered
  as a fix on #32 rather than changed unilaterally, because it alters
  what a provenance flag means for every bench.
- The settling section fails its `agrees_with_stored_dso_range` gate and
  says so: **there is no oscilloscope on this bench**, and those figures
  must not be quoted. That is the report working, not a defect.

Generated by `tools/metrics.py`. Every figure below is qualified by the
conditions in this block; a figure quoted without them is not a figure.

## Exact versions

| | |
|---|---|
| **firmware track** | b |
| **fw_version** | 0.2.0 *(bumped by hand; not an identifier on its own)* |
| **firmware commit** | `0e0189b` |
| **firmware sha256** | `b07882b01631c11e...` |
| **build stamp** | Aug 29 2026 17:05:52 |
| flashed at | 2026-08-29T22:18:00-0400 |
| build/commit match | **matched** |
| image built after newest fw commit | **NO - the image predates a firmware commit; a build cache probably served a stale object** |
| firmware source since flashed | **unchanged** - the board runs current firmware however far the host tree has moved |
| ctl / frame version | 3 / 3 |
| scope | **firmware only** - the board is opened directly and no daemon is in the path |
| instrument | **none required** - the ADC is the instrument, so this report is reproducible on any bench with a board |
| host tree | `0e0189b` |
| host | Linux 7.0.0-30-generic (x86_64), python 3.14.4 |
| bench | **linux-x1** |
| wiring | DAC0->A0, DAC1->A1, A2 bare *(declared)* |


## Effective resolution and noise

| metric | value | n | spread |
|---|---|---|---|
| effective_bits | 10.4989 | 9 | 0.01012 |
| noise_rms_codes | 0.817092 | 9 | 0.005739 |
| spectral_lines | 2 | 9 | 0 |
| advref_mv | 3270 | - | - |
| advref_source | measured | - | - |

*units: bits of 12; codes rms; count*

## The DAC to ADC loop

| metric | value | n | spread |
|---|---|---|---|
| tone_amplitude_codes | 1376.61 | 9 | 6.228 |
| windows_at_or_above_1340 | 0.993197 | 9 | 0 |
| overrun_frames_per_run | 63 | 9 | 28 |
| rate_measured_over_declared | 0.999976 | 9 | 1.435e-05 |

*units: codes; fraction; frames; ratio*

## Host-fed playback ladder

| RC | sps | underruns | host wrote | device got | deficit |
|---|---|---|---|---|---|
| 195 | 200,000 | 0 | 1,222,144 | 1,222,144 | 0 B (0.000%) |
| 98 | 397,959 | 0 | 2,412,032 | 2,412,032 | 0 B (0.000%) |
| 65 | 600,000 | 0 | 3,626,496 | 3,626,496 | 0 B (0.000%) |
| 44 | 886,363 | 0 | 5,237,760 | 5,228,544 | 9,216 B (0.176%) |
| 39 | 1,000,000 | 0 | 5,904,896 | 5,896,192 | 8,704 B (0.147%) |
| 32 | 1,218,750 | 0 | 7,344,640 | 7,344,640 | 0 B (0.000%) |
| 28 | 1,392,857 | 0 | 8,391,680 | 8,391,680 | 0 B (0.000%) |

## Settling, equivalent-time

| metric | value | n | spread |
|---|---|---|---|
| rise_10_90_ns | 410.256 | 1 | - |
| agrees_with_stored_dso_range | False  **<- fails; the figures above must not be quoted** | - | - |
| fold_margin | 21.38329441970484 | - | - |

*units: -*

---

A median with no spread beside it is a claim nobody can check. Where `n` is 1,
the figure is one observation and is not a result - this project has had four
false positives caught by taking a second one.
