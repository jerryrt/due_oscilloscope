# AWG Ra/Rb from existing part types (what-if, 2026-11-11)

Copy of `sim/awg/run.py` in this folder (`AWG_VARIANT=<name> python3 -I run.py`,
`summ.py` prints the figures); results in `out/<variant>/results.json`. Networks are
netlisted part by part; each added series node carries 0.3 pF *(check)* (0.1/0.3/0.7 pF
at the V+ corners). 1 % parts: 10k, 4.7k; 0.1 %: 953, 249, 49.9, 330k, 768k. AW-7
is judged after calibration, so its old gain/offset rows are information only. The
baseline reproduces `sim/awg` revision 6 exactly.

| | parts | added nodes | nominal offset (analytic / spice) | AW-1 window, position-aware, corners (<=92 %) | AW-5 corners (<=100 uA) | open-cable overshoot (<=5 %) | PW-3 corners (<=26 mA) | verdict |
|---|---|---|---|---|---|---|---|---|
| base 13.7k / 15.8k | 2 | 0 | +0.6 / +4.0 mV | 84.5 / 85.3 % | 94.7 uA | 3.0 % | 25.98 mA | pass |
| c1: 10k+4.7k / (4.7k\|\|4.7k)+10k+4.7k | 6 | 3 | +8.3 / +11.7 mV | 85.7 / 86.4 % | 88.7 uA | 2.6 % | 26.70 mA | **FAIL PW-3** |
| **c2: 10k+4.7k / 10k+4.7k+953+953** | 6 | 4 | -15.5 / -12.0 mV | 88.5 / 85.4 % | 89.9 uA | 3.7 % | 25.88 mA | **pass** |
| (a) 768k\|\|330k\|\|(10k+10k) / 953+10k+10k | 7 | 3 | +1.1 / +4.6 mV | 87.3 / 86.9 % | 71.5 uA | 3.9 % | 26.15 mA | **FAIL PW-3** |

- AW-1 into 50 ohm at the datasheet weak rail: 0.02 mV on every Ra/Rb corner (limit
  0.62 mV); rail edge to the -2.041 V corner: base 70, c1 81, c2 47, (a) 70 mV.
- c1 fails PW-3 even at nominal (26.10 mA): its slope 1.160 and offset push the
  window-end output past 1.30 V.
- c2 with temperature (100 / 25 ppm/K over +-40 K *(check)*): window 89.5 %.
- Unchanged on every variant: AW-6 79.4 uV, AN-1 64.3 deg, AW-3 >= 14.5 MHz into
  50 ohm; AW-8, PR-4, PW-1, PR-3 pass.
- c2 overshoot vs added-node capacitance: 3.90 % (0 pF), 3.65 % (0.3 pF), 3.09 % (1 pF).

Ca = 39 pF + 39 pF in series (19.5 pF), removes the 20 pF type, +1 placement:

| | overshoot | settling to 1 %, fast / DAC edge | mid-band gain, worst | 50 ohm BW | rows |
|---|---|---|---|---|---|
| base Ra/Rb | 1.7 % | 442 / 663 ns (was 340 / 547) | 0.883 | 14.1 MHz | pass |
| c2 | 2.4 % | 445 / 675 ns | 0.876 | 14.1 MHz | pass |

AWG supply filter 22||22 (11 ohm) for 10 ohm: all rows pass; the 50 ohm row's rail
edge moves from -1.971 to -1.990 V (headroom to -2.041 V: 70 -> 51 mV); PR-4 55.5 mA.

Guards (each seen to fail): Ra/Rb at 5 % fails the window (94.9-98.1 %); over-
compensated Ca fails overshoot (Ca 39 pF: 26.9-28.6 %; 33/22 pF: 5.5-6.4 %); AW-5
guard now Ra and Rb x 0.6 (117-155 uA; the old Ra = 9.09k guard was blind on (a)).
The blanket-5 % weak-rail guard does not fire on c1, because c1's offset passes it.

Note: the SM-5 loop simulation (`sim/loop`) found the Ca/Cb compensation to be the
AWG's share of the PAM16 ISI; the capacitor choice here waits for its no-Ca/Cb run.
