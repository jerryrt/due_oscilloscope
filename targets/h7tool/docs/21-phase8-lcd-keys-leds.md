# 21 - Phase 8 plan: LCD, keys and the two LEDs

Goal: our own image drives the backlight and panel, reads the keys and
switches both LEDs (RUN and CHG), with every pin taken from the stock
V2.33 firmware's behaviour and not from the schematic or the public
source. Rules: `README.md` (nothing below 0x08020000, no option bytes, the
boot loader untouched) and the image cycle of `tools/h7_cycle.sh`.

## Why the pins are not yet known

The pin table in docs/01 sections 5 and 6 comes from the schematic and the
public source for an older board revision. This unit (board register
0xFF60 = 0x4289) already disagreed with it once: the stock buzzer code
selects **PH9** on this board and PG1 on others, and PH9 is listed in
docs/01 as the backlight. A run LED on PI8 produced no light in image 1
(docs/03). Treat every pin in docs/01 sections 5 and 6 as a candidate.
The one method that has produced a confirmed pin is reading the stock
firmware's own code (docs/03: buzzer, TVCC pot).

## Constraints on checking

The owner checks the LCD and the LEDs by eye. The buzzer is not checked
by ear, so no test image pulses a buzzer pin on purpose, and a pin that
is a candidate for both buzzer and backlight (PH9) is tested through the
backlight.

## Phases

Each phase ends in a gate. Nothing is flashed until the phase before it
has a written pin and polarity with its evidence.

| Phase | Work | Gate |
|---|---|---|
| **8.0** Inputs | Disassemble `h7_tool_app(V2.33).bin` as in docs/03 (`objdump -b binary -m arm -M force-thumb`, base 0x08020000). Also disassemble V2.31 and V2.32 and the boot loader (`H7-BOOT.bin`), which draws the LCD and reads a key. Note the board-ID flag (0xFF60 masked with ~0xF) that selects pin sets, and read the register from this unit | A list of every function that writes GPIOx BSRR/ODR or reads GPIOx IDR, with the flag state under which it runs |
| **8.1** LEDs | From the disassembly find the RUN and CHG writers: the GPIO, the polarity, and whether CHG is software-driven at all (a charger-IC-driven LED has no GPIO). Check that the stock code reaches them with this unit's flag value. Look for when stock changes them (boot, USB, TVCC, charge state) | Per LED: port, pin, polarity, trigger, or "hardware only", each tied to an address in the stock image |
| **8.2** Keys | Find the key reader (stock key scan and the boot loader's power-up test): pins, pull configuration, polarity, debounce, long-press and combination handling, which of the two keys enters the boot loader | Per key: port, pin, polarity and the stock event it generates |
| **8.3** LCD | Find the panel power enable, backlight (GPIO or TIM12 PWM), reset, D/C, CS and the SPI instance, mode, speed and pin swap; extract the controller init command sequence and the window/orientation settings from stock and the boot loader. Note the screen-batch SPI phase variants of docs/02 | An init sequence listing with the command, data and delay at each step, plus the stock frame buffer layout |
| **8.4** Confirm by observation | Cross-check the findings without writing: with stock running, read GPIO IDR/ODR and the clock-enable state through the debug path if one exists; otherwise by the effect of our own test image only. Resolve every disagreement with docs/01 | Pin table with each row marked *observed* or *from code only* |
| **8.5** LED test image | One image: enable the GPIO clocks, drive RUN and CHG alternately on the pins from 8.1, with a distinct pattern per LED so the owner can say which one lit. Use the timer return of `h7_cycle.sh`. Break it on purpose first: build a variant that drives a wrong pin and confirm the owner sees nothing | The owner reports each LED by name, for both polarities. A pass requires seeing the wrong-pin variant fail |
| **8.6** Key test image | Report key state without the LCD: map each key to a LED pattern or a buzzer count | Each key and each combination tested, with the recovery entry still working |
| **8.7** LCD test image | Power enable, then backlight, then the init sequence, then a solid fill, then a test pattern with a frame buffer in SRAM1 and DMA2 Stream3 as in stock. Backlight on its own first, since it shows the supply works before SPI | The owner sees the correct colours and orientation; no tearing from the DMA; the frame buffer not in a cacheable region (invariant 1) |
| **8.8** Combine and record | Short image with screen text, key reads and both LEDs; update docs/01 sections 5 and 6 with the verified pins and the evidence; add a control opcode only if the host needs to drive them | Docs and the image agree; the new image returns to the boot loader without a key press |

## Status

**On hold, 2026-11-04, after the display work.** What is done, all observed on the unit (docs/22):

- The LCD, its backlight and the RUN and CHG LEDs from our own images: pins, polarity and sequence from the boot loader and checked
  by the owner's eyes; the expander on PB6 and PG0 (backlight P0_0, CHG P1_0 and P1_1, RUN P1_2); the ST7789 in portrait 240x320.
- The driver `fw/ui/h7_ui.c`: SPI5 at 80 MHz from PLL2 (started by the driver when it is free), DMA2 stream 3 for fills and blits,
  a full-screen fill in 15.6 ms (64 frames per second), a non-blocking blit and LED write for a shared main loop, and a shadow copy of
  everything drawn, because the panel cannot be read back. Works from a plain reset with no boot-loader screen behind it.
- Screen capture over the control function (`SCREEN 0x48`, `tools/h7_screen.py`) and exploring commands for test images
  (`PEEK`, `POKE`, `EXPLORE`, image 27, `tools/h7_explore.py`).
- The scope and generator monitor (`fw/ui/h7_mon.c`, image 28): the unit's state and counters, drawn in slices of a few tens of
  microseconds, with no frame lost at 1, 2 or 2.5 MS/s.
- `tests/test_h7_ui.py` (102 tests) builds the driver and the monitor for the host against a model of the registers, the SPI5 and
  DMA peripherals, the expander and the panel's memory, and breaks each guarded part on purpose.

**Decisions.** The display shows state, not waveforms: in stream mode the host draws the traces, and an on-device trace would have the
CPU read the sample stream (CLAUDE.md invariant 1). The state monitor is the device's display. The display driver stops at 60 frames
per second; no faster path is wanted.

**Still open.** The keys (set aside by the owner; PG0 is the expander's data line on this unit, so the old key pin table is unreliable).
CHG's two colours, one report each. The cause of a stuck SPI5 seen once after PLL2 experiments, and of a control-function hang seen
once; neither has recurred. The model byte at 0x24000022 and the app's own display table were not compared. The behaviour at the very
first power-on with no boot loader at all was not reached (every start so far went through it).

## Risks

| Risk | Handling |
|---|---|
| A wrong pin drives something else (buzzer, power, TVCC, the pot bus) | Read-only phases first; any pin written is read in 8.0 for what stock does with it |
| The board flag selects a different pin set from the one read | Print the flag value in every report and test with this unit's value |
| An image with no timer return and no working key leaves the unit stuck | Every test image keeps the timed return; stock is restored and verified after each cycle (docs/03 procedure) |
| The LCD needs a supply or clock stock enables earlier | The disassembly lists the writes before the first SPI transfer; reproduce them in order |
| Findings from the public source are mistaken for this board | A pin is *observed* only when our image moved it and the owner saw it |

## Not part of this phase

The 250M module, the eMMC, and any user interface logic above the three
drivers. Those wait for 8.8.

The throwaway test images of this phase are in `fw/ui-tests/`, outside
the `fw/imageNN` names the USB-image guards (`tests/test_h7_image13.py`)
read: they are USB-less, run for a fixed time and return to the boot
loader by themselves, which those guards forbid for the real images.

Image 27 in `fw/ui-tests/` is the exception: it is image 17 with the driver
and the exploring opcodes of the control function (PEEK 0x45, POKE 0x46,
EXPLORE 0x47 in `fw/ctl_h7.h`), so a test is driven and its numbers are read
over USB with `tools/h7_explore.py`. An image lists those opcodes in its
capability reply only when it provides them; any other image answers
CTL_ERR_OPCODE. The ids of EXPLORE are in the comment above `h7_explore` in
its `main.c`. POKE can write any peripheral register except the flash
controller, so the caller is responsible for pins such as the buzzer's.

Image 28 in `fw/image28/` is the first image with the display in it: image 17 plus the scope and generator monitor, the RUN LED and the
screen capture opcode (docs/22). It is a real image under the `fw/imageNN` guards: it returns to the boot loader by control opcode
only and has no timer.
