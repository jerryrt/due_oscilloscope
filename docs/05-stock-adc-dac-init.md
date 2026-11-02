# 05 - Stock V2.33: how the 2-channel scope ADC path, the TIM3 sample clock, the 74HCT595 front-end control and the DAC are brought up

Scope: the register-level sequence the stock app V2.33 (`stock233.bin`, 1,292,096 bytes, VMA 0x08020000) runs to acquire the built-in
2-channel 16-bit scope (CH1 = ADC1 ch2 on PF11, CH2 = ADC3 ch1 on PC3_C) and to drive DAC1 CH1 (PA4) with the +-12 V stage. Source of truth is
the disassembly (`arm-none-eabi-objdump -b binary -m arm -M force-thumb -D --adjust-vma=0x08020000`). Nothing here was run on a device. No USB,
serial or board access was used. Same style as `04-stock-usb-init.md`.

## Tags

| tag | meaning |
|---|---|
| SEEN-IN-STOCK | read directly from the V2.33 disassembly or image bytes; address given |
| SEEN-IN-STOCK (derived) | a register value I computed by hand from SEEN struct fields and the SEEN ST-HAL code (HAL_ADC_Init etc.); no register was read from a board |
| INFERRED-FROM-V1.49-SOURCE | only supported by the public V1.49 source (`reference/h7-tool-app-v1.49-public/User/bsp/src/bsp_cpu_adc.c`, `bsp_cpu_dac.c`, `bsp_74hc595_io.c`) |
| INFERRED-FROM-RM | follows from the STM32H750 reference manual / HAL convention, not from a stock address (marked *(check)*) |
| UNKNOWN | not determined |
| (name) | a function name in parentheses is **my label** from its shape (ST HAL / V1.49 `bsp_*`); the address and the register writes are the evidence |

## 0. Read this first: where V2.33 agrees with V1.49, and where it does not

The ADC/DAC layer is the same source as V1.49 compiled with a newer ST HAL; the HAL is inlined in places, so most evidence is "HAL struct
filled in, then a HAL function at a known address". Agreements, all SEEN: single-ended 16-bit, `ADC_CLOCK_SYNC_PCLK_DIV4`, TIM3 TRGO trigger,
circular DMA, 1.5-cycle sampling, AWD1 as the trigger comparator, 74HCT595 pin order, TIM6 + DMA1_Stream5 for the DAC, the 17-entry rate table.

Differences that matter (do not reuse the V1.49 / `01-mcu-resources.md` figure):

* **The ADC DMA buffers are NOT at 0x38000000.** `01-mcu-resources.md` section 5 and V1.49 put `aADCH1ConvertedData = 0x38000000` (SRAM4).
  V2.33 reads them from a pointer table in `.data` at **0x24004938**: ch1 raw **0x30025800**, ch2 raw **0x3002992C**, ch1 float **0x3002DA58**,
  ch2 float **0x30035A58** (decompressed `.data` image, `data_init.bin` offset 0x4938). That is D2 SRAM2, not SRAM4. SEEN.
* **Length is 8342 samples (0x2096) per channel**, not a power of two (every `HAL_ADC_Start_DMA` call passes `r2 = 0x2096`).
* **The housekeeping scan is oversampled 1024x in hardware** (CFGR2) exactly as V1.49, but the scope path has **no** oversampling.
* **The kernel clock is not what sets the ADC clock**: the ADC is in synchronous mode (CCR.CKMODE = 3), so the conversion clock is HCLK/4 whatever
  ADCSEL says (section 1).
* **The DMA stream interrupts are never enabled** (no `NVIC_EnableIRQ(12)` / `(57)` anywhere; section 5). V1.49's `HAL_ADC_MspInit` enabled them.
* **Board type matters.** The scope control path below is the **byte 0x24027888+0x169 == 0** path, which is what the D428-9 board takes
  (`id = 0x4289 -> (id == 0x4460) = 0`, set at 0x0809686e). The `== 1` path drives a different module through `0x0802ce00` and is not documented here.
  SEEN (0x08096818-0x0809692e).

## 1. Call flow, top to bottom (SEEN-IN-STOCK unless noted)

| step | address | what |
|---|---|---|
| 1 | 0x08083DF0 (call 0x080c6934) | (`MPU_Config` + `SCB_Enable{I,D}Cache`), then falls into the clock function of doc 04. Section 4.3 |
| 2 | 0x0804E588 | (`HC595_InitHard`) section 5 |
| 3 | 0x08033718 (via 0x08033850) | (`DSO_ConfigCtrlGPIO`): PG2 output, AC on both channels, gain 0 on both, PG2 low. Section 5.4 |
| 4 | 0x080340D0 | (`DSO_StartADC(freq_hz)`): stops TIM3, `0x0809b230`/`0x0809b2f0` (`bsp_StopAdcCH1/2`), `0x08033640` (`DSO_CloseTriger`), zeroes both raw buffers (8342 halfwords each), then **`0x0809a5e0` (`bsp_StartAdcCH1`), `0x0809a9a0` (`bsp_StartAdcCH2`), then `0x080848b0` (`TIM3_Config(freq)`)**. ADCs are armed before TIM3 starts |
| 5 | per ADC | `HAL_ADC_DeInit` 0x080400ea (calls MspDeInit, so every start resets the ADC12/ADC3 block) -> `HAL_ADC_Init` 0x08040308 (calls `HAL_ADC_MspInit` 0x080406b8, section 1.1) -> `ADC_ConfigureBoostMode` 0x08028738 -> `HAL_ADCEx_Calibration_Start` 0x0803f650 -> `HAL_ADC_ConfigChannel` 0x0803fa70 -> `DSO_SetTriger` 0x08033f88 (`HAL_ADC_AnalogWDGConfig` 0x0803f728) -> `HAL_ADC_Start_DMA` 0x08040b80 |
| 6 | 0x080848b0 | TIM3 configured and started: first trigger edge after this |
| 7 | 0x08033f88 / 0x080343ea | AWD IRQ (ADC_IRQn 18 / ADC3_IRQn 127) is enabled only when a trigger mode is active |
| 8 | 0x080338b8 | (`DSO_LockWave`) converts the frozen raw buffer to float volts through the calibration table, section 7 |

Mode byte: the halfword at **0x240061A8** (= g_tDSO+0x68) is the measurement mode, same values as the `0x01FF` USB register: **0 scope, 1 load current,
2 low-speed scan** (the device boots in 2). Every ADC function above branches on it.

## 2. RCC enables and the ADC clock - SEEN-IN-STOCK

RCC base 0x58024400. `HAL_ADC_MspInit` is 0x080406b8; mode 0 branches at 0x080406fa (ADC1) and 0x08040a1c (ADC3).

| item | ADC1 (CH1), mode 0, 0x080406fa-0x08040732 | ADC3 (CH2), mode 0, 0x08040a1c-0x08040a54 |
|---|---|---|
| GPIO clock | `RCC_AHB4ENR` (0x580244E0) `\|= 0x20` (GPIOF) | `AHB4ENR \|= 0x04` (GPIOC) |
| ADC clock | `RCC_AHB1ENR` (0x580244D8) `\|= 0x20` (**ADC12EN**) | `AHB4ENR \|= 0x01000000` (**ADC3EN**) |
| kernel clock mux | `RCC_D3CCIPR` (0x58024458) `[17:16] = 2` (**ADCSEL = per_ck**) | same write |
| DMA clock | `AHB1ENR \|= 0x01` (DMA1EN) | `AHB1ENR \|= 0x02` (DMA2EN) |
| pin | `HAL_GPIO_Init(GPIOF 0x58021400, Pin 0x0800 = PF11, Mode 3 analog, Pull 0)` | `HAL_GPIO_Init(GPIOC 0x58020800, Pin 0x0008 = PC3, Mode 3, Pull 0)` |

* Only the positive pin is configured. No PF12/PC2 (negative) pin is touched: **single-ended**, as in V1.49 with `ENABLE_DIFFERENTIAL_ENDED 0`.
* `MspDeInit` (0x08040560-0x0804067c) pulses `RCC_AHB1RSTR` (0x58024480) bit 5, clears `AHB1ENR` bit 5 and de-inits the GPIO, so the clock enable above is
  redone on **every** `DSO_StartADC`.
* **ADC conversion clock = HCLK / 4 = 50 MHz** (*derived*). `HAL_ADC_Init` writes `ClockPrescaler = 0x00030000` into the common `CCR`
  (`0x40022308` for ADC1/2, `0x58026308` for ADC3; mask 0x003F0000 cleared first, 0x08040424-0x08040438). `CCR[17:16] = CKMODE = 3` is the synchronous HCLK/4
  mode, `PRESC = 0`. HCLK is 200 MHz (doc 04 section 3, AHB DIV2 of 400 MHz SYSCLK), so 50 MHz. In CKMODE != 0 the ADC does not use `adc_ker_ck`, so
  ADCSEL / `CKPERSEL` do not affect conversion timing. The ADC is clocked from per_ck only nominally. *(check the 50 MHz against the
  datasheet ADC clock limit; the stock runs the ADC through the BOOST path below.)*
* **BOOST** (`ADC_ConfigureBoostMode`, 0x08028738-0x0802885c, SEEN): it recomputes the ADC clock the same way (`HAL_RCC_GetHCLKFreq` 0x0804af60, /1 /2 /4
  from CKMODE), then reads the device revision (0x08046108): **rev Y (<= 0x1003)**: `CR.BOOST (bit 8) = 1` when clock > 20 MHz; **rev V**: `CR[9:8] = 0`
  for <= 12.5 MHz, `1` <= 25 MHz, `2` <= 50 MHz, `3` above. At 50.000 MHz exactly that is **BOOST = 2 on rev V**. Called from inside `HAL_ADC_Init` (0x08040520)
  and again explicitly after it (0x0809a684).
* The ADC LDO and enable sequence is the stock HAL one: `CR` cleared of DEEPPWD (mask 0x5FFFFFC0), `ADVREGEN` set (0x10000000), a busy-wait
  of `((SystemCoreClock>>6) * 0x053E2D63 >> 38) + 1` iterations (0x08040358-0x080403a4), then `ADC_Enable` (0x08028a50) inside `Start_DMA`.

SystemCoreClock itself is the `.data` word at 0x2400499C (init value 64,000,000, i.e. HSI) that the clock function updates; **the value after init is
400,000,000 by the doc-04 clock table (INFERRED, not read)**.

## 3. Per-ADC configuration

HAL structure values are read from the stores into the handle (ADC handle 0x240063EC for ADC1, 0x24006450 for ADC3; Init struct at handle+4). Field order is
the ST H7 HAL's (`ClockPrescaler`, `Resolution`, `ScanConvMode`, `EOCSelection`, `LowPowerAutoWait`, `ContinuousConvMode`, `NbrOfConversion`,
`DiscontinuousConvMode`, `NbrOfDiscConversion`, `ExternalTrigConv`, `ExternalTrigConvEdge`, `ConversionDataManagement`, `Overrun`, `LeftBitShift`,
`OversamplingMode`, `Oversampling{Ratio,RightBitShift,TriggeredMode,OversamplingStopReset}`), confirmed by `HAL_ADC_Init` reading `[r4+0x24]`
(ExternalTrigConv, zero = software) and `[r4+0x2c]` (DMNGT).

### 3.1 Scope mode (mode 0): CH1 on ADC1 (0x0809a5e0) and CH2 on ADC3 (0x0809a9a0) - SEEN-IN-STOCK

| field | CH1 / ADC1 (0x0809a602-0x0809a6cc) | CH2 / ADC3 (0x0809a9c2-0x0809aa96) |
|---|---|---|
| instance | 0x40022000 | 0x58026000 |
| channel | `0x08600004` = ADC_CHANNEL_2 (PF11 = ADC1_INP2) | `0x04300002` = ADC_CHANNEL_1 (PC3_C = ADC3_INP1) |
| ClockPrescaler | 0x00030000 (SYNC /4) | same |
| Resolution | 0 = **16 bit** | 0 |
| ScanConvMode | 0 (disabled) | 0 |
| EOCSelection | 4 (single conversion) | 4 |
| LowPowerAutoWait / Continuous | 0 / 0 | 0 / 0 |
| NbrOfConversion / Discontinuous / NbrOfDisc | 1 / 0 / 1 | 1 / 0 / 1 |
| ExternalTrigConv | **0x480** = ADC_EXTERNALTRIG_T3_TRGO (EXTSEL = 4) | 0x480 |
| ExternalTrigConvEdge | **0x400 = rising** | 0x400 |
| ConversionDataManagement | **3 = DMA circular** (DMNGT = 11) | 3 |
| Overrun | 0x1000 = data overwritten (OVRMOD = 1) | 0x1000 |
| LeftBitShift | 0 | 0 |
| OversamplingMode | **off** (byte 0 at +0x38) | off |
| sampling time | **0 = 1.5 ADC cycles** (`ConfigChannel` struct +8) | 0 |
| rank | 6 = ADC_REGULAR_RANK_1 | 6 |
| SingleDiff | 0x7FF = ADC_SINGLE_ENDED | 0x7FF |
| OffsetNumber | 4 = ADC_OFFSET_NONE (offset 0, no right shift / signed saturation) | 4 |
| calibration | `0x0803f650(h, 0, 0x7FF)`: **ADC_CALIB_OFFSET, single-ended**, once per start | same |
| DMA length | **8342** (0x2096) halfwords, `pData = [0x24004938]` | 8342, `pData = [0x2400493C]` |

Resulting ADC registers, **SEEN-IN-STOCK (derived)** from `HAL_ADC_Init` 0x08040308, `HAL_ADC_ConfigChannel` 0x0803fa70, `HAL_ADCEx_Calibration_Start` 0x0803f650,
`HAL_ADC_Start_DMA` 0x08040b80 and `HAL_ADC_AnalogWDGConfig` 0x0803f728:

| register (offset) | value | where |
|---|---|---|
| `ADC_CR` (0x08) | DEEPPWD=0, ADVREGEN=1; BOOST = 2 (rev V) or bit 8 (rev Y); `ADCAL` pulse (0x80000000, no ADCALDIF, no ADCALLIN) then `ADEN`; `ADSTART` (`CR += 4`, i.e. bit 2) at the end of `Start_DMA`, 0x08040c70-0x08040c7c | 0x0803f696-0x0803f6b4 |
| `ADC_CFGR` (0x0C) | `DMNGT=3 \| EXTSEL=4 (0x80) \| EXTEN=01 (0x400) \| OVRMOD (0x1000) \| RES=0 \| CONT=0 \| DISCEN=0 \| AUTDLY=0` = **0x1483**, plus `AWD1EN\|AWD1SGL` (0x00C00000) and `AWD1CH` in bits 30:26 from `DSO_SetTriger` (2 for ADC1, 1 for ADC3), plus bit 31 (JQDIS, from `DeInit`) = **0x88C01483 (ADC1)**, **0x84C01483 (ADC3)** | 0x08040464-0x080404a4, 0x080404b6-0x080404ca |
| `ADC_CFGR2` (0x10) | untouched by `Init` (oversampling off) = 0 | 0x080404cc-0x08040510 |
| `ADC_SMPR1` (0x14) | channel 2 (ADC1) / 1 (ADC3) field = 0 (1.5 cycles) | 0x0803fb02-0x0803fb0e |
| `ADC_PCSEL` (0x1C) | `\|= 1 << ch` : 0x04 (ADC1), 0x02 (ADC3) | 0x0803fac0-0x0803fac4 |
| `ADC_SQR1` (0x30) | `L = 0`, `SQ1 = ch`: 0x80 (ADC1: 2<<6), 0x40 (ADC3: 1<<6) | 0x0803fad0-0x0803fada |
| `ADC_LTR1` (0x20) / `ADC_HTR1` (0x24) | idle (`DSO_CloseTriger` 0x08033640): **LTR1 = 0, HTR1 = 0xFFFF**; trigger armed: threshold = `TrigLevel` (halfword at 0x24006198, default 0x7FFF) goes into **HTR1 for edge 1, LTR1 for edge 0**, the other stays 0xFFFF / 0 | 0x0803f8b0-0x0803f918, 0x08033fd8-0x080340b6 |
| `ADC_IER` (0x04) | `OVRIE` set by `Start_DMA` (`\|= 0x10`); `AWD1IE` (0x80) set only for `ITMode` (the trigger channel) | 0x08040c52, 0x0803f930-0x0803f93c |
| `ADC_ISR` (0x00) | `= 0x1C` written before start (clear EOC/EOS/OVR) | 0x08040c48 |

The AWD is configured on **both** ADCs on every start (SEEN-IN-STOCK, 0x08033f88): `WatchdogNumber = 0x7DC00000` (AWD1), `WatchdogMode = 0x00800000`
(single regular channel), `Channel` as in the table, `ITMode = (TrigChan == this ADC)`, `HighThreshold = 0xFFFF`/`LowThreshold = 0` unless
`TrigMode` (halfword 0x2400619E) is 1 or 2. Then `NVIC_SetPriority(18, 2, 2)`, **`NVIC_DisableIRQ(18)`**, `NVIC_SetPriority(127, 0, 2)`,
**`NVIC_DisableIRQ(127)`** (0x08034094-0x080340b0; the two helper addresses are `0x080478c8` = ICER write = *disable*, `0x080478f8` = ISER write = *enable*).
The AWD interrupt is enabled later, by 0x080343ea/0x080343f2 (`EnableIRQ(127)` or `EnableIRQ(18)` by trigger channel), only after `TIM3_Config` returns.
Edge/level naming ("edge 1 = rising") is INFERRED-FROM-V1.49-SOURCE and the USB doc `07` table (`0x020C`: 0 falling, 1 rising).

### 3.2 Load-current mode (mode 1, board type 0) - SEEN-IN-STOCK, short

Same structure, ADC1 channel `0x0C900008` (ADC_CHANNEL_3, PA6, `GPIOA` pin 0x40) and ADC3 channel `0x1D500080` (ADC_CHANNEL_7, PF8, `GPIOF` pin 0x100).
Handles 0x24006710 / 0x24006878, `ExternalTrigConv`, DMA length and calibration as in 3.1. Selected by the same `DSO_StartADC`.

### 3.3 Low-speed scan / housekeeping (mode 2, the boot mode) - SEEN-IN-STOCK

Both ADCs, **software-started** (`ExternalTrigConv = 0`), `ContinuousConvMode = 1`, `ScanConvMode = 1`, `DMNGT = 3`, `OVRMOD`, 16 bit,
**sampling time 5 = 64.5 cycles**, hardware oversampling `Ratio = 1024` (HAL value; `OVSR = 1023`), `RightBitShift = 10` (value 0x140 = OVSS<<5), `TriggeredMode = 0`
(single trigger), `OversamplingStopReset = 1` (continued mode, ROVSE=1), so `ADC_CFGR2 = 0x03FF0141` (*derived*).
Calibration is done **twice**: `0x0803f650(h, 0, 0x7FF)` (offset) and `0x0803f650(h, 0x10001, 0x7FF)` (offset + linearity, `ADCALLIN`), both single-ended.

| ADC | init at | ranks (channel, pin) | `NbrOfConversion` | DMA length |
|---|---|---|---|---|
| ADC1 | 0x0809a818 | 1: ch2 PF11 (CH1 V); 2: ch3 PA6 (high-side current) | 2 | **32** (2 x 16) |
| ADC3 | 0x0809abf8 | 1: ch1 PC3 (CH2 V); 2: ch4 PF5 (TVCC current); 3: ch5 PF3 (NTC); 4: ch7 PF8 (load V); 5: ch13 PH2 (TVCC V); 6: ch14 PH3 (12 V); 7: ch16 PH5 (USB 5 V); 8: ch9 PF4 (expansion); 9: ch6 PF10 | 9 | **144** (9 x 16) |

Channel words in stock order: `0x04300002, 0x10C00010, 0x14F00020, 0x1D500080, 0x36902000, 0x3AC04000, 0x43210000, 0x25B00200, 0x19200040` for ADC3
(0x0809ace8-0x0809ae9a), rank words 6, 12, 18, 24, 0x100, 0x106, 0x10C, 0x112, 0x118. `MspInit` mode-2 GPIO sets (0x08040838 branch): ADC3 (0x0804094c-0x08040a1a) GPIOC pin 0x08,
GPIOF pins 0x538 (PF3/4/5/8/10), GPIOH pins 0x2C (PH2/3/5); ADC1 (0x08040854-0x08040932) GPIOA pin 0x40 (PA6) and GPIOF pin 0x800 (PF11). All analog, single-ended.
This mode shares the ADC12/ADC3 blocks with the scope, so scope start `DeInit`s it first.

## 4. TIM3 (the sample clock), DMA, buffers, MPU

### 4.1 TIM3 - SEEN-IN-STOCK, `TIM3_Config(freq)` 0x080848b0

* `RCC_APB1LENR` (0x580244E8) `|= 0x02` (TIM3EN), then the HAL time base on TIM3 (base 0x40000400, handle 0x24006BE8).
* **`PSC`**: 0 when `freq > 2000`, **31** when `freq <= 2000` (`cmp r0,#2000; bf98` at 0x080848d6-0x0808490a).
* **`ARR = (SystemCoreClock/2 / (PSC+1)) / freq - 1`** (integer; the `/32` case is a `>>6`): at 400 MHz core that is **`200,000,000 / freq - 1`**
  for freq > 2 kHz and `6,250,000 / freq - 1` for freq <= 2 kHz. TIM3 is 16 bit: 100 Hz gives 62,499; 5 kHz gives 39,999. `freq = 0` stops the timer
  (`CR1.CEN` and `DIER.UDE` cleared, 0x08084968).
* Counter mode up, clock division 0, repetition 0. **`TRGO = update`**: `MasterOutputTrigger = 0x20`, `MasterSlaveMode = 0`
  (`HAL_TIMEx_MasterConfigSynchronization` 0x0804d468), then `HAL_TIM_Base_Start` 0x0804d630.
* Both ADCs use `EXTSEL = 4` (`tim3_trgo`), `EXTEN = rising`: **CH1 and CH2 are triggered by the same TIM3 update event**, so the two channels are sampled
  simultaneously, not interleaved. The ADC3 `EXTSEL = 4 = tim3_trgo` mapping is INFERRED-FROM-RM *(check)*.

### 4.2 Rates the stock offers - SEEN-IN-STOCK

Table at **0x080F3964**, 17 words: **100, 200, 500, 1k, 2k, 5k, 10k, 20k, 50k, 100k, 200k, 500k, 1M, 2M, 5M, 10M, 20M** (same as V1.49 `TabelFreq`).
The USB settings halfword `0x0206` indexes it. (Words after it - 327681, 3932175, 0, ... - are other data.) Resulting `ARR`: 1 MS/s = 199, 2 MS/s = 99,
5 MS/s = 39, 10 MS/s = 19, 20 MS/s = 9.

Depth table at **0x080F38EC**: 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288 (V1.49 `TabelBufSize`, then 50, 50).

### 4.3 DMA streams, DMAMUX requests, buffers

`HAL_DMA_Init` 0x08042700 is called from `HAL_ADC_MspInit`; handle fields set (SEEN, mode 0): `Direction 0` (periph to mem), `PeriphInc 0`, `MemInc 0x400`,
`PeriphDataAlignment 0x800` (halfword), `MemDataAlignment 0x2000` (halfword), **`Mode 0x100 = DMA_CIRCULAR`**, **`Priority 0x10000 = MEDIUM`**.
`FIFOMode`, thresholds and bursts are never written (zero-initialised handle = **direct mode, no FIFO**). `HAL_ADC_Start_DMA` installs the HAL half/complete/error
callbacks (0x08028959, 0x080289D1, 0x080289B9) and calls `HAL_DMA_Start_IT` (0x08042ea0); the DMA's own interrupt enables are set but **the NVIC is not**.

| channel | DMA stream | handle | DMAMUX1 request (value in the handle) | DMAMUX channel | peripheral address | memory |
|---|---|---|---|---|---|---|
| CH1 / ADC1 | **DMA1_Stream1** (0x40020028) | 0x24006698 | **9** = ADC1 | 1 | `ADC1_DR` 0x40022040 | raw **0x30025800**, 8342 hw |
| CH2 / ADC3 | **DMA2_Stream1** (0x40020428) | 0x24006800 | **115 (0x73)** = ADC3 | 9 | `ADC3_DR` 0x58026040 | raw **0x3002992C**, 8342 hw |

* DMAMUX channel = stream index (+8 for DMA2) is INFERRED-FROM-RM *(check)*; the request numbers are SEEN (stores at 0x0804077e..., 0x08040a9e...).
* Resulting `DMA_SxCR` = 0x00012D00 (*derived*: PL medium, MSIZE/PSIZE 16 bit, MINC, CIRC; `Start_IT` ORs the four interrupt-enable bits and `EN`). `NDTR = 8342`.
* The unfiltered raw data is therefore a free-running circular ring of 8342 samples per channel; capture ends by stopping TIM3 (`DSO_PauseADC`, in the
  AWD ISR path) and reading the write position from `DMA1_Stream1.NDTR` (0x4002002C, read at 0x08033982) to find the oldest sample. (Reading the
  position from NDTR is SEEN; the ISR path itself was not traced.)
* Float output buffers (for the USB readout, doc `07`): **0x3002DA58** and **0x30035A58**, 32,768 bytes apart (8192 floats of room).
* Other mode-1/mode-2 DMA handles: mode 1 ADC1 0x24006710 / ADC3 0x24006878; mode 2 ADC1 0x24006788 / ADC3 0x240068F0 (all `Priority MEDIUM`, circular, halfword;
  mode-2 ADC3 uses request 115 as well).

### 4.4 MPU and caches - SEEN-IN-STOCK, 0x08083DF0-0x08083FF4

`HAL_MPU_Disable` 0x08047868, then six `HAL_MPU_ConfigRegion` 0x08047808 calls (fields decoded from the packed RASR build at 0x0804782e-0x08047854: byte 8
size, 9 SRD, 10 TEX, 11 AP, 12 XN, 13 S, 14 C, 15 B), then `HAL_MPU_Enable(PRIVDEFENA)` 0x08047888 (`MPU_CTRL = 5`, `SHCSR.MEMFAULTENA`):

| region | base | size field (bytes) | TEX / C / B / S | AP | XN | what |
|---|---|---|---|---|---|---|
| 0 | 0x30040000 | 7 (256 B) | 0 / 0 / 1 / 0 (device, bufferable) | 3 | 0 | start of SRAM3 |
| 1 | 0x30044000 | 13 (16 KB) | 1 / 0 / 0 / **1** (non-cacheable, shareable) | 3 | 0 | part of SRAM3 (purpose UNKNOWN; likely Ethernet descriptors) |
| 2 | 0x24000000 | 18 (512 KB) | 1 / 0 / 0 / 0 (**non-cacheable**) | 3 | 0 | all AXI SRAM |
| **3** | **0x30000000** | **17 (256 KB)** | **1 / 0 / 0 / 0 (non-cacheable)** | 3 | 0 | **SRAM1 + SRAM2: holds the ADC raw and float buffers** |
| 4 | 0x60000000 | 4 (32 B) | 1 / 0 / 0 / 0 | 3 | 0 | FMC bank 1 (32-byte window) |
| 5 | 0x38000000 | 15 (64 KB) | 1 / 0 / 0 / 0 | 3 | 0 | SRAM4 |

Then (0x08083ef2-0x08083ff2) **I-cache and D-cache are both enabled** (`SCB_CCR |= 0x20000` then `|= 0x10000`, with the invalidate loops). Because the
ADC buffers (region 3) and all of AXI SRAM (region 2) are **non-cacheable**, no cache maintenance is needed for the scope or DAC buffers. Flash code
and everything else is cached. D2 SRAM clocks (`RCC_AHB2ENR` bits 29-31) are enabled in the clock function (doc 04 section 3).

## 5. Scope front-end control: the 74HCT595

### 5.1 Pins and init - SEEN-IN-STOCK, `HC595_InitHard` 0x0804E588

`RCC_AHB4ENR |= 0x100` (GPIOI), `|= 0x40` (GPIOG). `HAL_GPIO_Init` x3, **Mode 1 (push-pull), Pull 0, Speed 2 (high)**:
**PI4 = RCLK (latch)**, **PI9 = SCLK**, **PG5 = SDI** (GPIOI = 0x58022000, GPIOG = 0x58021800). Then the shadow byte at **0x24033880** is cleared and 8 zero bits are
shifted out and latched (so after init: PG5 low, PI9 high, PI4 low, all 595 outputs 0 = AC coupling, gain code 0, both channels). Same pins as V1.49 and the
schematic (`01-mcu-resources.md` section 11.2).

### 5.2 Shift sequence - SEEN-IN-STOCK, `HC595_LockData` 0x0804E668, `HC595_WriteGPIO` 0x0804E750

* `HC595_WriteGPIO(pin, value)` (0x0804e750): sets or clears bit `pin` (0-7) of the shadow byte at 0x24033880; **does not latch**.
* `HC595_LockData()` (0x0804e668): reads the shadow byte (signed), then for each of the 8 bits, **MSB (bit 7) first**:
  1. `GPIOG->BSRR` = `0x20` (PG5 high) if the bit is 1, `0x200000` (PG5 low) if 0;
  2. `GPIOI->BSRR = 0x02000000` (PI9 low);
  3. `GPIOI->BSRR = 0x00000200` (PI9 high). **The 595 shifts on this rising edge; data is stable before it.**
  After the 8th bit: `GPIOI->BSRR = 0x10` (PI4 high) then `GPIOI->BSRR = 0x00100000` (PI4 low): **RCLK pulse, rising latches**.
  Registers used: `GPIOG->BSRR` 0x58021818, `GPIOI->BSRR` 0x58022018. SCLK ends high, SDI keeps the last bit.
* **No delay between the stores** (V1.49's `HC595_Delay` loop is compiled away: the 8 groups are back-to-back stores). Pulse widths are therefore a few AHB4 clock
  cycles (*not measured*). Treat adding a few-cycle delay as safe; the stock does not need one on the unit it was tested on.

### 5.3 Bit meanings - SEEN-IN-STOCK, `DSO_SetGain` 0x08033d38, `DSO_SetDC` 0x08033c88 (board type 0)

| 595 output | meaning |
|---|---|
| Q0, Q1, Q2 | CH1 gain code bits A, B, C (code = A + 2B + 4C), **Q0 = LSB** |
| **Q3** | **CH1 coupling: 1 = DC, 0 = AC** |
| Q4, Q5, Q6 | CH2 gain code bits A, B, C (Q4 = LSB) |
| **Q7** | **CH2 coupling: 1 = DC, 0 = AC** |

Decoded from the two `tbb` jump tables at 0x08033d68 (CH1) and 0x08033dae (CH2): gain code *g* writes pins {2,1,0} = bits of *g* for CH1 and pins {6,5,4}
for CH2; `DSO_SetDC(ch, mode)`: `ch == 1` -> pin 3, else pin 7, value `1` iff `mode == 1`, then lock. `DSO_SetGain` writes the three
bits and latches once at the end (tail call to 0x0804e668); the V1.49 source and the stock agree for all 16 (channel, code) cases I traced.

### 5.4 Other control pins - SEEN-IN-STOCK

* `DSO_ConfigCtrlGPIO` 0x08033718 (board type 0): `RCC_AHB4ENR |= 0x40` (GPIOG), `HAL_GPIO_Init(GPIOG, Pin 4 = PG2, push-pull)`; then `SetDC(1,0)`, `SetDC(2,0)`
  (both AC), `SetGain(1,0)`, `SetGain(2,0)`, and `GPIOG->BSRR = 0x40000` (PG2 low). `DSO_SetCurrGain` 0x08033c30 (type 0): argument 0 -> `BSRR = 4` (PG2 high),
  non-zero -> `BSRR = 0x40000` (PG2 low). PG2 is the high-side current range switch (schematic). INFERRED-FROM-V1.49-SOURCE for which level is "200 mA" (V1.49: 0 -> `GC_1()`).
* `DSO_SetOffset` 0x08033f80 is `bx lr`: **the stock has no offset control**, as V1.49.
* Defaults at start (0x080d2310-0x080d2386): both couplings **DC** (`SetDC(ch,1)`), gain **0** both channels, rate index **12 (1 MS/s)**, mode 2.

### 5.5 Gain code to input range

The stock firmware has **no range table**; it only keeps the code and picks the calibration entry by it. The ranges below come from the factory calibration
table dumped from this unit (`device_dump/calibration_C000-C0FF_addr1.json`): `V = (code - x1) * (y2 - y1) / (x2 - x1)`, full-scale = distance from `x1` to the 0 / 65535 end.
Gain code 0 is the widest range. Values are this unit's (**unit-specific**, not universal):

| code | CH1 x1 | CH1 ref (V @ code) | CH1 codes/V | +-range (approx.) |
|---|---|---|---|---|
| 0 | 32657.0 | 9.0093 @ 53242 | 2284.9 | **+-14.3 V** |
| 1 | 32676.0 | 6.0081 @ 60222 | 4584.8 | +-7.1 V |
| 2 | 32712.4 | 3.0054 @ 60358 | 9198.6 | +-3.56 V |
| 3 | 32785.4 | 1.5032 @ 60494 | 18433 | +-1.78 V |
| 4 | 32931.2 | 0.7531 @ 60783 | 36982 | +-0.89 V |
| 5 | 33227.6 | 0.3773 @ 61156 | 74017 | +-0.44 V |
| 6 | 33815.6 | 0.1720 @ 59301 | 148187 | +-0.22 V |
| 7 | 34990.6 | 0.0921 @ 62319 | 296687 | +-0.11 V |

CH2 is within ~1% of CH1 per code (x1 32108-32723). The inputs are analog-front-end-limited (the board carries the 4051 gain mux), so +-range is a
property of the module, not of the ADC (the ADC reference is 2.5 V, doc 01 section 2).

## 6. Raw code to volts (calibration) - SEEN-IN-STOCK

* The calibration lives in a RAM struct at **0x24020E68** with the V1.49 `CALIB_T` layout for the scope part: `+0` version word, **`CH1[8]` at +0x04**, **`CH2[8]` at +0x84**,
  each entry `{float x1, y1, x2, y2}` (16 bytes) = 8 USB registers. USB `0xC000 + 8*i` = `CH1[i]`, `0xC040 + 8*i` = `CH2[i]` (consistent with the dump; the
  RAM-address-to-register mapping is INFERRED from the matching layout).
* Conversion functions: **`0x08095708`** (CH1 volts; index = halfword at `0x24006140+0x4C`, the CH1 gain code) and **`0x08095740`** (CH2 volts; index at `+0x4E`). Both do
  `CaculTwoPointFloat(x1, y1, x2, y2, x = (float)raw)` with the entry above; the interpolator is **0x0802D990**: `y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)`, and
  `x2 == x1` returns 0. `DSO_LockWave` (0x080338b8) calls them per sample (function pointers loaded at 0x080338f0-0x08033900) for mode 0 and fills the float
  buffers (CH1 -> 0x3002DA58, CH2 -> 0x30035A58). The raw value is the **unsigned 16-bit code from the ADC buffer** (0 to 65535, zero volts about 32.7k).
  Mode 1 (current) uses different functions (0x08095778 / 0x08095818) with another table; not analysed.
* The trigger level is stored as a **raw code** (`0x24006198`, default 0x7FFF) and is converted from volts (`TrigVolt` halfword at +0x5A, in millivolts: x 0.001, double
  at 0x08034658) by 0x08034500 through the same entry (gain index of the trigger channel).
* **Where the dumped 0xC0xx entries apply**: `0xC000-0xC03F` CH1 gain 0-7, `0xC040-0xC07F` CH2 gain 0-7 (scope and low-speed scan). Further groups follow the V1.49 order
  `LoadVolt, LoadCurr[2], TVCCVolt, TVCCCurr, NtcRes, TVCCSet` at `0xC080...` with `0xC098` = high-side current and `0xC0B0` = TVCC current (USB doc `08`); the RAM-side
  offsets of those groups differ from V1.49 by 0x20 bytes (the DAC table sits at +0x1B4 here) and **are not mapped in this document: UNKNOWN**. `0xC0C8-0xC0CF` is the VOUT
  table (section 7.4) and `0xC0D0-0xC0D7` the IOUT table.
* Where the table is **persisted** (EEPROM as in V1.49, or elsewhere) and who writes the RAM copy at boot: UNKNOWN. Keep the EEPROM read-only (doc 01 section 3.2).

## 7. DAC1 channel 1 and the +-12 V supply

### 7.1 Sequence - SEEN-IN-STOCK, `bsp_StartDAC1_DMA(buf, count, rate)` 0x0809aef8

1. **`GPIOE->BSRR = 8`: PE3 high - first thing, with no delay before the next step.** PE3 = `65130_SW`, the TPS65130 supply enable (doc 01 section 11.3).
2. TIM6 (base 0x40001000, handle 0x24028654): **`PSC`/`ARR` from the requested DAC update rate** *f* (hertz):
   * f < 400 (checked as `f>>4 <= 24`): `PSC = 99`, `ARR = SystemCoreClock/200/f - 1`;
   * f < 4000 (`f>>5 <= 124`): `PSC = 9`, `ARR = SystemCoreClock/20/f - 1`;
   * otherwise `PSC = 0`, **`ARR = SystemCoreClock/2/f - 1`** (0x0809af22-0x0809af8a).
   Up counter, `TRGO = update` (`MasterOutputTrigger 0x20`), `HAL_TIM_Base_Init` 0x0804d590, `HAL_TIMEx_MasterConfigSynchronization` 0x0804d468,
   `HAL_TIM_Base_Start` 0x0804d630. TIM6 clock: `RCC_APB1LENR |= 0x10` in `HAL_TIM_Base_MspInit` 0x0804d610.
3. DMA1 clock (`AHB1ENR |= 1`), DAC1 `MspInit` at 0x08041178: `AHB4ENR |= 1` (GPIOA), **`RCC_APB1LENR |= 0x20000000` (DAC12EN)**, `HAL_GPIO_Init(GPIOA, PA4 = pin 0x10, analog)`.
4. `HAL_DMA_Init` on **DMA1_Stream5** (0x40020088), handle 0x240089F0: **request 0x43 = 67 (DAC1_CH1)**, `Direction 0x40` (memory to periph), `PeriphInc 0`, `MemInc 0x400`,
   halfword/halfword, **`Mode 0x100` circular**, **`Priority 0x20000` high**; no FIFO. `DMA_SxCR` = 0x00022D40 (*derived*).
   The DMA IRQ (`IRQ 16`) is enabled at priority (4,0) only when a repeat-count callback is set (0x0809b044-0x0809b054); otherwise disabled.
5. `HAL_DAC_ConfigChannel(&hdac (0x24005B0C), &cfg, channel 1)`: **`Trigger = 0x16` (TSEL1 = 5, tim6_trgo, TEN1)**, **`OutputBuffer = 2` (buffer disabled)**, no sample-and-hold,
   no trimming. Struct layout is the older H7 HAL (+4 Trigger, +8 OutputBuffer), confirmed by 0x08040ed4-0x08040ef8 reading +16 as UserTrimming.
6. `HAL_DAC_Start_DMA(&hdac, channel 1, buf, count, alignment 0 = 12-bit right-aligned)` 0x08041230. DAC output register `DHR12R1` = 0x40007408.

Idle DAC (`bsp_InitDAC1`, 0x08096c58): `AHB4ENR |= 0x10` (GPIOE), **`HAL_GPIO_Init(GPIOE 0x58021000, PE3, push-pull, speed 2)`** - this is the only PE3 configuration found, and its level
is not set here (reset-state low) - then `HAL_DAC_DeInit` 0x08041078, `HAL_DAC_Init` 0x080410a8, `HAL_DAC_ConfigChannel` with **Trigger none, OutputBuffer enabled (0)**, `HAL_DAC_Start`
0x080411d0.

### 7.2 Buffer format - SEEN-IN-STOCK

Halfwords, 12-bit right-aligned (`DHR12R1` format), circular. The built-in sine (0x0809e2xx-0x0809e462, builder tail-calls 0x0809aef8) writes into **0x2401CB62** (AXI SRAM, non-cacheable by MPU
region 2): **128 samples (256 bytes) when f < 50,000 Hz, 64 samples when f >= 50,000 Hz**, DAC update rate = `f << 7` or `f << 6`. Sample *i* = `trunc(sin(2*pi*i/N) * A) + M` (`vcvt.s32.f64`, toward zero) with
`A = (code_hi - code_lo)/2`, `M = (code_hi + code_lo)/2` where the codes come from the amplitude/offset mapping of 7.4 (constants 2*pi/128 = 0.0490873... for N = 64 and
2*pi/256 = 0.0245437... for N = 128 at 0x0809e4b0/0x0809e4b8). The other waveform builders (just before 0x0809e340, e.g. the 128-point ramp loop at 0x0809e2f4) feed the same 0x0809aef8 call with 128 samples; they were not analysed in detail.

### 7.3 DC and parking - SEEN-IN-STOCK

* DC level: `DHR12R1 (0x40007408) = usat12(code_for(mV))`, then **`GPIOE->BSRR = 8`** (PE3 high) at 0x08033088-0x0803309a / 0x08040fe6-0x08040ffa.
* After a finite waveform (DMA1_Stream5 TC handler 0x08032fc8, repeat counter at 0x24005AE0/0x24005ADC): stop TIM6 (0x0804d788), `bsp_InitDAC1` again (0x08096c58), then write the
  code for **0 mV** to `DHR12R1` and set PE3 high again: the output is parked at 0 V **with the supply left on**. The exact site that drives PE3 low (the stock's `DAC_POWER_OFF`)
  was not found: UNKNOWN.

### 7.4 Amplitude / offset mapping stage - SEEN-IN-STOCK (structure), values from the dump

Four-point piecewise-linear table of signed 16-bit pairs in the same RAM struct at **0x24020E68 + 0x1B4** (`code` at +0x1B4, +0x1B8, +0x1BC, +0x1C0; `mV` at +0x1B6, +0x1BA, +0x1BE, +0x1C2).
`code_for(mV)` picks the segment by comparing the target millivolts against the second point (+0x1BA) and third point (+0x1BE), interpolates with the integer two-point function
**0x0802D960**, and saturates to 12 bits (`usat #12`). It is the inverse of `Dac10V` in V1.49 (`dac1_VoltToDac`). The unit's values (USB `0xC0C8-0xC0CF`):

| point | DAC code | output mV |
|---|---|---|
| 1 | 500 | -9190 |
| 2 | 1500 | -3212 |
| 3 | 2500 | +2771 |
| 4 | 3500 | +8755 |

(slope about 5.98 mV per code in all three segments; the end segments extrapolate, so by that rule +-10 V falls near codes 365 and 3708, INFERRED, not read.) IOUT (`Dac20mA`, `0xC0D0`): 500 -> 2609, 1500 -> 7798, 2500 -> 12992, 3500 -> 18185 uA.
There is no separate gain/offset stage in the MCU: amplitude and offset arrive as `min mV` / `max mV` (USB `0x0100` block words 2-3, doc `09`) and are mapped to two codes
by the table above; the analog stage turns the code into +-10 V / 0-20 mA.

## 8. Limits the stock enforces, and the maximum rate

* **Rate index**: the acquisition-start paths (0x08092066 and 0x0809232a, `DSO_StartADC` callers) refuse an index above **15**, i.e. the stock will start at most **10 MS/s**; index 16
  (20 MS/s) is in the table but is not accepted by those two paths. No other check on the rate was found. SEEN.
* **User-facing maximum**: the manual (chapter 12) and the USB doc `07` call the built-in scope 16-bit, **2 Msps**. That limit is not in the DSO code I read: it is a UI/range choice
  (INFERRED).
* **Hardware ceiling implied by the config** (INFERRED-FROM-RM *(check)*): 16-bit conversion = 1.5 + 8.5 = 10 ADC cycles at 50 MHz = 200 ns = **5 Msps** per ADC, so TIM3 triggers
  faster than that will be missed. Not measured.
* **Depth**: the write handler for the depth register (struct halfword at 0x24006188+14, compare at 0x0809201a) rejects an index above **3**, so 1K/2K/4K/**8K** samples; the DMA ring is 8342.
* **Mode**: the housekeeping scan (mode 2) and the scope cannot run together: `DSO_StartADC` tears down the scan first.
* Trigger: the comparator is AWD1 on the regular channel (single-channel mode), and it only exists for the trigger channel (`ITMode`); trigger position pre-delay is computed from depth and rate
  with a constant 150,000,000 (0x080342b0) - not analysed further.

## 9. What is not established

* The value of `SystemCoreClock` after the clock function (400 MHz is from doc 04), hence the exact `ARR` values, and the silicon revision (rev Y / rev V `BOOST` branch).
* The 50 MHz ADC clock vs. the datasheet limit; the 5 Msps ceiling; the ADC3 `EXTSEL` mapping; the DMAMUX channel numbers (all INFERRED-FROM-RM).
* The path from AWD interrupt to "capture done" (ISR bodies at vectors 18 and 127 were not read), and the pre-trigger delay logic around 0x08034270-0x080342c8.
* The register-to-struct mapping of the `0x01FF` block beyond what is quoted (rate index, depth, coupling and range were matched to the handlers; trigger fields have a one-slot ambiguity in
  the defaults at 0x080d2366).
* Where the calibration table is persisted; RAM offsets of the non-scope calibration groups; the DAC `DAC_POWER_OFF` site.
* The `board-type 1` scope module protocol (`0x0802ce00`).
* Whether `RCC_D1CCIPR.CKPERSEL` is ever written (irrelevant while the ADC runs in synchronous mode).
