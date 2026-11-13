# AFE tool bench

image `sha256:d59d5…` installed `a64aa4f285c5…` · machine jerry-x1gen7 · KiCad 10.0.8 · ngspice 45.2 · Python 3.14.4 · numpy 2.3.5 · 5 runs per step, first dropped by index · remeasured in a later run in the same image: new-v2-cap, new-v2-check, new-v2-check-mutate, new-v2-fence, old-v1-build_pcb, old-v1-check-pcb, old-v1-fence_check, old-v1-lr_check, old-v1-lr_check-mutate, old-v2-cap, old-v2-fence_check, old-v2-lr_check, old-v2-lr_check-mutate

| board | tool | status | wall median (s) | wall max (s) | peak RSS median (MB) | peak max (MB) |
|---|---|---|---|---|---|---|
| v1 | pcbnew-load | OK | 0.29 | 0.31 | 150 | 150 |
| v2-BASE | pcbnew-load | OK | 0.33 | 0.34 | 156 | 157 |
| v2-awg | pcbnew-load | OK | 0.34 | 0.35 | 156 | 157 |
| v2-integrated | pcbnew-load | OK | 0.33 | 0.33 | 155 | 155 |
| v2-power | pcbnew-load | OK | 0.33 | 0.35 | 156 | 157 |
| v2-power3 | pcbnew-load | OK | 0.34 | 0.35 | 156 | 156 |
| v2-refcal | pcbnew-load | OK | 0.34 | 0.35 | 156 | 157 |
| v2-scope2east | pcbnew-load | OK | 0.34 | 0.34 | 156 | 157 |
| v1 | boardio-read | OK | 0.38 | 0.40 | 168 | 169 |
| v2-BASE | boardio-read | OK | 0.46 | 0.49 | 175 | 175 |
| v2-awg | boardio-read | OK | 0.47 | 0.48 | 174 | 177 |
| v2-integrated | boardio-read | OK | 0.46 | 0.47 | 175 | 176 |
| v2-power | boardio-read | OK | 0.47 | 0.48 | 175 | 176 |
| v2-power3 | boardio-read | OK | 0.49 | 0.49 | 175 | 176 |
| v2-refcal | boardio-read | OK | 0.48 | 0.48 | 176 | 177 |
| v2-scope2east | boardio-read | OK | 0.47 | 0.49 | 174 | 175 |
| v1 | kicad-cli-step | OK | 2.65 | 2.74 | 203 | 204 |
| v2-BASE | kicad-cli-step | OK | 2.70 | 2.75 | 210 | 212 |
| v2-awg | kicad-cli-step | OK | 2.74 | 2.77 | 209 | 211 |
| v2-integrated | kicad-cli-step | OK | 2.70 | 2.73 | 210 | 211 |
| v2-power | kicad-cli-step | OK | 2.67 | 2.72 | 209 | 210 |
| v2-power3 | kicad-cli-step | OK | 2.67 | 2.82 | 210 | 211 |
| v2-refcal | kicad-cli-step | OK | 2.74 | 2.78 | 210 | 212 |
| v2-scope2east | kicad-cli-step | OK | 2.74 | 2.78 | 210 | 210 |
| v1 | kicad-cli-render | OK | 1.74 | 1.78 | 344 | 344 |
| v2-BASE | kicad-cli-render | OK | 2.46 | 2.48 | 363 | 364 |
| v2-awg | kicad-cli-render | OK | 2.44 | 2.47 | 362 | 363 |
| v2-integrated | kicad-cli-render | OK | 2.40 | 2.44 | 362 | 363 |
| v2-power | kicad-cli-render | OK | 2.46 | 2.48 | 364 | 364 |
| v2-power3 | kicad-cli-render | OK | 2.47 | 2.51 | 364 | 365 |
| v2-refcal | kicad-cli-render | OK | 2.46 | 2.49 | 365 | 366 |
| v2-scope2east | kicad-cli-render | OK | 2.48 | 2.50 | 363 | 364 |
| v1 | sexpr-parse | OK | 0.08 | 0.09 | 20 | 20 |
| v2-BASE | sexpr-parse | OK | 0.13 | 0.15 | 25 | 25 |
| v2-awg | sexpr-parse | OK | 0.13 | 0.13 | 25 | 25 |
| v2-integrated | sexpr-parse | OK | 0.13 | 0.13 | 24 | 25 |
| v2-power | sexpr-parse | OK | 0.13 | 0.13 | 25 | 25 |
| v2-power3 | sexpr-parse | OK | 0.13 | 0.15 | 25 | 25 |
| v2-refcal | sexpr-parse | OK | 0.13 | 0.14 | 25 | 25 |
| v2-scope2east | sexpr-parse | OK | 0.13 | 0.13 | 25 | 25 |
| v1 | editor-roundtrip | OK | 0.46 | 0.46 | 179 | 180 |
| v2-BASE | editor-roundtrip | OK | 0.62 | 0.62 | 192 | 192 |
| v2-awg | editor-roundtrip | OK | 0.61 | 0.63 | 190 | 193 |
| v2-integrated | editor-roundtrip | OK | 0.60 | 0.61 | 190 | 191 |
| v2-power | editor-roundtrip | OK | 0.62 | 0.63 | 192 | 193 |
| v2-power3 | editor-roundtrip | OK | 0.63 | 0.65 | 191 | 193 |
| v2-refcal | editor-roundtrip | OK | 0.63 | 0.64 | 193 | 193 |
| v2-scope2east | editor-roundtrip | OK | 0.63 | 0.63 | 191 | 192 |
| v1 | erc-v1-schematic | OK | 6.51 | 6.58 | 1333 | 1334 |
| - | ngspice-rc-ladder | OK | 0.17 | 0.18 | 32 | 32 |
| v1+v2 | netlib-text-v1v2 | OK | 0.10 | 0.11 | 35 | 35 |
| v1 | schematic-build-v1 | OK | 2.10 | 2.11 | 209 | 209 |
| v1 | board-build-v1 | OK | 4.18 | 4.23 | 231 | 231 |
| v1 | old-v1-build_pcb | OK | 4.32 | 4.44 | 231 | 232 |
| v1 | old-v1-check-pcb | OK | 44.18 | 44.20 | 1501 | 1521 |
| v1 | old-v1-lr_check | OK | 5.97 | 6.02 | 1440 | 1459 |
| v1 | old-v1-lr_check-mutate | OK | 12.12 | 12.35 | 1453 | 1463 |
| v1 | old-v1-fence_check | OK | 0.35 | 0.35 | 153 | 154 |
| v2-awg | old-v2-lr_check | OK | 6.95 | 7.09 | 1454 | 1466 |
| v2-awg | new-v2-check | OK | 0.88 | 0.88 | 177 | 179 |
| v2-integrated | old-v2-lr_check | OK | 6.87 | 6.97 | 1448 | 1482 |
| v2-integrated | new-v2-check | OK | 0.88 | 0.91 | 176 | 178 |
| v2-power | old-v2-lr_check | OK | 7.30 | 7.47 | 1462 | 1471 |
| v2-power | new-v2-check | OK | 0.93 | 0.94 | 178 | 179 |
| v2-power3 | old-v2-lr_check | OK | 7.31 | 7.40 | 1469 | 1475 |
| v2-power3 | new-v2-check | OK | 0.93 | 0.94 | 177 | 179 |
| v2-refcal | old-v2-lr_check | OK | 7.15 | 7.28 | 1450 | 1483 |
| v2-refcal | new-v2-check | OK | 0.93 | 0.94 | 178 | 178 |
| v2-scope2east | old-v2-lr_check | OK | 7.21 | 7.30 | 1446 | 1468 |
| v2-scope2east | new-v2-check | OK | 0.93 | 0.95 | 176 | 178 |
| v2-awg | old-v2-fence_check | OK | 0.45 | 0.46 | 163 | 164 |
| v2-awg | new-v2-fence | OK | 0.63 | 0.63 | 182 | 183 |
| v2-power | old-v2-fence_check | OK | 0.45 | 0.47 | 163 | 164 |
| v2-power | new-v2-fence | OK | 0.63 | 0.65 | 181 | 182 |
| v2-power3 | old-v2-fence_check | OK | 0.45 | 0.46 | 163 | 165 |
| v2-power3 | new-v2-fence | OK | 0.63 | 0.64 | 182 | 184 |
| v2-refcal | old-v2-fence_check | OK | 0.46 | 0.47 | 163 | 164 |
| v2-refcal | new-v2-fence | OK | 0.63 | 0.65 | 182 | 183 |
| v2-scope2east | old-v2-fence_check | OK | 0.46 | 0.48 | 162 | 163 |
| v2-scope2east | new-v2-fence | OK | 0.62 | 0.64 | 182 | 183 |
| v2-integrated | old-v2-cap | OK | 48.40 | 48.93 | 310 | 310 |
| v2-integrated | new-v2-cap | OK | 28.35 | 28.41 | 537 | 537 |
| v2-integrated | old-v2-lr_check-mutate | OK | 11.12 | 11.32 | 1440 | 1453 |
| v2-integrated | new-v2-check-mutate | OK | 1.03 | 1.04 | 178 | 179 |

## Old / new, interleaved

Measured alternately (old, new, old, new, ...) in one run so machine load hits both arms alike: **quote the ratios, not the absolute wall times** (those are from a loaded machine). Ratio = old / new, so above 1 the new tool is faster or smaller.

| board | old | new | wall ratio median (min–max) | peak RSS ratio |
|---|---|---|---|---|
| v2-awg | old-v2-lr_check | new-v2-check | 7.92 (7.89–8.15) | 8.21 |
| v2-integrated | old-v2-lr_check | new-v2-check | 7.77 (7.55–8.01) | 8.22 |
| v2-power | old-v2-lr_check | new-v2-check | 7.82 (7.68–8.03) | 8.21 |
| v2-power3 | old-v2-lr_check | new-v2-check | 7.78 (7.73–7.96) | 8.30 |
| v2-refcal | old-v2-lr_check | new-v2-check | 7.69 (7.53–7.74) | 8.16 |
| v2-scope2east | old-v2-lr_check | new-v2-check | 7.73 (7.59–7.85) | 8.20 |
| v2-awg | old-v2-fence_check | new-v2-fence | 0.71 (0.70–0.75) | 0.90 |
| v2-power | old-v2-fence_check | new-v2-fence | 0.71 (0.70–0.75) | 0.90 |
| v2-power3 | old-v2-fence_check | new-v2-fence | 0.72 (0.70–0.73) | 0.89 |
| v2-refcal | old-v2-fence_check | new-v2-fence | 0.73 (0.69–0.75) | 0.89 |
| v2-scope2east | old-v2-fence_check | new-v2-fence | 0.74 (0.72–0.76) | 0.89 |
| v2-integrated | old-v2-cap | new-v2-cap | 1.71 (1.69–1.73) | 0.58 |
| v2-integrated | old-v2-lr_check-mutate | new-v2-check-mutate | 10.80 (10.70–10.88) | 8.08 |
