# Handoff

Read this first, then `docs/status.md` and `docs/usb.md`.

## Where the work stands

**The full loop works.** Track B, one channel pair:

```
HOST -> USB -> DAC0 -> jumper -> A0 -> ADC -> USB -> HOST
```

Verified 2026-08-21: `python3 host/loopback.py --seconds 5` reports 1024
frames, seq 0..1023, 0 gaps, 0 CRC errors, 0 overruns, Goertzel
amplitude 1371 codes on A0 (theoretical max ~1370), A1 flat at 0.1
codes. DAC at 200 ksps from bulk OUT, capture at 400 ksps aggregate on
bulk IN, simultaneously.

## What the previous "blocking defect" actually was

The prior handoff described a defect: playback alone worked, capture
alone worked, and together the analog output "froze at mid scale" while
every playback counter read nominal. **The freeze never existed on the
device.** A stream from an earlier run keeps flowing into the kernel's
tty input buffer after the run ends; the receiver read ~800 kB of stale
frames first - the flat mid-scale startup of an *old* capture - and the
"1 sequence gap" every run reported was the splice between the stale
epoch and the live one. Frame timestamps proved it: one capture
contained an epoch at device time ~0 s and another at ~52 s inside a
5-second host run. The playback counters were right all along.

This was the *second* time the stale-kernel-buffer failure mode bit
this project (see "Two host-side bugs that looked like firmware bugs"
in `docs/status.md`). A one-shot `tcflush` at open is not a defense: the
buffer refills as long as the device still streams. `host/loopback.py`
now drains the native port until it stays silent for a full second,
warns if the first frame is not near seq 0, and windows the tone
amplitude against device timestamps.

Real fixes that came out of the investigation:

- **`usb_cdc_read()` discarded the undrained tail of an OUT bank after
  a clipped read.** One short packet from the host then byte-shifted
  the whole playback stream. It now resumes at an offset and releases
  the bank only when drained.
- **Command `M`** plays gen's flash sine through play's exact
  DACC + TIOA1 + TC1 configuration with capture running and no USB
  involved. It exonerated the trigger path on hardware in one run.
- **Command `D`** snapshots both loops' counters, the live `DACC_TPR`
  slot walk, and `ADC_CDR[7]/[6]` (the converter's live last result,
  bypassing ring, framer and USB) while everything runs, printing only
  afterwards. `loopback.py --diag` triggers it mid-run.

## Known imperfection, counted and visible

The host's non-blocking feed sustains ~0.396 MB/s against the
0.400 MB/s the DAC consumes, so a few underruns per second repeat a
buffer and dent the tone in those windows (`under=26` per 5 s run;
visible in `loopback.py`'s windowed amplitude). Host scheduling, not
firmware. Options: larger/earlier writes host-side, or a deeper ring.

## Next objectives, in order

1. **Feed margin.** Close the ~1% OUT shortfall so a 5 s run counts
   zero underruns.
2. **Push the single pair toward the ADC ceiling**: 453 ksps per
   channel at 906,738 sps aggregate. `L` currently hardcodes
   200 kHz / 200 kHz; parameterize it.
3. **The second pair.** Budget for two pairs is ~2.85 MB/s OUT plus
   ~1.81 MB/s IN against a measured duplex best of ~4.96 MB/s. Viable
   but tight; bias the direction budgets toward OUT.
4. **Endpoint DMA.** Restores the invariant that the CPU never touches
   sample data. The primitives in `drivers/usb_cdc.c`
   (`usb_dma_in_start`, `usb_dma_out_start`) stall after one transfer;
   status-register handling is the likely culprit.

## Hard-won facts the next session must not rediscover

- **Never analyse a capture without proving it is fresh.** Sequence
  numbers near zero and device timestamps that span the host window are
  the proof. A receiver describing data the source cannot have produced
  in that window is describing its own bug.
- **Never infer firmware state the firmware can report.** `boot_log()`
  exists; `u` dumps USB registers; `V` dumps the ring; `D` samples the
  live loop. Validate a new counter before trusting it.
- **Discover ports, never hardcode them.** `host/ports.py`. A stale
  hardcoded path once aimed the 1200-baud erase at the wrong port.
- **The board resets whenever the programming port is opened** (NRSTB).
  This also re-enumerates the native port, possibly under a new name,
  and invalidates any open fd to it: open control first, keep it open,
  then re-glob and open native. It also clears the backup domain, so
  the device cannot time its own benchmarks; the host keeps the clock.
- **`A0` is ADC channel 7, not 0.** A0..A7 map to AD7..AD0 descending;
  A8..A11 map to AD10..AD13 ascending.
- **Trigger overrun is silent.** `ACQ_MIN_RC` (86) guards it; 86 holds
  at any MCK because timer and converter clocks scale together.
- **The DAC is not rail to rail**: 546-2760 mV. A DACC channel that has
  never converted since `SWRST` sits at its code-0 level (~679 ADC
  codes): under the all-tag0 host stream, DAC1 reads ~681 until the
  leftover tag1 prime samples reach it, and that is normal.
- **A 1 kHz tone is phase-locked to 150 ms sampling** (150 cycles
  exactly). Periodic peeks at a periodic signal alias; six identical
  `next` codes in twelve snapshots meant a strobed sine, not a frozen
  ring. Pick diagnostic intervals coprime to the signal, or vary them.
- **An asymmetry produced by a scheduler is not a property of the
  hardware.** Equal byte budgets before comparing directions.
- **Instrument the suspect region before attributing anything to it.**

## Environment

- macOS 12.7.6, Intel x86_64, no Homebrew.
- `~/.local/bin` must be on `PATH` (holds `arduino-cli` and `cmake`).
- Track B: `cmake --build build -j`, flash with
  `tools/flash.sh build/baremetal_bringup.bin`.
- Track A: needs `--build-property build.f_cpu=78000000L`, because the
  core's `micros()` divides by the compile-time `F_CPU` and MCK is 78 MHz.
- Use the **xPack** ARM toolchain. ARM's own macOS build links `cc1`
  against Homebrew's zstd and cannot run here.
- Wiring: **DAC0 -> A0**, DAC1 -> A1 (second pair currently unused).

## Track B command reference

| Key | Action |
|---|---|
| `h` | banner |
| `r` `s` `x` | read A0/A1, DAC sweep, crosstalk |
| `t` | TC/ADC/PDC trigger-rate sweep |
| `1`..`5` | capture streaming presets, `5` = max in-spec |
| `0` | stop everything |
| `?` | stream + playback statistics |
| `F` `R` `X` | transport benchmarks: flood IN, sink OUT, duplex |
| `G` `T` `Y` | same three via DMA (**currently broken**, stalls after one transfer) |
| `L` | full loop: playback + capture (**works**) |
| `P` | playback only |
| `V` | dump playback ring + DACC registers |
| `D` | loop diagnostic: 12 snapshots at 150 ms, printed afterwards |
| `M` | mimic loop without USB: gen sine on TIOA1 + capture |
| `B` | bench + playback counters |
| `u` | dump USB registers |
| `z` | software reset |

## Host tools

```sh
python3 host/ports.py                       # discover both ports
python3 host/loopback.py --seconds 5        # the full loop test
python3 host/loopback.py --diag             # same, with mid-run firmware snapshots
python3 host/loopback.py --dc 4095          # constant code instead of a tone
python3 host/usbbench.py duplex --seconds 4 # transport benchmark
python3 host/receive.py --send 5 --seconds 5 --expect-hz 953.85
```
