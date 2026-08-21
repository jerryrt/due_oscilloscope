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

## Headline result: the CDC ceiling was an implementation limit

Same host, same receiver, same wire format:

| Trigger | Aggregate | Required | Track A | Track B |
|---|---|---|---|---|
| 200 kHz | 400 ksps | 0.80 MB/s | 0.807, ratio 1.001 | 0.806, ratio 1.000 |
| 400 kHz | 800 ksps | 1.60 MB/s | 0.871, **ratio 0.540** | 1.613, **ratio 1.000** |
| 488 kHz | 976,744 sps | 1.95 MB/s | 0.946, **ratio 0.480** | **1.969, ratio 1.000** |

**Track B streams the ADC's entire output continuously, with no gaps.**

The earlier conclusion that continuous full-rate capture was impossible
over CDC was wrong in an important way: it is impossible over the
*Arduino* CDC, whose `UDD_Send` copies into the endpoint FIFO one byte at
a time and spins on `TXINI`. It is not a limit of CDC, of the CDC-ACM
host driver, or of the 512-byte bulk endpoint. Writing whole 512-byte
banks and never spinning more than doubles the sustained rate.

A consequence worth noting: the vendor-class endpoint with UOTGHS DMA,
planned as the only way past the ceiling, is **no longer required** to
reach full rate. It remains the right destination for CPU cost, since
the FIFO copy still has the CPU touching every sample byte, but it is no
longer on the critical path for throughput.

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
