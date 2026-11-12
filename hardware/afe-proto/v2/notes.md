# AFE version 2: design notes (working)

Working notes for the version 2 design against `docs/afe-v2.md` (82096d0), which
amends `docs/afe.md`. The spec is being revised, so this design runs alongside it:
spec-robust work first (parts, the Basic catalogue, budgets that only need
constants changed), circuits after. Nothing here is accepted; every figure from a
datasheet carries its source, and the rest is marked *(check)*.

| File | What |
|---|---|
| `parts.md` | Dual op-amp choice, ADS1115 vs SGM58031, the shared negative rail |
| `jlc-basic.md`, `jlc-basic.csv` | The JLC Basic passives the design may use (V2-3), read from JLC's own pages |
| `../budget/v2_scope.py` | The scope's one range, by arithmetic and Monte Carlo at 1 % |

## Scope channel, proposal

No buffered mid-rail per channel. The input reaches one half of a dual through a
three-resistor network: R1 from the input, R2 to ground, R3 to the REF3030E.
The attenuation is Rp/R1, the centre Vr·Rp/R3, and the input resistance
R1/(1 − a). On JLC Basic 0603 values (`jlc-basic.csv`), two in series where
no single value fits: R1 510k + 30k, R2 1M + 510k, R3 470k + 200k, six parts
per channel. That gives a = 0.462, 71.1 % of full scale for 5 V, R_in 1004 kΩ,
1.76 mV per code, and the low/high margins at −2.0/+4.0 V pass with 60 and
112 mV to spare at 1 %.

What this asks of the rest of the board:

- The REF3030E carries both channels' offset current (about 4.6 µA each) and
  sinks about 1 µA per channel when an input past +4 V is clamped near the
  +3.3 V rail *(check its sink rating)*. It is also what the ADS1115 reads, so
  the scope's signal current through R3 must not move it by more than SC-7's
  share *(check: output impedance × 2 × ±16 µA)*.
- The follower's input sits between about 0.1 and 3.1 V, so it needs no
  negative rail for the signal; the negative rail is for the AWG and for
  output headroom near 0 V.

## Questions for the owner or the spec

1. **SC-3 "within 1 %"**: read as the nominal input resistance. With 1 %
   parts the worst-case spread is itself about ±1 % (988.8 to 1008.4 k on the
   values above), so a worst-case reading would need an exact 1 MΩ nominal.
2. **Nominal AREF** for "70 to 75 % of full scale at nominal AREF": taken as
   3.25 V, the middle of 3.20 to 3.30.
