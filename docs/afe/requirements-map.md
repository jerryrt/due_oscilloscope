# Contractor wording to our requirements

Internal. Not for the contractor. The contractor's `requirements.md` uses
rounded, general terms; check their results against the exact limits in
[afe.md](../afe.md).

| Contractor topic | Our requirement IDs |
|---|---|
| Scope inputs: ±5 V, readable to ±6 V, margin inside 0 to reference | SC-2 |
| Step size, range use | SC-4 |
| Input resistance and capacitance | SC-3 |
| Low-pass pole about 270 kHz, no peaking | SC-5 |
| Noise at the converter pin | SC-6 |
| Channel match | SC-8 |
| Shared sample-and-hold, low-impedance driver | SC-9, SC-10, AN-2 |
| Accuracy after software correction (not stated to the contractor) | SC-7, DF-4, AW-7 |
| Differential jumper | DF-1 |
| Two differential ranges | DF-2 |
| CMRR | DF-3 |
| Generator ±1 V, step, window use | AW-1, AW-2 |
| Generator low-pass | AW-3 |
| Generator load, output impedance, short | AW-4 |
| DAC draw | AW-5, AN-3 |
| Generator noise | AW-6 |
| Generator accuracy as built, offset from the reference rail | AW-7, AN-4 |
| Reset and boot state | AW-8 |
| ±30 V survival, pin limits, unpowered back-feed | PR-1, PR-2, PR-3 |
| Generator survives external ±5 V | PR-4 |
| Power draw, negative rail ripple, noise on 3.3 V | PW-1, PW-2, PW-3, PW-4 |
| Temperature | EN-1 |
| Construction | MC-1 to MC-10, PW-5 |
| Later amplifier module interface | P2-1 to P2-6 |
| Calibration (host software) | CA-1 |

## Left out of the contractor wording on purpose

- Exact tolerances, TBC values and test methods (VT-1 to VT-14). The
  contractor proposes a validation plan; we compare it with `afe.md`
  section 10.
- Phase 2 as a separate scope.
- Accuracy after calibration (the contractor can't affect it).

## Check on every revision

Compare the contractor's results table against the exact `afe.md` limits,
not their rounded wording. Where their wording was looser than ours, a pass
in their table is not a pass here.
