# Datasheet facts for the AFE parts

Read from the files in this directory (retrieval 2026-11-10). Page/table references are the datasheet's own section or table names and printed page numbers where the text extraction showed them. Anything that is only in a graph, or that I could not read, is marked *(check)*. Typical values at 25 C unless stated. Nothing was guessed.

## Op-amps

Conditions differ between parts, so compare with care: OPA354 and OPA356 are specified at VS = 5 V (some rows 2.7-5.5 V); OPA365 table is at VS = 5 V / RL = 10 k to VS/2. None of the three is specified at 3.3 V for the noise, swing and slew rows below unless a row says so.

| item | OPA354 (SBOS233H) | OPA356 (SBOS212A) | OPA365 (SBOS365G) |
|---|---|---|---|
| Supply, specified/recommended | 2.5-5.5 V (Sec 6.3, p5); PSRR spec 2.7-5.5 V | 2.7-5.5 V specified, 2.5-5.5 V operating (EC table, p3) | 2.2-5.5 V (Sec 7.6, p7) |
| Supply abs max | 7.5 V (Sec 6.1, p5) | 7.5 V (Abs Max, p2) | 5.5 V (Sec 7.1, p5) |
| GBW | 100 MHz (G=+10); f-3dB 250 MHz G=+1 RF=25 ohm; 90 MHz at G=+2 (Sec 6.7, p7) | 200 MHz (G=+10, RL=1k); f-3dB 450 MHz G=+1 RF=0 (EC, p3) | 50 MHz, VS=5 V (Sec 7.6 cont., p7) |
| Slew rate | 150 V/us (VS=5 V, 4 V step), 130 (2 V step), 110 (VS=3 V, 2 V step), G=+1 (p7) | +300 / -360 V/us (VS=5 V, G=+2, 4 V step) (p3) | 25 V/us (VS=5 V, G=1) (p7) |
| Input voltage noise density | 6.5 nV/rtHz at 1 MHz (p7) | 5.8 nV/rtHz at 1 MHz (p3) | 4.5 nV/rtHz at 100 kHz (p6); 5 uVpp 0.1-10 Hz |
| 1/f corner | not stated in tables; only on Fig 6-11 *(check)* | *(check)* (curve only) | *(check)* (curve only; 0.1-10 Hz noise 5 uVpp given) |
| Input current noise | OPA354: 300 fA/rtHz; OPA2354/4354: 50 fA/rtHz, at 1 MHz (p7) | 50 fA/rtHz at 1 MHz (p3) | 4 fA/rtHz at 10 kHz (p6) |
| Input offset VOS typ / max | +-2 mV / +-8 mV at 5 V, 25 C; +-10 mV over -40..125 C; drift +-4 uV/C (p7) | +-2 mV / +-9 mV (VS=5 V); +-15 mV over temp; drift +-7 uV/C (p3) | 100 uV / 200 uV; drift 1 uV/C (p6) |
| Input bias / offset current | IB 3 pA typ, +-50 pA max; IOS +-1 / +-50 pA (p7) | IB 3 pA typ, +-50 pA max; IOS +-1 / +-50 pA (p3) | IB +-0.2 pA typ, +-10 pA max (25 C); IOS +-0.2 / +-10 pA (p6); over temperature in Sec 7.7 curve *(check)* |
| Input capacitance | 2 pF differential and common-mode (p7) | 1.5 pF (p3) | 6 pF differential, 2 pF common-mode (p6) |
| Input common-mode range | (V-) - 0.1 to (V+) + 0.1 V, rail-to-rail, CMRR drops from 80 dB to 68 dB beyond VCM above (V+)-2 V (p7: 3.5 V vs 5.6 V rows at 5.5 V supply) | **(V-) - 0.1 to (V+) - 1.5 V. Not rail-to-rail input.** (p3) | (V-) - 0.1 to (V+) + 0.1 V, no crossover (CMRR 100 dB min over full range) (p6) |
| Output swing from rail | 0.1 V typ / 0.3 V max, RL = 1 k, VS=5 V, AOL>94 dB (p8); 0.4 V max over temp | 0.2 V typ / 0.3 V max RL=150 ohm; 0.1 V typ RL=1 k; 0.8 V typ at IO=+-100 mA (p3) | 10 mV typ / 20 mV max, RL = 10 k, VS=5.5 V (p7) |
| Max output current | 100 mA at VS=5 V; 50 mA at VS=3 V (p8) | +-60 mA continuous, +-100 mA peak (5 V), +-80 mA peak (3 V) (p3) | RL spec'd at 600 ohm; swing at heavier load: see Sec 7.7 curve *(check)* |
| Short-circuit current | text: peak currents up to 200 mA, "typical short-circuit current" (Sec 7.3.4 area) | +250 / -200 mA (p3) | +-65 mA (p7) |
| Quiescent current per channel | 4.9 mA typ / 6 mA max (OPA2354); 5 / 6.3 mA (OPA354), VS=5 V (p8) | 8.3 mA typ / 11 mA max, VS=5 V; 14 mA max over temp (p3) | 4.6 mA typ / 5 mA max (p7) |
| Abs max, signal inputs | (V-) - 0.5 V to (V+) + 0.5 V; input current +-10 mA (Sec 6.1, p5) | same: -0.5/+0.5 V beyond rails, 10 mA, "diode-clamped to the supply rails" (p2) | -0.5/+0.5 V beyond rails, +-10 mA, diode-clamped (Sec 7.1, p5) |
| ESD (device handling) | HBM +-2000 V, CDM +-250 V (Sec 6.2) | *(check)* (older datasheet; ESD sensitive note only) | *(check)* (Sec 7.2 not read) |
| Stability with capacitive load | unity-gain stable; "performs well with large capacitive loads"; 10-20 ohm series R recommended for large CL (Sec 7.3.7, Figs 6-13/6-14/6-15); max CL number not stated in text *(check)* | no number extracted; curves "Frequency Response for Various CL" and "Recommended RS vs CL" *(check)* | stable to approx 1 nF pure capacitive load in unity gain (Sec 8.3.3) |
| Other | open-loop output resistance 35-39 ohm; AOL 94 dB min at 5.5 V; closed-loop Zout 0.05 ohm | closed-loop Zout 0.02 ohm; AOL 84 dB min | open-loop Zout 30 ohm at 1 MHz; AOL 100 dB min; THD+N 0.0004% |

Design notes drawn directly from the numbers above:

- OPA356 cannot be used as a mid-rail follower to the top rail: its input range stops 1.5 V below V+. It is only valid for the non-rail-to-rail positions.
- OPA354's rail-to-rail input has a stage crossover near (V+) - 2 V (inferred from the two CMRR rows; the datasheet does not name the crossover voltage) *(check)*. Expect offset/CMRR change across it. OPA365 has no crossover (its text says no input stage crossover is present; CMRR spec covers the full range).
- OPA354 and OPA356 draw 5-8 mA per channel; OPA365 draws 4.6 mA per channel. Budget the LM27762 (250 mA) accordingly.

## LM27762 (SNVSAF7C, Oct 2025)

| item | value | ref |
|---|---|---|
| Input range | 2.7-5.5 V operating; abs max VIN to GND 5.8 V | Sec 5.1 / 5.2, p4 |
| Output ranges | positive LDO 1.5-5 V; negative -1.5 to -5 V, both adjustable by resistor dividers (VFB+ 1.2 V, VFB- -1.22 V) | Sec 5.5, p5 |
| Load current | up to +-250 mA each rail (operating), 300 mA abs max | Sec 5.1-5.2 |
| Switching frequency | 2 MHz typ (1.7-2.3 MHz) at VIN 3.6 V | Sec 5.5 |
| Output noise | 22 uV rms each rail, 10 Hz-100 kHz, IL = 80 mA | Sec 5.5 |
| PSRR | OUT- 50 dB; OUT+ 43 dB; both at 10 kHz, IL=100 mA, Vout +-1.8 V | Sec 5.5 |
| Ripple | about 1-5 mV vs load current (Fig 5-1, VIN 3.7 V, Vout +-3 V) - numbers read from graph *(check)* | Sec 5.6 |
| Dropout | 30 mV (neg., 100 mA, -5 V), 45 mV (pos., 100 mA, 5 V) | Sec 1, 5.5 |
| Quiescent | 390 uA typ, shutdown 0.5 uA typ | Sec 5.5 |
| Charge-pump output resistance | 2.5 ohm at 100 mA, VIN 5.5 V | Sec 5.5 |
| Note | at VIN = 5.5 V the charge pump may enter PWM mode in hot conditions (footnote); package WSON-12 3x2 mm | Sec 5.5 |
| Not read | startup time/inrush, EN thresholds beyond VIH 1.2 V / VIL 0.4 V, PG thresholds | *(check)* |

## Converters

| part | resolution | noise / accuracy | INL | interface | supply | inputs | reference input | ref |
|---|---|---|---|---|---|---|---|---|
| DAC8551 | 16-bit, monotonic | SNR 95 dB (20 kHz BW, 1 kHz out, 5 V); glitch 0.1 nV-s; output noise density Fig 26 *(check)* | +-12 LSB max (DAC8551), +-16 (DAC8551A); DNL +-1 LSB | SPI-type 3-wire, to 30 MHz | 2.7-5.5 V | 1 output | VREF 0 to VDD (spec), external; output range 0 to VREF; ref input impedance in datasheet *(check)* | Sec 6.x static/output/AC tables; settling 8-10 us |
| DAC8571 | 16-bit, monotonic | no noise spec found *(check)*; zero-code/offset +-1 mV max | +-0.098 % FSR relative accuracy; DNL +-0.25 typ, +-1 max LSB | **I2C** (to 3.4 MHz), not SPI | 2.7-5.5 V | 1 output | external VREF; ref impedance 140 kohm typ | Electrical table |
| ADS8688 | 16-bit SAR, 500 ksps aggregate | SNR 89 dB typ (+-0.625 VREF range) up to 92 dB feature-list figure | +-0.75 LSB typ (+-2 max); DNL +-0.5 typ | SPI, daisy-chain | AVDD 4.75-5.25 V (5 V only), DVDD 1.65-5 V | 8 inputs (ADS8684: 4), 1 Mohm, +-20 V overvoltage tolerant | internal 4.096 V, or external 4.046-4.146 V on REFIO | Sec 7.5, p7+ |
| ADS1256 | 24-bit delta-sigma, 30 ksps | up to 23 bits noise-free; noise tables vary with rate/PGA *(check)* | +-0.0003 % FSR typ, +-0.0010 % max (PGA 1) | SPI | AVDD 4.75-5.25 V (5 V only), DVDD 1.8-3.6 V | 8 single-ended or 4 differential | VREF 0.5-2.6 V (2.5 V typ) | Electrical table |
| MCP3564 (MCP3561/2/4 family) | 24-bit delta-sigma, to 153.6 ksps | 106.7 dB SINAD, 107.2 dB SNR (AVDD=VREF=3.3 V, gain 1, 4800 SPS); 23.3 effective bits | +-10 ppm FSR max (gain 0.33x) | SPI 20 MHz | AVDD 2.7-3.6 V, DVDD 1.8-3.6 V (3.3 V single supply fits) | MCP3564: 4 diff or 8 single-ended | external VREF 0.6 V to AVDD, differential | Features, Electrical Specs |
| ADS1220 | 24-bit delta-sigma, 2 ksps | tables by rate/gain *(check)* | +-6 ppm FSR typ (15 max), gain 1-128 | SPI mode 1 | AVDD 2.3-5.5 V | 4 SE / 2 diff only (too few) | internal 2.048 V or external 0.75 V to (AVDD-AVSS) | Sec 6 table |
| ADS1118 | 16-bit delta-sigma, 860 sps | *(check)* | *(check)* | SPI | 2-5.5 V | 4 SE / 2 diff only (too few) | internal only (no external reference pin) | features |
| ADS1115 | 16-bit, 860 sps | fetched for comparison only; not read | *(check)* | I2C | 2-5.5 V | 4 SE only | internal | - |

Notes: only ADS8688, ADS1256, MCP3564 offer 8 single-ended inputs. ADS8688 and ADS1256 need a 5 V analog rail (not the 3.3 V Due rail); MCP3564 runs from 3.3 V.

## Reference, switches

| part | key numbers | ref |
|---|---|---|
| REF3030 (3.0 V, SOT-23-3) | non-E: initial accuracy 0.2 %, noise 33 uVpp (10 Hz-1 kHz) and 94 uV rms (10 Hz-10 kHz), VIN to 5.5 V, drift 75 ppm/C (family table); REF3030E: 0.1 %, 24 uVpp (0.1-10 Hz), 51 uV rms (10 Hz-10 kHz), 5-6 ppm/C typ (15-20 max), IQ 27 uA, dropout 20 mV, ISC 35 mA, stable with 0.1-22 uF output cap, load regulation 15 ppm/mA max source. The non-E table prints VOUT max as 3.06 V, which looks like a typo for 3.006 V *(check)* | Sec 6.5 / 6.6 |
| TMUX1119 (SPDT 2:1) | VDD 1.08-5.5 V; RON 1.8 ohm typ at 5 V, 3.7 ohm typ / 8.8 max at 3.3 V (25 C); charge injection -6 pC typ (CL=1 nF); leakage 3 pA; BBM; 1.8 V-compatible logic; BW 250 MHz | Sec 5.5, 5.6 |
| TS5A3159 (SPDT) | V+ 1.65-5.5 V; ron 1.15 ohm typ (1.5 max) at 3.3 V; charge injection 20 pC at 3.3 V (36 pC at 5 V); BW 100 MHz; 5 V-tolerant control; THD 0.015 % at 3.3 V | Sec 6.5, 6.6 |
| ADG719 | datasheet not obtained (analog.com unreachable) | - |

## Models

See SOURCES.md. Models usable in ngspice 47 out of the box: OPA354, OPA2354, OPA356, OPA365. Not usable without editing: LM27762, TMUX1119, TS5A3159, REF3030.
