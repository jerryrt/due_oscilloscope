# AFE shield PCB

The working KiCad 10.x project for the AFE: a custom shield in the Arduino Mega/Due
form factor, stacked on the Due through stacking headers, with all three phases in
one design built over several rounds. The requirements are in
[docs/afe.md](../../docs/afe.md) and the plan that builds them is
[docs/afe-plan.md](../../docs/afe-plan.md), including its "Rounds" section.

| Location | Role |
|---|---|
| This directory | The shield PCB project, its models, simulation benches and reports, created as the plan's steps need them |
| [Due V03 reference](../reference/arduino-due/README.md) | The Due: mating geometry, header pins and the AREF, ADVREF network the shield's reference reaches. Not edited |

Rules:

- Use KiCad 10.x only.
- Every optional part, and every undecided choice, is an unfitted footprint or a jumper
  (MC-11); the BOM says which are fitted in the round.
- Header pin positions come from the Due V03 reference and are checked by
  continuity on the owner's boards before a round is ordered (MC-4).
- The shield does not modify the Due: the reference reaches the Due's AREF pin
  through an unfitted series element, and JR1 and BR1 stay untouched (PA-7).
