# 3D models carried by the project

KiCad 10's footprint `Package_QFP:TQFP-32_5x5mm_P0.5mm` names a model,
`TQFP-32_5x5mm_P0.5mm.step`, that KiCad's 3D library does not publish
(not in the installed library, not in kicad-packages3D master,
2026-11-11). U9 (ADS124S08, TQFP-32 PBS, 5 x 5 mm, 0.5 mm pitch) uses
the nearest published model instead. It has the same body outline and lead
pattern, and is taller (LQFP 1.4 mm body against TQFP's thinner one; the PBS
package's maximum height is not read *(check)*). It is for the 3D view and
fit only; the copper is the TQFP footprint's.

| file | source | sha256 | licence |
|---|---|---|---|
| LQFP-32_5x5mm_P0.5mm.step | https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/master/Package_QFP.3dshapes/LQFP-32_5x5mm_P0.5mm.step (fetched 2026-11-11) | 9f2be83a713ff62d2355f91718245c4e93f9a75ac14a804dc68810514dd9a3a3 | CC BY-SA 4.0 with the KiCad libraries' design exception, (C) 2025 KiCad; unmodified |

`build_pcb.py` assigns it through `MODEL_OVERRIDE` and refuses a file whose
hash differs.
