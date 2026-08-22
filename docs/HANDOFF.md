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

## Feed margin: closed (2026-08-21, second pass)

The loop is now solid to spec: **zero underruns, zero gaps, 1371 +/- 2
codes in every 40 ms window** (theoretical 1370.5), reproducible at
multiple tones. Getting there uncovered a macOS behaviour that must
not be relearned: **a pressured CDC-ACM output queue silently drops
~128-byte chunks that write() already counted.** Blocking writes that
saturate the queue produced ~75 clean phase jumps per second on the
DAC with every counter green; clock-paced writes dropped at every
tested lead. The only measured-clean policy is in `host/loopback.py`:
a real-time thread (see `host/rt.py`: QoS + Mach time-constraint band;
XNU has no core pinning) polls TIOCOUTQ and bursts 16 KB only into a
truly empty queue, while the device's 8 KB ring covers the latency.

Related firmware fact: the device now drains bulk OUT whenever nothing
consumes it, because macOS's close() waits on in-flight write URBs
that a NAKing pipe never completes - host processes used to hang in
close() holding the port.

Transport ceilings remeasured with per-direction real-time threads
(the old numbers were partly the host's own scheduling): IN 5.20 MB/s,
OUT 5.03 MB/s byte-perfect, duplex 2.77 + 2.47 = 5.25 MB/s combined.

Also fixed while verifying every working feature against spec: preset
`5` hardcoded the MCK-84 ceiling (488372 Hz) and was silently refused
at MCK 78; it now derives 453488 Hz from the running clock like Track
A, and full-rate capture measures ratio 1.000, 1.83 MB/s gapless.

## Ceilings measured (2026-08-21, third pass)

`L`/`P` now take rates ("=<dac>[,<adc>]" before the letter;
`loopback.py --dac-sps/--adc-hz/--burst`), and the ladder was measured
with the tone-amplitude oracle validating fidelity at every point:

| Regime | Solid ceiling | Evidence |
|---|---|---|
| Matched loop (DAC = ADC/ch) | **453,488 sps - the ADC's in-spec limit** | under=0, gaps=0, 1372-1377 codes |
| AWG, play-only | **1.383 Msps - the DACC's hardware limit** (RC 28) | under=0 at 2.81 MB/s feed; needed the 32-slot ring |
| Asymmetric loop (AWG + 200 kHz capture) | **600 ksps DAC** | under=0, 1372 codes; 650 k shows 4 underruns/5 s |

The asymmetric regime exposed the next real bound: **queue-gated OUT
while capture streams caps near 1.7 MB/s.** It is not host-side (burst
size 16-64 KB changes nothing; GIL switch interval changes nothing;
play-only reaches 2.81 MB/s with the identical feed policy) - it is
the device's FIFO-copy interleave between play_service ingest and
stream_service egress. Free-running writes reach 2.47 MB/s but drop on
the macOS side, so they are not an option.

## Two-channel DAC: routing verified, purity open

Retested with trustworthy measurement (tag-interleaved 975 Hz on DAC0
+ 1500 Hz on DAC1, 97.5 ksps per channel, capture 97.5 ksps per
channel): **tag routing works** - each tone appears only on its own
channel (cross-terms ~2% of signal), refuting the old "both samples
reached channel 0" note in `host/loopback.py`, which dates from the
stale-buffer era. The raw waveforms are locally pristine sines.

Open: spectral purity is poor in dual mode only. A0 shows ~5 phase
jumps/s aligned to ring-slot boundaries (index mod 256 constant), A1
shows dense steps at an exact 32-sample period - with `under=0`, zero
gaps, zero overruns, byte counts exact, and the single-channel control
at identical rates measuring a perfect 1370.7. Two distinct signatures,
both tag-alternation-specific, neither explained. Reproduce with
`scratchpad`-style interleaved feed; the analysis prints jump indices.

Also measured on request: DAC0 at 906,976 sps with capture at the full
ADC rate needs 1.81 MB/s of gated OUT against the ~1.7 MB/s duplex cap
and is not clean (under=1037/5 s, tone 376 codes) - the exact
configuration objective 1 unblocks.

## Endpoint DMA: working, playback converted (2026-08-22)

The one-transfer stall was three findings deep, all now in the
`usb_cdc.c` history: DMA needs AUTOSW (manual FIFOCON and automatic
bank switching cannot share an endpoint), a `DEVEPTCFG` write while
EPEN is clear is silently ignored on this part, and the mode must be
reapplied on every endpoint rebuild or an enumeration reverts it.

Transport ceilings via DMA: **IN 32.0 MB/s, OUT 26.6 MB/s
byte-perfect, duplex 8.55 + 8.40 = 16.95 MB/s** (vs 5.20/5.03/5.25 for
CPU copies). The playback ring is now fed by endpoint DMA - multi-slot
spans, progress published from BUFF_COUNT mid-flight, no END_TR on the
stream variant - and the host feed is clock-paced with a 20 KB lead
(the empty-queue gate is obsolete now that the DMA-fed ring drains the
tty queue at wire speed; see the loopback.py history for why each
piece is shaped as it is).

Result: **the full-rate single pair runs - DAC 906,976 sps + capture
906,976 sps aggregate, zero underruns.** Purity at that extreme is
~90-95% of theoretical amplitude with run-to-run variance: capture
resyncs (honestly flagged, 1-1300 per run) from the still-CPU-copied
IN path, plus suspicion of link-level retransmits on a cable that
failed hard twice today. Baseline through 600 k configs remeasure
clean (1371 +/- 2) after every change.

## Next objectives, in order

1. **Capture IN over endpoint DMA.** The remaining CPU copy, the
   remaining invariant violation, and the source of the resyncs at
   full-rate duplex. Needs the frame header contiguous with the
   payload: give each capture buffer 32 B of headroom, point the PDC at
   the payload, CPU writes only the header, one DMA per frame.
2. **Replace the marginal native-port cable** and remeasure the
   full-rate purity variance before attributing anything further to
   software.
3. **The second pair.** Two pairs need ~2.85 MB/s OUT + ~1.81 MB/s IN
   - trivial against the DMA duplex numbers once objective 1 lands.
4. **Two-channel DAC purity** (routing verified; A0 slot-aligned jumps
   and A1 32-sample-periodic steps unexplained - retest after 1 and 2,
   which may explain both).
5. **Equivalent-time reconstruction** (sampling-scope trick): coprime
   dividers on a shared MCK give a 25.6 ns-resolution view of the DAC
   waveform through the slow ADC. Firmware pieces exist; needs a
   single-channel capture mode and a host reorder script.
6. **`usb_cdc_write` bank clobbering at flood rates** (status.md "Next"
   item 0); the DMA path shows the same overcommit when the host stops
   draining - harmless in normal operation, meaningless flood counters.

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
