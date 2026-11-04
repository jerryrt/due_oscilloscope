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

Which model byte this unit's boot loader holds, and whether the app uses
the same table, are not yet read.

## First LCD run (image 18a, bench linux-x1, 2026-11-03)

`fw/image18` drives the pins above with a hand-clocked SPI, the boot
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

`fw/image19` reads the expander's ID register over a hand-clocked I2C
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

## Next

- Locate the app's LCD, backlight, key and LED code (SPI5 base is not a
  literal in the app; search for the SPI5 register offsets and the
  display init sequence by its command bytes).
- Read the boot loader's board-flag test (RAM 0x24000270 + 12) and the
  app's channel writes to assign RUN and CHG among P1_0..3 and P1_5..6.
- Get the AW9523B datasheet and confirm the register meanings.
- A test image that drives the chip over PB6 and PG0 and dims the
  backlight (P0_0) and the two LEDs, with a build that does not run the
  chip init so the boot loader's leftover state is separated from ours.
- Read what sets the model byte at 0x24000022, and which model this
  unit's panel is (1.3 inch 240x240 in docs/01 suggests model 0 or 1).
- Compare with the app's table, starting from the string at 0x0812c716. A pin-decoding
  script over the HAL calls proved unreliable on this code; read the
  call sites by hand.
- Find the key reads (GPIO IDR users) and the RUN and CHG writers.
