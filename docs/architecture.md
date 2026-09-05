# Architecture

**Organising principle: the CPU never touches sample data.** It moves
pointers and nothing else. Every design decision below follows from that.

> **Implementation status.** The PDC halves of this design are built
> and verified, and the playback USB hop now runs on UOTGHS endpoint
> DMA: bulk OUT data lands in the ring with no CPU byte-copy,
> multi-slot spans keep the transfer independent of main-loop latency,
> and progress publishes from the channel's BUFF_COUNT mid-flight. The
> capture USB hop runs on it too: `stream_core_start()` arms IN DMA on
> every USB start, and the header is written into the headroom in front
> of that buffer's payload, so a frame is one transfer and the header is
> the only thing the processor writes into it. Two details also differ
> from the sketches below, from measurement rather than accident:
> host-fed playback runs the DACC from its own timer channel (TIOA1) so
> the AWG rate is independent of the capture rate, and the playback
> stream uses half-word transfers with TAG rather than `WORD=1`.

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

## The Arduino CDC and the zero-copy rule

*(verified against `arduino:sam@1.6.12`)*

The core's `UDD_Send()` spins on `TXINI` and copies into the endpoint
FIFO one byte at a time, and the core never touches the UOTGHS DMA
registers except to zero them. So `SerialUSB` makes the CPU read every
sample byte, with a blocking wait per packet.

That violates the invariant at the top of this document. It is not a
performance detail to be optimised later; it is the wrong shape.

What this rules out, and what it does not:

- **Ruled out**: `SerialUSB` for *continuous* streaming. There the copy
  is deadline-bound and competes with acquisition.
- **Viable as an interim step**: `SerialUSB` for *burst* mode. Capture
  is already finished when the transfer starts, so the copy costs CPU
  but misses no deadline — roughly 1–2 ms per 8 KB frame. This is a
  reasonable way to reach a working end-to-end loopback before the
  vendor-class path exists, and it should be treated as scaffolding
  rather than the destination.
- **Still fine**: `SerialUSB` in Track A sketches, and CDC on the
  *programming* port for the ASCII control channel, where throughput is
  irrelevant.
- **Not a gain**: reconfiguring endpoint size or banking. Both are
  already optimal at 512 bytes and 2 banks. Nothing is left on the table
  there.

### Measured on this host

Both tracks were run end to end at increasing trigger rates:

| Aggregate | Data rate | Track A | Track B |
|---|---|---|---|
| 400 ksps | 0.80 MB/s | gapless | gapless |
| 800 ksps | 1.60 MB/s | gapless | gapless |
| 976 ksps | 1.95 MB/s | **gapless** | **gapless** |

**CDC carries the ADC's entire output.** An earlier version of this
section reported a 0.93 MB/s ceiling and concluded that continuous
full-rate capture over CDC was impossible. The ceiling was an artefact of
calling `(bool)SerialUSB` in the service loop, since
`Serial_::operator bool()` ends with `delay(10)`. Removing that call
took Track A from 0.946 to 1.969 MB/s unchanged in every other respect.

Timing only the region inside `SerialUSB.write` gives an effective
8.9 MB/s, so at full rate the transport occupies roughly a fifth of wall
time and about 80% of the processor remains idle.

What still argues for the DMA path is the invariant at the top of this
document, not throughput. `UDD_Send` copies every sample byte with the
processor, which is the one thing the architecture forbids. A
vendor-class endpoint driven by UOTGHS DMA is therefore still the right
destination, but it is now an efficiency improvement rather than the
only way to reach full rate.

One CDC hazard remains, found the hard way: `Serial_::write` spins on
`TXINI` once the host has set the line state, and `availableForWrite()`
returns a constant rather than real space. If the host stops draining
mid-write, **the board wedges** with no way for firmware to detect or
escape it. Recovery needs the 1200-baud touch, which is a hardware path
through the 16U2 and works even with the CPU hung.

## The hard problem: producer/consumer mismatch

The ADC produces at a rigid 1.95 MB/s. USB drains at a **variable** rate
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

Sizing example: two 16 KB ping-pong buffers fill in ~8.4 ms at 1.95 MB/s.
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
ADC -> SRAM via PDC      1.95 MB/s
SRAM -> USB via DMA      1.95 MB/s
combined SRAM load       3.90 MB/s
32-bit bus @ 84 MHz    ~336 MB/s theoretical
                       -> ~1% utilisation
```

**The silicon is not the constraint.** USB throughput and the analog
front end are.

## Verification hooks

Required from the first commit of driver code, because there is no debug
probe:

- **GPIO toggle at ISR entry/exit** — **measured at ~69 ns** per direct
  `PIO_SODR`/`PIO_CODR` write on this board (138.3 ns for a set+clear
  pair). Cheap enough to sit inside the ADC ISR without perturbing the
  timing being measured, and observable externally. printf measures
  3600 us for one 40-char line, roughly 26000x more: it would change the
  system, a pin toggle does not. Use direct register writes, not
  `digitalWrite()`, which measures ~31x slower. See `docs/debugging.md`.
- **`GOVRE` / `RXBUFF` / sequence counters** carried in every frame
  header, giving the host dropped-sample detection with no real-time
  cost.

See `docs/debugging.md`.

## Bring-up order

Each stage is independently verifiable, which matters without a
debugger. All four are done; the order is kept because it was right:

1. TC + ADC + PDC ping-pong, dumping a few buffers over UART printf
2. Verify sample timing against the configured trigger rate
3. Add DACC, close the DAC0-to-A0 loopback
4. Replace the printf sink with the real USB path

Step 2 earned its place: it found the silent trigger-overrun cliff
(RC 86), and later caught a stale preset that a clock change had
quietly invalidated. If the trigger rate is wrong, every subsequent
measurement is wrong in a way that looks like an analog fault.
