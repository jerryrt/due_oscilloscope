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
| LCD control pins, boot loader | GPIOE, GPIOG, GPIOB and GPIOH clocks on; **PE1, PG15 and PB6 set as push-pull outputs** (CS, D/C and reset as in docs/01); PE1 driven high and PH6 high at start | `H7-BOOT.bin` 0x0800c114..0x0800c1ce | code |
| SPI5 handle | 8-bit or 16-bit data size chosen by the caller (8 at 0x0800c56e), with an optional DMA setup | `H7-BOOT.bin` 0x080119fc | code |
| PB6 and PG0 as a serial pair | A routine clocks 8 bits with PB6 toggled as a clock and PG0 as data in and out (BSRR on GPIOB and GPIOG, IDR on GPIOG bit 0) | `H7-BOOT.bin` 0x08010d28..0x08010e88 | code |
| Panel identity | The app carries the text "ST7789 / %dx%d" and `lcd_*` drawing function names | app 0x0812c716, 0x080bf300 | code |
| ULPI pins | AF10 on the ports listed in the boot loader's GPIO init at 0x08004fb0 | `H7-BOOT.bin` | code |

PB6 is the LCD reset in docs/01, but the boot loader also toggles it as
the clock of a two-wire serial exchange with PG0, and PG0 is the second
key in docs/01. The boot loader's panel reset sequence uses PB6, so PB6 is the reset;
the serial routine is a separate use of the pin and is not an LCD one.

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
   commands. So **PB6 is the panel reset, low-active**.

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

## Next

- Locate the app's LCD, backlight, key and LED code (SPI5 base is not a
  literal in the app; search for the SPI5 register offsets and the
  display init sequence by its command bytes).
- Read what sets the model byte at 0x24000022, and which model this
  unit's panel is (1.3 inch 240x240 in docs/01 suggests model 0 or 1).
- Compare with the app's table, starting from the string at 0x0812c716. A pin-decoding
  script over the HAL calls proved unreliable on this code; read the
  call sites by hand.
- Find the key reads (GPIO IDR users) and the RUN and CHG writers.
