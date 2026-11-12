# AFE shield PCB

The working KiCad 10.x project for the AFE: a custom shield in the Arduino Mega/Due
form factor, stacked on the Due through stacking headers, with Phase 1 and Phase 3
in one design built over several rounds. The requirements are in
[docs/afe.md](../../docs/afe.md) and the plan that builds them is
[docs/afe-plan.md](../../docs/afe-plan.md), including its "Rounds" section.

| Location | Role |
|---|---|
| This directory | The shield PCB project, its models, simulation benches and reports, created as the plan's steps need them |
| [Due V03 reference](../reference/arduino-due/README.md) | The Due: mating geometry, header pins and the AREF, ADVREF network the shield's reference reaches. Not edited |

Rules:

- Use KiCad 10.x only.
- No jumpers or solder jumpers. Every optional part is an unfitted footprint and
  every choice a Due-pin switch (MC-11); the BOM says which are fitted in the round.
- Header pin positions come from the Due V03 reference and are checked by
  continuity on the owner's boards before a round is ordered (MC-4).
- The shield does not modify the Due: the reference reaches the Due's AREF pin
  through an unfitted series element, and JR1 and BR1 stay untouched (PA-7).

## Vendor models

Vendor SPICE models and datasheets are used locally and never committed
(MC-6), so a fresh clone has none. `models/manifest.json` lists each file
with its vendor URL, the zip member it comes from, and its sha256;
`models/SOURCES.md` carries the provenance, terms and smoke tests. Git ignores
everything else under `models/`. Models that may be committed are in
`models-open/`.

```sh
python3 -I hardware/afe-proto/tools/fetch_models.py           # fetch what is missing
python3 -I hardware/afe-proto/tools/fetch_models.py --check   # verify, download nothing
```

A file is installed only after its hash matches, and a present file that
fails its hash is left alone unless `--replace` is given. Any mismatch exits
non-zero. If a vendor changes a file, the fetch fails: check the new file and
update the manifest and `SOURCES.md` together.
