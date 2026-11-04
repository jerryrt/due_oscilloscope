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

## The module's USB socket and the backup of its firmware (observed, 2026-11-04)

The module has a USB socket on its RP2040. In normal operation it is silent on USB (the 49 KB image never touches the RP2040's USB
controller); with BOOT held while it is connected it enumerates as `2e8a:0003` "RP2 Boot", serial E0C9125B0D9B, with a drive RPI-RP2 whose
`INFO_UF2.TXT` says "UF2 Bootloader v3.0, Model: Raspberry Pi RP2, Board-ID: RPI-RP2": the ordinary RP2040 boot ROM, no custom board id.

Before anything could be written, the whole flash was read through the boot ROM's PICOBOOT interface with `tools/rp2040_picoboot.py`
(`tests/test_rp2040_picoboot.py`: it can send only READ and the two commands that set up reading, and the test fails with that guard removed).
Saved in `~/MCU.Projects/h7tool_backup/rp2040_module/` (outside the repo, with a README and SHA256SUMS):

- `module_flash_2048KB.bin`: the full 2 MB flash, read twice in one session and once more in another, all identical, sha256
  `ef6881c9120bf9d12584cb859797743b38ad680850b78ca46eefa59f6bb87d7f`. The window repeats at 2 MB, so the flash is 2 MB.
- The firmware occupies the first 49,152 bytes (0xC000); everything after is 0xFF. There is no calibration region elsewhere in the flash, so
  the fixed status values (114.9, 212.7, 1.699 ...) are in the firmware or computed.
- **It is not the vendor's `DSO_250M(V1.04).bin`.** The first 256 bytes (the boot stage) match, but 39,619 of the vendor file's 49,028 bytes
  differ, the module image is 124 bytes longer, and the reset vector is `0x10008271` against `0x10008269`. The module runs a different build; which
  one is unknown. The module's own flash is therefore the only copy of what it runs.

Flash reads need the boot ROM told how to read: right after connecting, the flash window returns the cache's contents (the first bytes of
"flash" and of SRAM were identical); after EXIT_XIP and ENTER_CMD_XIP the first 256 bytes equal the vendor boot stage. A 16 KB read stalls the
interface; 4 KB reads work. The boot ROM itself reads normally.

## Programming the module from the H7-TOOL

The H7-TOOL is a CMSIS-DAP probe (a WinUSB interface and an HID one are up while the stock app runs, no mode switch needed) and its device
library has the RP2040 (`Device/Rasberry/RP2040`: a Lua script and the Raspberry Pi Pico flash algorithm; the changelog adds it with "new:
Raspberry Pi RP2040"). So the H7-TOOL can program an RP2040 in place, through its **SWD port** (GND, TVCC, SWCLK, SWDIO, RESET), which is not
the D0 to D9 header that the module uses for its serial and SPI link.

`tools/h7_swd_probe.py` asks the probe to connect, reset the SWD line, select the RP2040's core 0 and read the debug-port ID, with no memory or
flash access. With the module plugged in as it is, it answers ACK 7 (no target). That says nothing is connected to the SWD port, not that the
module cannot be programmed: nothing in the vendor files says whether the module exposes SWCLK and SWDIO, and no schematic of the module
exists. Two things were needed before anything is written: the module's SWD pads or its USB boot mode (found: the USB socket, above),
and a read-back of the whole flash first (done, above: the stock firmware keeps no calibration outside its image).

## What the module's own firmware sets up (emulated start-up, not measured on hardware)

`tools/rp2040_trace.py` runs the backed-up image from its reset vector in an emulator (`unicorn`, in a scratch venv; the boot ROM's first 8 KB are
read from the module, the rest of the ROM cannot be read over PICOBOOT) and reports the registers it writes. The trace reaches the firmware's main
loop, 40,407 register writes in, where it waits for something from outside (PIO FIFO and GPIO input reads), and is the same on every run. What it
shows (**from the code**; the readings of what a pin is *for* are marked *inferred*):

- **Clock.** 12 MHz crystal, PLL at 12 x 125 / (3 x 2) = **250 MHz** for the system clock (the RP2040 is overclocked from its 133 MHz), a second PLL at 48 MHz.
- **Sample capture.** PIO0 state machine 0 runs `in pins, 16` from **GPIO0 to GPIO15**, autopush at 16 bits; seven DMA channels drain its FIFO into
  seven 32 KB buffers at 0x20000000 (about 224 KB, which fits "200K depth"). Sixteen pins sampled together suggests two 8-bit channels, GPIO0 to 7
  and GPIO8 to 15 *(inferred)*; the same sampler at 250 MHz is 250 Msps. The state machines are set to 125 for the divider at the end of start-up, so
  the real rate is set when a capture is configured.
- **Pacing.** State machine 1 of PIO0 is a counter (`pull`, `out y`, `jmp x--` loops, then `irq wait`) that sets GPIO25; state machine 0 waits on
  GPIO25 and drives GPIO23 and GPIO24 with side-set. Both PIO0 interrupt lines are armed (IRQ0 for state-machine IRQ 0, IRQ1 for 1), but only
  PIO0_IRQ_1 is enabled in the NVIC at the end of start-up. This is the pre-trigger and post-trigger machinery, so it is where the module's trigger lives.
- **ADC clock.** GPIO22 is switched to PWM (slice 3, channel A); the PWM itself is not configured during start-up. It is probably the converter's sample
  clock, set per rate *(inferred)*.
- **Link to the H7: an SPI slave in PIO1, not a UART.** State machine 0 waits for GPIO29 low (chip select), then for GPIO18 rising, and samples
  GPIO16 (`in pins, 1`, in_base 16); state machine 1 shifts out on GPIO19. So MOSI is GPIO16, SCK is GPIO18, MISO is GPIO19, CS is GPIO29, both at
  a divider of 1 (250 MHz oversampling). That fits the H7's SPI4 (SDO D2, SDI D3, SCK D5) with D4 the chip select; the manual's UART pins (D0, D1)
  are not used by this image at start-up.
- **Other pins.** GPIO20 and GPIO21 are outputs (SIO) driven low with pull-ups; GPIO26 and GPIO27 are outputs (their ADC function unused). What they
  switch is not shown by start-up code; the front end's range and coupling controls are the likely users *(inferred)*.
- **Interrupt handlers present:** SysTick, PIO0 IRQ 0 and 1, GPIO bank 0 (a pin-change handler). None for USB, SPI, UART, DMA or ADC: the application
  has no USB (as seen), and no hardware serial port.

Not yet seen: the range, coupling and trigger code, which only runs when the H7 sends a command. The next step is to feed the emulator the same
SPI words the H7 sends (a settings block write with a different range each time) and read the pin and PIO changes it causes.

## Writing our own firmware for it

Possible in principle (the RP2040 is a generic part and the stock image is 49 KB), and it would let the trigger be done properly. Not started.
What it still needs: the front-end controls (which pins set the range, coupling and offset, and with what words) and the ADC clock, from the command
paths of the module's image (above: the capture bus, the SPI link and the clock are now known), and what the ADC and the front end are. The image
names no parts. Measured so far: an 8-bit converter, the sample rate verified at 1 MS/s, the input range and gain table above.
