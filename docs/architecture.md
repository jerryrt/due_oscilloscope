# Architecture

**Organising principle: the CPU never touches sample data.** It moves
pointers and nothing else. Every design decision below follows from that.

## Datapath

```
                 TC0 ch0  (TIOA0)  <- single master timebase
                    |
        +-----------+-----------+
        v                       v
   ADC trigger             DACC trigger
        |                       |
      [ADC]                  [DACC]
        | ADC_LCDR              ^ DACC_TDR
     PDC-RX                  PDC-TX
        |                       |
        v                       |
  +-----------------+    +--------------+
  | capture ring    |    | waveform buf |
  | (SRAM bank A)   |    | (SRAM bank B)|
  +--------+--------+    +--------------+
           |
    UOTGHS DMA (linked descriptors)
           |
           v
     bulk IN endpoint  ->  host
```

Sample data is written once by PDC and read once by USB DMA. **No memcpy
anywhere.** Zero-copy is the single largest win available; everything
else is second-order.

## Three independent DMA engines

The SAM3X8E provides genuinely concurrent movers, not one shared
controller. ADC-to-SRAM, SRAM-to-USB and SRAM-to-DAC all proceed
simultaneously on different hardware.

| Engine | Serves | Notes |
|---|---|---|
| PDC | ADC, DACC (separate channels) | Pointer + counter, plus next-pointer for chaining. Counters are 16-bit |
| UOTGHS DMA | USB endpoints | Per-endpoint, **linked-list descriptors**. A circular chain ships buffers with zero CPU involvement |
| DMAC | mem-to-mem, other peripherals | 6 channels, present on SAM3X8E. Unused so far |

The UOTGHS descriptor capability is the underused piece. Building a
circular descriptor chain in SRAM means USB transmission needs no
per-buffer interrupt at all.

## Timebase

Drive `ADC_MR.TRGSEL` and `DACC_MR.TRGSEL` from the **same TIOA output**.

This buys two things:

1. **Deterministic sample clock.** Hardware triggering, not
   `ADC_MR.FREERUN`. Free-run rate depends on the ADC state machine and
   jitters; jitter smears FFT bins. Non-negotiable for spectral work.
2. **Phase-coherent generation and capture.** DAC output and ADC
   sampling hold a fixed, known relationship. This is what makes the
   Phase 1 loopback a real measurement, and what enables
   transfer-function work later.

The ADC sequencer converts **all enabled channels per trigger event**.
So a 12-channel configuration triggered at 87.5 kHz yields 1.05 Msps
aggregate. Size the TC period against the per-trigger sequence, not
against the aggregate rate.

## ADC path

- `ADC_EMR.TAG = 1` — channel index in `ADC_LCDR[15:12]`. Free, since
  16 bits move regardless. Makes the stream self-describing and lets the
  host resync after a glitch.
- PDC receive pointer targets `ADC_LCDR`, transferring half-words.
- **Ping-pong**: write `RNPR`/`RNCR` while `RPR`/`RCR` are active. When
  `RCR` reaches zero the next pair is promoted automatically and `ENDRX`
  fires. Reload the next-pointer in that handler.
- **`RXBUFF` is the overrun alarm**: it means both `RCR` *and* `RNCR`
  reached zero, i.e. the reload deadline was missed and samples were
  lost. Wire it to a counter.
- `ADC_ISR.GOVRE` / `ADC_OVER` likewise.

Overrun counters must appear in the frame header. **Silent corruption is
far worse than a reported gap** — the host must be able to distinguish
"continuous" from "spliced across a hole".

## DAC path

- `DACC_MR.WORD = 1` — PDC moves 32-bit words carrying two samples,
  halving transaction count.
- `DACC_MR.TAG = 1` — bits [13:12] of each half-word select DAC0 or
  DAC1, so a **single** PDC stream drives both channels.
- For a periodic generator waveform, re-arm the same buffer in the
  `ENDTX` handler, or chain it to itself. It then repeats indefinitely
  with no maintenance.

## USB path

- **512-byte bulk packets** (High-Speed maximum) and multi-bank
  endpoints, so the next bank fills while the current one drains.
- Buffer size must be an exact multiple of 512 **and** a whole number of
  sample frames. Example: `8192 bytes = 16 x 512 = 4096 samples`.
  Short packets mid-stream waste a transaction slot and confuse framing.
- Circular UOTGHS descriptor chain for continuous shipping.

## The hard problem: producer/consumer mismatch

The ADC produces at a rigid 2.1 MB/s. USB drains at a **variable** rate
set by the host. That mismatch is the actual design challenge, not
bandwidth.

Backpressure is not available — an ADC cannot be stalled mid-sequence.
The honest options are:

- **Drop and report** (continuous mode): N-deep ring of buffers, not
  simple ping-pong. Depth absorbs host latency jitter. On overflow, flag
  it in the frame header.
- **Burst mode** (scope mode): capture a fixed buffer set at full rate,
  stop, ship at leisure, re-arm. **Sample rate is fully decoupled from
  USB throughput.** This is how real scopes work and it is the mode to
  build first — it is both easier and more useful.

Per-frame sequence numbers let the host *prove* continuity rather than
assume it.

## Memory placement

96 KB SRAM in two banks (64 KB + 32 KB) on a multi-layer AHB matrix.

If the banks sit on separate matrix slaves — **to be confirmed in the bus
matrix chapter** — then placing the **ADC capture ring in one bank and
the DAC/USB buffers in the other** lets PDC writes and USB DMA reads
proceed without arbitrating against each other. Free parallelism from
linker script placement alone.

Two supporting facts:

- **Cortex-M3 has no data cache**, so there are no coherency concerns and
  no cache maintenance around DMA buffers.
- Align buffers to 4 bytes: PDC requires half-word alignment, UOTGHS DMA
  prefers word.

Sizing example: two 16 KB ping-pong buffers fill in ~7.8 ms at 2.1 MB/s.
That interval is the USB deadline per buffer.

## Interrupt priorities

```
ADC ENDRX        highest — above configMAX_SYSCALL_INTERRUPT_PRIORITY
USB DMA          lower
everything else  lower still
```

Placing the ENDRX handler above the RTOS syscall ceiling means the kernel
can never mask or delay it. The cost is that this handler **must not call
any FreeRTOS API** — it touches only a lock-free ring. A lower-priority
task collects the data.

That constraint is the correct architecture regardless of RTOS, and it is
the concrete form of "keep acquisition out of the scheduler path". See
`docs/rtos.md`.

## CPU budget

```
ADC ENDRX ISR:  write RNPR/RNCR to next ring slot; bump head   (~5 writes)
USB DMA ISR:    advance tail; refill descriptor if not circular
main / task:    nothing in the data path
```

With 8 KB buffers that is roughly 128 interrupts/sec.

```
ADC -> SRAM via PDC       2.1 MB/s
SRAM -> USB via DMA       2.1 MB/s
combined SRAM load        4.2 MB/s
32-bit bus @ 84 MHz    ~336 MB/s theoretical
                       -> ~1% utilisation
```

**The silicon is not the constraint.** USB throughput and the analog
front end are.

## Verification hooks

Required from the first commit of driver code, because there is no debug
probe:

- **GPIO toggle at ISR entry/exit** — one to two cycles, ~12–24 ns at
  84 MHz. Cheap enough to sit inside the ADC ISR without perturbing the
  timing being measured, and observable externally. A printf in that
  handler would change the system; a pin toggle does not.
- **`GOVRE` / `RXBUFF` / sequence counters** carried in every frame
  header, giving the host dropped-sample detection with no real-time
  cost.

See `docs/debugging.md`.

## Bring-up order

Each stage is independently verifiable, which matters without a debugger:

1. TC + ADC + PDC ping-pong, dumping a few buffers over UART printf
2. Verify sample timing against the configured trigger rate
3. Add DACC, close the DAC0-to-A0 loopback
4. Replace the printf sink with the real USB path

Do not skip step 2. If the trigger rate is wrong, every subsequent
measurement is wrong in a way that looks like an analog fault.
