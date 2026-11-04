# 24 - The 250M module's RP2040: its firmware, programming and recovery, and what new firmware would need

Companion to `docs/23-250m-module.md` (how to drive the module and how it behaves). Observed on one module on 2026-11-04. Tags: **observed** (read from the module or measured), **code**
(read out of the module's own firmware, by emulating its start-up), **inferred** (a reading of that, said so), **unknown**. The owner decided that new firmware and a streaming mode are not worth
the investment now; this is the record so that it can be picked up without redoing any of it.

## 1. The module's RP2040

| Item | Value | Basis |
|---|---|---|
| Chip unique id (also the USB serial in boot mode) | E0C9125B0D9B | observed |
| Boot ROM | UF2 Bootloader v3.0, "Raspberry Pi RP2", Board-ID RPI-RP2; ROM version byte 3 (revision B2); magic `Mu\x01` at 0x10 | observed |
| Flash | 2 MB QSPI (0x10000000..0x101FFFFF; the window repeats at 2 MB) | observed |
| Used flash | 0x0000..0xBFFF (49,152 bytes: the 256-byte boot stage, the vector table at 0x100, code and data); the other 2000 KB is 0xFF | observed |
| System clock | 250 MHz (12 MHz crystal x 125 / (3 x 2)); USB PLL 48 MHz | code |
| RAM use | stack top 0x20040000; seven 32 KB sample buffers at 0x20000000..0x20037FFF | code |
| Is it the vendor's `DSO_250M(V1.04).bin`? | **No.** The first 256 bytes match; 39,619 of the vendor file's 49,028 bytes differ, the module's image is 124 bytes longer (the used region ends at 0xC000), the reset vector is 0x10008271 against the vendor's 0x10008269. Which build it is, is unknown | observed |

**Vector table** (0x10000100; 'stub' is the SDK's default handler, one per interrupt): SP 0x20040000, Reset 0x10008271, HardFault 0x10008289, NMI 0x1000AA33, SVCall 0x1000AA35, PendSV 0x1000AA37,
**SysTick 0x10002195**, **PIO0_IRQ_0 0x10003545**, **PIO0_IRQ_1 0x100035F9**, PIO1_IRQ_0 0x1000B775 and PIO1_IRQ_1 0x1000B779 (stubs), **IO_IRQ_BANK0 0x1000A841** (a GPIO pin-change handler), the rest stubs
(0x1000AA39 and up). **Nothing for USB, SPI, UART, DMA or ADC**: the application has no USB and no hardware serial port; its only host link is the PIO one below.

## 2. Programming, backup and restore

**Boot mode.** Hold the module's BOOT button while connecting its USB socket (or while power-cycling it); it enumerates as `2e8a:0003` "RP2 Boot" with a 128 MB mass-storage drive labelled RPI-RP2
(`INDEX.HTM`, `INFO_UF2.TXT`) and a PICOBOOT vendor interface (USB interface 1, class 0xFF, bulk OUT 0x03 and IN 0x84). In normal operation the socket is silent. *Unknown whether the 5 V of the USB socket and of the
H7-TOOL header are isolated on the module: it was connected to the host with the H7-TOOL supply as well and nothing was damaged, but unplug it from the header while on USB power unless that is known.*

**The backup** (outside the repo, `~/MCU.Projects/h7tool_backup/rp2040_module/`, with a README and SHA256SUMS):

| File | What | sha256 |
|---|---|---|
| `module_flash_2048KB.bin` | the whole flash, read three times, identical | `ef6881c9120bf9d12584cb859797743b38ad680850b78ca46eefa59f6bb87d7f` |
| `module_restore.uf2` | its first 49,152 bytes as UF2 (192 blocks), converted back and compared | `7c4deb82551c4c27bedf183344ce45011fa916cbd9bde578ea6df153cd649396` |
| `rp2040_bootrom_16KB_partial.bin` | the boot ROM's first 8 KB; the rest could not be read | - |

**To restore the stock firmware:** boot mode, then copy `module_restore.uf2` onto the RPI-RP2 drive; the module reboots into it on its own. The ROM's boot mode cannot be overwritten by a bad image, so a bad firmware is
always recoverable with the BOOT button. The vendor's own UF2 is *not* what the module had: restoring it would change the module's firmware.

**Reading the flash** (`tools/rp2040_picoboot.py`, read-only: it can send only EXIT_XIP, ENTER_CMD_XIP and READ, and a test holds that): what was learnt about the boot ROM's USB reader, in case it is rewritten:
1. Right after connecting, the flash window returns the XIP cache's contents (the first bytes of "flash" and of SRAM were identical). Send EXIT_XIP (0x06) then ENTER_CMD_XIP (0x07) and the flash reads true.
2. A 16 KB read stalls the interface; 4 KB reads work. The first command after an interface reset sometimes times out; retry after a reset.
3. Only the first 8 KB of the boot ROM (0x0..0x1FBF) reads; higher addresses stall.
4. Open the device once per process; a second `claim_interface` is refused as busy.

**Programming over SWD instead.** The H7-TOOL is itself a programmer with an RP2040 algorithm (`EMMC/H7-TOOL/Programmer/Device/Rasberry/RP2040`: a Lua script, `Raspberry_Pi_Pico.FLM`, `MCU_ID 0x0BC11477` in
the script) and enumerates as CMSIS-DAP on USB interfaces 0 (WinUSB) and 1 (HID) while the stock app runs. `tools/h7_swd_probe.py` reads the debug-port id through it with no memory access. On this module it answered
**ACK 7 (no target)**: nothing is wired to the programmer's SWD port, and no document says whether the module exposes SWCLK and SWDIO. The USB boot mode makes SWD unnecessary for writing.

## 3. What the firmware sets up at start-up (code)

Method: `tools/rp2040_trace.py` runs the image from its reset vector in an emulator (`unicorn`) and logs every peripheral write; it reaches the main loop (40,407 register writes) and waits there for input from outside.
The emulation answers the SDK's "is it ready" reads (resets done, crystal stable, PLL locked, clock mux selected, timer and SysTick moving, spinlocks free, DMA idle) and delivers SysTick as a function call at intervals; it is
a start-up trace and not a model of the chip. Reproduce with `python3 targets/h7tool/tools/rp2040_trace.py module_flash_2048KB.bin rp2040_bootrom_16KB_partial.bin`.

**Clock.** XOSC 12 MHz (CTRL 0xAA0, startup 0x2F); PLL_SYS FBDIV 125, POSTDIV 3 and 2: **250 MHz**; PLL_USB FBDIV 40, 5 and 2: 48 MHz; CLK_SYS from the PLL. The RP2040 is overclocked from its rated 133 MHz.

**Pins** (final state at the end of start-up; all pads have the input enabled and 2 mA drive unless noted):

| GPIO | Function | Reading |
|---|---|---|
| 0 to 15 | PIO0 | the sample bus: `in pins, 16` (two 8-bit channels, GPIO0 to 7 and GPIO8 to 15 *inferred*) |
| 16 | PIO1 | SPI slave MOSI (in_base 16) |
| 17 | not configured | unknown |
| 18 | PIO1 | SPI slave SCK |
| 19 | PIO1 | SPI slave MISO (out_base 19) |
| 20, 21 | SIO output, driven low, pull-up | unknown (front-end switches are the likely users, *inferred*) |
| 22 | PWM slice 3 channel A (the slice itself is not configured at start-up) | the converter's sample clock *inferred* |
| 23, 24 | PIO0 (set and side-set of state machine 0, two bits) | capture control (*inferred*) |
| 25 | PIO0 (set pin of state machine 1) | the pacing counter's output, read back by state machine 0 |
| 26, 27 | SIO outputs (their ADC function is unused) | unknown |
| 28 | pad left at its default | unknown |
| 29 | read as an input by PIO1 (`wait 0 gpio 29`, jmp pin 29); function SIO | SPI chip select |

**PIO0** (32 instructions loaded, clock divider 125 at the end of start-up, so the real values are set when a capture is configured; interrupt lines: IRQ0_INTE 0x100, IRQ1_INTE 0x200; only PIO0_IRQ_1 is
enabled in the NVIC at the end of start-up, ISER 0x100):

```
 0-15  jmp n            filler (each word jumps to itself)
 16  e000  set pins, 0                       ---- state machine 1, wrap 16..29, divider 125, pull threshold 32, TX FIFO joined (8 deep), set_base GPIO25 x1
 17  80a0  pull block
 18  6040  out y, 32
 19  a022  mov x, y
 20  0054  jmp x-- 20                         a countdown of the first word pulled
 21  a021  mov x, x          (delay)
 22  a021  mov x, x
 23  c020  irq wait 0                         raises PIO IRQ 0 and waits for it to be cleared
 24  80a0  pull block
 25  6040  out y, 32
 26  a022  mov x, y
 27  005b  jmp x-- 27                         a countdown of the second word
 28  e001  set pins, 1                        GPIO25 high
 29  c021  irq wait 1
 30  4010  in pins, 16                        ---- state machine 0, wrap 30..31, divider 125, RX FIFO joined (8 deep), autopush at 16 bits, in_base 0
 31  3819  wait 0 gpio 25  [side 3, delay 0]  waits for GPIO25 low; sets GPIO23, GPIO24 high through side-set
```
The words in 0 to 15 and the exact way the two machines hand over to each other were not traced to the end: this is the *initial* program memory and configuration, and the capture program is probably rewritten for each rate
and trigger setting *(inferred)*. Seven DMA channels (0 to 6) read PIO0's RX FIFO (0x50200020) into 0x20000000, 0x20008000, ..., 0x20030000, 16,384 halfword transfers each (32 KB), ctrl 0x00020FE5 on channel 0: a 224 KB ring,
the "200K depth". State machine 1 looks like the pre-trigger and post-trigger counter; the manual's hardware trigger lives here.

**PIO1** (14 instructions at 18..31, both machines at divider 1, i.e. 250 MHz sampling):

```
 18  e080  set pindirs, 0                    ---- state machine 1 (transmit), wrap 21..24, jmp pin GPIO29, out_base GPIO19 x1, autopull 32, TX FIFO joined
 19  201d  wait 0 gpio 29                     chip select low
 20  e081  set pindirs, 1                     drive MISO
 21  6001  out pins, 1                        the next bit
 22  2092  wait 1 gpio 18                     SCK high
 23  a021  mov x, x
 24  2012  wait 0 gpio 18                     SCK low
 25  00d2  jmp pin 18                         chip select high: start again
 26  a0c3  mov isr, null                      ---- state machine 0 (receive), wrap 28..31, jmp pin GPIO29, in_base GPIO16, autopush 32
 27  201d  wait 0 gpio 29
 28  2092  wait 1 gpio 18
 29  2012  wait 0 gpio 18
 30  4001  in pins, 1                         MOSI sampled after SCK falls
 31  00da  jmp pin 26
```
So the link is an SPI slave at 250 MHz oversampling: MOSI GPIO16, SCK GPIO18, MISO GPIO19, CS GPIO29, bits shifted most-significant first into 32-bit words (autopush at 32), the next word pulled from the TX FIFO
(autopull at 32). The transmit machine spends about 5 instructions per bit, so its clock cannot exceed about 50 MHz (**arithmetic, not measured**). Start-up writes one word, 0x55AA55AA, to PIO1's transmit FIFO (a preload of the reply line), and four words (0, 0x1000, 0, 0x1000) to PIO0's, the counts the pacing machine starts with.

Not seen at start-up, because it runs only on a command: the PWM setup (the sample clock), the per-rate PIO divider and program changes, the front-end pin writes for range and coupling, the trigger arming, the framing of the SPI words.

## 4. The link between the H7 and the module

**What is known:** the module side above; the H7 side is SPI4 (docs/02 A4); the vendor says TVCC sets the level; the stock host protocol (docs/23 section 3) is carried over it as Modbus RTU frames with the
module as slave 0x10, by the H7 stock app (the host never sees the SPI link).

**What is unknown:** the framing of those frames on SPI (word packing, length, padding, idle bytes, any handshake), the SPI clock and mode the H7 uses, and which GPIO of the module (if any) is wired to the header's D0 and D1 for a
"ready" signal. Without these our own H7 firmware cannot drive the module directly; through the stock app the host can (docs/23).

**Where to find them (for whoever resumes):**
1. The stock H7 app V2.33, file `h7_tool_app(V2.33).bin`, loaded at 0x08020000. The 250M driver's source name `../../User/bsp_ext/bsp_dso_250m.c` is a string at **0x0812CE14** (no direct reference). SPI4's base address
   0x40013400 is built at **0x08096E34** inside a HAL-style SPI init that starts at about **0x08096E04** (it fills an init structure and calls a function at 0x0804C120, then builds a DMA2 stream handle at 0x40020488, stream 5,
   right after); further SPI4 base-address loads at 0x0804C946, 0x0804D38A, 0x08097DE4, 0x08097F42, 0x0809A402; UART7 base-address loads at 0x08098052 and 0x08098498. These are the addresses of the `movt` that completes
   each base address, found by scanning the disassembly; nothing here has been read function by function. The 250M functions sit around 0x08096xxx to 0x0809Axxx. `h7tool_usb_control` and the earlier scratch work have the full disassembly method
   (`arm-none-eabi-objdump -b binary -m arm -M force-thumb --adjust-vma=0x08020000`).
2. The PC app (`h7toolPC.exe`) strings: "Reconfigure the 250M communication interface", "The 250M module has been powered off and restarted", `AdcDiff_250M`, `EditAdcDiff250M` (an offset calibration in the app).
   The PC app power-cycles the module (TVCC off and on) to restart it.
3. Feed the module's emulation the SPI words: PIO1's receive FIFO is the module's input. Writing words into it with a chip-select held low and reading what the firmware does (the pin writes for a given range code, the
   PIO and PWM setup for a given rate index, the trigger arming) answers most of the unknowns at once without the board; the emulation harness of `tools/rp2040_trace.py` is the starting point (it answers FIFO status reads
   with "empty" today).
4. A logic analyser on the header's D2 to D5 while the stock app captures would give the framing directly.

## 5. What a streaming mode would be (design, not built; the figures are arithmetic from measured or traced values)

The converter's raw rate is **250 MB/s** (250 Msps on one channel or 125 Msps on each of two, 8 bits). No link here carries that: the H7's USB bulk stream measured 40 MB/s (docs/08), the module's own USB is full speed
(about 1 MB/s), and the SPI link ceiling above is about 6 MB/s. So the module could stream continuously only at a reduced rate, and the full rate only in bursts.

- **Continuous: about 3 to 6 MS/s on one channel, or 1.5 to 3 MS/s each on two** (a purpose-written PIO transmit program might reach a 62 MHz clock; whether the header wiring is clean at 30 to 50 MHz is untried). The same
  class as the H7's own two-channel 2.5 Msps scope (docs/11); at 5 MS/s the front end's 30 to 50 MHz bandwidth aliases anything above 2.5 MHz.
- **Full rate: bursts.** 224 KB at 250 MS/s is 0.9 ms; reading it out at 6 MB/s takes about 37 ms, so about 25 triggered bursts a second with blind time between them: the stock behaviour. A burst must be flagged as one
  (CLAUDE.md invariant 5).
- **The DMA-only strategy carries over to both ends.** Module: PIO0 capture to DMA to the RAM ring (exists), then a second DMA chain from the ring into PIO1's transmit FIFO, paced by its DREQ: the RP2040 CPU never touches a
  sample. H7: SPI4 master with receive DMA into a D2 SRAM ring, then the existing frame and USB IN DMA path (image 17), the CPU writing only headers. Flow control: a "ready" line from the module (if a free header pin is
  wired to an RP2040 pin: unknown) or a short status exchange between frames; the data path stays CPU-free either way. A frame with no data behind it goes out flagged as filler.
- **It needs our own module firmware** (the stock image only captures, then waits to be read), with the front-end control and the sample clock, which are in the command paths and are the first unknown.

## 6. Writing new firmware for the module: what is known, what is not, how to test it

**Known (enough for a firmware that streams or bursts a fixed configuration):** the clock (250 MHz); the sample bus (GPIO0 to 15 as 16 bits, PIO0); the host link (SPI slave on GPIO16, 18, 19, 29, PIO1); the DMA ring layout;
the interrupt structure of the stock image; the boot and recovery path (a bad image is always recoverable with BOOT and the restore file); the stock host protocol that new firmware should keep answering so the stock app
and `tools/h7_250m.py` keep working (docs/23 section 3).

**Not known (each one is a blocker for the feature that needs it):**

| Unknown | Needed for | How to find it |
|---|---|---|
| the SPI framing on the link and the H7's clock and mode | any new firmware that the stock app must talk to; any H7-side driver | section 4, items 1, 3, 4 |
| which pins set the range, coupling and offset, with what codes | selecting a range at all | emulate command frames (item 3), or a logic analyser |
| the sample-clock setup (PWM on GPIO22: frequency per rate index) and whether the converter needs other control | running at anything but the stock rates | emulate a settings-block write |
| what GPIO17, 20, 21, 26, 27, 28 do | completeness; possibly the "ready" line | the same traces, and the board |
| the ADC and front-end parts | datasheet limits (input range, bandwidth, clock limits) | a photo of the board, or the module's schematic from the vendor |
| why the trigger fires on either edge and misses 38 % of the time | a proper trigger | the PIO0 program as rewritten at arm time (item 3) |

**Risks.** A new image can be written and replaced at will in boot mode, so the module cannot be bricked by firmware alone; but a firmware that drives a front-end pin wrongly could damage the front end, and driving an
unknown pin as an output could fight whatever the board connects to it. Treat every pin not in the table above as an input until it is understood. The module's 5 V and the negative rail make the analog side the one place
a mistake costs hardware.

**Test strategy for new firmware (what coverage there would be).**
1. *Host-side model of the PIO programs*: a small RP2040 PIO interpreter in Python (the instruction set is eight opcodes, decoded in `tools/rp2040_trace.py`) driven with modelled pins, to test the SPI slave, the capture
   and the trigger programs cycle by cycle with mutation tests, as the H7 display driver is tested against a register model. *Not written.*
2. *Start-up regression by emulation*: `tools/rp2040_trace.py` on the new image, asserting the pin table, the clock and the DMA layout (the tests already assert the stock values on the stock image).
3. *The host protocol* against the simulated module of `tests/test_h7_250m.py`, extended with whatever the new firmware adds; the real module then behaves as the simulator does or the simulator is wrong.
4. *On the bench*, the acceptance targets, taken from the measurements in docs/23: the gain table within 3 % per range; the zero code within 3 codes; a single trigger that honours the edge in 98 % or more of 360 captures and
   places it within 3 samples of the requested position at 1 MS/s on the triangle test; a +10 V trigger that times out; no capture ever silently partial; if streaming, byte conservation over minutes at each rate with
   the discontinuity flags (CLAUDE.md invariants 5 and 7). `measure/h7_250m_quality.py` produces the figures.

## 7. Open questions, in the order they would block work

1. The SPI framing and clock (section 4). 2. The front-end control pins and codes. 3. The sample-clock setup per rate. 4. The ADC and front-end parts. 5. Which build the module's firmware is (and what differs from V1.04: 39,619 bytes do).
6. Coupling: the register had no visible effect. 7. CH2, two-channel capture and the 125 and 250 MS/s rates were never run. 8. Whether USB 5 V and the header's 5 V are isolated on the module.
