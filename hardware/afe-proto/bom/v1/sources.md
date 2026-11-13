# Sources of bom.txt / bom.md (AFE v1)

References only; vendor pages and datasheets stay local (MC-6).
- Parts list and counts: `kicad/design.py` (source of truth; `make_parts.py` writes the streams from it), checked by `bomdiff.py` (C21189 16, every other type equal) and by `pcbtools.schematic_check` S4.
- Part numbers and LCSC codes: the `T` table in `kicad/design.py`; Basic/Extended classes from `v2/jlc-basic.csv`.
- Domestic CNY ladders: read from jlc-smt.com part pages on 2026-11-11 / 2026-11-12 and recorded in bom.md "Domestic part prices". C21189 (0R) not read: priced at the 1R ladder *(check)*. Not re-read for this pass.
- Fee rules: JLC China Economic SMT help pages recorded in bom.md "Domestic SMT fees" (setup 50 CNY, 20 CNY per Extended type, 0.01 CNY per joint, X-ray tiers).
- PCB price: the engine's rule (20 CNY + 410 CNY/m2 over its `BOARD_MM` 100 x 53.34 mm); v1's board is 100 x 58.34 mm, so the engine under-counts the area *(check)*.
- International assembly fees: `docs/jlcpcb.md` (not used for the totals).
- CNY at 6.6912 per USD *(check)*. Owner-fitted: `data/extra.csv`, the same rows as v2's (BNC ladder, header listings, M2.5 hardware unpriced).
- Board outline 100 x 58.34 mm: `kicad/afe-proto.kicad_pcb`.
- Arithmetic: `v2/bom/bom.py`, the engine version 2 uses, over `bom/v1/data/` (`make_bom.sh` regenerates the streams and `bom.md`; `selftest.py` checks them). The old narrative `bom.md` and its `money.py` are superseded: `legacy/bom-2026-11-13.md`.
- Prices: `data/catalog.csv` and `data/intl.csv` carry v2's rows for every LCSC number v2 also uses and, for the nine v1-only Basic types (C1658, C22797, C22978, C23024, C23046, C23196, C23242, C31850, C4190), the 2026-11-12 domestic ladders recorded in `legacy/bom-2026-11-13.md` (no international ladder read *(check)*). The 0R C21189 is now priced from v2's international read (a D price), not the 1R placeholder.
