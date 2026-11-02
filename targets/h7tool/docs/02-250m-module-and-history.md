# 02 - The 250M scope module, and the H7-TOOL history that can bite a bare-metal firmware

Tags: **VERIFIED-IN-SCHEMATIC** (read from the vendor schematic text in
`/tmp/.../scratchpad/sch_*.txt`, extracted from the PDFs in
`h7tool_pc_v2.3.3/help/sch/`), **FROM-SOURCE-OR-CHANGELOG** (vendor
manual V4.0, CHANGELOG, ChangeLog.txt, `h7tool_usb_control` docs, file
inspection), **UNKNOWN**. Nothing here touched a device. Part numbers and
pins are quoted from the text; where the text layout made a
designator-to-value assignment ambiguous, it is said so.

## 0. The important correction first

**`D268-5_H7-TOOL示波器模块（2019-10-19整理）` is NOT the 250M module.**
It is the 2019 analog front end of the *built-in* 2-channel 16-bit scope:
its outputs go to H7 ADC pins and it is controlled by a 74HCT595 driven
from H7 GPIOs. The text contains no RP2040, no external ADC and no
250 MHz anything. (VERIFIED-IN-SCHEMATIC: grep of the whole D268 text
for RP2040/250/AD9/THS finds nothing; title block reads
"H7-TOOL 示波器模块 ... SHEET NAME [7]ADC REV 3.0, armfly, 2019-10-19".)

**No schematic of the 250M module (RP2040 + ADC + AFE) exists in the
release folder.** Every statement below about the 250M's internals is
therefore FROM-SOURCE-OR-CHANGELOG (the vendor manual) or UNKNOWN.
`h7tool_usb_control/13-custom-firmware-feasibility.md` says "needs the
module schematic (D268-5 text is in the release)"; that is wrong for the
250M and should be corrected. The only route to the real 250M schematic
is the vendor (armfly / armbbs.cn) or tracing a physical module.

## Part A - The 250M module

### A1. What the vendor says it is (FROM-SOURCE-OR-CHANGELOG, manual V4.0 ch. 13, 2026-07-13)
- "单通道 250Msps，双通道 125Msps" (1 ch 250 Msps, 2 ch 125 Msps each),
  1 Mohm input, x1/x10/x100 probes.
- "模拟带宽 30M - 50M" (analog bandwidth 30-50 MHz). A vendor claim, no
  measurement behind it in this repo. The manual separately says the
  probe's X1 position is for signals below 6 MHz and X10 for below
  200 MHz; that is a probe statement, not a module bandwidth.
- "200K 存储深度" (200K depth, hardware). The app build offers up to 16K
  (V2.32/2.33 disabled larger depths, manual 13.3 item 4; usb_control
  doc 04).
- Programmable AC/DC coupling, waveform-correction trim capacitor, range
  +-40 mV to +-40 V, hardware trigger CH1 or CH2, 5 V supply only with an
  on-module negative rail ("内置负压电源电路").
- "主控采用 RP2040 + ADC + 模拟前端，利用 RP2040 的可编程 PIO" - the
  RP2040's PIO replaces an MCU+FPGA design. The ADC part number and
  resolution are **not stated** in the manual.
- USB, WiFi or Ethernet are the *H7-TOOL's* transports to the PC; the
  module itself is reached from the H7 (below).

### A2. ADC part, resolution, rate: what is actually known
| item | value | tag |
|---|---|---|
| ADC part number | not stated anywhere in the release | UNKNOWN |
| sample rate | 250 Msps single / 125 Msps dual (vendor); app rate list tops out at index 20 = 250M "CH1 only" | FROM-SOURCE-OR-CHANGELOG (usb_control doc 04 lists 0:100 Hz ... 19:125M 20:250M) |
| rates confirmed on the bench | index 10 = 200 kS/s and index 14 = 5 MS/s only | FROM-SOURCE-OR-CHANGELOG (usb_control 04/06, run on this unit) |
| resolution | samples are 8-bit unsigned bytes on the wire; the ADC itself is "deduced" 8-bit, not documented | FROM-SOURCE-OR-CHANGELOG (usb_control 05) |
| depth | 1K..16K via index 0..4 | FROM-SOURCE-OR-CHANGELOG |
| noise/offset | zero near code ~118 not 128; volts per code uncalibrated | FROM-SOURCE-OR-CHANGELOG (usb_control 04/06) |

A 125/250 Msps 8-bit converter cannot be fed to the RP2040 over a
serial-style link at those rates without PIO capture, which fits the
vendor's own description; the RP2040 captures into its own RAM and the
H7 pulls 1 KB blocks afterwards (usb_control 05: "not streaming - nothing
arrives unrequested"). The ADC interface to the RP2040 (parallel GPIO
pins, clock source) is UNKNOWN.

### A3. RP2040 role and its pins
- Role: capture engine and Modbus slave. It is a separate Modbus slave at
  address `0x10` behind the H7-TOOL (FROM-SOURCE-OR-CHANGELOG, usb_control
  03; verified on a bench over USB through the H7, not on the module link).
- Firmware: `DSO_250M（V1.04）.uf2` (98,304 B, 192 UF2 blocks of 256 B,
  target 0x10000000 = RP2040 XIP flash, UF2 familyID `0xe48bff56` =
  RP2040) and `.bin` (49,028 B; first bytes `00 b5 32 4b` = the 256-byte
  RP2040 boot2 stage). Identification only: read from the file headers.
  sha256 of the .bin
  `76ae76eb0a1af1ad12a31b0d024dde1b6b9a684f2d5fc3e5b9fa80ad07d574a6`,
  of the .uf2 `89e06dafd8bf17b921e3bb3d29857aa6f1c2fc88da9b320012ec127cb62c6415`
  (VERIFIED by file inspection; version "V1.04" is the file name only).
  strings show a Pico-SDK-style panic/assert text.
- RP2040 GPIO assignment (which pins are the ADC data bus, ADC clock,
  SPI/UART to the H7): UNKNOWN. Not in any available document.
- The PC app's ChangeLog notes "解决RP2040没接IC时，打印很多idcode问题"
  (V2.31) - that is about the *programmer* supporting RP2040 targets, not
  the module. Do not confuse the two.

### A4. Interface to the H7 (which signals, which H7 pins)
Manual 13.3 item 3 (FROM-SOURCE-OR-CHANGELOG): the module "占用串口2引脚
UTX D0, URX D1 以及 SPI 控制器接口 SDO D2, SDI D3, SCK D5"; TVCC must be 3.3 V
because TVCC sets the SPI level; the module must be used via the probe
input, not the CH1/CH2 header pins (those are the built-in scope).

H7 pins behind D0..D5. The adapter board and the main board give this
mapping; nothing labels the D-numbers on the pin text itself, so the
D-number column is an inference from list order and agrees with the
vendor's own 2020-10-26 planning table in `Doc/待解决问题.txt` (UNKNOWN
for the numbering, VERIFIED-IN-SCHEMATIC for the pin names):

| D | H7 pin candidates (as printed) | likely function for the 250M | tag |
|---|---|---|---|
| D0 | `PD14/FMC_D0/PI0/TIM5_CH4/PA15/UART7_TX` | UART TX (manual: "UTX D0") | pins VERIFIED-IN-SCHEMATIC (D291, D253 `[7] PA15/UART7_TX`); D0 numbering from planning table |
| D1 | `PD15/FMC_D1/PA8/UART7_RX/PH10/...` | UART RX ("URX D1") | same |
| D2 | `PD0/FMC_D2/PB7/TIM4_CH2/PE6/SPI4_MOSI` | SPI MOSI ("SDO D2") | same; net `PE6/SPI4_MOSI` is on D253 |
| D3 | `PD1/FMC_D3/PE5/SPI4_MISO/...` | SPI MISO ("SDI D3") | same; net `PE5/SPI4_MISO` on D253 |
| D4 | `SWRST/PE7/FMC_D4/PH12/TIM5_CH3/PE4/SPI4_NSS` | not listed as used by the module (CS or software chip-select; UNKNOWN) | |
| D5 | `PE8/FMC_D5/PE2/SPI4_SCK/PI5/TIM8_CH1` | SPI SCK ("SCK D5") | net `PE2/SPI4_SCK` on D253 |

D253 also shows the UART7 alternates `PA15/UART7_TX` and `PA8/UART7_RX`
as nets, and `PE7`/`PE8` UART7_RX/TX as pin functions. **Which of the
alternatives the stock firmware actually routes (pin AF choice) is
UNKNOWN**; H7 pins carry several candidate names per header pin because
the D-lines are shared by the programmer, the FMC bus-trace feature and the
buffers (U1 74HCT244 on D291). Protocol on the link: Modbus RTU framing
with address `0x10` (usb_control 03-05, observed from the USB side). Whether
the H7-to-module hop is SPI, UART or both, and at what baud/clock, is
UNKNOWN; the manual names both pin pairs.

Control surface as seen from the PC through the H7 (FROM-SOURCE-OR-CHANGELOG,
all VERIFIED on a bench by `h7tool_usb_control`, not re-run here):
enable via `0x0212` on address 1 (2 then 1); configure with FC10 at
`0x0100` x17 on address `0x10`; poll `0x021C`; read 1 KB blocks at
`0x2000+k` (CH2 `0x4000+k`); status block `0xC100` x16 floats (meaning
UNKNOWN). Blind register scans knock the module out ("Do not scan"); the
2-1 enable cycle recovers it. Coupling and range codes are unverified
(coupling flip had no visible effect; range code 0..9 to volts UNKNOWN).

### A5. The 250M analog front end (stage by stage)
**Not available.** All of the following is UNKNOWN for the 250M module:
attenuator values, relays/switches, op-amp part numbers, ADC driver, voltage
reference, negative-rail generator, the 5 V input filtering. The vendor
only states the specs in A1. (Do not borrow the D268 values below for the
250M.)

### A6. What D268 does show (the built-in 16-bit scope AFE), VERIFIED-IN-SCHEMATIC
Useful as a reference for the sibling front end and because a bare-metal
firmware that keeps the built-in scope must drive it. Designator
assignments are approximate: the text extraction scrambles which label
belongs to which part, so a PDF rasterisation should confirm before any
layout reuse (not done here).

- Inputs: J1 (probe-side, "示波器输入通道1/2"); stated input
  "输入阻抗：1M欧姆，可与标准示波器探头匹配" (1 Mohm); stated ranges
  "±2V、±10V、±20V、±100V ... 配合探头的X10开关，实现4档信号", i.e. 4 ranges
  with the probe's X10 switch, and "输入：±25V、±250V(探头X10)".
- Coupling: two **CPC1017N** photo-MOS parts (U1 for CH1, U6 for CH2), each
  driven through a 1 k resistor (R25, R21) from 74HCT595 outputs `595Q3/AC1`
  and `595Q7/AC2` - AC/DC coupling selected by switching the series
  capacitor. (That the capacitor is C6/C7-class 104/50 is not certain from
  the text.)
- Attenuator/gain: `CD74HC4051PW` analog muxes (two, one per channel)
  selected by `595Q0..2` (G1A/B/C) and `595Q4..6` (G2A/B/C); their 8
  inputs are labelled X1, X2, X4, X8, X16, X32, X64, X128 with resistor
  ladder values 3.24K, 1.62K, 806, 402, 200, 100, 49.9 (plus 825K and
  174K at the input); compensation caps "5/20pF", "270/25", "C4/C8:36-39PF"
  (trim). Note labelled "低增益通道 1:10" (low-gain channel 1:10).
- Buffer and level shift: **TLV2372IDR** dual op-amps (U2-A/B, U7-A/B),
  note "(可选用AD8066)" (AD8066 optional); sections labelled
  "信号缓冲电路" then "电平平移电路 (-2.5V -> +2.5V) (0V -> +2.5V)", with 2K 1 %
  resistors and a 33-ohm series resistor into the ADC input, 100/50 caps.
- Reference: **REF3025AIDBZR** (2.5 V) producing `+2.5V`.
- Rails: `CPU+5V` from the main board, `+5V_DSO`, `VDD+5V`, `VDD-5V`, via
  4.7 uH inductors (L1..L6) and 475/10, 226/25, 105/10 caps. Negative rail
  from **SGM3204YN6G/TR** (SOT23-6, `CFLY+/-`, `IN`, `OUT`, `EN`), a
  charge-pump inverter, with R27 10K near the connector J3.
- Digital control: **74HCT595PW** (U9) on H7 nets `PI4/595_RCLK`,
  `PI9/595_SCLK`, `PG5/595_SDI` (Q0..Q7 as above).
- Outputs to the H7 ADC: CH1 net `PF11/ADC1_INP2/PF9/ADC3_INP2/PF13/ADC2_INP2`
  (the three names are alternate-function names of the same 3 pad
  routing candidates), CH2 net `PC3_C/ADC3_INP1/[PC3/ADC12_INN12/ADC12_INP13]`.
  The manual states the built-in scope is 16-bit, up to 2 Mbps (usb_control 07);
  it is the H7's own ADC, there is no external converter on D268.
- Internal scope data is read back as 256 big-endian float32 per block =
  calibrated volts (usb_control 07), and disagrees with the voltmeter mode
  by `1.0049 x + 24 mV` on the bench (UNRESOLVED there).

### A7. Main-board facts that matter for this link (VERIFIED-IN-SCHEMATIC, D253-6, 2020-12-26)
- CPU: "STM32H750IB/TFBGA176+25" (title text). The usb_control docs report
  the *unit on the bench is board D428-9*, not D253-6; the schematic
  generations may differ (UNKNOWN how).
- USB: **USB3300-EZK** ULPI PHY on OTG_HS, with the H7 pins:
  D0 PA3, D1 PB0, D2 PB1, D3 PB10, D4 PB11, D5 PB12, D6 PB13, D7 PB5,
  CK(CLKOUT) PA5, STP PC0, DIR PI11, NXT PH4; RBIAS 12.1K; VBUS_DET net;
  3.3 V `VDD3.3V_USB3300` and a +1.8 V rail. (D253 also prints PC2 as a
  ULPI_DIR alternate and PC3 as ULPI_NXT alternate; the nets used are
  `PI11/OTG_HS_ULPI_DIR` and `PH4/OTG_HS_ULPI_NXT`.) The 250M scope
  supplies are not on this sheet.
- Crystals: 25 MHz and 24 MHz parts are printed (exact roles - H7 vs
  USB3300 vs RP2040 - not attributed; UNKNOWN).

## Part B - History

### B1. Versions and dates (FROM-SOURCE-OR-CHANGELOG)
Public tree CHANGELOG (`reference/h7-tool-app-v1.49-public/CHANGELOG`) runs
V1.02 (2019-10-20, "批量发货版本，首版" first shipping) to V1.49
(2021-03-25, PC V1.4.6). The PC `ChangeLog.txt` continues it:

| firmware | date | PC | BOOT | note |
|---|---|---|---|---|
| APP V1.49 | 2021-03-25 | 1.4.6 | V2.01 | last public source |
| BOOT V2.00 | 2021-03-17 | 1.4.5 | 2.00 | USB virtual-disk (U-disk) update introduced |
| BOOT V2.01 | 2021-03-25/31 | 2.0.0 | 2.01 | fix: black screen on upgrade when the OS wrote small system files and TOOL took them as firmware; now validates the file is legal firmware first |
| APP V2.00 | 2021-03-31 | 2.0.0 | 2.01 | "程序结构重大升级": RTX OS, AC6 compile, **USB changed from virtual serial to high-speed HID** |
| BOOT V2.02 | 2021-04 | 2.0.3 | 2.02 | HAL V1.10.0; RTC/LSE timeout fix (RTC_EnterInitMode; LSE timeout 5 s to 1 s); `RAM1_JUMP_VAR` moved from backup registers to internal RAM |
| BOOT V2.03 | 2021-07-01 | 2.0.6 | 2.03 | Win7 U-disk update: close USB then wait 2 s before jumping to the app |
| BOOT V2.04 | 2021-08-03 | 2.0.7 | 2.04 | LCD SPI phase change for a new batch of 2.0-inch screens |
| BOOT V2.05 | 2024-02-21 | 2.2.5 | 2.05 | (boot release note says only the version) |
| BOOT V2.06 | 2025-08-21 | 2.3.1 | 2.06 | (no change text found; see below) |
| APP V2.31 | 2025-08-21 | 2.3.1 | 2.06 | "新增250M示波器功能" (250M scope added); HID interrupt BINTERVAL 1 to 4 (`USBD_HID0_EP_INT_IN_HS_BINTERVAL`); fixes the internal-scope start glitch; fixes I2C-chip programming resetting the TOOL (AT24_DetectIC bug exposed by AC6 optimisation) |
| APP V2.33 | 2026-07-13 | 2.3.3 | 2.06 | RISC-V programming, AES/ECDSA APIs, MDK+RTT attach, "250M示波器大更新" (FFT, windows, measurements), Lua FFT API |

Note ChangeLog.txt line ordering has a 2020-era typo (BOOT 2020-01-24 for
what is 2021-01-24); trust the version numbers.

The two boot note files in `stock_release_files/`
(`boot版本V2.04.txt`, `boot版本V2.06.txt`) are **zero bytes**. Nothing can
be learned from them. (VERIFIED by `ls -la`.) The 250M-module-communication
code appeared in PC V2.2.7-era notes ("已添加250M示波器模块通信代码(暂未开放
使用)", 2025-01-01) before being enabled in V2.31.

Earlier boot fixes in the same ChangeLog: BOOT V1.03 "解决V板CPU写Flash失败
的问题" (CPU flash-write failure on the "V" board - a silicon/board
revision tag, V-board never explained); BOOT 1.00 to 1.02 adds flash
read-back verify after programming. The system-settings "about" page
shows a board-model parameter (APP V2.09, 2021-11-28) (matches the "D428-9" ID the
unit reports).

### B2. Hardware revisions and PCB notes
- The release schematics: main board D253-6 (2020-12-26), display D254-6,
  scope module D268-5 (2019-10-19 sorted), adapter D291-2 (2019-10-26),
  1-to-4 programmer adapter D315-2, simple adapter D380-1
  (VERIFIED-IN-SCHEMATIC names). The bench unit is D428-9 (usb_control 14):
  a later main-board revision with no schematic here (UNKNOWN delta).
- Display: 2.0-inch 320x240 screens supported from APP V2.00 via a
  parameter; LCD SPI phase retimed in BOOT/APP V2.04 for a new screen batch
  (FROM-SOURCE-OR-CHANGELOG) - if the bare-metal firmware drives the LCD,
  the timing depends on which batch.
- Boot flash: the H7 is a STM32H750IB (128 KB internal on paper) but the
  vendor flow forces the 2 MB H743 algorithm; the app is ~1.29 MB at
  0x08020000 (usb_control 13/14). Board hardware facts for the bare-metal
  work belong in the project docs; this file only records what the history
  says.

### B3. USB / ULPI history (FROM-SOURCE-OR-CHANGELOG)
- V1.05 (2019-11-29): HAL and USB library to STM32CubeH7 V1.5.0.
- V1.04 (2019-11-25): CDC serial driver reworked, COM switch no longer
  toggles the USB device; TeenyUSB stack added to the source but "未完全
  调通" and masked, ST's USB library still used.
- V1.07: USB hang after screen wake: `while (wTransferState == 0){}`.
- V1.43 (2020-12-17): USB interrupt and eMMC interrupt priorities adjusted
  "to avoid hangs"; Modbus decoding inside the USB serial ISR hung when it
  hit an SD-card write ("阻塞死机"). Open-issue file: `OTG_HS_IRQn` priority
  changed from (0,0) to (1,0); QSPI IRQ priority must be below USB; systick
  priority 0 is an issue.
- V1.44: USB initialisation delayed 2 s after power-up to fix Win7.
- V2.00: USB virtual serial replaced by high-speed HID (this is the
  `c251:f00a` three-interface device the PC tool uses; register channel is
  interface 2, 1024-byte HID reports per usb_control 14).
- BOOT V2.03: 2 s delay before leaving the U-disk mode for Win7.
- APP V2.31: HID interrupt-endpoint BINTERVAL 1 to 4 (transfer-rate
  tuning). No ULPI-specific bug is recorded anywhere in either changelog.

### B4. 250M-module history
Only: communication code present in PC around 2025-01 but disabled; the
250M scope enabled in V2.31 (2025-08-21); 250M "大更新" with FFT and
measurements in V2.33 (2026-07-13); V2.32/V2.33 limited the capture depth
(manual 13.3). The DSO_250M firmware is "V1.04" in its file name; no
release note exists for it in the folder. The protocol the H7 speaks to the
module is not in the public source (V1.49 predates it).

### B5. Open issues from `Doc/待解决问题.txt` (translated)
Header: "This file records problems to be solved or optimised."
1. `qspi_read()` - reading continuously from Lua has problems.
2. File-manager screen: writing the font file takes 1 min; after the screen
   saver starts and wakes, the program never leaves the screen-refresh
   function.
3. SysTick interrupt priority is 0 (`TICK_INT_PRIORITY 0` in
   `stm32h7xx_hal_conf.h`; the HAL default would be 0x0F).
4. `bsp_CheckRunTime` / `bsp_GetRunTime` should not disable interrupts
   internally; it affects QSPI writes.
5. 2020-12-13 V1.42 `swd_prog_file.c`: calling the FLM `uninit()` then
   `target_flash_init(_FlashAddr, 0, FLM_INIT_VERIFY)` before verify fails to
   program STM32F407 (init fails); reverted. "Code may have other issues."
   The Suzhou Guoxin QSPI FLM fails with `FLM_Verify` but works with
   read-back verify.
6. 2020-09-16 V1.31: in normal trigger mode, dragging the trigger-position
   scrollbar beyond the waveform range makes the program hang (frequent
   watchdog interrupts); unsolved; switching to the voltage screen recovers.
   (V1.32 reduced it "很小几率还是会挂"; V2.06 fixed the normal-trigger
   hang by not busy-waiting for a hardware edge inside the watchdog ISR.)
7. 2020-10-26 SPI-flash programmer plan: not enough pins for 4-way
   programming; pin table D0..D9 with direction pins (e.g. D2 PE6/PD0/PB7
   MOSI with DIR PD9, D5 PE2/PE8/PI5 SCK with DIR PG7). It is useful as a
   mapping of the D-line buffers.
8. Interrupt-priority list (the table of the intended NVIC priorities,
   USART1 0/1, UART4 0/4, UART8 0/6, TIM_HARD 0/2, TFT DMA2_Stream3 1/1,
   SPI5 1/0, QUADSPI 0x0F to 0x04 "higher than USB", MDMA 0x02, OTG_HS
   1/0, SDMMC1 0/0, ADC/ADC3 0/0, CH1/CH2 DMA 1/0).
9. Protocol notes: function code `0x61` = TOOL sends unsolicited (print
   text), no master ack; `0x64` = Lua/file transfer (sub-functions 0 to 7,
   CRC16). (Same channel the update/file transfer uses; see usb_control 13.)

### B6. Other bugs worth knowing (FROM-SOURCE-OR-CHANGELOG)
- ADC/DMA: ADC buffers must be non-cacheable (V1.46 removed the ADC DMA
  interrupt and set the buffer region "not cache"; V1.31 "示波器ADC缓冲区禁止
  cashe, 解决波形断裂问题"); ADC buffers (128K+64K) moved to D3 SRAM at
  `0x38000000` and `+32 KB` in V1.30.
- DAC waveform generator broke below 30 Hz until V1.30 (now 1 Hz).
- Low-frequency capture needs ADC sample-rate division below 2 kHz
  (V2.06 "低于2K的采集频率需要分频"), similarly CAN below 100 kbit/s.
- Internal scope glitch at record start fixed only in APP V2.31.
- Hardware CRC vs software CRC mismatch on some bin files (V1.21).
- Watchdog: disable during target reset sequences; the Lua scripts do it.
- The AC6 compiler's optimisation exposed a non-conforming ("不规范")
  `AT24_DetectIC()` (V2.31) - the same class of bug can appear in any
  new toolchain.

## Part C - Known issues that could bite a bare-metal replacement firmware

Ordered by severity for this project:

1. **Boot-loader contract is the safety net; protect it.** The boot loader
   reads `0x20000000` (`0x5AA51234` enter update, `0x11223344` run) and
   checks the app stack pointer; BOOT V2.01 added "is this really firmware"
   validation, V2.00/2.03 added the Win7 delay; flash writes are a ~0.8 s
   timer-restart state machine (usb_control 14). Any custom app must keep
   the DTCM word, the vector table at 0x08020000 and an SP in DTCM/AXI
   (FROM-SOURCE-OR-CHANGELOG, partly VERIFIED on the bench by usb_control).
2. **Board revision uncertainty.** Documentation is for D253-6 (2020);
   the unit is D428-9 and BOOT history mentions a "V board" with a flash-write
   defect. Pin maps, LCD timing batches, regulator/LDO choices may differ.
   Verify against the real unit before trusting any pin in this file.
3. **USB OTG_HS + USB3300 over ULPI.** The PHY needs its 60 MHz ULPI
   clock from the PHY (CLKOUT on PA5) so the H7 PLL/USB init order matters;
   the vendor needed a 2 s USB startup delay for Win7 and special handling
   of USB IRQ priority versus QSPI/eMMC/watchdog. Stock behaviour is
   high-speed HID with 1024-byte reports and BINTERVAL 4 (changed from 1 in
   V2.31): expect timing sensitivity. No documented ULPI hardware erratum.
4. **Interrupt priority/blocking hazards**, repeatedly hit by the vendor:
   USB ISR must not run Modbus handlers that touch SD/QSPI (blocks and
   hangs); QSPI IRQ priority must be below USB; SysTick at priority 0 and
   `bsp_GetRunTime` disabling IRQs break QSPI writes; ADC DMA buffers must
   be non-cacheable; the H7 has a data cache (unlike the Due) so DMA
   buffers need MPU/non-cache or cache maintenance.
5. **250M module is a black box.** Its Modbus-over-UART/SPI link, baud/clock
   and framing are not documented; blind register scans crash it until an
   enable cycle; its status block is undecoded; range/coupling mapping
   unknown; ADC part unknown. A bare-metal H7 must re-implement the exact
   module protocol (read the stock V2.33 `bsp_dso_250m.c` behaviour) or
   replace the RP2040 firmware (UF2) as well.
6. **Pin sharing on D0..D9.** The 250M occupies D0, D1, D2, D3, D5 and TVCC
   level (3.3 V). The same D-lines are used by the programmer, I2C, the
   digital-bus bank and direction buffers; the vendor planning table shows
   direction pins (PD9, PG7 ...) that a bare-metal build must also drive
   correctly or the lines contend.
7. **Built-in scope and 250M interaction.** The user believes they cannot
   run at once (usb_control 03/07); unverified. The built-in front end is
   switched by the 74HCT595 (`PI4/PI9/PG5`) - if the bare-metal firmware
   never initialises it the relays/gain muxes stay in their reset state.
8. **Calibration data.** Factory calibration area `0xC000..0xC0FF` is read
   through the stock app; where it is stored (internal flash vs eMMC) is
   UNKNOWN; the bench scope-vs-voltmeter disagreement is unresolved.
9. **Clocks.** A 25 MHz and a 24 MHz crystal are on the main sheet; the
   boot loader's PLL assumptions do not matter (the app re-inits), but a
   custom app needs the right oscillator and the SDRAM/QSPI/eMMC bring-up.
10. **Version drift between docs and silicon.** Public source is V1.49
    (2021) and lacks everything after, including all 250M code and the
    RTX-based V2.x structure; the V2.x binaries are the only reference
    for post-2021 behaviour.

## Uncertainty summary
UNKNOWN: ADC part and RP2040 pinout of the 250M; the module schematic;
the H7-RP2040 physical protocol parameters; D428-9 vs D253-6 differences;
D-number to pin numbering (inferred); crystal roles; exact designator
mapping in D268 (not rasterised).
