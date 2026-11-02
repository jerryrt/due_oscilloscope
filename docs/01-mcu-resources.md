# 01 - H7-TOOL main MCU resource inventory (for a bare-metal image, no SWD probe)

Scope: every hardware resource the main MCU (STM32H750IBK6 per schematic, behaves as a
2 MB-flash part) can use on the H7-TOOL main board, with pin names. Nothing here was
measured on a device; it is a read of the schematics and the public V1.49 source.

## Tags and sources

| tag | meaning |
|---|---|
| VERIFIED-IN-SCHEMATIC | read from the main board schematic D253-6 (net names, parts, pin labels), text or rasterized page |
| FROM-PUBLIC-SOURCE | from the public app V1.49 (2021). The shipping hardware and firmware is V2.33 (2026); this may differ |
| UNKNOWN | not determinable from the supplied material |

Source shorthand:

- **SCH-n** = `h7tool_pc_v2.3.3/help/sch/D253-6_H7-TOOL主板原理图( 2020-12-26).pdf`, page n of 8.
  Page n is also the number in square brackets on net labels. Pages: 1 CPU GPIOA-F, 2 CPU GPIOG-I + HSE/LSE/reset/SWD/VBAT,
  3 EEPROM/QSPI/LCD/buzzer/current sense, 4 RS232/RS485/CAN/ESP32/eMMC, 5 Ethernet + USB PHY, 6 DAC + scope interface + boost,
  7 target port, 8 power. The sheets are dated 2019-09-30 inside a PDF named 2020-12-26 (notes on the sheet record a 2021-01 change).
- **D254** display board, **D268** old 2-channel scope module, **D291 / D315 / D380** adapter boards, same `sch/` folder.
- **SRC** = `h7tool_baremetal/reference/h7-tool-app-v1.49-public/` (paths below are relative to it). `User/bsp/src/*.c` is shortened to `bsp/`.
- **DOC13 / DOC14** = `h7tool_usb_control/13-custom-firmware-feasibility.md`, `14-firmware-update-procedures.md`. **DOC01** = `01-transport-and-framing.md`. **DOC03** = `03-250m-enable.md`.
- **MAN** = `h7tool_pc_v2.3.3/help/H7-TOOL 使用说明书（V4.0 2026-07-13）.pdf`.

Three discrepancies found while cross-reading (all resolved below in favour of the schematic):

1. DOC13 lists the ULPI pins as "PB0/1/10/11/12/13, PC0/2/3, PA5". That is wrong. PC2/PC3 are the scope CH2 analog inputs.
   The real set (SCH-5, `User/teeny_usb/usb_app/board_config.h`) also has PB5, PH4 and PI11.
2. The big comment block in `bsp/bsp_fmc_io.c` lists direction pins that are stale (D2 "PG15", D3 "PH7", D5 "PF4", TTL "PE3").
   The `#define`s lower in the same file match the schematic; this document uses those.
3. The source comment puts I2C SDA on D8; the adapter schematics (D291, D380) and SCH-7 net names put it on D7 (PF0) with SCL on D9 (PF1).
   Treat D7/D9 as probable and check before use (see 12).

---

## 1. Clocks and oscillators

| item | value | pins / part | source | tag |
|---|---|---|---|---|
| HSE | 25 MHz, X1 25M/2520, 3.9 pF load caps | PH0-OSC_IN, PH1-OSC_OUT | SCH-2 "HSE晶振"; `stm32h7xx_hal_conf.h` `HSE_VALUE = 25000000` | VERIFIED-IN-SCHEMATIC |
| LSE | 32.768 kHz, X4, 1.5 pF caps | PC14-OSC32_IN, PC15-OSC32_OUT | SCH-2 "LSE晶振"; RTC init in `bsp/bsp_cpu_rtc.c` | VERIFIED-IN-SCHEMATIC |
| USB PHY clock | 24 MHz, X3 24M/2520, into USB3300 XI/XO | USB3300 pins 28/27 (not an MCU pin) | SCH-5 | VERIFIED-IN-SCHEMATIC |
| Ethernet PHY clock | 25 MHz, X2, into LAN8720A XTAL1/XTAL2; REF_CLK out to MCU PA1 | PA1 | SCH-5 | VERIFIED-IN-SCHEMATIC |
| ULPI clock into MCU | 60 MHz from USB3300 CLKOUT | PA5 (USB_OTG_HS_ULPI_CK) | SCH-5 | VERIFIED-IN-SCHEMATIC |

Stock PLL set-up (`SystemClock_Config()` in `User/bsp/bsp.c`, lines ~138-250), FROM-PUBLIC-SOURCE:

- Supply: `PWR->CR3.SCUEN` cleared (LDO mode, no SMPS), voltage scale 1 (VOS1), wait for VOSRDY.
- PLL1: source HSE, M=5, N=160, P=2, Q=4, R=2, VCOWIDE, input range 2. VCO = 25/5*160 = 800 MHz, P = 400 MHz (SYSCLK), Q = 200 MHz, R = 200 MHz.
  HSI, CSI off at that point (CSI is re-enabled afterwards for the I/O compensation cell).
- Bus: SYSCLK /1 = 400 MHz, AHB (HPRE) /2 = 200 MHz, APB1/APB2/APB3/APB4 each /2 = 100 MHz. Flash latency 4 WS.
- PLL3: M=5, N=48, P=2, Q=5, R=2 (VCO 240 MHz), USB kernel clock selected = PLL3-Q = 48 MHz. With the external ULPI PHY the OTG_HS core takes its clock from the PHY (PA5), so the
  48 MHz is probably only for the FS core. Whether the stock HS path needs it is UNKNOWN; a bare-metal image can leave it configured the same way at no cost.
- After clocks: enable CSI, SYSCFG clock, and the I/O compensation cell (`HAL_EnableCompensationCell`) because GPIOs run in high-speed mode.
- The stock app enables the D2 SRAM1/2/3 clocks, the backup SRAM and the D3 SRAM1 clock.
  A bare-metal image must enable those itself or those RAM blocks bus-fault on access.
- UNKNOWN: whether V2.33 uses the same PLL values. The 400 MHz / 200 MHz tree is the datasheet maximum for the H7 rev-V/Y parts; a H750 marked part is the same die family.

Reset values that matter: at reset the core runs from HSI 64 MHz; the boot loader leaves its own clock state, but a software reset (SYSRESETREQ) returns to HSI.
SystemInit in `User/bsp/system_stm32h7xx.c` sets `VTOR = 0x08000000 + 128 KB` (`VECT_TAB_OFFSET`), i.e. the app's vector table at 0x08020000. FROM-PUBLIC-SOURCE.

## 2. Power rails and supplies

All VERIFIED-IN-SCHEMATIC from SCH-8 and SCH-2 unless noted.

| rail | source | notes |
|---|---|---|
| +24V / +VDD_ET (7-36 V input, "7-36V转5V") | external power connector CN5 | TPS5430 buck to +5V. Input voltage sensed on PH3 (ADC3_INP14) |
| +5V | TPS5430 or USB | main 5 V rail. USB 5 V comes from +5V_USB via a boost (SX1308, 5.2 V) |
| VDD3.3V | MP2144GJ buck from +5V | CPU, eMMC, QSPI, PHYs. 3.3 V only |
| CPU_VDDA | VDD3.3V through ferrite | analog supply of the MCU |
| VREF+ | **VREF_2.5V, external 2.5 V reference** (CJ431 mounted; REF3025 position is the alternative) | the ADC reference is 2.5 V, not 3.3 V. VREF- = CPU_VREF- (ground). SCH-2, SCH-8 note |
| VCAP1/VCAP2 | 2.2 uF each ("225/10") | internal LDO in use, consistent with `SCUEN = 0` in source |
| VBAT | coin cell MS621FE through 1N4148 and 3K, also fed from +5V by diode | backs RTC, backup SRAM |
| PDR_ON | tied high through 10K (read from the rasterized page, small print: check) | brown-out reset enabled |
| BOOT0 | 10K pull-down R108; R109 pull-up position not fitted (不贴) | BOOT0 is low: flash boot. Read from the rasterized page: check |
| VOUT_3.3V, VOUT_5V | MT9700 current-limited switches, to target port pins 24 and 26 | limit about 2 A on 5 V (R159 note, 2020-07). No MCU control or sense pin of their own was found |
| TVCC (target supply and level-shifter reference) | ME6221 LDO, output set by MCP4018 digital pot on soft I2C; enable on PC13 | see section 17 |
| +/-12.4 V, +9 V (DAC output stage) | TPS65130 inverting/boost converter, enabled by **PE3** (65130_SW) through Q7 and a P-FET | see section 11 |
| +5V_DSO | SX1308 boost, 5.2 V, for the old scope module | SCH-8 |
| +5V_1MH, +3.3V_CURRTEST | filtered 5 V and an XC6206 3.3 V for the high-side current-sense amplifier | SCH-3 |

Supply monitoring the MCU can read: TVCC voltage (PH2), TVCC current (PF5), 12 V/24 V input (PH3), USB 5 V (PH5). All on ADC3, see section 11.

## 3. Memory map

### 3.1 Internal

| region | address | size | source | tag |
|---|---|---|---|---|
| Internal flash | 0x08000000 | 128 KB per datasheet; behaves as **2 MB** (2 banks of 1 MB) | DOC13 (app image 1.29 MB at 0x08020000); `project.uvprojx` "STM32H743IIKx", IROM 0x08000000/0x200000; vendor note says force 2 MB | FROM-PUBLIC-SOURCE / DOC13. The marking was not read from a chip: UNKNOWN |
| Boot loader | 0x08000000-0x0801FFFF (128 KB, sector 0) | H7-BOOT v2.06 | DOC14 table 1 | verified on a unit (DOC14), not a schematic item |
| Application | 0x08020000-0x081FFFFF | stock V2.33 is 1,292,096 bytes; keep <= 1,310,720 | DOC14 section 4 | as DOC14 |
| ITCM | 0x00000000 | 64 KB | ST reference manual, not in supplied sources; stock scatter does not use it | UNKNOWN (use) |
| DTCM | 0x20000000 | 128 KB | `h7-tool_release.sct` (commented block), `bsp_cpu_adc.c` buffers at 0x20000000 and +64 KB | FROM-PUBLIC-SOURCE |
| AXI SRAM | 0x24000000 | 512 KB | scatter file RW region `0x24000000 0x00080000`, MPU region 2 | FROM-PUBLIC-SOURCE |
| SRAM1 | 0x30000000 | 128 KB | stock frame buffer for the LCD (`s_pDispBuf = 0x30000000`) | FROM-PUBLIC-SOURCE |
| SRAM2 | 0x30020000 | 128 KB | scatter comment | FROM-PUBLIC-SOURCE |
| SRAM3 | 0x30040000 | 32 KB | Ethernet descriptors/buffers in the scatter file; MPU region 0/1 | FROM-PUBLIC-SOURCE |
| SRAM4 | 0x38000000 | 64 KB | stock ADC DMA buffers (`aADCH1ConvertedData = 0x38000000`, `aADCH2ConvertedData = +32 KB`), MPU region 5 | FROM-PUBLIC-SOURCE |
| Backup SRAM | 0x38800000 | 4 KB | clock enabled in `bsp.c`; contents use UNKNOWN | FROM-PUBLIC-SOURCE |

Stock linking (scatter `h7-tool_release.sct`, FROM-PUBLIC-SOURCE): code at 0x08020000 length 0x1E0000; `.data/.bss` in AXI 0x24000000-0x2407FFFF;
`startup_stm32h743xx.s` puts the stack (28 KB) and heap (256 KB) in `.bss`, so the **V1.49 initial SP is in AXI** (0x24075DF8 in the shipped bin).
The V2.33 binary has SP 0x2001FFFF (DTCM top) per DOC13, so the layout changed. DOC14 requires only that SP be in DTCM or AXI.

Stock MPU set-up (`MPU_Config()` in `bsp.c`), FROM-PUBLIC-SOURCE: 0x30040000 256 B device, 0x30044000 16 KB non-cacheable shared,
AXI 0x24000000 512 KB write-back-cacheable, 0x30000000 256 KB non-cacheable, 0x60000000 32 B (FMC I/O) non-cacheable, 0x38000000 64 KB non-cacheable.
`CPU_CACHE_Enable()` turns on I and D cache. A bare-metal image that runs DMA from SRAM1-4 should set the same non-cacheable attributes or clean/invalidate by hand.

**DTCM word 0x20000000 is reserved by the boot loader protocol** (DOC14 sections 1 and 4): the app writes 0x5AA51234 there and resets to enter the update mode,
the boot loader clears it. Stock uses 0x20000000 for waveform buffers, so it only works because the word is written just before the reset. A bare-metal image must not
zero it before reading, and its linker script should start DTCM at 0x20000004 or put a NOLOAD word there.

### 3.2 External

| device | part | bus | pins | source | tag |
|---|---|---|---|---|---|
| QSPI NOR | W25Q256JV, 32 MB (256 Mbit), WSON 8x6 | QUADSPI bank 1 | CS **PG6** (AF10), CLK **PB2** (AF9), IO0 **PD11**, IO1 **PD12**, IO2 **PF7**, IO3 **PD13** (all AF9) | SCH-3; `bsp/bsp_qspi_w25q256.c` first pin block (a second block there is an old eval-board option, ignore) | VERIFIED-IN-SCHEMATIC. Contents: fonts per DOC13; layout UNKNOWN, do not erase |
| eMMC | Toshiba THGBMDG5D1LBAIL, WFBGA153 (4 GB class, part-number reading) | SDMMC1, 8-bit | D0 **PC8**, D1 **PC9**, D2 **PC10**, D3 **PC11**, D4 **PB8**, D5 **PB9**, D6 **PC6**, D7 **PC7**, CLK **PC12**, CMD **PD2** (22 ohm series; 47K pull-ups on data) | SCH-4; `bsp/bsp_emmc.c` | VERIFIED-IN-SCHEMATIC. eMMC RSTN is wired to MCU NRST through R19 (0 ohm); no GPIO controls it |
| I2C EEPROM | 24C16 fitted (footprint FT24C04A), device address 0xA0, 1-byte word address in the 24C16 config | soft I2C: SCL **PI7**, SDA **PF15** | SCH-3 note "实际贴装的是24C16", `bsp/bsp_i2c_gpio.c`, `bsp_i2c_eeprom_24xx.h` | VERIFIED-IN-SCHEMATIC / FROM-PUBLIC-SOURCE |
| SDRAM / SRAM / parallel bus | none fitted. FMC pins are used as GPIO/alternate functions on the target port | | SCH-1, SCH-7 | VERIFIED-IN-SCHEMATIC |

eMMC details: bus 3.3 V (VCC and VCCQ), the stock SDMMC1 driver uses `ClockDiv = 4` of the kernel clock, hardware flow control on, 4-bit and 8-bit modes both possible. FROM-PUBLIC-SOURCE.
It is the "user disk" (Lua, fonts, files) and **must not be written** in a first image: layout and boot-loader interaction are UNKNOWN.

**The EEPROM probably holds the factory calibration.** In V1.49 `PARAM_ADDR = 0` (basic parameters) and `PARAM_CALIB_ADDR = 1024` (calibration, all ADC/DAC/TVCC gain tables) are both read/written with `ee_ReadBytes/ee_WriteBytes`
(`app/src/param.c`). DOC14 says "where the calibration lives is UNKNOWN" for V2.33; V1.49 says EEPROM. **Do not write the EEPROM from a first bare-metal image.** Read-only use is safe.
The vendor scope calibration is also needed for any meaningful voltage figure from the ADC.

## 4. USB

### 4.1 High-speed port through an external ULPI PHY

PHY: Microchip/SMSC **USB3300-EZK** (SCH-5). 60 MHz ULPI, 8-bit SDR, own 24 MHz crystal. VERIFIED-IN-SCHEMATIC for the whole table.

| ULPI signal | MCU pin | AF |
|---|---|---|
| CK (CLKOUT) | **PA5** | AF10 |
| DIR | **PI11** | AF10 |
| NXT | **PH4** | AF10 |
| STP | **PC0** | AF10 |
| D0 | **PA3** | AF10 |
| D1 | **PB0** | AF10 |
| D2 | **PB1** | AF10 |
| D3 | **PB10** | AF10 |
| D4 | **PB11** | AF10 |
| D5 | **PB12** | AF10 |
| D6 | **PB13** | AF10 |
| D7 | **PB5** | AF10 |

AF10 and the pin list also match `User/teeny_usb/usb_app/board_config.h` (`GPIO_AF10_OTG_HS`). FROM-PUBLIC-SOURCE.

Facts about the PHY wiring (all VERIFIED-IN-SCHEMATIC, SCH-5):

- **There is no PHY reset GPIO.** The USB3300 RESET pin (9) is drawn tied to GND. The PHY comes up with power. No MCU pin needs to toggle.
- The PHY pins DP/DM go through a USBLC6-2SC6 ESD array to the mini-USB connector CN4 (+5V_USB, D-, D+, GND). The USB ID pin is not connected ("ID不能接地": ID must not be grounded). Device mode only.
- PHY VBUS pin 4 is fed from the +5V rail through R138 (820 ohm) with a 12.1 K bias resistor R111, so VBUS looks present whenever the board is powered, not only when a cable is plugged.
  EXTVBUS (pin 10) is on net VBUS_DET, a 10K/10K divider from +5V (about 2.5 V). The drawing is small here; whether EXTVBUS is really on that divider or on 3.3 V is the one place the text is ambiguous (check on the page).
  No MCU pin reads VBUS (`VBUS_DET` stays on sheet 5). Consequence for firmware: it cannot tell cable-attached from not-attached by a GPIO; use the PHY/OTG session logic.
- `HOST_PORT_POWER_ON_HS()` in `board_config.h` toggles PH12 as a host power switch, but the call is commented out (`HOST_PORT_POWER_ON()` is empty). PH12 is D4 on the target port (section 12), so **do not drive it as a USB power pin.**
- PA4's alternate "USB_OTG_HS_SOF" is not used.
- PB12/PB13 double as FDCAN2 pins in `bsp/bsp_can.c`; with ULPI in use FDCAN2 is **not available**. Only FDCAN1 (PA11/PA12) exists (section 13).

Stock USB stack: TeenyUSB (`User/teeny_usb`), external-PHY HS only (`OTG_HS_EXTERNAL_PHY`), DMA **not** enabled (`OTG_HS_ENABLE_DMA` commented out), `SUPPORT_OTHER_SPEED`.
A second USB path, the ST library in `User/st_usb` (VCP, mass storage), is compiled in V1.49 as well. FROM-PUBLIC-SOURCE.
USB clock selection in `bsp.c` is PLL3-Q 48 MHz; the OTG_HS core in ULPI mode needs the AHB clock >= 30 MHz (ST general rule, not in the supplied sources).

### 4.2 Full-speed port

The internal FS PHY pins PA11 (DM) and PA12 (DP) exist on the MCU but on this board they are the **CAN1 RX/TX nets** (section 13). `HOST_PORT_POWER_ON_FS` in source refers to PG8, which is D1_DIR. No FS USB connector exists. Not usable. VERIFIED-IN-SCHEMATIC.

### 4.3 What is known about the V2.33 enumeration (HID + Modbus)

From DOC01 (observed on a unit): VID:PID **c251:f00a**, manufacturer "H7-TOOL By ARMFLY", product "H7-TOOL CMSIS-DAP", high speed, three interfaces:
0 = vendor class (probably CMSIS-DAP bulk), 1 = HID vendor usage page 0xFF00, 512-byte reports, 2 = HID vendor usage page 0xFF00, **1024-byte in/out reports, no report ID** = the Modbus-RTU register channel.
Frame inside the report: `[addr][fc][payload][CRC16 lo][CRC16 hi]` zero-padded to 1024 bytes; address 0x01 is the tool, 0x10 the 250M module.
The public V1.49 source has **different descriptors**: a composite with a 64-byte HID report (descriptor `COMP_ReportDescriptor_if0`, count 0x40), five CDC functions and VID/PID in `teeny_usb_desc.c`; the Modbus link there runs over a CDC (`usbd_RxHostModbus` in `usb_if.c`, a 512-byte split heuristic).
So the V2.33 descriptor set, endpoint numbers, polling intervals, string descriptors and the HID report descriptor are **UNKNOWN from sources and must be reproduced from a live `lsusb -v`/hidraw descriptor dump** (a read-only action on a running unit; not done here).
The Modbus register map (e.g. 0xFF07 app version, 0xFF00-0xFF05 UID, 0xFF7F boot request) is in `modbus/modbus_reg_addr.h` for V1.49 and DOC02 for V2.33.

## 5. Display

| item | value | source | tag |
|---|---|---|---|
| Panel | 1.3 inch, **240x240 colour**, controller **ST7789**, SPI, on the display board D254 (rev 3.0, 2019-10-19) through a 12-pin FPC (CN1/CN3) | D254; `bsp/bsp_tft_st7789.c` header | VERIFIED-IN-SCHEMATIC (board), FROM-PUBLIC-SOURCE (controller part) |
| SPI | **SPI5** master, SCK **PH6** (AF5), data **PH7** (AF5, the pad named SPI5_MISO; stock uses `IOSwap = ENABLE` so the shifted data appears on it), CS **PE1** (software GPIO), D/C (called LCD_RS) **PG15**, reset **PB6** | SCH-3; `bsp_tft_st7789.c` lines 70-105, 155-175 | VERIFIED-IN-SCHEMATIC for the net names, FROM-PUBLIC-SOURCE for the IOSWAP trick |
| Backlight | **PH9**, TIM12_CH2 PWM (stock 20 kHz) -> transistor Q1 on the display board; LED supply +5V | SCH-3, D254; `bsp_tft_lcd.c:196` | VERIFIED-IN-SCHEMATIC |
| Panel power enable | **PH15** (LCD_PWR_EN) -> LDO GM6155 EN on D254, 3.3 V TFT supply | D254; source | VERIFIED-IN-SCHEMATIC |
| Stock transfer | SPI5 16-bit frames, DMA2 Stream3, request `DMA_REQUEST_SPI5_TX`, prescaler 2, CPOL=1 CPHA=1edge, framebuffer in SRAM1 at 0x30000000 | `bsp_tft_st7789.c` | FROM-PUBLIC-SOURCE |

Older hardware revisions in the source comment ("第4、5版", "旧版") used other pins (PG10, PF3, PG2, PC10, PC12 ...). The schematic and the "第6版" block agree with the table above, but V2.33 hardware could be a later revision: UNKNOWN. Pin numbers on the FPC itself were not decoded; the net names are what the table relies on.

## 6. Keys, LED, buzzer

| item | pin | polarity | source | tag |
|---|---|---|---|---|
| Key S (KEY1) | **PF2** | active low (10K pull-up on D254) | SCH-2/3, D254; `bsp/bsp_key.c` `{GPIOF, GPIO_PIN_2, 0}` | VERIFIED-IN-SCHEMATIC |
| Key C/OK (KEY2) | **PG0** | active low | same, `{GPIOG, GPIO_PIN_0, 0}` | VERIFIED-IN-SCHEMATIC |
| LED | **PI8** (net LED_RED, goes to the display board as RUN_LED with a 2K resistor) | on = 0 (`LED1_ON()` = `BSP_SET_GPIO_0`) | `bsp/bsp_led.c`; D254 | FROM-PUBLIC-SOURCE (polarity) |
| Buzzer | **PG1**, active buzzer through S8050 (Q8), 1k base | high = sounding | SCH-3; `bsp_beep.c` | VERIFIED-IN-SCHEMATIC |

The boot loader's "hold S (old) / OK (new) at power-up" entry (DOC13/DOC14) means the stock boot reads one of these two keys. Which of PF2 / PG0 it reads, and whether V2.33 hardware is the "old" or "new" mapping, is UNKNOWN.
An app does not need them to boot; they are only the recovery entry.

## 7. Debug/trace pins and JTAG

- The H7's own SWD: **PA13 SWDIO**, **PA14 SWCLK**, **NRST**, each with 33 ohm series and an ESD array, to header CN7 (5 pins; SWDIO pin 3, SWCLK pin 4, NRST pin 5 and 3.3 V on pin 1 read from the rasterized page, check before use). SCH-2. VERIFIED-IN-SCHEMATIC. **No probe was available** and the boot loader is not rewritable without one (DOC14).
- Trace/JTAG alternates PB3 (JTDO/SWO) and PB4 (NJTRST) are used as SDMMC2_D2/D3 for the ESP32 (section 15) - they are plain I/O after reset, not JTAG, once configured.
- NRST reset circuit: 1k (R115) + 1 uF (C97, "105/10") on the NRST net, which also feeds the eMMC RSTN, Ethernet PHY nRST and the ESP32 reset logic. SCH-2, SCH-4, SCH-5. VERIFIED-IN-SCHEMATIC.

## 8. Watchdog

- No watchdog is started anywhere in V1.49: `HAL_IWDG_MODULE_ENABLED` is defined in `stm32h7xx_hal_conf.h`, and `bsp/bsp_watchdog.c` is leftover Cortex-M4 StdPeriph code (`IWDG_Enable()`, `IWDG_WriteAccessCmd`) that is not called by `bsp_Init()` or `main.c`. FROM-PUBLIC-SOURCE.
- Option bytes (hardware IWDG option `IWDG1_HW`, RDP, BOR level, boot address) of this unit were never read: **UNKNOWN**. If hardware IWDG is set the board would reset in about the IWDG timeout after reset.
  The stock V2.33 application starts normally and the boot loader jumps to it, so a watchdog that fires needs the app to refresh it: the first image should assume nothing and write the IWDG registers explicitly only if a reset loop is seen.
- The H7 has the independent watchdog on LSI and a window watchdog on APB3; neither has a board dependency.

## 9. RTC and backup

RTC on LSE (X4), VBAT from the coin cell, tamper pins PC13 (`TVCC_ON/OFF`, see below), PI8 (LED), PA0-WKUP and PI11 (ULPI DIR) are also tamper/wake pins and share the net. `bsp_InitRTC()` is called at start-up. FROM-PUBLIC-SOURCE.
PC13 is in the backup domain: 3 mA, 2 MHz limits when used as an output. It is the **TVCC enable**, so the limit applies to a TVCC gate signal (a transistor drive from PC13 is the schematic's choice).

## 10. Timers and DMA used by the stock app (for conflict planning only)

FROM-PUBLIC-SOURCE: TIM3 (scope ADC trigger, `bsp_cpu_adc.c`), TIM6 trigger for DAC with DMA1_Stream5, TIM12_CH2 (backlight), TIM1 CC1 (sampling-rate timer), DMA1_Stream1 (ADC1 CH1), DMA2_Stream1 (ADC3 CH2), DMA2_Stream3 (SPI5 TX for LCD), MDMA channel 1 (QSPI), SDMMC1 internal DMA (eMMC), ETH DMA (SRAM3 descriptors).
None of these is forced by the board; they are just what the stock build chose.

## 11. ADC and DAC

### 11.1 Analog supply and reference

ADC reference VREF+ = **2.5 V** (external CJ431), VREF- = 0 V, VDDA = 3.3 V filtered (section 2). So full scale of the ADCs is 2.5 V. The H7 ADC runs from a kernel clock that the stock code sets; the clock mux (ADC clock source) in the stock build is UNKNOWN beyond the PLL values above. VERIFIED-IN-SCHEMATIC for the reference; the rest is FROM-PUBLIC-SOURCE.

### 11.2 ADC channel assignment

| function | MCU pin | ADC/channel | front end | source | tag |
|---|---|---|---|---|---|
| Scope CH1 (old module / "CH1" header pin) | **PF11** (P, ADC1_INP2) with **PF12** (N, ADC1_INN2); PF13/PF9 and PF14/PF10 are the same nets for ADC2/ADC3 | ADC1 channel 2, DMA1_Stream1 | D268 module: TLV2372 buffer, CD74HC4051 gain mux, CPC1017N AC-coupling relay, +-2.5 V -> 0..2.5 V level shift. Control via 595 (below) | SCH-6 connector J4, `bsp_cpu_adc.c:94-110` | VERIFIED-IN-SCHEMATIC (nets), FROM-PUBLIC-SOURCE (ADC1/ch2) |
| Scope CH2 | **PC3_C** (P, ADC3_INP1) and **PC2_C** (N, ADC3_INN1) | ADC3 channel 1, DMA2_Stream1 | same module, second channel | same | same |
| High-side load current | **PA6** (ADC12_INP3, via R168 0 ohm) | ADC1 ch3 | AD8418 current-sense amp + LMV321, two gains selected by **PG2** (GAIN_CURR) through RS2057 switch | SCH-3 | VERIFIED-IN-SCHEMATIC |
| Load voltage | **PF8** (ADC3_INP7) | ADC3 ch7 | resistor divider + LMV321 | SCH-3 | VERIFIED-IN-SCHEMATIC |
| NTC / resistance measure | **PF3** (ADC3_INP5) | ADC3 ch5 | LMV321 + header CN9 | SCH-3 | VERIFIED-IN-SCHEMATIC |
| TVCC current | **PF5** (ADC3_INP4) | ADC3 ch4 | INA180A3, shunt 0.05 ohm | SCH-8 | VERIFIED-IN-SCHEMATIC |
| TVCC voltage | **PH2** (ADC3_INP13) | ADC3 ch13 | divider 15K | SCH-8 | VERIFIED-IN-SCHEMATIC |
| Input 12/24 V | **PH3** (ADC3_INP14) | ADC3 ch14 | divider | SCH-8 | VERIFIED-IN-SCHEMATIC |
| USB 5 V | **PH5** (ADC3_INP16) | ADC3 ch16 | divider 10K/15K (gives 2.4 V at 6 V) | SCH-8 | VERIFIED-IN-SCHEMATIC |
| Expansion pin | **PF4** (ADC3_INN5/INP9) to header CN8 pin | ADC3 | direct | SCH-2 | VERIFIED-IN-SCHEMATIC |

`bsp_cpu_adc.c` header comment lists the same assignment (PF11 CH1, PA6 high-side current, PC3 CH2, PF5, PF3, PF8, PH2, PH3, PH5). FROM-PUBLIC-SOURCE.
The stock scope samples in single-ended mode (`ENABLE_DIFFERENTIAL_ENDED 0`).
Single-ended sampling of the INP pins with 16-bit mode: depth not verified. Stock buffers are 16-bit in 64 KB of SRAM4.

**Scope module gain/coupling control** is a 74HCT595 on the module driven by three MCU lines on port 6 header J1: **PG5** (595_SDI), **PI4** (595_RCLK), **PI9** (595_SCLK) (SCH-6, SCH-2). Output bits: Q0-Q2 CH1 gain (A,B,C -> 4051), Q3 CH1 AC/DC, Q4-Q6 CH2 gain, Q7 CH2 AC/DC (`bsp_cpu_adc.c:30-70`, D268). VERIFIED-IN-SCHEMATIC / FROM-PUBLIC-SOURCE.
J1 pins are +5V_DSO, ground, three signals; the pin order is not fully decoded.

The 26-pin target port carries CH1+/CH1-/CH2+/CH2- on pins 1-4 (section 12). These are the inputs to the same ADC front end (CH1 -> PF11/PF12, CH2 -> PC3/PC2) through the J3/J4 header pair. Not a separate scope.

### 11.3 DAC

| item | value | source | tag |
|---|---|---|---|
| DAC1_OUT1 | **PA4** -> TP2274 (later OPA4171) four op-amp stage with a P-FET current source, output +-10 V / 0-20 mA "AOUT1"/VOUT on CN6 | SCH-6 | VERIFIED-IN-SCHEMATIC |
| DAC1_OUT2 | PA5 - **not available**: it is the ULPI clock pin | SCH-1, SCH-5 | VERIFIED-IN-SCHEMATIC |
| Output stage supply | +12.4 V / -12.5 V from TPS65130; its enable is **PE3** through a transistor and P-FET (high = on); +9 V rail from the +12.4 V by a zener | SCH-6; `bsp_cpu_dac.c:42-48` | VERIFIED-IN-SCHEMATIC |
| Stock waveform output | TIM6 trigger, DMA1_Stream5 | `bsp_cpu_dac.c` | FROM-PUBLIC-SOURCE |
| DAC reference | VREF_2.5V_DAC (same CJ431 net) | SCH-6 | VERIFIED-IN-SCHEMATIC |

One DAC channel drives both outputs "synchronously": the 0-20 mA and +-10 V are two outputs of one op-amp chain ("一个DAC控制，两路输出是同步变化的"). The "0-5V" switch note on the sheet is a range-select option and the way it is wired is UNKNOWN.
The old scope module also has an MCP4725 (address 0xC0) in the source for a scope offset bias (`bsp_i2c_mcp4725.c`); on which I2C bus it sits and whether it exists on the hardware that shipped is UNKNOWN (no MCP4725 appears in the main board schematic text and the D268 text did not show one).

## 12. Target port (26-pin RK-26P, J2) and its signals

All VERIFIED-IN-SCHEMATIC (SCH-7, D380 which draws the same pin numbers on its mating J1). The target port is a 2x13 header.

| J2 pin | signal | MCU net |
|---|---|---|
| 1 / 3 | CH1+ / CH1- | scope CH1 (sec. 11) |
| 2 / 4 | CH2+ / CH2- | scope CH2 |
| 5 | RS232_TX | PA9 path (USART1) via transceiver UT3232 |
| 6 | RS232_RX | into the 3-input AND to PA10 |
| 7 | RS485_A | TP8485E transceiver |
| 8 | RS485_B | " |
| 9 | CANH | TJF1051T transceiver |
| 10 | CANL | " |
| 11 | TTLTX (D10) | PA9 / PE13 |
| 12 | TTLRX (D11) | PA10 / PE14 |
| 13 | UTX / **D0** | |
| 14 | URX / **D1** | |
| 15 | SDO / **D2** | |
| 16 | SDI / **D3** | |
| 17 | NRST / **D4** | target reset |
| 18 | SCK / **D5** | |
| 19 | CLK / **D6** | SWCLK |
| 20 | SDA / **D7** | I2C SDA (probable) |
| 21 | DIO / **D8** | SWDIO |
| 22 | SCL / **D9** | I2C SCL (probable) |
| 23 | GND | |
| 24 | +3.3V (VOUT_3.3V) | |
| 25 | TVCC | |
| 26 | +5V (VOUT_5V) | |

The pin order of 11-22 was taken from the D380 adapter (it draws the 26 pins one per line) and checked against SCH-7 for pins 1-10 and 23-26; the resistor/label alignment of 11-22 on SCH-7 itself is dense, so treat pins 11-22 as read from D380, and verify with a continuity check before wiring anything critical.
Rows D291 and D380 agree.

Each digital line D0-D9 goes through a **74LVC1T45 direction-controlled level shifter** to the target (A = CPU side at 3.3 V, B = target side at TVCC) with a 33 ohm (later 100 ohm for R63/R71, note 2021-01) series resistor and an ESD array.
DIR = 1: CPU -> target, DIR = 0: target -> CPU. Each line has **up to three MCU pins tied to the same net through 0 ohm resistors**; the unused two must be left as high-impedance inputs (analog or input mode) or the pins fight.
Direction pins and MCU pin choices (`bsp/bsp_fmc_io.c` defines, SCH-7 net labels agree):

| line | DIR pin | candidate MCU pins (same net) |
|---|---|---|
| D0 | **PH8** | PD14 (FMC_D0), PI0 (TIM5_CH4), PA15 (**UART7_TX**) |
| D1 | **PG8** | PD15 (FMC_D1), PH10 (TIM5_CH1 / encoder), PA8 (**UART7_RX**) |
| D2 | **PD9** | PD0 (FMC_D2), PE6 (SPI4_MOSI), PB7 (TIM4_CH2) |
| D3 | **PG10** | PD1 (FMC_D3), PE5 (SPI4_MISO), PH11 (TIM5_CH2) |
| D4 | **PG12** | PE7 (FMC_D4), PE4 (SPI4_NSS), PH12 (TIM5_CH3) |
| D5 | **PG7** | PE8 (FMC_D5), PE2 (SPI4_SCK), PI5 (TIM8_CH1) |
| D6 | **PD10** | PE9 (FMC_D6), PD3 (SPI2_SCK), PA0 (TIM2_CH1) |
| D7 | **PI1** | PE10 (FMC_D7), PI6 (TIM8_CH2), PF0 (I2C2_SDA, per D291; the source comment says D8) |
| D8 | **PG9** (NOE_DIR) | PE11 (FMC_D8), PD4 (FMC_NOE), PI3 (SPI2_MOSI) |
| D9 | **PI2** (NWE_DIR) | PE12 (FMC_D9), PD5 (FMC_NWE), PF1 (I2C2_SCL, per D291) |
| D10 TTL TX | (no DIR pin in the source list; PE3 in the stale comment is the DAC supply enable) | PA9 (USART1_TX), PE13 (FMC_D10) |
| D11 TTL RX | fixed | PA10 (USART1_RX), PE14 (FMC_D11) |

(The D2/D3/D4 net-to-MCU alternates are read from SCH-7 net labels and the source comment, check D2 and D3 before relying on the alternates; the DIR pins are from `#define`s and SCH-1/2 labels.)

Stock usage (FROM-PUBLIC-SOURCE): D0/D1 as UART7 (AF11) for the 250M module and user serial; D4/D6/D8 as SWD target (`daplink/.../stm32h750/IO_Config.h`: nRESET **PE4**, SWCLK **PD3**, SWDIO **PD4**; the DAPLink code is the 2021 version and uses the FMC/SPI pin choices);
D2/D3/D5 + D0/D1 as 250M SPI (SDO D2, SDI D3, SCK D5: DOC03); D7/D9 as I2C; FMC data/OE/WE strobes for fast parallel capture; TIM5 and TIM8 channels for pulse/encoder meters.

**Target reset drive.** SCH-7 also shows **PG3 (SWD_NRST)** driving a transistor Q11 (S8050, through R103 5.1K) that pulls the target-reset net; the DAPLink code uses PE4. Whether V2.33 uses PG3 instead of PE4 is UNKNOWN. Both are on the board.

### 12.1 250M scope module connection (signals only)

There is no dedicated connector: the module plugs into the same header (DOC03): UTX D0, URX D1, SDO D2, SDI D3, SCK D5, plus TVCC set to 3.3 V as its logic level; do not use those pins for anything else while it is in use. The module is a Modbus slave at address 0x10 reached through the H7-TOOL (DOC03/04). UNKNOWN from sources: the protocol between H7-TOOL firmware and the RP2040 beyond the register map; its UART baud, SPI mode and the enable sequence's electrical effect on the lines (D2/D3/D5 are SPI AF on PE6/PE5/PE2 or PB7/...; which alternate the stock firmware selects is UNKNOWN).

### 12.2 Adapter boards (outside the MCU, listed for completeness)

- D291-2: breakout of CH1/CH2, 8-bit bus with LED indicators (74HCT244), RS232/RS485/CAN screw terminals, SWD header. Signals D0-D7 named as above.
- D315-2: 1-to-4 programmer adapter. Uses D0 (NRST), D2/D3 (SWCLK-4/SWDIO-4), D4/D5/D6/D7 (SWDIO-3, SWDIO-2, SWCLK-3, SWCLK-2), D8/D9 (SWDIO-1, SWCLK-1) - note these differ from the single-target SWD choice D4/D6/D8. FROM the adapter schematic.
- D380-1: simple breakout, same as D291.

## 13. UART, I2C, SPI, CAN summary

| peripheral | pins | role | source | tag |
|---|---|---|---|---|
| USART1 | TX **PA9**, RX **PA10** (AF7) | console/RS232/RS485/TTL on the target port. RX is the AND of the three receivers (SN74LVC1G11 3-input AND: RS232_CPU_RX, RS485_CPU_RX, TTL_RX), so unused ones must idle high | SCH-4/7; `bsp_uart_fifo.c` | VERIFIED-IN-SCHEMATIC |
| RS-485 direction | **PI10** (RS485_TXEN) | high = transmit (source EIO_485_TXEN) | SCH-4 | VERIFIED-IN-SCHEMATIC |
| UART4 | TX **PH13**, RX **PH14** (AF8) | ESP32-S WiFi module TXD0/RXD0 | SCH-4 | VERIFIED-IN-SCHEMATIC |
| UART7 | TX **PA15**, RX **PA8** (AF11) | target port D0/D1 | SCH-7; `bsp_fmc_io.c` | VERIFIED-IN-SCHEMATIC |
| FDCAN1 | TX **PA12**, RX **PA11** (AF9) | CAN via TJF1051T on the target port (pins 9/10) | SCH-4; `bsp_can.c` | VERIFIED-IN-SCHEMATIC |
| FDCAN2 | would be PB13/PB12 | **unavailable** (ULPI) | | VERIFIED-IN-SCHEMATIC |
| I2C (soft) | SCL **PI7**, SDA **PF15** | on-board 24C16 and MCP4018 TVCC pot | SCH-3/8; `bsp_i2c_gpio.c` | VERIFIED-IN-SCHEMATIC |
| I2C (external, soft/I2C2) | SDA **PF0**, SCL **PF1** | target port D7/D9 | SCH-7 | VERIFIED-IN-SCHEMATIC (nets) |
| SPI5 | SCK PH6, MOSI-by-swap PH7 | LCD | sec. 5 | |
| SPI2/SPI4 | PD3/PI3 and PE2/PE5/PE6/PE4 | target port D-lines | `bsp_spi_bus.c` | FROM-PUBLIC-SOURCE |
| ESP32 control | EN **PF6** (ESP32-S_RESET), IO0 boot **PG4** (BOOT_OPTION) | reset and download-mode strap | SCH-4 | VERIFIED-IN-SCHEMATIC |
| ESP32 SDIO | SDMMC2: D0 **PB14**, D1 **PB15**, D2 **PB3**, D3 **PB4**, CK **PD6**, CMD **PD7** | alternative to UART for WiFi | SCH-4 | VERIFIED-IN-SCHEMATIC |

## 14. Ethernet

LAN8720A RMII (SCH-5): REF_CLK **PA1**, MDIO **PA2**, MDC **PC1**, CRS_DV **PA7**, RXD0 **PC4**, RXD1 **PC5**, TXEN **PG11**, TXD0 **PG13**, TXD1 **PG14**. The PHY reset comes from NRST. RJ45 with magnetics (CN1). VERIFIED-IN-SCHEMATIC. Descriptors in SRAM3 at 0x30040000 in stock. Not needed for a first image.

## 15. 5 V / bus switches and boot-strap pins an app must not disturb

- **PC13** TVCC enable (output, high = TVCC on). Stock source also has an inversion-free helper, so default out-of-reset is low = TVCC off. If the app does not touch it, TVCC stays whatever the pull resistors dictate: UNKNOWN pull direction, read it on the board; a target board must not be connected during the first test.
- **PG4** ESP32 IO0 strap: leave as input/float or high; low at an ESP32 reset puts it in download mode.
- **PF6** ESP32 EN: leave as input; the ESP32 pulls itself up.
- **PG3** target-reset driver (Q11) and **PE4/PD3/PD4** target SWD lines: leave as inputs so the target is not reset.
- **PE3** enables the +-12 V DAC supply: leave low until the DAC is wanted.
- **PH15** LCD power, **PH9** backlight: only needed if the display is used.
- **PI4, PI9, PG5**: 595 lines; leaving them as inputs lets the scope-module relays stay in their last state, so drive them to a known value if the module is plugged in.

## 16. What the boot loader and stock app depend on

From DOC13/DOC14 (observed and disassembled, not from schematics):

1. Boot loader (H7-BOOT v2.06) at 0x08000000-0x0801FFFF. It reads `*(u32*)0x20000000` at reset: 0x5AA51234 -> update mode, 0x11223344 -> normal path, anything else -> key test then jump to the app.
2. App valid when `((*(u32*)0x08020000) + 0x20000) & 0x2FF00000` equals 0x20000000 or 0x24000000, i.e. initial SP in DTCM (0x2000xxxx) or AXI (0x2400xxxx). No CRC or signature.
3. Words 1..5 of the vector table (reset, NMI, HardFault, MemManage, BusFault) must all be 0x08xxxxxx when the image is written through the boot loader's USB disk.
4. The boot loader itself runs USB HS through the same ULPI PHY (enumerates as 0483:5720 "Mass Storage in HS Mode") and a virtual FAT12 disk served from RAM. It also needs the LCD (it shows an "upgrade APP firmware" screen per the vendor manual) and a key for the manual entry. A bare-metal app inherits no peripheral state worth relying on: after SYSRESETREQ the clock is HSI and all peripherals are in reset state.
5. After a flash write the boot loader resets by itself in about 1 s (DOC13/14).
6. The app must set `SCB->VTOR = 0x08020000`. SystemInit in the stock code does exactly this (`VECT_TAB_OFFSET = 128*1024`).
7. Parameters and factory calibration live on the EEPROM in V1.49 (section 3.2). Do not write the EEPROM or eMMC, and do not erase any flash sector below 0x08020000.
8. The stock app does a software reset into the boot loader with this sequence for register 0xFF7F = 2 (`modbus/modbus_register.c:2284`): stop USB, wait 2 s, `*(u32*)0x20000000 = 0x5AA51234; NVIC_SystemReset();`. DOC14 measured that the 2 s is optional.

## 17. TVCC and power-output control

| item | detail | source | tag |
|---|---|---|---|
| TVCC enable | **PC13** (high = on) | `bsp/bsp_power_tvcc.c` `TVCC_EN_GPIO = GPIOC pin 13`, SCH-8 net "PC13/TVCC_ON/OFF" | VERIFIED-IN-SCHEMATIC |
| TVCC voltage set | MCP4018T-503E digital potentiometer, I2C address **0x5E**, on soft I2C PI7/PF15 (shares the bus with the EEPROM) | SCH-8; `bsp_i2c_mcp4018.h` | VERIFIED-IN-SCHEMATIC / FROM-PUBLIC-SOURCE |
| TVCC regulator | ME6221 LDO with feedback network set by the pot; schematic note: 1.221 V*(1+(10.7K+R)/3.24K) = 5.25 V max; manual says output 1.2-5 V, 450 mA max | SCH-8; MAN | VERIFIED-IN-SCHEMATIC / manual |
| TVCC readback | voltage PH2 (ADC3_INP13), current PF5 (ADC3_INP4) through INA180A3 | SCH-8 | VERIFIED-IN-SCHEMATIC |
| TVCC also used as | reference supply (VCCB) of every 74LVC1T45 level shifter and the TVCC buffer op-amp | SCH-7 | VERIFIED-IN-SCHEMATIC |
| VOUT_3.3V, VOUT_5V | fixed current-limited switches (MT9700) to J2 pins 24 and 26; always on, no GPIO | SCH-8 | VERIFIED-IN-SCHEMATIC |

The source calibrates the TVCC set point with a stored table (`AN_CALIB_T TVCCSet`). Without the calibration table (EEPROM), the digital-pot code to voltage mapping is not known: **do not enable TVCC with a target attached in the first image**.
SWD target interface: bidirectional through the same level shifters (section 12), no separate resource.

## 18. Minimum resource set for a first bare-metal image

### (a) Boots, shows it is alive

1. Link at 0x08020000: vector table first; initial SP in DTCM top (0x2001FFFC) or AXI top (0x2407FFFC); words 1..5 flash addresses; image <= 1,310,720 bytes; start DTCM data at 0x20000004.
2. Reset handler: set VTOR = 0x08020000; set up the stack; (optionally) clocks.
3. Clock: the quickest safe state is HSI 64 MHz out of reset. The USB path then still works because the ULPI clock comes from the PHY. If the PLL is brought up, use the stock one: HSE 25 MHz, PLL1 M5 N160 P2 Q4 R2 VOS1, flash latency 4, HPRE /2, all APB /2.
   Power: leave `PWR->CR3` as stock (SCUEN cleared, LDO). **Do not touch option bytes.**
4. One visible output: LED **PI8** (low = on, 8 mA class pin) and/or buzzer **PG1** (high = on); alternatively the backlight **PH9** + power **PH15** + LCD init if a screen is wanted.
5. Do not drive: PC13, PE3, PG3, PG4, PF6, the 595 lines; no flash/eMMC/EEPROM/QSPI write.

### (b) ULPI USB HS with 1024-byte HID Modbus-RTU framing

1. Resources: GPIOA, GPIOB, GPIOC, GPIOH, GPIOI clocks; the 12 ULPI pins in AF10 at very-high speed: PA3, PA5, PB0, PB1, PB5, PB10, PB11, PB12, PB13, PC0, PH4, PI11. RCC: USB1 OTG HS and USB1 ULPI enable bits (RM0433). Compensation cell enabled.
2. USB device core in HS with external ULPI PHY. FIFO budget: the H7 USB OTG HS has 4 KB of FIFO RAM (ST reference manual, not in the supplied sources). A 1024-byte interrupt/bulk packet needs at least 256 words of TX FIFO for the IN endpoint, plus RX FIFO space for the OUT endpoint and EP0: tight and must be sized deliberately. DMA disabled in stock; stay with FIFO mode.
3. Descriptors: match the stock V2.33 enumeration at least for the HID interface (interface 2, vendor usage page 0xFF00, 1024-byte in/out reports, no report ID) so the existing host scripts work; VID:PID c251:f00a for compatibility or a test PID of your own (with the udev rule of DOC01 extended). The descriptor details are UNKNOWN and need a read-only dump of the running unit.
4. Modbus layer: address 0x01, FC 0x03/0x06/0x10, CRC-16/MODBUS poly 0xA001 init 0xFFFF, low byte first, report = frame zero-padded to 1024 bytes, replies larger than 1024 span reports (DOC01).
   Minimum registers (DOC14 section 4, 7): FC03 reads of 0xFF07 (app version) and 0xFF00-0xFF05 (UID, can be a constant), and FC06 0xFF7F = 2 -> echo, stop USB, `*(u32*)0x20000000 = 0x5AA51234; DSB; NVIC_SystemReset()` so that the host update loop keeps working.
5. Nothing else is required: no eMMC, EEPROM, QSPI, LCD, ADC, DAC.

## 19. Risky unknowns, ranked

1. **V2.33 USB descriptors and interface layout are not in the supplied material** (V1.49 differs: 64-byte HID + five CDC, Modbus over CDC). Reproducing interface 2 exactly needs a read-only `lsusb -v` / HID report descriptor dump of a running unit (no write, but it does touch a device, so not done here). Also the endpoint type (interrupt vs bulk), interval and max packet size of the 1024-byte report.
2. **Option bytes, flash size and RDP of this H750 unit are unread.** "Behaves as 2 MB" is from DOC13; any option-byte/IWDG/BOR setting that matters is UNKNOWN, and without an SWD probe the first image cannot recover from a wrong write. Never touch option bytes, never erase below 0x08020000.
3. **Which hardware revision's pin set is on this unit** - the schematics are dated 2019-09-30 (main), the source comments show earlier revisions with other pins, and the schematic notes a 2021-01 resistor change. V2.33 firmware is 2026. The USB, QSPI, eMMC, LED, key, buzzer pins were cross-checked between schematic and source (consistent); the D-line alternates and the DIR pins are consistent; the LCD PH7-by-IOSWAP and PG3 target-reset were not confirmed on hardware.
4. **EEPROM/eMMC/QSPI contents are the product's state** (calibration, fonts, Lua files, parameters). Their layout in V2.33 is UNKNOWN; a bare-metal image that touches them can lose factory calibration, and the vendor GUI would no longer work. Keep them read-only.
5. **VBUS detection and the PHY power-up**: USB3300 RESET is grounded and VBUS is fed from the +5V rail through 820 ohm, EXTVBUS wiring ambiguous (section 4.1). Whether the OTG_HS core sees a valid session/B-device correctly with this wiring, and whether any "disconnect" is ever visible to firmware, is untested; the boot loader and stock app evidently work, so mimic the stock TeenyUSB set-up (soft-connect only).
6. Smaller: SRAM clock enables (D2 SRAM1-3, SRAM4, BKPSRAM) must be enabled explicitly - the stock uses HAL macros whose exact register bits were not re-checked; cache/MPU attributes for DMA regions; PLL3/48 MHz need for the HS core; BOOT0/PDR_ON levels read from a small rasterized page; the DTCM boot-magic word must not be clobbered by `.data/.bss` init.
