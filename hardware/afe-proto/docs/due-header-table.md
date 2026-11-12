# Due V03 header table for the AFE shield

Read by parsing `hardware/reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb` (KiCad
10.0.6 conversion of the EAGLE V03 board; reference designators are that file's).
*(check)* marks inference. V03 is selected on the six-pin IC2, separate L4 and
AMS1117 evidence only (`../../reference/arduino-due/hardware-observations.json`); it is
not continuity-verified, and MC-4 in `docs/afe.md` still requires that before ordering.

**Coordinates.** File coordinates, mm, y DOWN: the board occupies x 0..101.6,
y 0..-53.34. The origin is the outline's lower-left corner; "Y_up" below is `-y`.
Analog and power headers are on the y = -2.54 edge, PWM and communication headers on
y = -50.8. A shield with its origin on the Due's origin reuses these numbers.

## 1. Outline and mounting holes

Source: `Edge.Cuts` lines/arcs (0.254 mm); np_thru_hole pads in `UNK_HOLE_0..5`.

- Size 101.6 x 53.34 mm. Left edge x = 0 (y -1..-52.34), top edge y = -53.34 (x 1..97.536),
  bottom edge y = 0 (x 1..98.06); r = 1 mm corners at the three left and bottom-left/top-left
  points and the bottom-right (99.06,-1)->(98.06,0). Right side: x = 99.06 from y -51.816 to
  -40.386; chamfers (97.536,-53.34)->(99.06,-51.816), (99.06,-40.386)->(101.6,-37.846),
  (101.6,-5.08)->(99.06,-2.54); x = 101.6 from y -37.846 to -5.08; x = 99.06 from -2.54 to -1.
- Six mounting holes, all non-plated, 3.2 mm drill and 3.2 mm pad:

  (x, y): (96.52, -2.54), (15.24, -50.8), (90.17, -50.8), (13.97, -2.54),
  (66.04, -35.56), (66.04, -7.62), as UNK_HOLE_0..5 in that order.

  Confirmed against the STEP in `models/alignment.json` (radius 1.6 mm). Holes 4 and 5
  lie inside the area a full-size shield covers.

## 2. Header footprints

All 2.54 mm pitch except JTAG0. Through-hole headers on the Due are drawn as
male pin rows in the CAD (3D models `ADCH0` etc.); the real Due fits female
sockets *(check)*. Pads: 1.778 x 1.4224 oval, 0.85 mm drill (1x8/1x10); XIO0 pads
1.6764 round, 0.95 drill. Net names are the V03 EAGLE net names; the Arduino
labels in the right column are by standard Due header order *(check)* except where
the net name itself carries the label.

| ref | footprint | pin 1 (x, y) | row direction | pins |
|---|---|---|---|---|
| ADCL0 | 1X08 | (50.8, -2.54) | +x | 8 |
| ADCH0 | 1X08 | (73.66, -2.54) | +x | 8 |
| POWER0 | 1X08 | (27.94, -2.54) | +x | 8 |
| PWML0 | 1X08 | (63.5, -50.8) | -x | 8 |
| PWMH0 | 1X10 | (41.656, -50.8) | -x | 10 |
| COMMUNICATION0 | 1X08 | (68.58, -50.8) | +x | 8 |
| XIO0 | 2X18 | (93.98, -50.8) | pin n odd at x 93.98, even at x 96.52; rows step +y 2.54 | 36 |
| SPI0 | 2X03 | (63.627, -30.48) | cols x 63.627 / 66.167, rows y -30.48, -27.94, -25.4 | 6 |
| ICSP1 | 2X03 | (26.059, -12.192) | cols x 26.059 / 23.519, rows y -12.192, -14.732, -17.272 | 6 |
| JTAG0 | PINHEAD_2X05_127 (1.27 pitch) | (23.8, -35.966) | cols x 23.8 / 22.53, rows y -35.966..-41.046 | 10 |
| DEBUG0 / JP5 | 1X04 / 2X02 (JP5 not mounted) | (33.274, -43.485) / (20.576, -13.767) | -x / n.a. | 4 / 4 |

Pad centres below are absolute, resolved through each footprint's rotation.

### 2.1 Analog and power (lower edge, y = -2.54)

| ADCL0 pin | x | net | Arduino | | ADCH0 pin | x | net | Arduino |
|---|---|---|---|---|---|---|---|---|
| 1 | 50.80 | AD0 | A7 | | 1 | 73.66 | AD8 | A8 *(check)* |
| 2 | 53.34 | AD1 | A6 | | 2 | 76.20 | AD9 | A9 *(check)* |
| 3 | 55.88 | AD2 | A5 | | 3 | 78.74 | AD10 | A10 *(check)* |
| 4 | 58.42 | AD3 | A4 | | 4 | 81.28 | AD11(TXD3) | A11 *(check)* |
| 5 | 60.96 | AD4 | A3 | | 5 | 83.82 | DAC0(CANRX1) | DAC0 |
| 6 | 63.50 | AD5 | A2 | | 6 | 86.36 | DAC1 | DAC1 |
| 7 | 66.04 | AD6 | A1 | | 7 | 88.90 | CANRX0 | CANRX |
| 8 | 68.58 | AD7 | A0 | | 8 | 91.44 | CANTX0 | CANTX |

A0..A7 follow the verified map in `docs/hardware.md` (A0 = AD7). The ADCH0 net names AD8..AD11
are EAGLE labels two below the chip channels AD10..AD13 (PB17..PB20) that hardware.md gives
for A8..A11; use the Arduino labels. Each net's only other connection is one U1 pad.

| POWER0 pin | x | net | Due label |
|---|---|---|---|
| 1 | 27.94 | (no net) | NC |
| 2 | 30.48 | +3V3 | IOREF (tied to +3V3) |
| 3 | 33.02 | MASTER-RESET | RESET |
| 4 | 35.56 | +3V3 | 3.3 V |
| 5 | 38.10 | +5V | 5 V |
| 6 | 40.64 | GND | GND |
| 7 | 43.18 | GND | GND |
| 8 | 45.72 | VIN | VIN |

### 2.2 Upper edge (y = -50.8)

| PWMH0 pin | x | net | Arduino | | PWML0 pin | x | net | Arduino |
|---|---|---|---|---|---|---|---|---|
| 1 | 41.656 | PWM8 | D8 | | 1 | 63.50 | RX | D0 |
| 2 | 39.116 | PWM9 | D9 | | 2 | 60.96 | TX | D1 |
| 3 | 36.576 | SS0/PWM10 | D10 | | 3 | 58.42 | PWM2 | D2 |
| 4 | 34.036 | PWM11 | D11 | | 4 | 55.88 | PWM3 | D3 |
| 5 | 31.496 | PWM12 | D12 | | 5 | 53.34 | SS1/PWM4 | D4 |
| 6 | 28.956 | PWM13 | D13 | | 6 | 50.80 | PWM5 | D5 |
| 7 | 26.416 | GND | GND | | 7 | 48.26 | PWM6 | D6 |
| 8 | 23.876 | AREF | AREF | | 8 | 45.72 | PWM7 | D7 |
| 9 | 21.336 | SDA1 | SDA1 (D70) *(check)* | | | | | |
| 10 | 18.796 | SCL1 | SCL1 (D71) *(check)* | | | | | |

| COMMUNICATION0 pin | x | net | Arduino *(check)* |
|---|---|---|---|
| 1 | 68.58 | TXD0 | D14 TX3 |
| 2 | 71.12 | RXD0 | D15 RX3 |
| 3 | 73.66 | TXD1 | D16 TX2 |
| 4 | 76.20 | RXD1 | D17 RX2 |
| 5 | 78.74 | TXD2 | D18 TX1 |
| 6 | 81.28 | RXD2 | D19 RX1 |
| 7 | 83.82 | SDA0-3 | D20 SDA (net also on RN5.8, 1.5 k to 3V3) |
| 8 | 86.36 | SCL0-3 | D21 SCL (net also on RN5.7, 1.5 k to 3V3) |

Net names TXD0..RXD2 do not match D14..D19; the labels use standard header order
*(check)*. D20/D21 are the only edge signals with an on-board pull-up.

### 2.3 XIO0, the 2x18 right-hand header (x 93.98 odd pins, 96.52 even pins)

Each row of two: pin y, odd pin net, even pin net. D numbers = net `PINnn` = Arduino
Dnn *(check)*; every one of these nets has exactly one other connection (a U1 pad).

| y | odd (x 93.98) | even (x 96.52) | y | odd | even |
|---|---|---|---|---|---|
| -50.80 | 1 +5V | 2 +5V | -27.94 | 19 D38 | 20 D39 |
| -48.26 | 3 D22 | 4 D23 | -25.40 | 21 D40 | 22 D41 |
| -45.72 | 5 D24 | 6 D25 | -22.86 | 23 D42 | 24 D43 |
| -43.18 | 7 D26 | 8 D27 | -20.32 | 25 D44 | 26 D45 |
| -40.64 | 9 D28 | 10 D29 | -17.78 | 27 D46 | 28 D47 |
| -38.10 | 11 D30 | 12 D31 | -15.24 | 29 D48 | 30 D49 |
| -35.56 | 13 D32 | 14 D33 | -12.70 | 31 D50 | 32 D51 |
| -33.02 | 15 D34 | 16 D35 | -10.16 | 33 AD14(RXD3) = D52 | 34 CANTX1/IO = D53 |
| -30.48 | 17 D36 | 18 D37 | -7.62 | 35 GND | 36 GND |

### 2.4 SPI, ICSP, reset and JTAG: not on the edge headers

SPI0 (6-pin, mid-board): 1 MISO (63.627, -30.48), 2 +5V (66.167, -30.48), 3 SPCK
(63.627, -27.94), 4 MOSI (66.167, -27.94), 5 MASTER-RESET (63.627, -25.4), 6 GND
(66.167, -25.4). MISO, SPCK and MOSI appear **only on SPI0 and U1** (pads 108/110/109):
**hardware SPI is not on any edge header**. A stacked shield could reach SPI0 only
with its own underside 2x3 socket (pins are 7.55 mm high, under the 8.47 mm plastic)
*(check)*. ICSP1 is the 16U2's header (MISO2/SCK2/MOSI2/RESET2), not the SAM3X's.
**RESET** = net MASTER-RESET: POWER0.3 (33.02, -2.54), SPI0.5, DEBUG0.4.
**SDA/SCL**: SDA1/SCL1 on PWMH0.9/.10 (no pull-ups); SDA0-3/SCL0-3 on
COMMUNICATION0.7/.8 (1.5 k to 3V3). **CAN**: CANRX0/CANTX0 ADCH0.7/.8, CANRX1 shares
DAC0 (ADCH0.5), CANTX1 on XIO0.34.

## 3. Mating pins, coordinates relative to the board origin

Shield stacking-header footprints must repeat these positions exactly (pad centre
to pad centre); relative to the origin `Y_up = -y`.

| signal | header.pin | x | y | Y_up |
|---|---|---|---|---|
| A0 (AD7, CH2) | ADCL0.8 | 68.58 | -2.54 | 2.54 |
| A1 (AD6, CH1) | ADCL0.7 | 66.04 | -2.54 | 2.54 |
| A2..A7 | ADCL0.6..1 | 63.50, 60.96, 58.42, 55.88, 53.34, 50.80 | -2.54 | 2.54 |
| A8..A11 | ADCH0.1..4 | 73.66, 76.20, 78.74, 81.28 | -2.54 | 2.54 |
| DAC0 | ADCH0.5 | 83.82 | -2.54 | 2.54 |
| DAC1 | ADCH0.6 | 86.36 | -2.54 | 2.54 |
| AREF | PWMH0.8 | 23.876 | -50.8 | 50.8 |
| GND (upper edge) | PWMH0.7 | 26.416 | -50.8 | 50.8 |
| GND | POWER0.6, .7 (also XIO0.35/.36 at y -7.62) | 40.64, 43.18 | -2.54 | 2.54 |
| 5V | POWER0.5 (also XIO0.1/.2 at x 93.98/96.52, y -50.8) | 38.10 | -2.54 | 2.54 |
| 3.3 V / VIN | POWER0.4 / .8 | 35.56 / 45.72 | -2.54 | 2.54 |

Gaps: POWER0.8 to ADCL0.1 and ADCL0.8 to ADCH0.1 are 5.08 mm; PWML0.8 to PWMH0.1 is 4.064 mm.

**Height and keepout** (3D STEP local extents in `models/components/*.step`, z = 0
taken as the Due PCB top *(check)*; `models-3d.json` has no heights): headers 8.47 mm,
so the shield underside sits about 8.5 mm up *(check)*; X2 jack 11.0 mm, the only
part taller than the headers; PC1/PC2 6.42; ICSP1/SPI0 7.55; JTAG0 4.78; micro USB
J3 2.75, USB1 2.81; reset switch 3.15; U1 1.4. Heights are generic models, "unqualified"
per `v03/README.md`. Pad bounding boxes, absolute: X2 x 5.69..11.68, y -9.07..-3.30
(body overhangs the left edge); USB1 (native) x 0..4.55, y -42.3..-33.9; J3
(programming) x 1.14..4.09, y -25.7..-18.7; reset button x 2.0..10.4, y -51.0..-46.5.
Cables enter from the left, so keep the shield outline and tall parts out of x < about
16 *(proposal, measure)*; keep its underside parts well under 8.5 mm.

## 4. Power paths in the file

From nets only; MOSFET and diode orientation needs datasheets *(check)*.

- **The 5V pin is net `+5V`** (POWER0.5, XIO0.1/.2, SPI0.2, ICSP1.2). Source: **IC2
  LM2734Y** buck from net `VIN` (pin 5; EN from VIN via R10), SW to **L4 10 uH** to
  +5V, catch diode D4, boot diode D3, feedback R12 52K3 / R11 10K, output PC2 47 uF.
  Jack X2 pin 2 (`VIN+`) reaches `VIN` through D5 (pads VIN / N$10) and L6 *(check)*.
  **IC4 NCP1117** (reported AMS1117) takes +5V and makes +3V3.
- **USB into +5V:** **T1** FDN340P (pad1 USBVCC, pad2 +5V, gate pad3 = GATE_CMD from
  IC1 LMV358, which compares VIN via RN4) and **T2** (pad1 USBVCCU2, pad2 +5V, gate
  pad3 = GND). F1/F2 are 500 mA fuses. D2: RESET2 anode, +5V cathode.
- **Back-feed with the Due unpowered:** nothing in the file isolates +5V from the USB
  VBUS nets. T2's gate is hard to GND, so externally driven +5V appears to turn it on
  and feed USBVCCU2 / F2 / the 16U2's VBUS pin (IC6.31), and IC4 powers 3V3
  *(check by datasheet and test)*. So the shield takes 5 V and never drives the pin
  (`docs/afe.md` PW-1).
- **3V3 pin** (POWER0.4; IOREF POWER0.2 is the same net): from IC4; also U1 digital
  3V3, IC1, IC10, ERASE0 and the 1.5 k I2C pull-ups RN5.
- **AREF.** Pin PWMH0.8 is net `AREF`, whose **only** other connection is BR1 pad 1.
  The chip's reference is net `AVREF` (U1 pad 75, C19, ferrite L3 pad 2) from
  `AVREFL` (L3 pad 1, C34, JR1 pad 2, BR1 pad 2). **JR1** is 0 ohm, +3V3 to AVREFL,
  fitted; **BR1** (J0402 "NM", pads 1 AREF, 2 AVREFL, 3 +3V3) is not bridged. So
  **on a stock Due the AREF pin connects to nothing** and ADVREF is +3V3 through JR1
  and L3. `docs/afe.md` line 72 ("AREF is the board's 3.3 V rail") holds for the
  chip's reference, not for the pin in this reference *(check by continuity)*. A
  shield load on AREF is harmless until BR1 is bridged (README: pads 1-2, JR1 off).

## 5. Pins the AFE proposes to use (a proposal)

Firmware pin use (`drivers/`, `lib/`, `sketches/`, `apps/`): ADC `drivers/adc.c`
only disables pull-ups on PA2/3/4/6 and PB15..18; TC0 ch0/ch1 TIOA0/TIOA1 are
internal triggers and no PIO peripheral mux is programmed (grep: no `PIO_ABSR`/`PDR`
in firmware); the LED is PB27 = D13; the console is on UART0 (D0/D1, programming
port); USB uses dedicated pins and DACC uses DAC0/DAC1. The Arduino core's own
`init()`/`variant.cpp` for Track A is not in the repo and was not read *(check)*.

Updated to the pins the round-1 design uses (`../kicad/design.py`, FR-01).

| function | pin | header.pin, absolute (x, y) | reason |
|---|---|---|---|
| CH1 | A1 (AD6) | ADCL0.7 (66.04, -2.54) | PA24; PGA pair partner of A0 (`docs/afe.md`) |
| CH2 | A0 (AD7) | ADCL0.8 (68.58, -2.54) | PA16 |
| AWG | DAC0 | ADCH0.5 (83.82, -2.54) | PB15; DAC1 stays the bench trigger (CLAUDE.md) |
| ladder taps | A2..A7, six taps, A2 lowest (0.188 V) to A7 the 3.0 V top (the REF3030E output itself) | ADCL0.6..1 x 63.5..50.8 | `docs/afe.md` PA-9; A8..A11 stay free |
| reference to AREF | AREF | PWMH0.8 (23.876, -50.8) | through an unfitted 0R (PA-7); floats on a stock Due, section 4 |
| 3.3 V sense | 3.3V | POWER0.4 (35.56, -2.54) | the scope Vmid sense, microamps (PW-1) |
| 5 V in | 5V | POWER0.5 (38.10, -2.54); XIO0.1/.2 | PW-1 |
| ground | GND | POWER0.6/.7 (40.64/43.18, -2.54); PWMH0.7; XIO0.35/.36 | star to the shield's plane |
| range CH1 | D38 (PC6) | XIO0.19 (93.98, -27.94) | single-net GPIO, no on-board load; 4.7k pull-down |
| range CH2 | D39 (PC7) | XIO0.20 (96.52, -27.94) | same |
| tee ratio switch | D40 (PC8) | XIO0.21 (93.98, -25.4) | same |
| unassigned | D41 (PC9) | XIO0.22 (96.52, -25.4) | free: the second calibration switch is gone with the tee |
| SCK | D33 (PC1) | XIO0.14 (96.52, -35.56) | bit-banged SPI on one port (PIOC bits 1..4) |
| MOSI (ADS124S08 DIN) | D34 (PC2) | XIO0.15 (93.98, -33.02) | idem |
| MISO (ADS124S08 DOUT/DRDY) | D35 (PC3) | XIO0.16 (96.52, -33.02) | idem |
| CS ADC | D36 (PC4) | XIO0.17 (93.98, -30.48) | idem; 4.7k pull-up to +3.3 V_A |
| unassigned | D37 (PC5) | XIO0.18 (96.52, -30.48) | free: no precision DAC, so no DAC chip select |
| alt. bus | SDA1/SCL1 (D70/D71) | PWMH0.9/.10 (21.336 / 18.796, -50.8) | hardware TWI, no on-board pull-ups; not used |

Why: D33..D41 are single-net GPIO (table 2.3), clear of D0/D1 (console, 16U2), D13 (LED,
IC1.3), D4 and D10 (each net ties **two** U1 pads: 112+137 and 102+111), D20/D21 (pull-ups),
D2 (PB25, the TIOA0 pin, in case the trigger is brought out *(check)*) and the analog
and DAC pins. PC1..PC8 are contiguous in one port, so one `SODR`/`CODR` write sets a
pattern. The D-to-PIO mapping is read from the V03 schematic's nets (`whatif/bom.md`,
pin check). The firmware drives none of them today. Hardware SPI (PA25/26/27) is not on
the edge, hence the bit-banged bus, used during calibration only, not while capturing.

**Reset and undriven state (requirement: +/-5 V, ratio switch on the AWG's Vmid).**
After reset the PIO lines are inputs with the SAM3X pull-up enabled (datasheet 11057C
31.5.1, 50..150 kohm, Table 45-2); with the Due off they sit near 0 V. **Low** is the
safe state: high selects +/-1.25 V or the ratio switch's 3.0 V throw, and D38..D40 get
a 4.7k pull-down, which holds them at 0.31 V or less against the TMUX1119's 0.8 V VIL
(`whatif/bom.md`, "Control-pin pull resistors"). The chip select idles high, pulled to
the AFE's 3.3 V rail (itself off when the Due is off). The nets in the file carry no
other Due load on D33..D41 *(check boot-time behaviour)*.

Not established: shield pin length and underside clearance, the heights' z datum, the
real BR1 state, T1/T2 orientation, Track A core reset-time pin setup.
