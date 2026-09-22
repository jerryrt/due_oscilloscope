# Stage A design review

**Not released for assembly or fabrication.** The schematic is usable and
the real-model simulations run, but Phase A1 performance is not established.
Evidence: KiCad 10.0.6 and ngspice 47, nominal vendor models, 3.3 V supply,
27 C; reproduce with `check.py` and `sim/run.sh`.

## Electrical and file checks

| area | state |
|---|---|
| All three schematic sheets | ERC: zero errors; 61 isolated-pin-label warnings from unused pass-through header nets. Warnings remain visible, not globally suppressed |
| Due headers | J5.5/6 = DAC0/1, J5.7/8 = CANRX0/CANTX0; J2.1/2 = SCL1/SDA1, separate from J6.8/7 = SCL/21, SDA/20 |
| Critical connectivity | Automated checks cover DAC inputs, A0/A1/A2 outputs, reference feedback, supplies, AREF and the separate I2C buses |
| Annotation and readability | Unique power references across the hierarchy; no dangling VREF3V0 sheet port; D1 and rotated passive labels readable; jumper symbol/pin endpoints match the installed library |
| BOM intent | U1 MPN = MCP6024-E/SL; D1 MPN = LM4040AIM3-3.0/NOPB to match the TI -N A-grade model; R3/R4 have explicit 0.1% fields; C5/C6/C7 specify C0G/NP0 |
| Models | Original vendor archives and extracted text retained with licenses; separate 14-pin quad and 3-pin reference adapters; no ideal placeholder model is active |
| PCB | Mechanical template only: seven headers, six mounting holes, no Stage A components or routing. DRC has six unconnected items, 26 missing schematic footprints, and seven header-library mismatch warnings |
| PCB graphics | Header net assignments agree with schematic; J7 silkscreen corner clears the board edge and solder mask |
| Local footprint library | Three NPTH hole sizes inspected: 1.2 mm, 1.651 mm (65 mil), 3.2 mm; descriptions match drill sizes. Library path is project-relative |
| Project settings | Existing KiCad 10 project migration retained. Do not treat template clearances or library defaults as a fabrication specification |

The header footprint mismatch warnings require a controlled footprint update
before PCB layout. Preserve header positions, orientation and pin numbering;
do not blindly replace the template geometry. The mounting-hole positions,
connector mating, USB/barrel-jack clearance and stack heights still need a
physical/mechanical fit check. Routing belongs to Phase P, after the prototype.

## Simulation findings

| check | nominal result | disposition |
|---|---|---|
| VREF3V0 / VREF1V5 | 2.99839 V / 1.49959 V | Plausible nominal operating points, not worst-case accuracy |
| DAC0 DC transfer, 0.5–2.5 V | maximum error about 0.418 mV | Below one 3 V / 4096 code in this model |
| U1C follower at 5.012 MHz, before R5 | -5.86 dB | Does not demonstrate the A1 “flat past 5 MHz” requirement |
| A0 after 68 ohm / 470 pF | -8.90 dB at 5.012 MHz; first sampled -3 dB crossing about 3.39 MHz | The passive RC's 4.98 MHz corner is not the full signal-path bandwidth |
| 2 V DAC0 step, both polarities | about 1.218 us to remain within 0.732 mV of the final plateau | Exceeds the 1.129 us interval at 886 ksps; DC error is assessed separately |
| AREF capacitive stress | about 0.828 mV p-p during 100 uA load steps with 200 nF | Slightly above one code; not a stability qualification |

The AREF test approximates the Due's two 100 nF capacitors as one lumped
200 nF load. It does not model L3 ferrite impedance, PCB parasitics, ADC
sampling switches, power-up sequencing or supply noise. The transient starts
from a solved operating point, not a power-on ramp. The 14 kohm reference load
draws about 214 uA at 3 V. This is a modified-Due/closed-link load assessment,
not a simulation of the default open JP1. A stock Due has a different DAC
window because its reference remains 3.3 V.

## Decisions before a prototype

1. Reconcile the 5 MHz follower target and full-scale settling target with
   the MCP6024 implementation. Evaluate another suitable op-amp or a revised
   drive network against ADC acquisition loading; do not shrink the 470 pF
   charge reservoir merely to make a bandwidth plot pass.
2. Validate U1A reference-buffer loading and compensation, including the Due
   ferrite and capacitors. Keep JP1 open until this is settled and JR1/BR1
   configuration is physically confirmed.
3. Run tolerance, supply and temperature corners; check capacitor voltage
   ratings/DC-bias derating, resistor grades, supply decoupling and layout.
   Then measure real hardware. Vendor macro models do not establish noise,
   channel crosstalk, distortion or worst-case performance by themselves.

Official datasheets, application guides and manuals are indexed in
[`docs/reference`](../../docs/reference/README.md). The selected TI -N part
has the same K/A pin positions as the cached generic symbol; pin 3 is left
floating as allowed by its own datasheet. Select parts by MPN, not by symbol
library name alone.
