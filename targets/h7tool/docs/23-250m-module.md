# 23 - The 250M scope module: found, measured, and what it would take to reprogram it

Observed on the unit, bench linux-x1, 2026-11-04, with the stock app V2.33 running and the module's CH1 wired to VOUT (probe on 1x). Tags as in
docs/02: **observed** is something this session measured; **vendor** is the manual or the stock files; **unknown** is not in either.

## Found

The module is connected and alive. It answers at Modbus address 0x10 behind the H7-TOOL only when TVCC is 3.3 V; the unit was at 1.4 V
(a front-panel setting from an earlier test), and at that value every read at 0x10 returned the not-ready exception `10 83 03`. After
FC6 on address 1, register 0x0085 = 3300 (measured 3.311 V) and the enable cycle (0x0212 = 2, 1 s, 1, 1.5 s) the settings block read back as
the documented defaults `[0,1,1,4,4,0,0,12,0,0,0,0,0,0,1,0,1]`, the capture-done flag was 1, and the status block read
`[114.90, 0, 212.72, 1.699, 125.55, 0, 223.36, 1.699]`. Those eight floats are identical to the example in the earlier notes, taken with a
different signal, so they are fixed module values (offsets and levels), not measurements; what they mean is unknown. TVCC was left at 3.3 V.

## What the converter does (observed, range codes 0 to 9, 1x probe, VOUT as the source)

Samples are 8-bit codes and saturate at 0 and 255. Gain and zero from three DC levels each, two captures averaged, the first capture of each
point discarded (after a range change or a level change the first capture is wrong: a range-6 reading of 75 at 0 V against 117 once settled):

| range code | codes per volt | mV per code | span | vendor list |
|---|---|---|---|---|
| 0 | 2.83 | 353 | about +-45 V | +-40 V |
| 1 | 5.74 | 174 | +-22 V | +-20 V |
| 2 | 14.35 | 69.7 | +-8.9 V | +-8 V |
| 3 | 28.70 | 34.8 | +-4.4 V | +-4 V |
| 4 | 56.93 | 17.6 | +-2.2 V | +-2 V |
| 5 | 133.4 | 7.5 | +-0.96 V | +-800 mV |
| 6 | 264.6 | 3.78 | +-0.48 V | +-400 mV |
| 7 | 677 | 1.48 | +-0.19 V | +-200 mV |
| 8 | 1394 | 0.72 | +-0.09 V | +-80 mV |
| 9 | 2539 | 0.39 | +-0.05 V | +-40 mV |

Code n is the vendor's range list in order, about 10 to 20 % wider than nominal. The earlier notes' 37 mV per code at range 6 was ten times
off: that measurement went through a 10x probe. The code at 0 V is 118.0 at ranges 0 and 1, 117.4 and 116.4 at 2 and 3, 114.4 at 4, 117.4,
116.5 and 113.4 at 5 to 7, and 109.5 and 100.1 at the two most sensitive; it is not the middle of the range and it moves with the range.
Noise: at ranges 0 to 3 the spread of a DC capture is 0.1 to 0.7 code. From range 6 up it grows in proportion to the gain (1.5, 4 to 6, 7 to 12 and
16 codes), which is VOUT's own noise of about 6 mV rms times the gain, so VOUT limits what can be said of the module's noise at the sensitive
ranges. No independent meter is in the loop, so absolute accuracy is only as good as VOUT (an earlier measurement of VOUT against a Due input: 1.8 mV rms residual, and an offset of
about 34 mV that could not be separated from that input's own).

Timebase: a 1000 Hz square from the generator (type 2 in the generator block) sampled at rate index 12 has its rising edges 1000.0 samples apart.

## The hardware trigger (observed, range 6, 2048 samples at 1 MS/s, a 1 kHz 0.4 V triangle, 20 captures per setting)

- Trigger mode `0x010C`: 0 (auto) and 1 (normal) are free-running. Every capture completes in 0.03 s even with a level of +10 V that the signal
  never reaches, and the samples at the trigger point are scattered. Mode 2 (single) is the live trigger: +10 V never completes, and the
  captured edge sits at the requested position.
- The level is a float32 in volts across `0x0109` and `0x010A`. The edge field `0x010E` is not honoured: asking for rising puts a rising edge at the
  trigger point in 20 of 40 captures and a falling edge in 17, asking for falling gives 19 and 21. The vendor's own screen has a trigger value
  and no edge, which is consistent: this is a level-crossing trigger in either direction.
- Position: 222 of 360 captures (62 %) had an edge at the requested point, in the requested direction or not (this counts any edge within 60
  samples; nine of the 18 settings were below 60 %). When they did, the edge landed between 14 samples early and 7 late for rising (mostly 2 to 7
  late) and 6 to 20 late for falling, with a spread of 4 to 12 samples (microseconds) from capture to capture. The spread is consistent with
  VOUT's noise on the triangle's 0.8 mV per microsecond slope; the lateness of falling edges is a hysteresis or a latency that was not separated.
- Not tested: both channels, other rates (the 125 and 250 MS/s indices), depths above 2K, CH2 as the trigger source.

Read-out was not the problem: repeated captures of a DC level agree to 0.1 code, and blocks read in the documented order and discarded for the
first 100 samples were clean.

## What the generator block does (observed)

In the 10-word block at address 1, register 0x0100, word 1 = 2 gave a square at the requested frequency and levels, 3 a triangle at the requested
frequency, and 4 and 5 triangle-like waves at about two and three times the frequency (not explained). Word 1 = 0 switches the output off, and
every test ended with that.

## Programming the module from the H7-TOOL

The H7-TOOL is a CMSIS-DAP probe (a WinUSB interface and an HID one are up while the stock app runs, no mode switch needed) and its device
library has the RP2040 (`Device/Rasberry/RP2040`: a Lua script and the Raspberry Pi Pico flash algorithm; the changelog adds it with "new:
Raspberry Pi RP2040"). So the H7-TOOL can program an RP2040 in place, through its **SWD port** (GND, TVCC, SWCLK, SWDIO, RESET), which is not
the D0 to D9 header that the module uses for its serial and SPI link.

`tools/h7_swd_probe.py` asks the probe to connect, reset the SWD line, select the RP2040's core 0 and read the debug-port ID, with no memory or
flash access. With the module plugged in as it is, it answers ACK 7 (no target). That says nothing is connected to the SWD port, not that the
module cannot be programmed: nothing in the vendor files says whether the module exposes SWCLK and SWDIO, and no schematic of the module
exists. Two things are needed before anything is written: the module's SWD pads (or its USB boot mode, the vendor ships a UF2) found on the board,
and a read-back of the whole flash first, because the stock firmware may keep calibration there.

## Writing our own firmware for it

Possible in principle (the RP2040 is a generic part and the stock image is 49 KB), and it would let the trigger be done properly. Not started.
What it needs that is not known: which RP2040 pins are the ADC data bus, the ADC clock, the front-end switches and offsets, and the link to
the H7 (the stock image can be read for the pins its code configures, as the LCD was); and what the ADC and the front end are. The stock image
names no parts. Measured so far: an 8-bit converter, the sample rate verified at 1 MS/s, the input range and gain table above.
