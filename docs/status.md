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
| ADC aggregate ceiling | 976,744 sps (RC 86); RC 85 silently halves |
| Multiplexer crosstalk | +/-1 code at slow tracking |
| USB, Arduino CDC | 0.8 MB/s gapless, ~0.95 MB/s ceiling |
| USB, bare-metal CDC | **1.97 MB/s gapless at full ADC rate** |
| printf, 40-char line | 3600 us |
| GPIO set+clear pair | 138.3 ns (Track A) / 71.5 ns (Track B) |

## Next

1. Understand why the UOTGHS interrupt stops firing after the first
   reset. Polling works, but the cause is unknown and may bite elsewhere.
2. Vendor-class endpoint with UOTGHS DMA, to get the CPU out of the
   sample path entirely. No longer needed for throughput; still the
   right architecture.
3. Burst mode, for capture bursts above the sustainable stream rate.
4. Twelve-channel capture, now that the transport can carry full rate.
