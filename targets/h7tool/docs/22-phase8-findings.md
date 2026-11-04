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
key in docs/01. Until the owner's board is checked, neither pin is
trusted as LCD reset or as a key; the LCD test must find out which
works.

PH9 is the backlight in the boot loader and the buzzer in the app on this
unit's board code. Either the app drives the buzzer from the same pin as
the boot loader's backlight, or the app's flag path differs from what was
read. This is the first thing to settle: no test image drives PH9 until
it is.

## Next

- Locate the app's LCD, backlight, key and LED code (SPI5 base is not a
  literal in the app; search for the SPI5 register offsets and the
  display init sequence by its command bytes).
- Find the LCD command table: no standard ST7789 byte sequence is in
  either image, so follow the callers of the SPI5 handle at 0x080119fc
  and the app's `ST7789 / %dx%d` string at 0x0812c716. Also find the
  panel power enable (PH15 in docs/01) and the CS and D/C writers
  (no GPIOE BSRR literal exists in the boot loader). A pin-decoding
  script over the HAL calls proved unreliable on this code; read the
  call sites by hand.
- Find the key reads (GPIO IDR users) and the RUN and CHG writers.
