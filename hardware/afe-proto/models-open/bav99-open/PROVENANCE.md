# bav99.lib provenance

Clean-room model. Inputs: `FACTS.md` in this folder (sha256 1477492f68ca16a1649f8dd9dbf0e339d6d09d10e3a3ca54c88cc22966b9b2fe),
`IMPL_RULES.md`, and the brief: build bav99.lib with `.model BAV99_OPEN_D` and `.subckt BAV99_OPEN A1 K2 CA`, fit the
diode parameters to FACTS.md Fig. 1-3 and the trr table numerically, set BV/IBV as a labelled choice, and test per the
rules. Date: 2026-11-13. The implementer had no vendor SPICE model in context and did not consult one.
CC-BY-SA 4.0 (LICENSE). Regenerate with `python3 make_lib.py` (numpy, scipy, ngspice).

## What was fitted, from what

| model part | FACTS source | residual (model minus digitised) |
|---|---|---|
| IS, N, RS, IKF, TRS1, EG, XTI (one `.model` for all four temperatures, TNOM=25) | Fig. 1, 32 points (4 temps x 8 currents) | within the stated accuracy at all 32 points (+-5 mV to 30 mA, +-8 mV at 100/300 mA); worst 25 C / 300 mA +7.3 mV; the 300 mA row is weighted x4 in the fit; full table in `fit_residuals.json` |
| CJO, VJ, M and a fixed parallel CP (0.4458 pF) | Fig. 3, 7 points | within 3 mV of the points, accuracy +-10 mV |
| reverse leakage source (tabulated) | Fig. 2, 28 points | exact at the digitised points up to the diode's own IS(T); tested within the stated 0.012 decade (0.02 at 1 V, 95, 99 V) |
| TT | Table 7 trr max 4 ns | simulated trr 4.00 ns in the Fig. 5 style circuit, see below |

The fitted forward parameters: IS 2.972 nA, N 1.848, RS 1.161 ohm, IKF 0.108 A, TRS1 6.8e-4 /K, EG 1.234 eV, XTI 6e-14 (fitted to its lower bound of 0, so EG and XTI together only carry the temperature slope and are not separately meaningful).
IKF and TRS1 are not in the list the brief named; they were added because a plain IS/N/RS diode misses the 300 mA row
by 20-38 mV, and they are fitted to Fig. 1 like the rest. Read off ngspice by sweep, not assumed: its knee is
I = If/(1 + sqrt(If/IKF)), and the fit uses that form.

## Modelling choices not in the datasheet

1. **BV = 125 V, IBV = 10 uA.** FACTS gives no breakdown voltage (only VR/VRRM = 100 V). Chosen above VRRM so the model
   shows no breakdown inside the rated range. Pinned by: a bench reverse sweep to the leakage knee at a current limit of
   10 uA, on a part not needed afterwards.
2. **TT = 7.84 ns, set so simulated trr equals the 4 ns Table 7 maximum.** FACTS gives only a maximum. Using the maximum is
   conservative for storage-time checks. The trr circuit is my reading of FACTS's Fig. 5 text (50 ohm source and 50 ohm scope
   in series with the diode, 10 mA forward, reverse level limiting the reverse current to 10 mA, 0.6 ns edge, trr from the
   current zero crossing to a reverse current of 1 mA); with TT at 0 the same circuit gives 0.41 ns. Pinned by: a
   10 mA/10 mA trr measurement on a real part.
3. **M = 0.98, not the fit's 1.0.** The Fig. 3 fit pushed M against its bound at 1; ngspice's junction-capacitance formula is
   singular at M = 1 (a transient with it aborts "timestep too small"), so M is capped at 0.98. Effect on the Cd points
   is under 3 mV-equivalent.
4. **The Cd curve's constant part is a parallel capacitor CP = 0.4458 pF** inside the subckt (ngspice has no fixed
   capacitance parameter); this puts the 0.455 pF tail at VR = 16 V. Its physical split between junction and package is
   unknown (FACTS: no package capacitance). Capacitance at VR above 16 V and any temperature dependence of CP are not in
   FACTS; above 16 V Cd keeps falling slowly with CJO's law. Pinned by: a CV measurement to 50 V.
5. **Reverse leakage is a table, interpolated.** Between the four curves the current is blended linearly in 1/T on the
   log scale; below -40 C and above 150 C it is held at the end curve; between the digitised voltages it is log-linear in V,
   below 1 V it falls linearly to 0 at 0 V (FACTS: curves do not extend below ~1 V); above 99 V it is held at the 99 V
   value (breakdown takes over). Pinned by: IR at 0.1, 5 V and at 0 C / 125 C.
   The table holds what Fig. 2 shows minus the diode's own IS(T) (so the sum matches); where that would be negative it is
   floored at 1e-9 uA.
6. **The two diodes are identical and independent** (no coupling, no lead inductance, no package capacitance: FACTS gaps).
7. **`.options gmin=1e-15` is required in a deck that reads the -40 C reverse curve**: ngspice's default gmin (1e-12 S) alone
   conducts 99 pA at 99 V, more than that curve's 64 pA. Noted in the lib header; the tests set it.
8. FC = 0.5 (ngspice default, forward-bias capacitance linearisation); no FACTS value.

## Not matched

- None of the Fig. 1 points: all 32 are inside the stated accuracy (worst 7.3 mV at 25 C / 300 mA).
- Fig. 4 (IFSM vs tp), Tj/thermal figures, VFRM (1.75 V) and the absolute maxima are not modelled or tested: FACTS
  gives the curves only coarsely and the model has no self-heating or surge-current limit.
- Table 7 IR maxima are checked only for the 25 C 25 V and 150 C 25/75 V points; the "80 V, 25 C, 0.5 uA" row is covered
  by the Fig. 2 curve test (which is far below it).
