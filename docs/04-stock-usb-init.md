# 04 - Stock V2.33: how the USB_OTG_HS device + USB3300 ULPI PHY is brought up

Scope: the register-level sequence the stock app V2.33 (`stock233.bin`, 1,292,096 bytes, VMA 0x08020000) runs to make the
unit enumerate as `c251:f00a` (3 interfaces) on a D428-9 board (`0xFF60 = 0x4289`). Source of truth is the disassembly
(`arm-none-eabi-objdump -b binary -m arm -M force-thumb -D --adjust-vma=0x08020000`). Nothing here was run on a device.
No USB, serial or board access was used.

## Tags

| tag | meaning |
|---|---|
| SEEN-IN-STOCK | read directly from the V2.33 disassembly or image bytes; address given |
| INFERRED-FROM-V1.49-SOURCE | only supported by the public V1.49 source (`reference/h7-tool-app-v1.49-public/User/teeny_usb`) |
| UNKNOWN | not determined |
| (name) | a function name in parentheses is **my label** from its shape (ST HAL / CMSIS-Driver); the address and the register writes are the evidence, the name is inference |

## 0. Read this first: the public V1.49 USB source does NOT describe V2.33

V1.49 used TeenyUSB (`teeny_usb_stm32_otg_device.c`, `OTG_HS_ENABLE_DMA` off, FIFO sizes from `teeny_usb_init.h`). V2.33 does not:

* The HID/vendor device enumerated today is the **Keil MDK USB Device middleware** (RTX threads named `USBD_HID0_Thread`,
  `USBD_HID1_Thread`, `USBD_CustomClass0_EP1_Thread` are in the image at 0x081342df-0x08134300) on top of a CMSIS-Driver
  `ARM_DRIVER_USBD` wrapper, which sits on a **ST HAL PCD / LL_USB** layer. SEEN-IN-STOCK (strings, vtable shape, HAL code shape).
* FIFO sizes, interrupt masks and endpoint numbers differ from V1.49. Do not reuse V1.49 numbers.
* A second, independent set of ST `USBD_LL_*` code (mode 2-4: USB disk / VCP) shares the same HAL_PCD code. It is selected by
  the byte at **0x2401CB60** (0 at reset = Keil HID path = the path documented here; 1 = ST library path). Only the Keil path is
  taken on D428-9 at boot (section 8).

Everything below is the byte-0 (Keil) path unless stated.

## 1. Call flow, top to bottom (SEEN-IN-STOCK unless noted)

| step | address | what |
|---|---|---|
| 1 | 0x08084004 -> 0x08046680 | `HAL_Init`-like: `NVIC_SetPriorityGrouping(3)` (0x08046682 `movs r0,#3`, 0x08046684 `bl 0x8047980`) |
| 2 | 0x08083ff4-0x0808418e | board clock init: VOS, PLL1, **PLL3 + USBSEL**, ClockConfig, CSI, SYSCFG, I/O compensation cell (section 3) |
| 3 | 0x0802ab4a, 0x0802ab50 | app start: `bl 0x80e6d2c(0)` = (`USBD_Initialize(0)`), `bl 0x80e5124(0)` = (`USBD_Connect(0)`). Skipped only for board ids 0x5a01/0x5a03/0x5a05 (section 8) |
| 4 | ARM_DRIVER_USBD vtable 0x080F3050..0x080F3094 | (CMSIS driver) Initialize = 0x08086368, PowerControl = 0x08086390, DeviceConnect = 0x08085F90, DeviceDisconnect = 0x08085FB8, SetAddress = 0x08086018, EndpointConfigure = 0x08086040, ... - INFERRED order; the addresses are SEEN |
| 5 | PowerControl(FULL) 0x080863dc-0x080864a4 | fills the PCD handle at 0x240280B4, calls `HAL_PCD_Init`, FIFO setup, NVIC enable (section 4/5) |
| 6 | `HAL_PCD_Init` 0x080488a0 | MspInit (GPIO, RCC, NVIC), CoreInit, SetCurrentMode, DevInit, DevDisconnect |
| 7 | DeviceConnect 0x08085F90 -> `HAL_PCD_Start` 0x08048DE0 | `GAHBCFG.GINT=1`, soft-connect |
| 8 | vector 77 = 0x080652B8 -> `HAL_PCD_IRQHandler` 0x08048018 | reset / enum-done / endpoint events |

PCD handle (statically allocated, RAM): **0x240280B4** (Keil path), second handle 0x24027CAC (ST-library path). Both have
`Instance = 0x40040000` (USB1_OTG_HS).

## 2. GPIO and RCC enables (HAL_PCD_MspInit, 0x08048AB8-0x08048C0A) - SEEN-IN-STOCK

RCC base 0x58024400.

| order | address | write |
|---|---|---|
| 1 | 0x08048ad2-0x08048b3a | `RCC_AHB4ENR` (0x580244E0) `|= 0x187`: GPIOA(bit0), GPIOB(1), GPIOC(2), GPIOH(7), GPIOI(8), one `orr` each with a read-back |
| 2 | 0x08048b54 | `HAL_GPIO_Init(GPIOA 0x58020000, pin 0x0020)` = PA5 ULPI_CK |
| 3 | 0x08048b6a | `HAL_GPIO_Init(GPIOA, pin 0x0008)` = PA3 ULPI_D0 |
| 4 | 0x08048b82 | `HAL_GPIO_Init(GPIOB 0x58020400, pin 0x3C23)` = PB0 D1, PB1 D2, PB5 D7, PB10 D3, PB11 D4, PB12 D5, PB13 D6 |
| 5 | 0x08048b98 | `HAL_GPIO_Init(GPIOC 0x58020800, pin 0x0001)` = PC0 ULPI_STP |
| 6 | 0x08048bae | `HAL_GPIO_Init(GPIOH 0x58021C00, pin 0x0010)` = PH4 ULPI_NXT |
| 7 | 0x08048bc6 | `HAL_GPIO_Init(GPIOI 0x58022000, pin 0x0800)` = PI11 ULPI_DIR |
| 8 | 0x08048bd0 | `RCC_AHB1ENR` (0x580244D8) `|= 1<<26` = USB1OTGHSULPIEN |
| 9 | 0x08048be8 | `RCC_AHB1ENR` `|= 1<<25` = USB1OTGHSEN |
| 10 | 0x08048bfe-0x08048c06 | `NVIC_SetPriority(77, 1, 0)` (0x08047920) then `NVIC_EnableIRQ(77)` (0x080478f8) |

Every `HAL_GPIO_Init` call uses the same init struct (stack at sp+4..sp+20 before the call, 0x08048b3e-0x08048b50):
**Mode = 2 (alternate function push-pull), Pull = 0 (none), Speed = 3 (very high), Alternate = 10 (AF10 = OTG_HS ULPI)**.
`HAL_GPIO_Init` itself is 0x08045F30 (OSPEEDR/PUPDR/OTYPER/MODER/AFR in the standard HAL order).

Pin list = exactly the 12 pins in `docs/01-mcu-resources.md` section 4.1; V1.49 `board_config.h` agrees. No pin is driven as plain GPIO.

**PHY reset / PHY power GPIO: none in this path.** `HAL_PCD_MspInit` touches only the 12 ULPI pins. The USB3300 RESET is tied to GND on
the schematic (doc 01), consistent. I did not prove a negative for the whole 1.29 MB image, only for the USB init path; no other
code that sets the 12 pins' port clocks together was found.

`HAL_PCD_MspDeInit` (0x08048A60, used by Uninitialize / `HAL_PCD_DeInit` 0x08047CD0): clears the same two AHB1ENR bits, `HAL_GPIO_DeInit`
(0x08045DE8) on GPIOB 0x3C23, GPIOI 0x0800, GPIOH 0x0010, GPIOC 0x0001, GPIOA 0x0028, and disables IRQ 77.

## 3. Clock tree actually programmed for USB - SEEN-IN-STOCK

Board clock function, 0x08083ff4-0x08084214 (D428-9 takes the `board id != 0x5a08` branch at 0x0808405e/0x0808407c).

| item | address | value |
|---|---|---|
| PLL1 / OscConfig struct | 0x080840e8-0x08084112, call 0x08084116 (`bl 0x804b1f8`) | HSE on (0x10000), PLL on, source HSE, **M=5, N=160, P=2, Q=4, R=2**, PLL1 VCI range 8 (RGE2), VCO wide (0); VCO 800, SYSCLK 400, Q 200. (board 0x5a08 uses N=40, VOS3, latency 0) |
| `SYSCFG_PWRCR` (0x5800042C) | 0x08084066-0x0808406a | `&= ~1` (ODEN off). `PWR_D3CR` (0x58024818) `|= 0xC000` = VOS1 for D428-9 |
| **PeriphCLKConfig for USB** | struct at sp+20 (0x08084120-0x08084140), call 0x08084144 (`bl 0x8049ee8`) | `PeriphClockSelection = 0x00040000` (USB), **PLL3: M=5, N=48, P=2, Q=5, R=2, VCI range 0x800 (RGE2), VCO wide, FRACN 0**, **`UsbClockSelection = 0x00200000`** |
| what that writes | 0x0804a79a-0x0804a7a2 | `RCC_D2CCIP2R` (0x58024454) `[21:20] = 2` = USBSEL = **pll3_q**; PLL3 Q output enabled by the RCCEx PLL3 config (0x0806a808). PLL3 VCO = 25/5*48 = 240 MHz, Q = 48 MHz |
| ClockConfig | struct 0x0808414a-0x08084158 / 0x0808417c-0x0808418e, call 0x0808418e (`bl 0x804ab40`) | all six clock types, SYSCLK source PLL1 (3), AHB DIV2 (8), APB1/2/3/4 DIV2, **flash latency 4** |
| after clocks | 0x08084198-0x080841b6 | `RCC_CR |= 0x80` (CSION), `RCC_APB4ENR (0x580244F4) |= 2` (SYSCFG), `bl 0x80441b0` = `SYSCFG_CCCSR (0x58000420) |= 1` (I/O compensation cell) |
| D2 SRAM clocks | 0x080841ba-0x080841e8 | `RCC_AHB2ENR (0x580244DC) |= bits 29,30,31` |

Order in the board function: OscConfig (PLL1) -> **PeriphCLKConfig(USB, PLL3Q)** -> ClockConfig. HCLK = 200 MHz (read back by
`HAL_RCC_GetHCLKFreq` at 0x0804af60 and passed to the turnaround-time routine, section 4.7).

With an external ULPI PHY the OTG_HS core is clocked from the PHY (PA5, 60 MHz). Stock still programs USBSEL=PLL3Q; whether the HS
core strictly needs it is UNKNOWN (doc 01 already said so). `PWR_CR3.USB33DEN` (0x5802480C bit 24) is set by exactly one site,
0x08048E68, called from the ST-library mode-2 start (0x080E3A8E), **not** on the Keil path. SEEN.

## 4. USB_OTG_HS register writes, in order (base 0x40040000) - SEEN-IN-STOCK

Offsets are the usual OTG_HS offsets. Register names are mine; the offsets and values are read from the code.

### 4.1 `HAL_PCD_Init` 0x080488a0 (ULPI, device, no DMA)

The handle fields set by PowerControl(FULL) at 0x080863f6-0x08086428 (all SEEN): Instance 0x40040000, dev_endpoints 8, speed 0 (high),
dma_enable 0, **ep0_mps 64, phy_itface 1 (ULPI)**, Sof_enable 0, low_power 0, lpm 0, vbus_sensing 0, use_dedicated_ep1 0,
use_external_vbus 0 (the last two are zero-initialised, not stored explicitly).

| # | address | register write |
|---|---|---|
| 1 | 0x080488c8-0x080488d0 | read `CID` (0x3C); if bit 8 is clear, force `dma_enable = 0` (already 0) |
| 2 | 0x080488d8 -> 0x08088ef0 | `GAHBCFG (0x08) &= ~1` (global interrupt off) |
| 3 | 0x08088994-0x0808899e (0x08088980 CoreInit, ULPI branch) | `GCCFG (0x38) &= ~0x00010000` (PWRDWN = 0) |
| 4 | 0x080889a0-0x080889ac | `GUSBCFG (0x0C) &= 0xFFBDFFBF` = clear TSDPS (b22), ULPIFSLS (b17), **PHYSEL (b6)** |
| 5 | 0x080889b2-0x080889b8 | `GUSBCFG &= ~0x00300000` (ULPIEVBUSD b20, ULPIEVBUSI b21 = 0). Bit 20 is set only if use_external_vbus==1: not our case |
| 6 | 0x080889c4-0x080889fe | core reset: wait `GRSTCTL (0x10)` bit 31 (AHBIDL) set, `GRSTCTL |= 1` (CSRST), wait bit 0 clear; 0x30D41 loop limit each |
| 7 | (dma_enable==0) | no GAHBCFG HBSTLEN/DMAEN write at all |
| 8 | 0x0808891a -> 0x080894a8 (SetCurrentMode(device)) | `GUSBCFG &= ~0x60000000`, `GUSBCFG |= 0x40000000` (FDMOD), then `HAL_Delay(50)` (0x08043250) |
| 9 | 0x080489e2 -> 0x08088b60 (DevInit) | see 4.2 |
| 10 | (after DevInit) | if `lpm`: 0x080479a0 (not taken); then `0x08088b40` DevDisconnect (4.2 last row); state = READY |

### 4.2 `USB_DevInit` 0x08088b60 (ordered)

| # | address | write |
|---|---|---|
| 1 | 0x08088b78-0x08088bb0 | `DIEPTXF1..15 (0x104..0x13C) = 0` |
| 2 | 0x08088bc0-0x08088be2 (vbus_sensing == 0) | `DCTL (0x804) |= 2` (SDIS); `GCCFG &= ~0x00200000` (VBDEN = 0); `GOTGCTL (0x00) |= 0x40` (BVALOEN) then `|= 0x80` (BVALOVAL) |
| 3 | 0x08088be4 | `PCGCCTL (0xE00) = 0` |
| 4 | 0x08088bec-0x08088c1a | `DCFG (0x800)` read-modify-write: PFIVL = 0 (80 %); ULPI + speed 0 -> DSPD = 0 (**high speed**); (speed != 0 would set 1). Final DCFG DSPD = 00 |
| 5 | 0x08088c1e-0x08088c3e | `GRSTCTL = 0x420` (TXFFLSH, TXFNUM = 0x10 = all), wait clear |
| 6 | 0x08088c42-0x08088c5c | `GRSTCTL = 0x10` (RXFFLSH), wait clear |
| 7 | 0x08088c6c-0x08088c7a | `DIEPMSK (0x810) = 0`, `DOEPMSK (0x814) = 0`, `DAINTMSK (0x81C) = 0` |
| 8 | 0x08088c8a-0x08088e92 | for each IN ep i < 8: `DIEPCTL(i) = EPENA ? (i==0 ? SNAK : EPDIS\|SNAK) : 0`; `DIEPTSIZ = 0`; `DIEPINT = 0xFB7F` |
| 9 | 0x08088d92-0x08088e92 | same for OUT eps with `DOEPCTL/DOEPTSIZ/DOEPINT` (DOEPINT = 0xFB7F) |
| 10 | 0x08088e92-0x08088e9a | `DIEPMSK &= ~0x100` (TXFURM) |
| 11 | 0x08088e9e-0x08088ea6 | `GINTMSK (0x18) = 0`; `GINTSTS (0x14) = 0xBFFFFFFF` |
| 12 | 0x08088ea8-0x08088eb0 (dma==0) | `GINTMSK |= 0x10` (RXFLVLM) |
| 13 | 0x08088eb2-0x08088ec4 | `GINTMSK |= 0x803C3800` = WUIM(31), IPXFRM_IISOOXFRM(21), IISOIXFRM(20), OEPINT(19), IEPINT(18), ENUMDNEM(13), USBRSTM(12), USBSUSPM(11). Final **GINTMSK = 0x803C3810** |
| 14 | 0x08088ec6-0x08088ece | SOFM (0x08) only if Sof_enable (not set) |
| 15 | 0x08088ed0-0x08088ee0 | VBUS interrupts (`SRQIM`, `OTGINT`) only if vbus_sensing==1 (not set) |
| 16 | `HAL_PCD_Init` tail 0x08048a52 -> 0x08088b40 | `PCGCCTL &= ~3`; `DCTL |= 2` (SDIS, soft-disconnect) |

### 4.3 FIFO sizes (HAL_PCDEx_SetRxFiFo 0x080479d0, SetTxFiFo 0x080479d8, called at 0x08086430-0x08086490)

Called as `SetRxFiFo(363)` then `SetTxFiFo(fifo, size)` for fifo 0..8 with sizes 16, 256, 128, 256, 1, 1, 1, 1, 1 (words). The routine
computes each start address as GRXFSIZ + sum of the previous TX sizes (code at 0x080479ea-0x08047a9c), so the resulting registers
(computed from the stock arguments, 1024 words = the whole 4 KB FIFO RAM used) are:

| register | value | meaning |
|---|---|---|
| GRXFSIZ (0x24) | 0x0000016B | RX 363 words at 0 |
| DIEPTXF0 (0x28) | 0x0010016B | EP0 IN: start 363, 16 words (64 B) |
| DIEPTXF1 (0x104) | 0x0100017B | EP1 IN (bulk): start 379, 256 words (1024 B) |
| DIEPTXF2 (0x108) | 0x0080027B | EP2 IN (HID, 512 B reports): start 635, 128 words |
| DIEPTXF3 (0x10C) | 0x010002FB | EP3 IN (HID, 1024 B reports): start 763, 256 words |
| DIEPTXF4..8 (0x110..0x120) | 0x000103FB, ...FC, ...FD, ...FE, ...FF | 1 word each (unused eps), starts 1019..1023 |

ST-library path (modes 2-4, not used here): `SetRxFiFo(512)`, `TxFiFo(0)=128`, `TxFiFo(1)=372`, at 0x08087778-0x08087798.

### 4.4 Soft connect (`HAL_PCD_Start` 0x08048DE0)

| address | write |
|---|---|
| (battery-charging term skipped: phy is ULPI) | - |
| 0x08048e0e -> 0x080892f8 | `GAHBCFG |= 1` (GINT). GAHBCFG ends as **0x00000001** (no DMA, HBSTLEN 0) |
| 0x08048e14 -> 0x08088b20 | `PCGCCTL &= ~3`; `DCTL &= ~2` (clear SDIS) = "device connected" |

NVIC for the core is enabled before this (section 5). `DeviceConnect` is reached from `USBD_Connect(0)` at 0x0802ab50 (vtable slot 0x080F3064,
function 0x08085F90) - the call chain is INFERRED, the register writes are SEEN.

### 4.5 Bus reset (`HAL_PCD_IRQHandler`, reset branch 0x0804852e-0x0804875a)

`DCTL &= ~1` (RWUSIG); `GRSTCTL = 0x420` flush all TX (0x08089338, num 0x10); for each ep < 8: `DIEPINT = DOEPINT = 0xFB7F`, `DIEPCTL`/`DOEPCTL`
`&= ~STALL`, `|= SNAK`; `DAINTMSK |= 0x10001`; with use_dedicated_ep1 == 0: `DOEPMSK |= 0x202B`, `DIEPMSK |= 0x0B`; `DCFG &= ~0x7F0`
(device address 0); `USB_EP0_OutStart` (0x08088ff8): `DOEPTSIZ0 = (1<<19) | 0x18 | 0x60000000` (1 packet, 3 setup packets), then
`GINTSTS = 0x1000` (clear USBRST). SEEN.

### 4.6 Enumeration done (branch 0x0804875a-0x08048790)

`ActivateSetup` (0x08088960): `DIEPCTL0 &= ~0x7FF` (EP0 MPS = 64), `DCTL |= 0x100` (CGINAK); read `DSTS (0x808)` -> speed (0 = HS, 2 = FS
via the routine at 0x08089370); `USB_SetTurnaroundTime` (0x08089500) with `hclk = 200 MHz` and that speed; then the EP0 open callback
(0x08048c10) and `GINTSTS = 0x2000` (clear ENUMDNE). SEEN.

### 4.7 Turnaround time

Code at 0x08089500: for speed 2 (FS) a table of HCLK ranges; for any other speed (HS) the branch at 0x08089504 goes straight to
0x080895c6: **`GUSBCFG.TRDT [13:10] = 9`** (`0x2400`: `GUSBCFG &= ~0x3C00; \|= 0x2400`). SEEN. (This is the standard value for ULPI HS.)

### 4.8 Endpoint 0 and the application endpoints

Endpoint activation is `USB_ActivateEndpoint` 0x080888c0, reached from `HAL_PCD_EP_Open` 0x08047e90 (args: handle, ep address, max
packet, type), which the CMSIS driver's EndpointConfigure (0x08086040, rejects mps > 0x530) calls:

* IN ep: `DAINTMSK (0x81C) |= 1<<n`; if `DIEPCTL(n)` bit 15 (USBAEP) clear: `DIEPCTL(n) |= (mps & 0x7FF) | (type << 18) | (n << 22) /*TXFNUM*/ | 0x10000000 /*SD0PID*/ | 0x8000 /*USBAEP*/`.
* OUT ep: `DAINTMSK |= 1<<(16+n)`; `DOEPCTL(n) |= (mps & 0x7FF) | (type << 18) | 0x10000000 | 0x8000`.
* EP0 open on reset/enum: IN 0x80 and OUT 0x00, mps 64, type 0 (control) - 0x08048c9c (`bl 0x8047e90`, IN) and 0x08048cae (tail `b.w 0x8047e90`, OUT). SEEN.
* Transfers: `USB_EPStartXfer` 0x08088f00, no DMA: `DIEPTSIZ/DOEPTSIZ = pktcnt<<19 | xfer_len`, `CNAK \| EPENA`, TX data pushed in the
  TXFE interrupt (`DIEPEMPMSK (0x834)`), RX data read in RXFLVL (`USB_ReadPacket` 0x080893f8, `USB_WritePacket` 0x080896f0).

Endpoint numbers, types and max packet sizes (values come from the SEEN configuration descriptor, section 7; that EndpointConfigure
is called with exactly these is INFERRED from the Keil middleware, not separately traced):

| iface | class | endpoint | type | MPS (HS) | bInterval | TXFIFO |
|---|---|---|---|---|---|---|
| 0 | vendor (WinUSB), `USBD_CustomClass0_EP1` | EP1 OUT 0x01 / EP1 IN 0x81 | bulk | 512 | 0 | FIFO1, 256 w |
| 1 | HID 1 (CMSIS-DAP HID) | EP2 OUT 0x02 / EP2 IN 0x82 | interrupt | 512 | 3 | FIFO2, 128 w |
| 2 | HID 2 "Communication" = **register channel** | **EP3 OUT 0x03 / EP3 IN 0x83** | interrupt | **1024** | 1 | FIFO3, 256 w |

## 5. NVIC - SEEN-IN-STOCK

* `OTG_HS` IRQ number **77** (vector table entry 93, address 0x08020174 holds 0x080652B9).
* Priority grouping 3 (`NVIC_SetPriorityGrouping(3)` at 0x08046684). `NVIC_SetPriority(77, preempt 1, sub 0)` at 0x08048bfe-0x08048c04
  -> `NVIC_IPR[77] = 0x10`.
* Enabled twice: `NVIC_EnableIRQ(77)` in MspInit (0x08048c06) and again by `PowerControl` at 0x08086494-0x080864a2 (`ISER2 (0xE000E108) = 0x2000`). Disabled by `ICER2 (0xE000E188) = 0x2000` at 0x080863a0-0x080863ac and in MspDeInit.
* Vector entries 74, 75, 76 and 78 (OTG_HS EP1 OUT/IN, WKUP, ...) are the default handler 0x0802038B: **no other OTG_HS vector is used**.
* ISR 0x080652B8: reads the byte at 0x2401CB60; ==1 -> `HAL_PCD_IRQHandler(0x24027CAC)`, else `HAL_PCD_IRQHandler(0x240280B4)` (0x08048018).

## 6. Strings

String descriptors are **RAM** tables at 0x24005418 (initialised by the scatter-load, see 7.4); the serial and a "#NN" field are patched at run time.
Decompressed initial image (`decomp.py` equivalent of the ARM routine at 0x08027fe4; the output reproduced valid UTF-16 strings, so the
decode is right), offsets from 0x24005418:

| idx | RAM offset | bytes (header + UTF-16) | text |
|---|---|---|---|
| 0 | +0x00 | `04 03 09 04` | LANGID 0x0409 |
| 1 (iManufacturer) | +0x04 | `24 03` + 17 chars | `H7-TOOL By ARMFLY` |
| 2 (iProduct) | +0x28 | `24 03` + 17 chars | `H7-TOOL CMSIS-DAP` |
| 3 (iSerial) | +0x4C | `32 03` + 24 chars | template `0001A00000000001A0000000`, overwritten by the 96-bit UID as 3 x 8 upper-case hex digits (0x0808b1a0 called from 0x0802ab44 with the words at 0x1FF1E800/4/8) -> on the unit `0040003D3330511833323938` (doc 02) |
| 4 (iInterface 0) | +0x7E | `3a 03` + 28 chars | `#08 H7-TOOL WinUSB CMSIS-DAP` |
| 5 (iInterface 1) | +0xB8 | `34 03` + 25 chars | `#08 H7-TOOL HID CMSIS-DAP` |
| 6 (iInterface 2) | +0xEC | `3c 03` + 29 chars | `#08 H7-TOOL HID Communication` |

The `08` in "#08" is rewritten at run time by 0x0808b448 (two decimal digits from a byte at 0x24023F74, clamped to 99, 0x0802ab2c-0x0802ab3a); the value on
the unit is UNKNOWN (template says 08). The index 0xEE string (OS descriptor, below) is flash-resident.

## 7. Descriptors in the image (flash, raw bytes from `stock233.bin`)

Addresses are image addresses. All SEEN-IN-STOCK.

### 7.1 Device descriptor, 0x0815A0B4 (18 bytes)

```
12 01 00 02 ef 02 01 40 51 c2 0a f0 00 01 01 02 03 01
```
bcdUSB 0x0200, class EF/02/01 (IAD), bMaxPacketSize0 64, **VID 0xC251, PID 0xF00A**, bcdDevice 0x0100, iMfr 1, iProd 2, iSerial 3, 1 configuration.
Device qualifier, 0x0815A0C8 and an identical copy at 0x0815A0D4 (10 bytes): `0a 06 00 02 00 00 00 40 01 00`.
An EP0 pseudo-descriptor at 0x0815A0E0: `07 05 00 00 40 00 00 00`.

### 7.2 Configuration descriptors

**HS configuration, type 2, 0x0815A008, 104 bytes** (bulk 512, interrupt 512/1024):
```
09 02 68 00 03 01 00 80 fa
08 0b 00 01 ff 00 00 04                                  IAD: first if 0, count 1, class FF, iFunction 4
09 04 00 00 02 ff 00 00 04                               iface 0: vendor, 2 eps, iInterface 4
  07 05 01 02 00 02 00                                   EP1 OUT bulk 512
  07 05 81 02 00 02 00                                   EP1 IN  bulk 512
09 04 01 00 02 03 00 00 05                               iface 1: HID, iInterface 5
  09 21 11 01 00 01 22 23 00                             HID 1.11, report desc 35 bytes
  07 05 82 03 00 02 03                                   EP2 IN  interrupt 512, bInterval 3
  07 05 02 03 00 02 03                                   EP2 OUT interrupt 512, bInterval 3
09 04 02 00 02 03 00 00 06                               iface 2: HID, iInterface 6
  09 21 11 01 00 01 22 23 00                             HID 1.11, report desc 35 bytes
  07 05 83 03 00 04 01                                   EP3 IN  interrupt 1024, bInterval 1
  07 05 03 03 00 04 01                                   EP3 OUT interrupt 1024, bInterval 1
```
bmAttributes 0x80 (bus powered), bMaxPower 0xFA (500 mA).

Two further copies of the same layout, both carrying descriptor type 7 (other-speed) in byte 1, `09 07 68 00 03 01 00 80 fa ...`:
* 0x0815A124 (104 bytes): HS values (bulk 512, interrupt 512/1024), as above.
* 0x0815A190 (104 bytes): **FS values**: bulk 64 (`07 05 01 02 40 00 00`, `07 05 81 02 40 00 00`), EP2 interrupt 64 / bInterval 1 (`07 05 82 03 40 00 01`, `07 05 02 03 40 00 01`), EP3 interrupt 4 / bInterval 16 (`07 05 83 03 04 00 10`, `07 05 03 03 04 00 10`).
Which one is returned for a given request, and whether byte 1 is patched at run time, is not traced (UNKNOWN); on a high-speed link the host sees the 0x0815A008 table.

### 7.3 HID report descriptors, 0x0815A36C and 0x0815A390 (35 bytes each)

```
0x0815A36C (iface 1, 512-byte reports):
06 00 ff 09 01 a1 01 15 00 26 ff 00 75 08 96 00 02 09 01 81 02 96 00 02 09 01 91 02 95 01 09 01 b1 02 c0
0x0815A390 (iface 2, 1024-byte reports):
06 00 ff 09 01 a1 01 15 00 26 ff 00 75 08 96 00 04 09 01 81 02 96 00 04 09 01 91 02 95 01 09 01 b1 02 c0
```
Vendor usage page 0xFF00, usage 1, collection application, logical 0..255, 8-bit items, **report count 0x0200 / 0x0400 for both Input and Output**,
one 8-bit Feature item. No report ID. (Pointer words at 0x0815B72C etc. in that region are not table entries; the one real reference to the
descriptor block is `movw/movt` 0x0815A074 at 0x080884e0.)

### 7.4 Other descriptor-area data

| item | address | bytes |
|---|---|---|
| Microsoft OS 1.0 string (index 0xEE) | 0x0815A110 | `12 03 4d 00 53 00 46 00 54 00 31 00 30 00 30 00 01 00` = "MSFT100", vendor code 0x01 |
| compat-ID descriptor | 0x0815A0E8 (40 B) | `28 00 00 00 00 01 04 00 01 00*7  00 01  57 49 4e 55 53 42 00 00 (WINUSB)  00*8  00*6`: interface 0 is WinUSB |
| extended-properties descriptor | 0x0815A204 (0x8E B) | `8e 00 00 00 00 01 05 00 01 00 84 00 00 00 01 00 00 00 28 00 "DeviceInterfaceGUID\0" (UTF-16) 4e 00 00 00 "{CDB3B5AD-293B-4663-AA36-1AAE46463776}\0" (UTF-16)` |
| descriptor config struct | 0x0815A074.. | words incl. 0x08134353, 0x2402DC14, 0x080F3050 (driver vtable), 0x24043E9C / 0x24043F60 / 0x24043EA0 (RAM, role UNKNOWN), 0x00030180, 0x00184006 |
| scatter-load table | 0x0815B03C | `{src 0x0815B060, dst 0x24000000, len 0x55A0, fn 0x08027FE4 (decompress)}`, `{src 0x0815B740, dst 0x240055A0, len 0x795A8, fn 0x080E9C40 (zero-init)}` - this is how the strings of section 6 reach RAM |

## 8. The D428-9 "newer hardware" branch for USB

Board id is the halfword at 0x24027950 (0x24027888 + 0xC8; `ldrh [r8,#200]`, set from the board-number read at 0x0808403c/0x0808404e).
In the app start function (0x0802aae8):

* 0x0802ab16-0x0802ab2a: `id - 0x5a01 <= 4` and mask `0x15` -> ids **0x5a01, 0x5a03, 0x5a05** skip the Keil HID bring-up (they run the ST-library modes 2/4/3 via 0x080E39A8, call sites 0x080D8C8C, 0x080CFB26, 0x080D8E46).
* **Every other id, including 0x4289, falls through to `USBD_Initialize(0)` (0x0802ab4a) and `USBD_Connect(0)` (0x0802ab50).** That is the whole branch for USB.
* Extra, only for id 0x5a08 (0x0802ab6a branch): a write of `0x02440000` to `0x40040034` (the OTG GPVNDCTL ULPI-viewport register: NEWREGREQ, REGWR, REGADDR 4) with a bounded poll; **not executed on D428-9**. Meaning of the value is UNKNOWN beyond that.
* Board-dependent clock bits (N=160, VOS, latency 4) are section 3; USB is otherwise identical.

## 9. Minimal bare-metal sequence (ordered; every register value from sections 2-4)

1. VOS1, PLL1 (HSE 25, M5 N160 P2 Q4 R2), flash latency 4, AHB/2, APBx/2 (SEEN). PLL3 M5 N48 P2 Q5 R2, `RCC_D2CCIP2R.USBSEL = 2` (SEEN; likely optional for ULPI, UNKNOWN).
2. `RCC_APB4ENR |= 2` (SYSCFG), CSI on, `SYSCFG_CCCSR |= 1`.
3. `RCC_AHB4ENR |= 0x187`; PA3, PA5, PB0/1/5/10/11/12/13, PC0, PH4, PI11: AF10, push-pull, no pull, very-high speed.
4. `RCC_AHB1ENR |= (1<<26)` then `|= (1<<25)`.
5. `GAHBCFG &= ~1`; `GCCFG &= ~(1<<16)`; `GUSBCFG &= ~((1<<22)|(1<<17)|(1<<6)|(1<<21)|(1<<20))`; core reset (AHBIDL then CSRST); `GUSBCFG` FDMOD (bit 30) set, clear bit 29, wait 50 ms.
6. `DIEPTXF1..15 = 0`; `DCTL \|= 2`; `GCCFG &= ~(1<<21)`; `GOTGCTL \|= 0xC0`; `PCGCCTL = 0`; DCFG DSPD 0; flush TX (0x420) and RX (0x10); mask registers 0; per-ep CTL/TSIZ/INT init (INT = 0xFB7F); `DIEPMSK &= ~0x100`; `GINTMSK = 0`; `GINTSTS = 0xBFFFFFFF`; `GINTMSK = 0x803C3810`.
7. `GRXFSIZ = 363`; `DIEPTXF0 = 0x0010016B`; `DIEPTXF1..8` as in 4.3.
8. `NVIC` prio of IRQ 77 = preempt 1 (IPR 0x10) with PRIGROUP 3; enable IRQ 77.
9. `GAHBCFG \|= 1`; `PCGCCTL &= ~3`; `DCTL &= ~2` - connected.
10. ISR: on `USBRST` follow 4.5; on `ENUMDNE` follow 4.6 and 4.7 (TRDT 9), open EP0 IN/OUT (mps 64); on SET_CONFIGURATION open EP1/2/3 IN+OUT as in 4.8.

## 10. What is not established

* The exact mapping of CMSIS-driver slot names to the vtable at 0x080F3050 and the Keil middleware call order (Initialize -> PowerControl -> Connect) are from function shape, not from named symbols.
* That the Keil middleware calls EndpointConfigure with exactly the descriptor values (section 4.8) was not traced; it follows from the descriptor bytes and the HAL open routine.
* Whether PLL3/USBSEL is required for the ULPI core: UNKNOWN. Whether the "#NN" digits on the unit are 08: UNKNOWN. Role of the RAM pointers at 0x24043E9C/0x24043F60/0x24043EA0: UNKNOWN.
* No negative is proven for "no other GPIO is toggled for the PHY anywhere in the image"; only the init path read here has none.
* Nothing in this file was exercised on hardware.
