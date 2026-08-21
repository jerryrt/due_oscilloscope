# Handoff

Written at the end of a long session. Read this first, then
`docs/status.md` and `docs/usb.md`.

## Objective for the next session

**Track B only. One channel pair: DAC0 -> A0.**

Fix the one defect blocking the full loop:

```
HOST -> USB -> DAC0 -> jumper -> A0 -> ADC -> USB -> HOST
```

Playback works. Capture works. **They do not work at the same time.**

## The defect, precisely

Command `L` starts playback and capture together. Command `P` starts
playback alone.

| | `P` (play only) | `L` (play + capture) |
|---|---|---|
| Host sends DAC0 = 0 | A0 = 679 (547 mV) | - |
| Host sends DAC0 = 2048 | A0 = 2051 (1652 mV) | - |
| Host sends DAC0 = 4095 | A0 = 3421 (2756 mV) | - |
| Host sends 1 kHz sine | (not yet tried) | **A0 frozen at 2051** |

Under `L`, in the settled window (after ~120 frames) A0 sits at a rock
steady 2051 (DAC mid-scale) for 40+ consecutive samples. A 1 kHz tone
would swing about 1000 codes over that span. Capture itself is healthy:
1239 frames, 0 CRC errors, 1 sequence gap, 1.417 MB/s combined.

Meanwhile the playback side reports everything nominal:

```
play: in=2006016 produced=1959 consumed=1954 under=0 isr=1954 endtx=1954
```

1954 end-of-transmit events in 5 s is 390.6/s, exactly 200000/512. The
PDC completes buffers at precisely the right rate, never underruns, and
the producer stays about 4 buffers ahead. And yet the analog output does
not move.

## What is already ruled out

Do not re-investigate these. Each was checked directly, not inferred.

- **Not the DAC, the jumper, or the analog domain.** Playback alone
  drives A0 to 547 / 1652 / 2756 mV for codes 0 / 2048 / 4095, matching
  the DAC's measured endpoints exactly.
- **Not the data reaching the device.** `V` dumps the playback ring;
  it holds byte-exact host data with correct channel tags.
- **Not the DACC configuration.** Register readback during the failure:
  `DACC_MR=10300105` -> `TAG=1 MAXS=1 WORD=0 TRGEN=1 TRGSEL=2`,
  `CHSR=00000003` (both channels enabled).
- **Not underrun.** `under=0` throughout.
- **Not USB bandwidth.** The loop moves 1.417 MB/s combined against
  measured ceilings of 3.86 in / 3.02 out / ~4.9 duplex.
- **Not the ring's correctness.** It was rewritten as a proper
  single-producer/single-consumer structure: one writer per counter,
  a two-slot reservation because the PDC owns both the current buffer
  and the one latched in `TNPR`, and a `__DMB()` before publishing.
  That fixed a real underrun storm. It did **not** fix the freeze.
- **Not wire propagation delay.** Picoseconds on a two-inch jumper.
- **Not the trigger path, the DACC, or the ADC interaction.** Measured
  2026-08-21 with command `M`: gen's flash sine played through play's
  exact DACC + TIOA1 + TC1 configuration, capture running at 200 kHz,
  start ordering matched to `L`. Live `ADC_CDR[7]` swung the full DAC
  range (686 / 3330 / 1261 / 2084 / ...) while `ADC_CDR[6]` held mid
  scale. This kills remaining suspects 3 and 4 below. **The freeze
  needs USB duplex traffic to manifest.** Suspects 1 and 2 are what is
  left.

## Remaining suspects, in order

1. **Interaction between the two service loops.** `play_service()` and
   `stream_service()` both run from `main()`. Playback alone works;
   adding capture breaks it. This is the strongest lead.
2. **Shared UOTGHS access.** `usb_cdc_read()` (bulk OUT) and
   `usb_cdc_write()` (bulk IN) touch the same peripheral from the same
   loop. Different endpoints, but worth confirming no register
   read-modify-write races.
3. **Interrupt interaction.** `ADC_Handler` runs at NVIC priority 0,
   `DACC_Handler` at 1. Verify the DACC handler is not being delayed or
   pre-empted in a way that matters.
4. **Something in `stream_start_capture_only()` disturbing the DAC
   side.** It calls `acq_init()` and `acq_start()`, which touch PMC,
   ADC and TC0 channel 0. TC0 channel 1 drives the DAC. Confirm no
   collateral damage.

## The next diagnostic to run

**Implemented 2026-08-21 as command `D`** (and
`host/loopback.py --diag`, which triggers it mid-run). It snapshots to
memory while both loops run and prints only afterwards:

- `play_produced` / `play_consumed` / `play_endtx_seen` /
  `play_svc_calls` over time
- the live `DACC_TPR` decomposed into ring slot + offset, plus
  `DACC_TCR`/`TNPR` and the half-word the PDC will fetch next
- `ADC_CDR[7]` / `ADC_CDR[6]`: the converter's live last A0/A1 result,
  bypassing the ring, the framer and USB entirely
- `acq_produced` / `acq_consumed`

One run distinguishes "ring stalls" from "PDC on a stale address" from
"service starvation" from "capture path serving stale data while the
pin actually moves".

**It has not yet run under `L`, because the native port is physically
absent** (see Environment). Run
`python3 host/loopback.py --diag --seconds 5` the moment the port is
back. If `cdr7` swings while the frames show a frozen A0, the capture
data path is lying; if `cdr7` is frozen too, watch whether `tpr` walks
the slots host data lands in.

Note the freeze table only ever tested DC under `P`; a sine under `P`
has still never been tried. With the port back, a `P` + sine run
(playback and USB OUT active, no capture, no USB IN) is the cheapest
next bisection after the `L` diagnostic.

Also fixed while blocked: `usb_cdc_read()` used to release an OUT bank
after a clipped read, discarding the tail; any short packet from the
host then shifted the sample stream and scrambled channel tags. It now
resumes at an offset and releases the bank only when drained. This is
on the play path but predicts garble, not a clean mid-scale freeze, so
the freeze is probably still there - retest under `L` regardless.

## Hard-won facts the next session must not rediscover

- **Never infer firmware state the firmware can report.** A boot counter
  in GPBR plus the reset cause from RSTC explained in one run what took
  many rounds of guesswork. `boot_log()` exists; use it. Validate any
  new counter before trusting it, the way GPBR was validated with a
  software reset.
- **Discover ports, never hardcode them.** `host/ports.py` identifies
  the control port by the fact that it answers. A stale hardcoded path
  once aimed the 1200-baud erase-and-reset touch at the wrong port and
  wiped the flash without writing anything. `tools/flash.sh` now refuses
  to guess.
- **The board resets whenever the programming port is opened.** This is
  normal, via NRSTB, and it clears the backup domain. The device
  therefore cannot time its own benchmarks; the host keeps the clock and
  the device reports byte counts only.
- **`A0` is ADC channel 7, not 0.** Arduino labels A0..A7 map to
  AD7..AD0 descending; A8..A11 map to AD10..AD13 ascending.
- **Trigger overrun is silent.** An over-fast ADC trigger is ignored
  with no status bit set and looks exactly like clean data at half the
  rate. `ACQ_MIN_RC` (86) guards it, and 86 is correct at any MCK
  because the timer and converter clocks scale together.
- **The DAC is not rail to rail.** 546 mV to 2760 mV, roughly 1/6 to
  5/6 of ADVREF.
- **An asymmetry produced by a scheduler is not a property of the
  hardware.** A duplex measurement of 2.85 in / 0.85 out turned out to
  reproduce the 4:1 ratio of the byte budgets the two loops had been
  given. Equal budgets gave 1.93 / 1.65.
- **Instrument the suspect region before attributing anything to it.**
  A supposed CDC throughput ceiling was really a `delay(10)` hidden
  inside `Serial_::operator bool()`, and a supposed compiler difference
  was refuted by comparing disassembly.

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
- **The native port is physically disconnected as of 2026-08-21.** The
  firmware sees VBUS and asserts attach (`u`: DETACH=0, CLKUSABLE=1,
  SR bit 11 set), but macOS never sends a bus reset and
  `system_profiler` lists only the programming port. The USB topology
  also changed since the last session (prog port moved from
  `usbmodem141301` to `usbmodem14201`), so cables were re-plugged. The
  native cable is powered but not data-connected to the Mac: re-seat it
  into the Mac (not a charger, not a power-only hub port) and check
  with `python3 host/ports.py`. Nothing in firmware changed on the
  attach path; do not debug it in software.

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
| `L` | full loop: playback + capture (**the failing case**) |
| `P` | playback only (**works**) |
| `V` | dump playback ring + DACC registers |
| `D` | loop diagnostic: 12 snapshots at 150 ms, printed afterwards |
| `M` | mimic loop without USB: gen sine on TIOA1 + capture (**works**) |
| `u` | dump USB registers |
| `z` | software reset |

## Host tools

```sh
python3 host/ports.py                       # discover both ports
python3 host/loopback.py --seconds 5        # the full loop test
python3 host/loopback.py --dc 4095          # constant code instead of a tone
python3 host/usbbench.py duplex --seconds 4 # transport benchmark
python3 host/receive.py --send 5 --seconds 5 --expect-hz 953.85
```

`host/loopback.py` skips the first 120 frames before spectral analysis,
because the DAC emits silence until the ring is primed. Analysing from
sample zero measures the start-up gap, not the waveform.

## After the defect is fixed

1. Confirm the loop with a tone: the host's waveform should come back on
   A0 with the expected Goertzel amplitude, and A1 should stay flat.
2. Push the single pair toward the ADC ceiling: 453 ksps per channel at
   906,738 sps aggregate.
3. Then consider the second pair. Budget for two pairs is 2.85 MB/s of
   DAC input plus 1.81 MB/s of ADC output, about 4.66 MB/s combined,
   against a measured duplex best of 4.96. Viable but tight, and it
   needs the direction budgets biased toward OUT.
4. Revisit endpoint DMA. It would restore the invariant that the
   processor never touches sample data, and give real headroom. The
   primitives exist in `drivers/usb_cdc.c` (`usb_dma_in_start`,
   `usb_dma_out_start`) but stall after a single transfer; the status
   register handling is the likely culprit.
