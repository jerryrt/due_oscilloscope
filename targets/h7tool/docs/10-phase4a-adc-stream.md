# Phase 4a: the CH1 acquisition path (image7, builds a/b/c)

`fw/image7/main.c`: ADC1 channel 2 (PF11, scope CH1) with the stock settings from
docs/05 (16-bit, single-ended, 1.5-cycle sampling, TIM3 update trigger, CKMODE 3,
BOOST by silicon revision, offset calibration), DMA1 stream 1 in double-buffer
mode writing straight into the payload area of 32 frame slots in D2 SRAM
(0x30001000), frames streamed over the bulk IN endpoint of image5. A full ring
points the DMA at a scrap slot, counts the frame as lost and flags the next
frame. The front end starts as stock does (both channels DC, gain 0).
Vendor requests: IN 0x03 clock meter, IN 0x04 acquisition counters (incl. the
ADC clock the settings should give), OUT 0x10 sample period, OUT 0x11 ADC
experiment knobs (sampling time, free-running, CKMODE, async prescaler), OUT
0x12 raw 74HCT595 byte. Tools: `h7_usb_probe.py acq|rate|adcx|fe`,
`h7_stream_check.py --adc`.

## Established (linux-x1, 2026-11-02, unit rev_id 0x2003)
- **Mechanics.** 1 Msps and 2 Msps triggered: 0 gaps, 0 bad CRC, 0 lost, 0
  missed TC, 0 ADC overruns; delivered samples equal rate x time to 0.03 %
  (4,998,720 of 5,000,002 at 1 Msps).
- **A bug the checker found.** Frames written and armed in the same pass failed
  every header CRC: the header stores had not reached SRAM when the USB DMA read
  them. A `dsb` before arming fixed it (phase 2 hid this by preparing a
  transfer ahead).
- **Rate check.** `h7_stream_check.py` now fails a capture whose delivered
  samples differ from `sample_rate_hz x time` by more than 1 %, because the
  next finding gave valid frames at the wrong rate.

## Measured, not yet explained: the conversion cycle
Triggered by TIM3, every trigger converts at 2.5 Msps (period 80) and up to
2.22 Msps tested below it; at 2.86 Msps (period 70) and above every second
trigger is lost (3.33 -> 1.67, 4 -> 2.0, 5 -> 2.5 Msps delivered), while the
header still claimed the requested rate. Free-running (no trigger), CKMODE 3:

| sampling time code | cycles | period per sample | step |
|---|---|---|---|
| 0 | 1.5 | 400.0 ns | |
| 1 | 2.5 | 440.1 ns | +40 ns / 1 cycle |
| 2 | 8.5 | 680.1 ns | +280 ns / 7 cycles |
| 3 | 16.5 | 1000.3 ns | +600 ns / 15 |
| 4 | 32.5 | 1640.4 ns | +1240 ns / 31 |
| 5 | 64.5 | 2920.6 ns | +2520 ns / 63 |

So one ADC cycle is 40 ns (25 MHz) and a conversion at 1.5 cycles takes 10 of
them, which is what ST's formula (sampling + 0.5 + N/2 = 10 for 16 bits, from
forum posts quoting the datasheet, not read from it *(check)*) gives. The
register setting (HCLK 200 MHz / 4) says 50 MHz, so the effective clock is half
of what the register arithmetic gives. CKMODE 2 and 1 gave exactly 5.0 and 10.0
Msps (effective 50 and 100 MHz), so the factor of two is constant across modes;
why is not established *(check: an undocumented divide in the synchronous path,
or the ADC's bus clock being 100 MHz)*. Asynchronous modes returned no data (the
kernel clock source was not set up).

Other evidence: the vendor PC-software changelog (`h7tool_docs/vendor/
pc-app-ChangeLog.txt`, line 1462) says the 5 Msps option was removed because "in
practice 16-bit only reaches about 3M"; a forum post quotes 3.6 Msps as the
fastest 16-bit setting, i.e. a 36 MHz ADC clock *(check, 2018 post)*.

**No hardware ceiling is claimed.** What is established: the stock-equivalent
settings deliver every trigger up to 2.5 Msps. Whether CKMODE 2 (5 Msps) or 1
(10 Msps) give *accurate* data is exactly what the accuracy gate must decide;
free-running at CKMODE 1 already shows a wider spread (32,985..36,197 against
36,100..37,000) *(not yet interpreted)*. The firmware refuses periods below 80
for now (`MIN_PERIOD`), a guard and not a spec.

## Accuracy gate: NOT passed
With DAC0 wired to CH1 (and a common ground, reported by the owner), CH1 did
not respond at all: codes held 36,6xx (std 56-70) for Due DAC codes 512, 1536,
2560, 3584 in every ADC configuration, for 74HCT595 coupling/gain bytes 0x88,
0x00 and 0x08, and with a full-swing 1 kHz square on DAC0. The Due native port
was bounced (`=200Z`) in case it was not playing, with the same result. So
either CH1 is not receiving the signal (wiring, or the Due not driving it), or
the front end needs something this image does not do. Open; the next step is a
known level on CH1 that does not depend on the Due (for example the H7's own
3.3 V pin on CH1).
