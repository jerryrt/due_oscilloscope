# Status and Known Issues

Updated after full-rate streaming was achieved on Track B.

## Working

| Capability | Track A | Track B |
|---|---|---|
| UART printf, LED, HardFault report | yes | yes |
| DAC/ADC loopback, sweep, crosstalk | yes | yes |
| TC-triggered ADC + PDC ping-pong | yes | yes |
| Trigger-rate verification | yes | yes, plus refusal past the ceiling |
| TC-triggered DAC playback (TAG mode) | yes | yes |
| USB CDC device | Arduino core | **own bare-metal stack** |
| Framed binary streaming | yes | yes |
| Host deframe / demux / tone check | yes | yes, same receiver |
| Host-fed DAC playback over bulk OUT | no | yes |
| Full loop: host waveform out, capture back, simultaneously | no | **yes** |

## Headline result: both tracks reach the full ADC rate

Same host, same receiver, same wire format:

| Trigger | Aggregate | Required | Track A | Track B |
|---|---|---|---|---|
| 200 kHz | 400 ksps | 0.80 MB/s | 0.806, ratio 1.000 | 0.806, ratio 1.000 |
| 400 kHz | 800 ksps | 1.60 MB/s | 1.613, ratio 1.000 | 1.613, ratio 1.000 |
| 488 kHz | 976,744 sps | 1.95 MB/s | **1.969, ratio 1.000** | **1.969, ratio 1.000** |

**Both tracks stream the ADC's entire output continuously, with no gaps**,
over ordinary USB CDC. Over eight seconds each delivers 3845 frames and
about 15.75 MB with zero sequence gaps, zero CRC errors, and a
measured-to-declared rate ratio of exactly one.

### A conclusion that was wrong twice

An earlier version of this document reported that the Arduino CDC capped
near 0.95 MB/s and that the bare-metal stack was roughly twice as fast.
Both the number and the explanation were wrong, and the sequence is worth
recording because the reasoning failed in two different ways.

**First error: blaming the transport.** The 0.95 MB/s ceiling was real
but self-inflicted. `stream_service()` tested `(bool)SerialUSB` on every
pass, and `Serial_::operator bool()` ends with `delay(10)`. Ten
milliseconds of pure sleep per service call was the entire ceiling. The
guard was also unnecessary: `Serial_::write` already returns zero without
blocking when the host has not set `lineState`. Deleting it took Track A
from 0.946 MB/s to 1.969 MB/s with no other change.

**Second error: blaming the compiler.** Before finding that, the gap was
attributed to gcc 4.8.3 versus gcc 15.2.1, on the strength of a measured
1.93x difference in a tight GPIO loop against a 2.07x difference in
throughput. Two experiments killed it:

- Rebuilding Track A with gcc 15.2.1 via
  `arduino-cli --build-property compiler.path=...` made the GPIO loop
  1.93x faster (138.3 ns to 71.5 ns) and left USB throughput **exactly
  unchanged** at 0.946 MB/s. That alone showed the write path was not the
  limit. `UDD_Send` also lives in the prebuilt
  `libsam_sam3x8e_gcc_rel.a`, so the new compiler never touched it.
- Compiling identical source with both compilers and comparing
  disassembly showed the difference is marginal, not 2x:

  ```
  copy_ptr  gcc 4.8.3   cmp / beq / ldrb / strb / adds / b    (6 per byte)
  copy_ptr  gcc 15.2.1  cmp / bne / ldrb.w+ / strb.w+ / b     (5 per byte)
  copy_idx  gcc 4.8.3   identical to gcc 15.2.1, instruction for instruction
  ```

  Track B's writer uses the indexed form, which both compilers compile
  the same way. The GPIO result simply did not generalise to a
  byte-copy loop.

**What actually settled it** was measuring instead of arguing. Timing
only the region inside `SerialUSB.write` gave an effective 8.925 MB/s,
about nine times the achieved rate. That located the cost outside the
transport immediately, and the `delay(10)` was found within minutes.

The transferable lesson: a throughput number is a property of the whole
loop, not of the call you suspect. Instrument the suspect region before
attributing anything to it.

### What survives about the DMA plan

The zero-copy argument is unaffected: `UDD_Send` still has the processor
copying every sample byte into the endpoint FIFO, which contradicts the
architecture's central rule. A vendor-class endpoint driven by UOTGHS
DMA remains the right destination on CPU-cost grounds.

But the throughput argument for it is gone. At full rate the write
occupies roughly a fifth of wall time, so about 80% of the processor is
still idle. DMA is now an efficiency improvement, not an enabler.

## How the USB stack was fixed

It did not enumerate for a long time. Register dumps showed everything
correct: clocks locked, PHY enabled, device attached, EP0 configured with
`CFGOK` set, interrupts unmasked. One `EORST` was serviced and no `SETUP`
ever followed.

Three real bugs were found and fixed along the way:

- `PMC_USB_USBS` was missing, so the PHY ran from PLLA rather than the
  UTMI PLL.
- `NBTRANS` was left at zero, which makes the controller reject the
  endpoint configuration outright.
- `DEVEPT` was written by assignment rather than OR, so configuring each
  endpoint disabled the previous ones.

None of those was the blocker. **The blocker was the interrupt path**:
`UOTGHS_Handler` serviced exactly one bus reset and then never fired
again, even with `PEP_0` unmasked in `DEVIMR`.

The fix was to stop relying on it. `usb_cdc_poll()` services the same
events from the main loop, and the device enumerated immediately at High
Speed. This is not a workaround so much as the right shape: control
transfers happen a few dozen times during enumeration and essentially
never afterwards, so polling them costs nothing, and only the bulk path
needs to be fast.

Why the interrupt never re-fires is still unexplained and worth
returning to, but it no longer blocks anything.

## The full loop works; the "frozen DAC" was the receiver's own bug

The complete chain - host-authored 1 kHz sine over bulk OUT, DAC0,
jumper, A0, ADC, bulk IN - runs simultaneously in both directions:
1024 frames in 5 s with zero sequence gaps, zero CRC errors, zero
overruns, Goertzel amplitude 1371 codes on A0 against a theoretical
maximum of ~1370, and A1 flat at 0.1 codes. DAC consumption at 200 ksps
and capture at 400 ksps aggregate, about 1.24 MB/s combined.

A full session was previously spent on a defect described as "playback
works, capture works, together the analog output freezes at mid scale".
That freeze never existed on the device. A stream from an earlier run
keeps flowing into the kernel's input buffer after the run ends; the
next run's receiver read ~800 kB of those stale frames first - the flat
mid-scale startup of an *old* capture - and the "1 sequence gap" it
reported on every run was the splice between the stale epoch and the
live one. Frame timestamps proved it: the capture contained one epoch at
device time ~0 s and a second at device time ~52 s, inside a 5-second
run. The device-side counters said all along that playback was
consuming host data on schedule, and they were right.

This is the *same* stale-buffer failure mode already recorded below
under "Two host-side bugs that looked like firmware bugs" - it bit
twice because a one-shot `tcflush` at open does not empty a buffer the
device is still refilling. `host/loopback.py` now drains the native
port until it stays silent for a full second, refuses to trust a
capture whose first frame is not near sequence zero, and reports tone
amplitude windowed against device timestamps so a late or intermittent
tone shows as what it is.

Two real firmware fixes came out of the same investigation, verified
independently: `usb_cdc_read()` used to discard the undrained tail of
an OUT bank after a clipped read (one short packet then byte-shifts the
whole sample stream), and the DACC + TIOA1 trigger path was exonerated
on hardware by command `M`, which plays gen's sine through play's exact
configuration with capture running and no USB involved.

The feed-margin problem was then closed for good, and the path there
uncovered a macOS behaviour worth its own record. Four feed policies
were measured: select()-paced writes in a shared loop starve on poll
granularity (~1% shortfall, underruns); free-running blocking writes
saturate the queue, and **a pressured macOS CDC-ACM output path
silently drops ~128-byte chunks that write() has already counted** -
measured as ~75 clean phase jumps per second on the DAC with every
counter on both sides green, and confirmed by byte conservation
(host-written minus device-received ~= jumps x 128 B); clock pacing at
the exact byte rate still dropped at every tested lead. The clean
policy, now in `host/loopback.py`: a real-time thread polls TIOCOUTQ
and bursts 16 KB only into a *truly empty* queue. Result: zero
underruns, zero gaps, 1371 +/- 2 codes in every 40 ms window of a run,
reproducible across tones.

The host threads use `host/rt.py`: macOS's QoS class plus the Mach
THREAD_TIME_CONSTRAINT real-time band (the CoreAudio I/O policy),
stdlib-only via ctypes. There is no thread-to-core pinning on XNU;
the real-time band is the mechanism that exists, and it measurably
suffices.

One firmware lesson came out of the same investigation: a CDC device
must keep accepting bulk OUT even when nothing consumes it, because
macOS's close() waits for in-flight write URBs that a NAKing pipe
never completes, wedging the host process in close() while it holds
the port. The main loop now drains and discards OUT when neither
playback nor a bench sink owns it.

## Two host-side bugs that looked like firmware bugs

Both produced symptoms that pointed convincingly at the device, and both
cost real time. They are recorded because the misdirection is the
lesson.

**Slow parsing dropped bytes.** The receiver parsed each frame inline,
including a per-sample Python loop. At around 0.9 MB/s it could not keep
up, so the port stopped being drained and the kernel buffer overflowed.
The symptom was samples attributed to ADC channels that were not enabled,
plus sequence jumps: exactly what a firmware framing bug looks like.
Splitting capture from parsing fixed it.

**Stale buffered data.** Restarting a stream resets the sequence number
to zero, but bytes from the previous run were still queued in the kernel
buffer. The receiver saw old high-numbered frames followed by new
zero-numbered ones, reported a single enormous sequence jump, and counted
more samples than the ADC could possibly have produced. Flushing the port
before starting the capture clock fixed it.

The tell in both cases was arithmetic: the frame count exceeded what the
configured sample rate could generate. **A receiver reporting more data
than the source can produce is describing its own bug.**

## Measured figures

| Quantity | Value |
|---|---|
| DAC output range | 546 mV to 2760 mV |
| ADC aggregate ceiling | RC 86; RC 85 silently halves. 906,976 sps at MCK 78 (976,744 at the old MCK 84) |
| Multiplexer crosstalk | +/-1 code at slow tracking |
| USB, Arduino CDC | 0.8 MB/s gapless, ~0.95 MB/s ceiling |
| USB, bare-metal CDC | **1.83 MB/s gapless at full in-spec ADC rate** |
| Capture at max in-spec (MCK 78) | 453,488 Hz/ch declared, 453,489 measured, ratio 1.000 |
| Full loop, duplex | 200 ksps DAC + 400 ksps ADC, tone 1371+/-2 in every window |
| USB IN only (RT threaded host) | 5.20 MB/s |
| USB OUT only (RT threaded host) | 5.03 MB/s, byte-perfect vs device counter |
| USB duplex (RT threaded host) | 2.77 in + 2.47 out = 5.25 MB/s combined |
| **Matched loop ceiling** | **453,488 sps DAC + 906,976 sps capture, solid** (under=0, gaps=0, 1372 codes) |
| **AWG (play-only) ceiling** | **1.383 Msps solid** (RC 28, under=0, 2.81 MB/s feed); DACC saturates ~1.41 M over-triggered |
| Asymmetric loop (AWG + 200 kHz monitor) | solid to 600 ksps DAC; 650 k = 4 underruns/5 s |
| USB via endpoint DMA (playback path converted) | IN 32.0 / OUT 26.6 byte-perfect / duplex 16.95 MB/s |
| **Full-rate pair (DAC 907 k + ADC 907 k aggregate)** | runs with **under=0** on DMA playback; purity 90-95% pending IN-side DMA and a cable swap |
| ~1.7 MB/s "gated OUT" cap | explained: DMA re-arm/service latency x transfer granularity, not FIFO interleave; removed by multi-slot spans |
| printf, 40-char line | 3600 us |
| GPIO set+clear pair | 138.3 ns (Track A) / 71.5 ns (Track B) |

## Next

0. `usb_cdc_write` clobbers IN banks when producing faster than the
   host drains: the flood benchmark's device-side counter reads far
   above the wire rate while the host receives a fraction of it. The
   streaming path never outruns the wire so frames are verifiedly
   intact, but the no-spin guard is not doing what it claims and the
   flood counter is meaningless until this is understood.
1. Understand why the UOTGHS interrupt stops firing after the first
   reset. Polling works, but the cause is unknown and may bite elsewhere.
2. Vendor-class endpoint with UOTGHS DMA, to get the CPU out of the
   sample path entirely. No longer needed for throughput; still the
   right architecture.
3. Burst mode, for capture bursts above the sustainable stream rate.
4. Twelve-channel capture, now that the transport can carry full rate.
