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
| ULPI pins | AF10 on the ports listed in the boot loader's GPIO init at 0x08004fb0 | `H7-BOOT.bin` | code |

PH9 is the backlight in the boot loader and the buzzer in the app on this
unit's board code. Either the app drives the buzzer from the same pin as
the boot loader's backlight, or the app's flag path differs from what was
read. This is the first thing to settle: no test image drives PH9 until
it is.

## Next

- Locate the app's LCD, backlight, key and LED code (SPI5 base is not a
  literal in the app; search for the SPI5 register offsets and the
  display init sequence by its command bytes).
- Locate the boot loader's SPI5 init at 0x08011b54 and the LCD init
  functions that call it.
- Find the key reads (GPIO IDR users) and the RUN and CHG writers.
