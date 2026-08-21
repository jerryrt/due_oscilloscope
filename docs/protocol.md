# Host Protocol

Two channels, deliberately separated:

| Port | Path | Traffic |
|---|---|---|
| Native (`SerialUSB`) | `/dev/cu.usbmodem1411401` | **Binary sample frames only** |
| Programming | `/dev/cu.usbmodem141301` | ASCII control commands, status, debug logs |

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

Default frame: **8192 bytes = 16 x 512**, comprising a 32-byte header and
8160 bytes of payload (4080 samples at 16-bit).

### Header (32 bytes)

```
off sz  field             notes
---------------------------------------------------------------------
 0   4  magic             "DUE0" - resync anchor
 4   1  version           = 1
 5   1  flags             see below
 6   1  bits_per_sample   = 12
 7   1  packing           0 = 12-bit right-aligned in 16-bit LE
                          1 = packed 12-bit (2 samples per 3 bytes)
 8   4  seq               monotonic frame counter, wraps at 2^32
12   4  sample_rate_hz    per-channel trigger rate
16   2  n_samples         sample count in payload (all channels)
18   2  channel_mask      bit n set = A_n present in the sequence
20   4  timestamp_us      free-running TC-derived microseconds
24   4  overrun_count     cumulative RXBUFF + GOVRE events since reset
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
  this board the floor is 976,744 sps aggregate, i.e. `TC_RC >= 86` at
  `TIMER_CLOCK1`, divided by the number of enabled channels.
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
