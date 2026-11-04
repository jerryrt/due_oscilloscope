# 23 - The 250M scope module: how to drive it, and how it behaves

Everything here was measured on one unit (bench linux-x1, 2026-11-04) with the stock app V2.33 running and the module's CH1 wired to the H7-TOOL's own VOUT
on a 1x probe. Tags: **observed** (measured on the unit), **vendor** (the manual V4.0 chapter 13, the stock files), **inferred** (a reading of the evidence, said so),
**unknown**. The module's own firmware, its programming and recovery, and the plan for new firmware are in `docs/24-250m-module-firmware.md`. The owner decided on
2026-11-04 that going further (new module firmware, streaming mode) is not worth the investment now; these two documents are the record that lets it be picked up.

## 1. At a glance

| Question | Answer | Basis |
|---|---|---|
| What is it? | An RP2040 (250 MHz, PIO capture), an 8-bit converter and an analog front end, 1 Mohm input, 10 ranges | vendor + firmware |
| Rate and depth | 250 Msps on one channel or 125 Msps on each of two; 224 KB of capture RAM (stock offers up to 16K samples, hardware 200K) | vendor + firmware |
| Does it answer? | Only with TVCC at 3.3 V and after the enable cycle | observed |
| Converter | 8 bits, saturating at 0 and 255; gain and zero for all ten range codes in section 5 | observed |
| Trigger | Only mode 2 is live; it fires on a level crossing in **either** direction; the edge setting is ignored; 62 % of captures had an edge at the requested point | observed |
| Read-out | Reliable (repeat reads agree to 0.1 code) when the notes' rules are followed | observed |
| Streaming | Not what the stock firmware does (capture, then read); the link would allow a low-rate stream only (docs/24) | arithmetic |
| Programming | Its USB socket is the RP2040's boot mode; the firmware is backed up and a restore file exists | observed |
| Not measured | CH2, two-channel capture, rates above 5 MS/s (the 125 and 250 MS/s indices), depths above 2K, trigger on CH2, coupling, the module's own noise at the sensitive ranges | - |

## 2. What it is and how it connects

- **Hardware** (vendor): single channel 250 Msps or two channels at 125 Msps; 1 Mohm input, 1x, 10x, 100x probes; analog bandwidth 30 to 50 MHz (a vendor figure,
  not measured); programmable AC/DC coupling; a compensation trimmer; ranges +-40 mV to +-40 V; hardware trigger on CH1 or CH2; 5 V supply with an on-board negative
  rail; the manual says the RP2040's PIO replaces an MCU plus FPGA.
- **The probe input.** The module's own probe input is the signal input. The CH1 and CH2 pins on the H7-TOOL's header are the built-in 16-bit scope, not the module.
- **The link to the H7-TOOL.** The module plugs into the extended IO header. The manual names UTX D0, URX D1, SDO D2, SDI D3, SCK D5 and says those five pins are
  not to be used otherwise. The module's firmware shows an **SPI slave** on its side (MOSI GPIO16, SCK GPIO18, MISO GPIO19, chip select GPIO29, docs/24), which fits
  D2, D3, D5 and D4 as the chip select; D0 and D1 (the serial port) are not used by the firmware's start-up. Which of the H7's pins carries each of these is in
  docs/02 section A4 (the H7 side is SPI4: SDO PE6, SDI PE5, SCK PE2, NSS PE4, from the schematic, *not confirmed on the board*).
- **TVCC must be 3.3 V.** It sets the SPI logic level. The unit had been left at 1.4 V after a front-panel test, and then every read of address 0x10 returned the
  not-ready exception `10 83 03` and the module looked dead. The supply is register 0x0085 on address 1, in millivolts, 30.7 mV per step, readable back; the
  measured voltage is float 6 of the live block (`h7tool_usb_control/10-tvcc-power.md`). **First thing to check when the module is silent.**
- **The USB socket on the module** is the RP2040's boot mode (docs/24); the application image has no USB at all.
- **Wiring used for the tests:** VOUT to the module's CH1, a 1x probe, shared ground. One lead on one input only (owner ruling, 2026-11-03).

## 3. Driving it: the stock protocol

This is the protocol the PC app speaks to the stock firmware over USB (`c251:f00a`, HID interface 2). **It is not the link between the H7 and the module**: our own H7
firmware would need the SPI framing, which is unknown (docs/24 section 4). `tools/h7_250m.py` is a client for this protocol with an injectable transport,
tested against a simulated module (`tests/test_h7_250m.py`).

**Framing.** Modbus RTU in one 1024-byte HID report per request (on Linux, `write()` 1024 bytes to hidraw, no report id; find the node by USB interface 2, its number
changes between plug-ins). Frame `[addr][function][payload][CRC16 low][CRC16 high]`, CRC-16/MODBUS (0xA001, init 0xFFFF), big-endian fields. Address 1 is the H7-TOOL,
0x10 the module. Functions: 3 read registers, 6 write one, 0x10 write many. The byte count is one byte (a read of 0x200 registers reports 0x00). A reply of 512 registers is
1029 bytes and spans two reports: header and 1021 bytes in the first, the last three bytes, the CRC and padding in the second. Exceptions are `[addr][fc|0x80][code]`.
Replies are sometimes misframed (a report that starts with raw sample bytes or `ff ff ..`): check address, function and byte count, drain stale reports before each request,
retry. The client does all of this.

**Enable.** Write 2 to register 0x0212 on address 1, wait 1.0 s, write 1, wait 1.5 s. Until then, and whenever TVCC is not 3.3 V, address 0x10 answers every read with
exception 3 and refuses writes (`10 90 03`). Read 0x0212 back to see 1. The cycle also recovers a module that has dropped out (it then resets to its defaults). **Never scan
registers at 0x10: wide reads knocked the module out.**

**Defaults after enable** (read back, matches the earlier notes): settings block `[0,1,1,4,4,0,0,12,0,0,0,0,0,0,1,0,1]`, capture-done flag 1.

**The settings block** (17 registers written with function 0x10 to address 0x10, register 0x0100; the last register starts a capture):

| Reg | Field | Notes |
|---|---|---|
| 0x0100 | mode | only 0 used |
| 0x0101, 0x0102 | CH1, CH2 coupling | 0 AC, 1 DC from the internal scope's convention; **flipping it changed nothing in a 390 Hz sine capture**, so unverified on this module |
| 0x0103, 0x0104 | CH1, CH2 range code | 0 widest (+-40 V) to 9 most sensitive (+-40 mV); table in section 5 |
| 0x0105, 0x0106 | offsets | the app writes 0 |
| 0x0107 | sample-rate index | 0 100 Hz, 1 200, 2 500, 3 1k, 4 2k, 5 5k, 6 10k, 7 20k, 8 50k, 9 100k, 10 200k, 11 500k, 12 1M, 13 2M, 14 5M, 15 10M, 16 20M, 17 50M, 18 100M, 19 125M, 20 250M (CH1 only). **Checked against a known signal: 10, 12 and 14 only** |
| 0x0108 | depth index | 0..4 is 1, 2, 4, 8, 16 blocks of 1024 samples |
| 0x0109, 0x010A | trigger level | float32, volts, high register first |
| 0x010B | trigger position, percent | the edge is placed there (section 6) |
| 0x010C | trigger mode | 0 and 1 free-run, **2 is the live trigger** |
| 0x010D | trigger channel | 0 used; 1 untested |
| 0x010E | trigger edge | **ignored** by the module |
| 0x010F | channel mask | bit 0 CH1, bit 1 CH2; only 1 tested |
| 0x0110 | start (1) / stop (0) | stopping mid-capture leaves a partial buffer: do not |

**Capture and read-out.** Write the block. Poll register 0x021C at 0x10 until it reads 1 (30 ms for 1K, up to 190 ms for 16K at 200 kS/s; a single trigger that never fires never
completes, so keep a timeout). Write 0x021C = 1 to acknowledge. Optionally read the status block (0xC100, 16 registers, eight float32). Read the samples as blocks: function 3, register
`0x2000 + k` for CH1 (`0x4000 + k` for CH2), count 0x200, k = 0 .. blocks-1; the block number is the low bits of the register, **not** a 0x200 stride. Each reply is 1024 bytes of
8-bit unsigned samples in time order. Drop the first 100 samples of block 0 (start-up junk). Reading every block twice and keeping it when both agree is cheap and was clean 30 of 30.

**The status block** read `[114.90, 0, 212.72, 1.699, 125.55, 0, 223.36, 1.699]` on this module, identical in two sessions with different signals: fixed values of the module (offsets
and levels), meaning unknown.

**The H7-TOOL's own generator**, used as the test source, is one 10-word block at address 1, register 0x0100: `[1, wave, min mV, max mV, hz high, hz low, duty, 0, 0, 1]`, levels as signed
16-bit. Wave 0 off, 1 DC, 2 a square at the requested frequency (a 1000 Hz square had its edges exactly 1000.0 samples apart at 1 MS/s), 3 a triangle at the requested frequency, 4 and 5
triangle-like at about twice and three times it (not explained). Always end a test with wave 0.

## 4. Rules that cost measurements

- **The first capture after any change is wrong**: after a range change (the front end settles) and after a level change. Settle, capture once, throw it away, then measure. A range-6 reading
  of 75 at 0 V against 117 once settled was exactly this.
- **Discard the first 100 samples** of block 0.
- **The single trigger waits for ever** on a level the signal never reaches; time out, then run the enable cycle.
- **TVCC first**, then enable. **Do not scan.**
- VOUT has about 6 mV rms of wideband noise: at the sensitive ranges it, not the module, sets the spread of a DC capture.
- Never wire VOUT to both CH1 and CH2 of the built-in scope (owner ruling); for the module, one input.

## 5. The converter (observed)

Three DC levels per range (at minus x, 0 and plus x with x about 40 % of the range), two captures averaged, first capture discarded, 5 MS/s, depth 1K. Repeat captures agree to 0.1 code at the
low-gain ranges. Gain is codes per volt at the 1x probe:

| range code | codes per volt | mV per code | span (0..255) | vendor range | code at 0 V | spread of a DC capture (codes) |
|---|---|---|---|---|---|---|
| 0 | 2.83 | 353 | about +-45 V | +-40 V | 118.0 | 0.1 to 0.4 |
| 1 | 5.74 | 174 | +-22 V | +-20 V | 118.0 | 0.1 to 0.3 |
| 2 | 14.35 | 69.7 | +-8.9 V | +-8 V | 117.4 | 0.1 to 0.5 |
| 3 | 28.70 | 34.8 | +-4.4 V | +-4 V | 116.4 | 0.5 to 0.7 |
| 4 | 56.93 | 17.6 | +-2.2 V | +-2 V | 114.4 | 0.5 to 0.7 |
| 5 | 133.4 | 7.5 | +-0.96 V | +-800 mV | 117.4 | 0.9 to 1.2 |
| 6 | 264.6 | 3.78 | +-0.48 V | +-400 mV | 116.5 | 1.5 |
| 7 | 677 | 1.48 | +-0.19 V | +-200 mV | 113.4 | 3.8 to 5.7 |
| 8 | 1394 | 0.72 | +-0.09 V | +-80 mV | 109.5 | 7 to 12 |
| 9 | 2539 | 0.39 | +-0.05 V | +-40 mV | 100.1 | 16 |

- Code n of the range register is the vendor's range list in order. The real half-span is 10 to 25 % wider than nominal at every range except code 7, which is 6 % narrower (and noisy). The earlier
  notes' "37 mV per code at range 6" was ten times too large (that capture went through a 10x probe).
- The code at 0 V is not mid-scale and moves with the range; as volts it is -41 mV at range 6 and about -230 mV at range 4, **but the source's own offset (about 34 mV, not separated from a Due
  input's) is in it**, so this is the offset of the pair, not of the module alone.
- From range 6 up the spread grows in proportion to the gain, which is VOUT's noise times the gain. **The module's own noise there is not measured.** At ranges 0 and 1 the spread is 0.1 to 0.4 code,
  quantisation plus the module, an upper bound on its noise.
- **No independent meter was in the loop.** Absolute accuracy is limited by VOUT (an earlier measurement of VOUT against a Due input: 1.8 mV rms residual, with an offset that could not be separated).
  The step from each range to the next is 2.0, 2.5, 2.0, 2.0, 2.3, 2.0, 2.6, 2.1, 1.8; the vendor's list steps 2, 2.5, 2, 2, 2.5, 2, 2, 2.5, 2. They agree within 10 % except at codes 7 and 8 (2.6 against 2.0,
  then 2.1 against 2.5), where VOUT's noise is largest and the gain is the least certain.
- **Timebase:** a 1000 Hz square had edges 1000.0 samples apart at index 12 (1 MS/s). Index 10 (200 kS/s) and 14 (5 MS/s) agree with earlier checks; the faster indices are untested.

## 6. The hardware trigger (observed)

Test: a 1 kHz, 0.4 V peak-to-peak triangle from VOUT (slope 0.8 mV per microsecond), range 6, 1 MS/s, 2048 samples, levels -0.1, 0, +0.1 V, both requested edges, trigger position 10, 50 and 90 %,
20 captures each (360 in all); where the edge landed was found by a straight-line fit through it.

- **Modes.** 0 (auto) and 1 (normal) free-run: every capture completes in 0.03 s even with a level of +10 V the signal never reaches, and the buffer is not aligned to anything. **Mode 2 (single)
  is the live trigger**: +10 V never completes; levels the signal crosses complete with the edge near the requested position.
- **The level** is a float32 in volts in registers 0x0109 and 0x010A (the high register first); a level read as a code in either register fired near 0 V, which is what the float of a small integer is.
- **The edge is ignored.** Requested rising: the edge at the trigger point was rising in 20 of 40 captures and falling in 17 (3 neither). Requested falling: 19 and 21. The module fires on a crossing in either direction.
  The vendor's own screen offers a trigger value and no edge, which agrees.
- **Position.** 222 of 360 captures (62 %) had an edge of either kind within 60 samples of the requested point; nine of the 18 settings were below 60 %. Where it was, the edge landed between 14 samples early and 7 late
  for rising (mostly 2 to 7 late) and 6 to 20 late for falling, spread 4 to 12 samples (microseconds) from capture to capture. The spread is about what VOUT's noise on that slope gives; the lateness of falling
  edges is a hysteresis or a latency that was not separated.
- **Meaning.** A usable trigger needs the edge honoured and a stable position; neither holds on this firmware. The trigger machinery is in the module's PIO (docs/24), so fixing it is a module-firmware job.
- **Not tested:** trigger on CH2, positions other than 10, 50 and 90 %, rates other than 1 MS/s, depths above 2K, other signals.

## 7. Test coverage

**Without hardware (in the board-free gate):**

| Test file | What it holds |
|---|---|
| `tests/test_h7_250m.py` | the client against a simulated module: the stock example frame byte for byte, the settings block layout, a float split in two registers, a negative generator level, the enable sequence and its two sleeps, exceptions from a module that is not ready, auto-enable inside a capture, the junk head, block order and the CH2 register base, retry on a misframed reply, a stale reply with the wrong byte count, a block with a bad CRC, verify mode, a capture that never completes; twelve mutants of the client each fail one of these |
| `tests/test_h7_250m_quality.py` | the analysis of `measure/h7_250m_quality.py` on synthetic triangles with noise: the gain fit, the edge position to under a sample, the either-direction classification, the junk-head exclusion; eight mutants |
| `tests/test_rp2040_picoboot.py` | the read-only boot-mode reader cannot send anything but reads (a guard test fails when removed) |
| `tests/test_rp2040_uf2.py` | the UF2 converter, against the vendor's own UF2 file |
| `tests/test_rp2040_trace.py` | the firmware start-up trace's naming, PIO decoder and summary; the emulation itself when `unicorn` and the backups are present (a skip says so and is not a pass) |

**On the bench (not automated; to be written when the module matters again).** Wiring as in section 2; stock app running; TVCC 3.3 V. Acceptance, taken from this document's measurements:
the module answers after the enable cycle; the defaults read back; range 6 reads 264.6 codes per volt within 5 %; the zero code at each range within 3 codes of the table; a +10 V single trigger times out; the trigger statistics
of section 6 are reproduced (and, for new firmware, replaced by the targets in docs/24: edge honoured in 98 % or more of captures, edge within 3 samples of the requested position at 1 MS/s). `measure/h7_250m_quality.py ranges` and
`trigger` produce exactly these figures.

**What these tests cannot say:** whether a real module behaves like the simulator beyond what was seen (one unit, one day), and nothing about CH2, the fast rates or coupling.

## 8. Tools

| Tool | Use |
|---|---|
| `tools/h7_250m.py` | the stock-protocol client (framing, enable, TVCC, generator, settings, capture, read-out) |
| `measure/h7_250m_quality.py` | `ranges` and `trigger`: the procedures behind sections 5 and 6, with the analysis functions |
| `tools/rp2040_picoboot.py` | read-only back-up of the module's flash over its USB boot mode (docs/24) |
| `tools/rp2040_uf2.py` | binary to UF2 and back; used to make the restore file |
| `tools/rp2040_trace.py` | what the module firmware sets up at start-up, by emulation (docs/24) |
| `tools/h7_swd_probe.py` | read-only SWD check of the H7-TOOL's programmer port (docs/24) |
