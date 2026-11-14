# ads1115-open provenance

Clean-room model: built only from FACTS.md (datasheet facts); no vendor SPICE model was consulted.
I had no vendor model in context at any point.

- Input: FACTS.md, sha256 `6bf50b02a2c70e4af33d33d8f9c326733669663f9e54f2e336020b6469050956`
- Brief: ads1115.lib modelling only the analog input load (ZCM per selected pin, ZDIFF across the selected
  pair, per FSR; leakage on unselected pins; clamps to GND and VDD) plus ads1115_open.py (ideal
  differential voltage to code), with tests per rule 5 including a break control.
- Date: 2026-11-13
- Licence: CC-BY-SA 4.0 (LICENSE).

## FACTS rows used
- ZCM, ZDIFF per FSR: sec 3 (p5). 0.7 V common-mode node: sec 3 Fig 7-5. MUX table: sec 2 Table 8-3.
- LSB per FSR: sec 6. Clamps exist, stay off within 0.3 V of the rails: sec 1 / sec 2 Fig 7-4.
- Not modelled (FACTS gaps): sampling-capacitor dynamics, input capacitance, switch resistance, crosstalk, settling.
  Valid for DC and low frequency only.

## Derived behaviour (not a FACTS number)
- For MUX 4..7 the negative input is GND, so a selected pin sees ZCM (to 0.7 V) in parallel with ZDIFF (to GND).
  This follows from Fig 7-5, not from a stated figure.
- A selected pin at DC draws (V - 0.7 V)/ZCM, per Fig 7-5, so it draws no current at 0.7 V. Parameter VINT=0 gives
  a plain resistor to GND.

## Modelling choices not in the datasheet
| choice | value | why needed | bench test that pins it |
|---|---|---|---|
| Unselected-input leakage ILEAK (FACTS sec 5: not given) | 100 nA, constant magnitude, tanh(V/0.1 V) sign shape | A leakage must exist for source-error budgets. 100 nA is deliberately high (conservative) for a CMOS input at hot temperature; only the digital pins' +/-10 uA is a datasheet bound. | Drive an unselected pin through a known high resistance (e.g. 10 Mohm) from a stable source, or use an electrometer; read the voltage drop at 25 C and at 85 C. |
| Clamp diodes | IS=1e-14 A, N=1, RS=50 ohm, no capacitance, from each AINx to GND and to VDD | FACTS gives no forward characteristic (sec 1 gaps). IS chosen so the diodes are off (about 1 nA) at the 0.3 V of margin the datasheet states. RS gives about 10 mA at roughly 1 V beyond the rail. | Source a current into a pin with VDD powered, 1 uA to 10 mA, record the pin voltage above VDD (and below GND), with the other pins floating. |
| ZCM/ZDIFF FSR snapping | thresholds at 5, 3, 1.5, 0.8 V | Non-listed FSR values need a rule. PGA codes 110/111 give 0.256 (FACTS sec 6). | None; software convention. |
| ZCM / ZDIFF constant in voltage and temperature | typical values | FACTS gaps: input-voltage and temperature dependence unstated. | Measure pin current versus input voltage and temperature on a bench part. |
| Code rounding | round to nearest, saturate at the 16-bit limits | Datasheet states no rounding rule; offset, gain error, noise and INL excluded (ideal). | Sweep a calibrated source across a code transition and read the code. |
| LSB reading | LSB = FSR/32768 (table values) | FACTS Eq. 4 text says FSR/2^16; the table values (187.5 uV at 6.144 V) correspond to FSR/32768, so the table governs. | Same sweep. |
| 1 Tohm shunt at the internal difference node | 1e12 ohm | Numerical convergence only. | None. |
