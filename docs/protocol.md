# Host Protocol

Two channels, deliberately separated (paths are enumeration-dependent;
discover them with `python3 host/ports.py`, never hardcode):

| Port | Traffic |
|---|---|
| Native (High Speed) | **Binary sample frames** in; playback samples out |
| Programming | ASCII control commands, status, debug logs |

Keeping logs off the data pipe means a stray `printf` cannot corrupt a
sample frame, and the debug stream can be watched in a second terminal
while the host application owns the data port.

---

## Data channel — binary frames

### Framing rules

- **Little-endian** throughout; matches both Cortex-M3 and host x86/ARM.
- **Never ASCII.** `Serial.print(value)` costs 5–6 bytes per sample
  instead of 2 and burns CPU formatting. Binary only.
- Total frame size is an exact multiple of **512** (High-Speed bulk max
  packet). Short packets mid-stream waste a transaction slot and confuse
  host framing.

Frame size in the current firmware: **4096 bytes = 8 x 512**,
comprising a 32-byte header and 4064 bytes of payload (2032 samples at
16-bit, `ACQ_BUF_SAMPLES`). Any exact multiple of 512 with a whole
number of samples is valid under these rules.

### Header (32 bytes)

```
off sz  field             notes
---------------------------------------------------------------------
 0   4  magic             "DUE0" - resync anchor
 4   1  version           = 3
 5   1  flags             see below
 6   2  channel_mask      bit n set = A_n present in the sequence
 8   4  seq               monotonic frame counter, wraps at 2^32
12   4  sample_rate_hz    per-channel trigger rate
16   4  timestamp_us      free-running TC-derived microseconds
20   4  overrun_count     cumulative RXBUFF + GOVRE events since reset
24   4  play_consumed     playback buffers the DAC has taken; 0 when
                          not playing, and 0 from the bench builders
28   4  header_crc32      CRC-32 over bytes 0..27
---------------------------------------------------------------------
32      payload
```

`flags`:

| Bit | Meaning |
|---|---|
| 0 | Overrun occurred since the previous frame — **payload is not continuous with the previous frame** |
| 1 | First frame of a burst |
| 2 | Last frame of a burst |
| 3 | Continuous mode (clear = burst mode) |

### Why there is no payload CRC

USB already provides a per-packet CRC-16 with hardware retry at the link
layer, so a payload CRC would be redundant. More importantly, computing
one would mean the CPU reading all 2.1 MB/s of sample data — which
directly violates the architecture's central rule that the CPU never
touches sample data. The header CRC costs 32 bytes' worth of work and is
kept; the payload is protected by USB itself.

Integrity of the *stream* is established by `seq` and the overrun flag,
not by checksums.

### Payload

With `packing = 0`, each sample is one 16-bit little-endian half-word
straight out of `ADC_LCDR`:

```
bits 15..12   channel index   (present when ADC_EMR.TAG is enabled)
bits 11..0    conversion result
```

The channel tag makes the stream **self-describing**: the host demuxes on
the tag rather than trusting position, and can resynchronise mid-stream
after any glitch. This is free, since 16 bits move regardless.

With `packing = 1`, two 12-bit samples occupy three bytes and the channel
tag is unavailable. This saves 25% of bandwidth (2.1 MB/s to 1.58 MB/s)
at the cost of the host having to trust the sequence order. Use only if
throughput measurement demands it.

### Host receive algorithm

### `play_consumed` is loop mode's rate carrier

The host paces playback against a model of how fast the DAC consumes,
and the converter does not always run at the rate it was asked for - at
886,363 sps it holds one of two rates, picked per run. Closing that loop
needs the device's consumption paired with the device's clock.

In play-only that arrives on a separate bulk-IN record
(`drivers/playstat.h`). In loop mode bulk IN carries frames and the
endpoint is on DMA, so nothing else may write there: the FIFO path and
DMA must not share an endpoint, and a record spliced between frames
would put non-sample bytes inside the sample stream. The header is the
only channel left, and it already carried `timestamp_us` from the same
clock, so this field completes the pair rather than adding one.

It is paid for out of fields that never varied. `bits_per_sample` was
always 12, `packing` always 0, and `n_samples` always `ACQ_BUF_SAMPLES`
- the frame is a fixed 4096 bytes because that is `8 x 512` and one DMA
sends whole packets, so its sample count is architecture, not data.

Growing the header instead was tried and withdrawn. Taking two samples
out of the payload to hold the 4096 moved `ACQ_BUF_SAMPLES` off 2032,
and that cost the ramp test 4 failing runs in 15 against 0 in 15 before
it. The geometry is load-bearing.

A reader that needs the payload encoding takes it from this document
and the frame's `version`; a recording carries the rest in the
daemon's sidecar.

1. Scan for `magic`, validate `header_crc32`.
2. Check `seq == expected_seq`. A gap means frames were lost on the host
   side; the overrun flag means samples were lost on the device side.
   **These are different failures and must be reported differently.**
3. Read `n_samples`, demux by channel tag.
4. Apply per-channel skew correction: consecutive conversions are
   ~0.95 us apart, so channel *k* in the sequence lags channel 0 by
   *k* x conversion period. Deterministic and correctable.
5. Never silently splice across a frame carrying flag bit 0. Either
   report the gap or zero-fill it visibly.

---

## Control channel — ASCII lines

Line-based ASCII over the programming port, so it can be driven by hand
from a terminal during bring-up. That is worth more than compactness here.

Commands are lower-case, whitespace-separated, terminated by `\n`.

| Command | Effect |
|---|---|
| `id` | Identify: firmware version, build hash, capabilities |
| `rate <hz>` | Set per-channel trigger rate |
| `chan <mask>` | Set channel mask, e.g. `chan 0x003` for A0+A1 |
| `mode burst\|cont` | Select capture mode |
| `depth <n>` | Burst depth in samples |
| `gen <wave> <hz>` | DAC waveform: `sine`, `square`, `ramp`, `dc`, `off` |
| `start` | Arm and begin |
| `stop` | Halt acquisition |
| `stat` | Dump counters: overruns, frames sent, ISR timing |
| `reset` | Software reset |

Responses:

| Prefix | Meaning |
|---|---|
| `OK` | Command accepted, optionally followed by data |
| `ERR <reason>` | Rejected |
| `#` | Log/debug line — always ignorable by a machine parser |

Prefixing every log line with `#` means the host parser can consume the
control port without being confused by debug output interleaved into it.

---

## Failure reporting

The device must never present discontinuous data as continuous. Where a
gap cannot be avoided, it is reported:

| Condition | Detection | Reported as |
|---|---|---|
| PDC reload deadline missed | `RXBUFF` | `overrun_count`, flag bit 0 |
| ADC conversion overrun | `ADC_ISR.GOVRE` | `overrun_count`, flag bit 0 |
| Host fell behind | `seq` gap at host | Host-side error |
| Frame corrupted | `header_crc32` mismatch | Host resyncs on next `magic` |
| **Trigger faster than the ADC** | **none - see below** | **must be prevented, not detected** |

### The one failure no status bit reports

Measured: with a trigger period below the ADC's conversion time, the part
**silently ignores every other trigger**. `GOVRE` and `RXBUFF` both stay
at zero. The result is a clean 2:1 decimation that is indistinguishable
from correctly acquired data at half the rate - the samples are valid,
there is no gap, and `seq` stays continuous.

This is the most dangerous failure mode in the system, because every
other one announces itself. A host doing an FFT on such a stream gets
frequencies wrong by exactly 2x with nothing to suggest anything is
amiss.

Two defences, and both are needed:

- **Firmware refuses** a trigger period below the measured floor. On
  this board that is `TC_RC >= 86` at `TIMER_CLOCK1` (correct at any
  MCK, since the timer and ADC clocks scale together; ~907 ksps
  aggregate at MCK 78), scaled by the number of enabled channels.
- **Host verifies** the rate independently: `n_samples` against
  `timestamp_us` deltas between consecutive frames must agree with
  `sample_rate_hz`. A steady 2x discrepancy is this bug.

A visible gap is a bug report. A silent splice is corrupted data that
will be mistaken for a physical signal.

### Ring overflow tears payloads, and no header field can see it

Found during bring-up. When the transport falls behind, the PDC keeps
writing and eventually overwrites a buffer **while it is being
transmitted**. The resulting frame passes its header CRC and carries a
correct sequence number, but its payload is spliced from two different
points in time.

It shows up at once on a channel that should be constant: a DC channel
reading 2051..2059 when healthy read 104..3663 while overrunning.

No header field detects this, because the header is written before the
payload is read out. The producer must prevent it:

- Before sending, compare `produced - consumed` against the ring depth.
  If the writer has lapped the reader, **skip forward to the newest safe
  buffer** and count the discontinuity rather than transmitting a torn
  one.
- The skip is reported through `overrun_count`, so the loss stays
  visible while the delivered samples stay trustworthy.

After the fix the same overload produced zero lost frames, a DC channel
holding 2043..2060, and an overrun count climbing honestly from 59 to
781. The host additionally sees measured rate over declared rate fall to
0.54, which is the independent check that catches it.
