# Status and Known Issues

Updated after the streaming milestone.

## Working

| Capability | Track A | Track B |
|---|---|---|
| UART printf, LED, HardFault report | yes | yes |
| DAC/ADC loopback, sweep, crosstalk | yes | yes |
| TC-triggered ADC + PDC ping-pong | yes | yes |
| Trigger-rate verification | yes | yes, plus refusal past the ceiling |
| TC-triggered DAC playback (TAG mode) | yes | yes |
| Framed binary streaming | **yes, over USB CDC** | **yes, over UART** |
| Host deframe / demux / tone check | yes | yes, same receiver |

Both tracks produce the same measurement from independent code:

```
                       Track A        Track B
tone amplitude (A0)    1371.9         1371.5   codes
DC channel (A1)            0.1            0.1  codes
rate ratio                1.001          1.000
CRC errors / seq gaps       0/0            0/0
```

## Not working: the bare-metal USB device

`drivers/usb_cdc.c` does not enumerate. The host resets the port once and
then suspends it.

Verified correct by live register dump (`u` command):

```
CTRL=02009000  USBE=1 OTGPADE=1 FRZCLK=0 UIMOD=1 UIDE=0
DEVCTRL        DETACH=0  SPDCONF=0
SR             CLKUSABLE=1
PMC_USB=1      (UPLL selected)  PMC_SR.LOCKU=1
EP0            CFGOK set, EPT bit 0 set
DEVIMR=1008    EORSTES + PEP_0 enabled
```

So: clocks locked, PHY enabled, device attached, EP0 configured and
accepted, interrupts unmasked. One `EORST` arrives and is serviced. No
`SETUP` ever follows, and the bus subsequently reads `SUSP` with
`EP0CFG` and `DEVEPT` cleared back to zero.

Ruled out during debugging:

- Missing `PMC_USB_USBS`, so the PHY ran from PLLA rather than the UTMI
  PLL. Fixed; not the whole story.
- `NBTRANS` left at zero, which makes the controller reject the endpoint
  configuration. Fixed; `CFGOK` now sets.
- `DEVEPT` written by assignment rather than OR, which disabled every
  previously configured endpoint. Fixed.
- Full Speed forced instead of negotiated High Speed, to test whether the
  high-speed chirp was failing. No change, so the fault is not
  speed-specific.
- Configuring EP0 before attach rather than only in the reset handler.
  Made it worse: no reset interrupt at all.

Most likely remaining causes, in order: a second bus reset that clears
the endpoint configuration and whose interrupt is being missed, or
something in the attach sequence that leaves the pull-up in a state the
host only half-accepts. Diagnosing further really wants a USB protocol
analyser; the device-side registers all read correct.

**Interim**: Track B streams over the programming-port UART instead. The
frame format is byte-identical, so `host/receive.py --uart` handles it
unchanged. It is bandwidth-limited to about 11.5 kB/s at 115200 baud,
which is why the demonstration runs at a 2 kHz trigger. Nothing about the
acquisition path is limited; only the transport.

## Measured figures

| Quantity | Value |
|---|---|
| DAC output range | 546 mV to 2760 mV |
| ADC aggregate ceiling | 976,744 sps (RC 86); RC 85 silently halves |
| Multiplexer crosstalk | +/-1 code at slow tracking |
| USB CDC sustained | 0.8 MB/s gapless, ~0.93 MB/s ceiling |
| printf, 40-char line | 3600 us |
| GPIO set+clear pair | 138.3 ns (Track A) / 71.5 ns (Track B) |

## Next

1. Bare-metal USB enumeration, ideally with a bus analyser.
2. Vendor-class bulk endpoint driven by UOTGHS DMA, which is the
   architecture's actual target and the only way past the CDC ceiling.
3. Burst mode, which decouples sample rate from link rate entirely and
   would let the full 976 ksps be captured over either transport.
