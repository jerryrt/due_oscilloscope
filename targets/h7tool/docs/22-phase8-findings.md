# 22 - Phase 8 findings: LCD, keys and LEDs from the stock code

Results of the phases in docs/21. Every row names the address it was read
from, in `H7-BOOT.bin` (boot loader v2.06, base 0x08000000) or
`h7_tool_app(V2.33).bin` (base 0x08020000), disassembled as in docs/03.
Tag *code* means read from the disassembly only; nothing here has been
observed on the unit yet.

## 8.0 Method

The boot loader is HAL-style code: port bases come from literal words, so
a scan for them finds the GPIO users. The app builds its addresses with
movw/movt pairs, so a scan of the disassembly finds those. Both scans
and the call-site counts were run on the two images.

## Findings so far

| Item | Finding | Where | Tag |
|---|---|---|---|
| Backlight, boot loader | PWM at 20 kHz on **GPIOH pin mask 0x200 (PH9)** with TIM12, duty = 10000 x level / 255 | `H7-BOOT.bin` 0x080099e0; pin mask is the shifted TIM12 base at 0x080099f8 | code |
| Backlight, app | Not located yet; the app has no TIM12 literal | `h7_tool_app(V2.33).bin` | open |
| Buzzer, app | Pin chosen by a flag from the board register: PH9 on this unit (docs/03) | app 0x0802b6e0 | code; the beep was heard |
| Soft I2C (TVCC pot) | SCL PI7, SDA PF15 | `H7-BOOT.bin` 0x080127b0..0x08012964 | code; matches docs/03 |
| SPI5 pins, boot loader | GPIOH clock on, SPI5 clock on (APB2ENR bit 20), **PH6 and PH7 as alternate function 5**, so SCK PH6 and data PH7 as in docs/01 | `H7-BOOT.bin` 0x08011b54..0x08011bd8 | code |
| LCD control pins, boot loader | GPIOE, GPIOG, GPIOB and GPIOH clocks on; **PE1, PG15 and PB6 set as push-pull outputs** (chip select and D/C as in docs/01; PB6 is the I2C clock, see below); PE1 driven high and PH6 high at start | `H7-BOOT.bin` 0x0800c114..0x0800c1ce | code |
| SPI5 handle | 8-bit or 16-bit data size chosen by the caller (8 at 0x0800c56e), with an optional DMA setup | `H7-BOOT.bin` 0x080119fc | code |
| PB6 and PG0 as a serial pair | A routine clocks 8 bits with PB6 toggled as a clock and PG0 as data in and out (BSRR on GPIOB and GPIOG, IDR on GPIOG bit 0) | `H7-BOOT.bin` 0x08010d28..0x08010e88 | code |
| Panel identity | The app carries the text "ST7789 / %dx%d" and `lcd_*` drawing function names | app 0x0812c716, 0x080bf300 | code |
| ULPI pins | AF10 on the ports listed in the boot loader's GPIO init at 0x08004fb0 | `H7-BOOT.bin` | code |

docs/01 gives PB6 as the LCD reset and PG0 as the second key. The boot
loader pulses PB6 before the display commands, but PB6 is also the clock
of the I2C bus to the expander (below) and PG0 its data line, and image
19a showed the display undisturbed while PB6 toggled. So PB6 is the I2C
clock, the panel resets itself at power-on, and the pulse is no proof of
a reset line.

PH9 is the backlight in the boot loader and the buzzer in the app on this
unit's board code. Either the app drives the buzzer from the same pin as
the boot loader's backlight, or the app's flag path differs from what was
read. This is the first thing to settle: no test image drives PH9 until
it is.

## LCD, from the boot loader (8.3)

Primitives, all in `H7-BOOT.bin` and all *code*:

| Primitive | Address | Does |
|---|---|---|
| write data byte | 0x08009a50 | PG15 high (BSRR 0x8000), PE1 low (CS), one SPI5 byte through 0x0800c568, PE1 high |
| write data halfword | 0x08009a78 | as above, high byte then low byte |
| write command | 0x08009aa8 | PG15 low (BSRR 0x80000000), PE1 low, one SPI5 byte, PE1 high |
| delay | 0x0801102c | SysTick based; the unit is probably microseconds *(check)* |

So CS is PE1 (active low) and D/C is PG15 (low = command). The pin
setup (8.3 above) and these writes agree.

Panel bring-up at 0x0800c850:

1. Panel power enable: GPIOH BSRR 0x8000, so **PH15 high** (docs/01 agrees).
2. A panel-model byte at RAM 0x24000022 (0 or 1 for the first
   sequence, 2 for the second) selects the sequence below.
3. Delay 50000, PB6 low, delay 200, PB6 high, delay 10000, then the
   commands. The pulse is on PB6, which is the I2C clock; see below.

Commands for model 0 or 1 (0x0800c88e..0x0800c9f4), command then data:

| Command | Data |
|---|---|
| 0x36 | 0x00 |
| 0x3a | 0x05 |
| 0xb2 | 0x0c 0x0c 0x00 0x33 0x33 |
| 0xb7 | 0x35 |
| 0xbb | 0x19 |
| 0xc0 | 0x2c |
| 0xc2 | 0x01 |
| 0xc3 | 0x12 |
| 0xc4 | 0x20 |
| 0xc6 | 0x0f |
| 0xd0 | 0xa4 0xa1 |
| 0xe0 | 0xd0 0x04 0x0d 0x11 0x13 0x2b 0x3f 0x54 0x4c 0x18 0x0d 0x0b 0x1f 0x23 |
| 0xe1 | 0xd0 0x04 0x0c 0x11 0x13 0x2c 0x3f 0x44 0x51 0x2f 0x1f 0x1f 0x20 0x23 |
| 0x21, 0x11, 0x29 | none (inversion on, sleep out, display on) |

Model 2 (0x0800ca28..0x0800cb8a) differs in 0x36 = 0x60, 0xbb = 0x1c,
0xc3 = 0x0b and its two gamma tables, and ends with the same three
commands. Window commands 0x2a, 0x2b and 0x2c are used with 16-bit
operands for drawing (0x0800c6e8). The boot loader sends 0x11 and 0x29
with no delay between them; a test image should wait after sleep out
all the same.

The table for model 0 and 1 gave correct colours on this unit. Which
model byte this unit's boot loader holds, and whether the app uses the
same table, are not read.

## First LCD run (image 18a, bench linux-x1, 2026-11-03)

`fw/ui-tests/image18` drives the pins above with a hand-clocked SPI, the boot
loader's model 0/1 table, a four-band test pattern and a 10% PWM on PH9,
for 20 s, then returns to the boot loader. Observed by the owner:

| Item | Result |
|---|---|
| Panel power PH15, CS PE1, D/C PG15, SCK PH6, data PH7 | Correct: the pattern is right (PB6 was pulsed as well; it is not shown to be a panel reset) |
| Init table, model 0/1 | Correct: the image is right |
| PH9 at 10% duty, 20 kHz | **The buzzer sounded for the whole run** |

So on this unit PH9 reaches the buzzer, as the stock app's buzzer code
says (docs/03), and a 10% PWM is enough to sound it. Image 18b, the same
picture with PH9 never touched, showed the pattern and the buzzer stayed
silent. So **the backlight is lit without PH9**: it comes on with the
panel power on PH15, or from a pin not yet found, and PH9 is the buzzer
on this unit. The boot loader's PH9 PWM, which docs/01 calls the
backlight, belongs to another board code. Backlight brightness control
on this unit is not known; the stock app's board-code flag (docs/03)
selects the pin set and its other branch is unread.

## The I2C LED and key chip (boot loader, code)

The two-wire exchange on PB6 and PG0 is a soft **I2C bus, PB6 = SCL and
PG0 = SDA**, and the device on it at 8-bit address **0xB6** (7-bit 0x5B)
is a 16-bit I/O expander with LED dimming, **AW9523B** by its register
map *(check against its datasheet, which is not in the repository)*.

| Item | Finding | Where |
|---|---|---|
| Write primitive | start, address, register, value, each with an acknowledge, stop | `H7-BOOT.bin` 0x080009c8, bit routines 0x08010d28..0x08010e88 |
| Init | register 0x04 = 0xFE, 0x05 = 0x90, 0x06 = 0xE1, 0x07 = 0xFF, 0x11 = 0x10, 0x12 = 0xFE, 0x13 = 0xF0 | 0x08011510 |
| Mode bits | 0x12 = 0xFE puts P0_0 in LED mode and P0_1..7 in GPIO mode; 0x13 = 0xF0 puts P1_0..3 in LED mode and P1_4..7 in GPIO mode | same |
| Dim channel to register | channels 0..7 use 0x24 + n, 8..11 use 0x20 + (n - 8), 12..15 use 0x2c + (n - 12) | 0x08000964 |
| Backlight | `set_backlight(level)` at 0x080099a0 uses channel 0 (**P0_0**, register 0x24) when a board flag (RAM 0x24000270 + 12) is 1, and the PH9 PWM otherwise | 0x080099a0 |
| Keys | the key function tests bits of a state byte (RAM + 14) | 0x080009f8 |

So on a board with the chip the **backlight is chip output P0_0, not
PH9**, and the chip's other LED-mode outputs, P1_0..3, are the candidates
for the RUN and CHG LEDs. The schematics (D253-6, D254-6) are older than
this unit and are not evidence here: they show no I2C chip and a PH9
backlight, which the code and the runs contradict. What the evidence
supports is that the boot loader drives the backlight through the chip
before the app starts, and that the 18b image kept it lit without ever
touching it, so the backlight is on only because something set it. That
the display board needs a driven level, rather than staying on by
itself, is read from the old D254 sheet (a 10 K pull-down on the
transistor base) *(check)*. The same fact would explain why the PI8 run
LED of image 1 showed nothing, if the LEDs are on the chip.

## Image 19a: the expander, observed (bench linux-x1, 2026-11-03)

`fw/ui-tests/image19` reads the expander's ID register over a hand-clocked I2C
on PB6 (SCL) and PG0 (SDA), sets the boot loader's mode registers with
the LED current at a quarter of the range, drives P1_0..P1_3 one at a
time (register 0x20 + n, 3 s each), then steps the backlight output
P0_0 (register 0x24) through off, 0x10, 0x80 and 0xFF.

| Item | Result |
|---|---|
| ID register 0x10 read at 0xB6 | acknowledged and 0x23: the chip and the bus are as read from the boot loader |
| P1_0..P1_3 stepped in turn | the RUN and the CHG LED both lit and went off; which output is which was not noted |
| P0_0 dimming | the backlight brightness changed with the register |
| Display during the I2C traffic | stayed correct |

So PB6 and PG0 as I2C and the chip at 0xB6 are observed, and the
backlight is dimmed by P0_0. The display staying correct while PB6
toggled shows PB6 is not the panel reset; the panel resets itself at
power-on, so the reset pulse in image 18 was not what made it work.
The assignment of RUN and CHG to P1_0..P1_3 is still to be read off a
run that names each step.

## Panel geometry and the LED outputs (images 20a and 21a, bench linux-x1, 2026-11-03)

Image 20a filled all 320 rows of the controller's 240-wide memory with
eight numbered bands, with MADCTL 0x00.

| Item | Result |
|---|---|
| Rows shown | all eight bands, so the glass shows all 320 rows: it is a 240x320-memory panel, not 240x240 (docs/02 lists 2.0 inch 320x240 screens) |
| Memory against glass | the grey band (last rows) was at the top and the black squares (column 0 side) at the right: at MADCTL 0x00 the memory is turned 180 degrees |
| 240-row picture of images 18 and 19 | drew only the 240 rows at the bottom of the glass, leaving the top 80 rows to the boot loader's content |

Image 21a/21b, MADCTL 0x60 (landscape, a 320x240 picture), reported
corners: the picture's top-left corner (red) appeared at the screen's
bottom left, and its bottom-left corner (blue) at the screen's bottom
right. That is the picture turned 90 degrees counter-clockwise, and both
corners that share the picture's left edge landing on one screen edge
fits a portrait glass of 240 columns by 320 rows. So the upright setting
is probably MADCTL 0xC0 (the boot loader's direction 1) in portrait,
which image 22a confirmed: at MADCTL 0xC0 with the window set to
columns 0..239 and rows 0..319 the F was upright and readable, red was
at the top left and green at the top right, and the white border showed
on all four sides (the owner did not name the bottom corners). So the
glass is portrait, 240 columns by 320 rows, and all 320 rows are shown;
the boot loader's 80-row offsets belong to its 240x240 sub-window.

The LED walk lit (forward run, then the same four steps in reverse
order, by the owner's reports; the reverse run did not name CHG's colours):

| Output, register | RUN or CHG | Colour |
|---|---|---|
| P1_0, 0x20 | CHG | green *(one report)* |
| P1_1, 0x21 | CHG | red *(one report)* |
| P1_2, 0x22 | RUN | red |
| P1_3, 0x23 | none seen | - |

No green RUN LED lit at any step. Both runs agree on the output for each
LED; the CHG colours rest on one report each.

## The SPI5 path (images 24 to 26, bench linux-x1, 2026-11-04)

The driver (`fw/ui/h7_ui.c`) can write the panel through SPI5 instead
of clocking PH6 and PH7 by hand: master, mode 3, 8-bit frames, software
slave select, simplex transmit, data on the pad the peripheral calls
MISO (IOSWP), kernel clock / 4.

| Item | Result |
|---|---|
| First run | never got a free FIFO slot: SR read 0x202 and CR1 0x1000 |
| Cause | a mode fault: with software slave select on and SSI still low, a master reads slave select as asserted, switches itself off and refuses to start. SSI must be written before the configuration that turns software select on |
| After the fix | SR and CR1 at the end read 0, nothing timed out, and the picture and the digits drawn through SPI5 were correct |
| Registers read back | CFG1 0x10000007, CFG2 0x87428000, SPI45 clock select 0 (the APB2 clock), APB2ENR 0x00100000 (SPI5 only), AHB4ENR 0xD2 (GPIOB, E, G, H) |
| Full-screen fill (153,600 bytes), instruction cache off | about 247 ms (timer calibrated by a 100 ms SysTick delay) |
| Same, instruction cache on | about 123 ms |
| Hand-clocked pins, for scale | about 3 s |

The wire at a quarter clock needs about 77 ms for the fill, so both
SPI5 figures are limited by the CPU feeding the FIFO one byte at a time
and not by the clock. Only DMA (the stock firmware uses DMA2 Stream3)
removes that. The driver also keeps a fallback: the first SPI5 wait that
gives up hands the panel to the hand-clocked pins, resends the byte
that failed and keeps the status it saw.

## SPI5 at the PLL clock, read over USB (image 27, bench linux-x1, 2026-11-04)

Image 27 is image 17 (core at 400 MHz) with the driver and three
exploring opcodes of the control function (PEEK 0x45, POKE 0x46,
EXPLORE 0x47; `tools/h7_explore.py`), so the numbers come back over USB
and need no reading from the screen. Cycle counts are DWT CYCCNT.

| SPI5 CFG1 MBR | divisor | full-screen fill | wire time at 100 MHz kernel |
|---|---|---|---|
| 0 | kernel/2 | 25.3 ms | 24.6 ms |
| 1 | kernel/4 | 56.1 ms cache off, 49.2 ms cache on | 49.2 ms |
| 3 | kernel/16 | 197 ms | 196.6 ms |

The kernel clock is therefore 100 MHz *(inferred from the three rows
agreeing with the wire time)*. At this core clock the CPU keeps up with
the FIFO, so the fill runs at wire speed and DMA would free the CPU
without making the fill shorter. A pattern of eight colour bands and a
one-pixel grid, drawn at kernel/2 (50 MHz), was reported clean by the
owner, so the driver now uses MBR 0, the stock rate. Observed on one
unit with one pattern. The earlier 247 ms and 123 ms figures were taken
at the 64 MHz reset clock.

## DMA and an 80 MHz clock (image 27, bench linux-x1, 2026-11-04)

`h7lcd_fill_dma` and `h7lcd_blit` feed the SPI5 FIFO from DMA2 stream 3
(DMAMUX1 channel 11, request 86 for SPI5 TX, the transfer completing is
the proof of the number). A solid fill repeats a two-byte pixel in
circular mode, so it needs two bytes of memory and no frame buffer.

| SPI5 kernel clock | divisor | bit clock | full-screen fill | fps |
|---|---|---|---|---|
| APB2, 100 MHz | 2 | 50 MHz | 24.7 ms by DMA (25.3 ms by CPU) | 40 |
| PLL2_Q, 160 MHz | 2 | 80 MHz | 15.35 ms by DMA | 65 |

The 80 MHz case is not in the driver: the images start only PLL1, so
PLL2 is started by hand (HSE 25 MHz / 5, x128, Q /4; PLL2 divider
register 0x58024438, PLLCFGR bits 7:6 = 2 and bit 20, CR bit 26) and
D2CCIP1R SPI45SEL set to 1. The owner reported the band-and-grid
pattern clean at 50 MHz by CPU and at 80 MHz by DMA (one unit). The
panel's datasheet limit was not checked *(check)*.

What the scope and the generator use: ADC1 DMA1 stream 1 (DMAMUX1
channel 1), ADC3 DMA2 stream 1 (channel 9), the DAC DMA1 stream 5, USB
its own internal DMA. DMA2 stream 3 is free, and the buffers live in
AXI SRAM or SRAM3, which the images do not use (SRAM1 and SRAM2 hold
the capture ring). The functions block until the data is out (about 15
to 25 ms per full screen), so before the display shares a main loop
with acquisition they must become start and poll calls that cost a
bounded slice per pass (CLAUDE.md invariant 7). The host model does not
cover the DMA path: it is verified on the unit only.

A stuck SPI5 on the unit. After the PLL2 experiments, SPI5 stopped
shifting: a byte in the FIFO and CSTART set, SR 0x10012 (TXP, TXTF, one
frame left), nothing on the wire, from a clean software reset and with
no driver involved (written by hand over POKE). Not the kernel clock
(HSI made no difference) and not the APB2 divider. Software resets did
not clear it and neither did earlier images; entering the boot loader
with the OK key held at plug-in did, and the same image then worked.
Cause unknown *(check)*. The first PLL2 attempt also wrote the PLL2
divider to 0x434 (PLL1's fractional register, with its enable bit
clear) and started PLL2 at its reset divider (about 322 MHz), which may
be what wedged it. If it comes back, the key-entered boot loader is the
recovery.

Without the boot loader screen first (same day). A plain software
reset starts the app directly, with no boot-loader display state behind
it: three of three resets gave a working SPI5, zero errors and the
full-screen fills above, and then nine more resets and three flashes
over USB with no key press did too. The screen was black after a reset
only until the driver ran, as the init needs. So the display driver
does not depend on the boot loader having set the panel up. Once,
after the third of the first three resets, the control function
stopped answering about two minutes later while the display stayed up
and the data port still enumerated; it was recovered with the OK key
at plug-in and has not recurred in about 25 minutes of resets, flashes
and idling *(not explained)*.

## PLL2 in the driver and screen capture (image 27, bench linux-x1, 2026-11-04)

The driver starts PLL2 itself when it sets up SPI5 (`pll2_start`): only
from the state the images leave RCC in (PLL1 from the HSE with M 5,
PLL2 off with no input divider), HSE 25 MHz / 5 x 128 / 4 = 160 MHz,
SPI45SEL moved onto it once PLL2 reports ready. A PLL that is already
on, a different clock tree or no lock leaves SPI5 on the 100 MHz APB2
clock and the PLL off again. The host model checks every register it
writes (PLL1 untouched, the only CR bit changed is PLL2ON, SPI45SEL
only after ready) and breaks each guard on purpose. On the unit the
full-screen DMA fill takes 15.6 ms with it, shadow copy included.

The panel cannot be read back (its data pad is the write line), so
capture works from a shadow copy: `h7ui_set_shadow` gives the driver
150 KB (image 27 uses AXI SRAM at 0x24010000) and every pixel sent is
also stored there, big-endian RGB565. The shadow is the driver's record,
not a reading of the glass: draw the whole screen once after switching
it on (image 27 clears to black in its init). A solid DMA fill writes
its shadow with 16-bit stores, because per-pixel stores cost 11 ms a
frame.

The host model now covers all of it. It builds the panel's memory from
the bytes that were actually sent, by the pins, by SPI5 or by DMA, and
the tests require the shadow to equal it; it models DMA2 stream 3 and the
DMAMUX request (direction, sizes, circular count, TXDMAEN, stream left
off) and the cases that must not start DMA: no scratch pixel, SPI5
already fallen back, the window set-up falling back, a transfer that
never ends. Each guard is broken on purpose in the tests. On the unit
the same check is a capture of a band-and-grid pattern drawn by DMA
against the pattern computed on the host: 0 of 230,400 bytes different.
Two driver faults came out of writing it: `h7lcd_fill_dma` did not
re-check SPI5 after opening its window, and TXDMAEN was cleared while
SPE was still on.

The protocol gained `SCREEN 0x48` (`fw/ctl_h7.h`): an empty body gives
the size, format and a draw count; offset and count return up to 440
bytes with the draw count, so a host can tell that the picture changed
while it read. `tools/h7_screen.py` reads the whole picture (0.13 s on
the unit), retries a torn read and writes a PNG. An image that keeps no
shadow leaves it out of its capability list and answers
CTL_ERR_OPCODE.

## The scope and generator monitor (image 28, bench linux-x1, 2026-11-04)

Image 28 is image 17 with the display: `fw/ui/h7_mon.c` draws a 30 x 20 text screen (8 x 16 font from `tools/gen_font.py`) of the unit's
state, `fw/ui/h7_ui.c` carries it, the RUN LED follows running or playing, and `tools/h7_screen.py` captures it over USB. It shows the
scope (run state, channels, sample rate, gains and coupling, frames, sent, lost, missed/bad/overrun) and the generator (play state,
update rate, units queued and consumed, underruns, minimum occupancy and resumes, short), with the up-time and build. Rows turn red or
yellow on loss and underruns. It reads counters and configuration through `h7_get_status` and `h7_get_config` and never the sample
stream, so CLAUDE.md invariant 1 holds for this target. A waveform trace would have to read samples; it is not built. The owner's
decision is that in stream mode the host draws the traces and the state monitor is the device's display.

What it cost to share the loop with acquisition, measured by DWT cycle counts on the unit and by the device's own loss counters
(`STATUS`, 10 s at each rate, the same run on image 17 as control):

| version | worst main-loop step | lost at 2.0 and 2.5 MS/s in 10 s |
|---|---|---|
| a row drawn in one step, shadow copied from the DMA buffer | 1670 us (render 430, shadow 1230) | gate fails at 1 MS/s |
| row copied from fast RAM, one step per row | 334 us | 2 and 3 frames |
| row in slices, blocking LED write | 92 us | 2 and 3 frames |
| row in slices, LED written one bus edge per pass | about 45 us | **0 and 0**, as image 17 |

Three things were learned, each by profiling and none by guessing. The CPU reading a buffer in SRAM3 costs about 60 cycles a byte, so
the shadow is copied from a core-coupled RAM copy and nothing is read back from the DMA buffer. A row done in one step is too long for
the top rate, where a frame arrives every 0.4 ms: it is done in slices of a few tens of microseconds. The blocking I2C write of the LED
(87 bus phases of 20 us, 1.8 ms) costs 2 or 3 frames each time the scope starts, and only the top rates show it; the daemon gate at 1 MS/s
did not. The display DMA's priority made no difference, and rendering alone did not either. With the unit running image 28 the gate passes
three times in a row and the loss test shows nothing lost at 1, 2 and 2.5 MS/s. A session that plays and captures with the slow Python reader
(`h7_play_check.py`) loses frames on image 17 as well, 996 against 642 shown on the screen at that moment, so the red `lost` there is the
host's.

DMA2 stream 3 and DMAMUX1 channel 11 belong to the display; the ADCs use DMA1 stream 1 and DMA2 stream 1, the generator DMA1 stream 5. The
line buffer and the pixel scratch are in SRAM3, the capture shadow (150 KB) in AXI SRAM, the row being drawn in core-coupled RAM.

## Next

On hold (docs/21). What would be next, were it resumed:

- The cause of the stuck SPI5 (after the PLL2 divider was written to PLL1's fractional register and PLL2 started at about 322 MHz) and of
  the one control-function hang. Both were cleared by entering the boot loader with the OK key held at plug-in.
- Locate the app's key reads (GPIO IDR users) and its RUN and CHG writers, to settle CHG's two colours and find the keys.
- Read the boot loader's board-flag test (RAM 0x24000270 + 12) and what sets the model byte at 0x24000022; compare the app's display
  table, starting from the string at 0x0812c716. A pin-decoding script over the HAL calls proved unreliable on this code; read the
  call sites by hand.
- A first power-on with nothing from the boot loader behind it.
