# AFE tool bench

image `sha256:39517…` installed `0b8f08a358c5…` · machine montreal5 · KiCad 10.0.8 · ngspice 45.2 · Python 3.14.4 · numpy 2.3.5 · 5 runs per step, first dropped by index · remeasured in a later run in the same image: new-v1-check, new-v1-check-mutate, new-v2-awg, new-v2-cap, new-v2-check, new-v2-check-mutate, new-v2-fence, new-v2-schematic-build, new-v2-schematic-check, new-v2-scope, old-v1-lr_check, old-v1-lr_check-mutate, old-v2-awg, old-v2-build_sch, old-v2-cap, old-v2-fence_check, old-v2-lr_check, old-v2-lr_check-mutate, old-v2-schematic-check, old-v2-scope

| board | tool | status | wall median (s) | wall max (s) | peak RSS median (MB) | peak max (MB) |
|---|---|---|---|---|---|---|
| v1 | pcbnew-load | OK | 0.29 | 0.29 | 111 | 112 |
| v2-BASE | pcbnew-load | OK | 0.33 | 0.35 | 118 | 118 |
| v2-awg | pcbnew-load | OK | 0.33 | 0.34 | 118 | 118 |
| v2-integrated | pcbnew-load | OK | 0.33 | 0.34 | 118 | 118 |
| v2-power | pcbnew-load | OK | 0.34 | 0.34 | 118 | 118 |
| v2-power3 | pcbnew-load | OK | 0.34 | 0.35 | 118 | 118 |
| v2-refcal | pcbnew-load | OK | 0.34 | 0.36 | 119 | 119 |
| v2-scope2east | pcbnew-load | OK | 0.33 | 0.34 | 118 | 118 |
| v1 | boardio-read | OK | 0.39 | 0.39 | 127 | 127 |
| v2-BASE | boardio-read | OK | 0.47 | 0.48 | 133 | 133 |
| v2-awg | boardio-read | OK | 0.46 | 0.47 | 132 | 133 |
| v2-integrated | boardio-read | OK | 0.45 | 0.46 | 133 | 133 |
| v2-power | boardio-read | OK | 0.47 | 0.47 | 133 | 133 |
| v2-power3 | boardio-read | OK | 0.46 | 0.47 | 134 | 134 |
| v2-refcal | boardio-read | OK | 0.46 | 0.47 | 133 | 134 |
| v2-scope2east | boardio-read | OK | 0.46 | 0.47 | 133 | 133 |
| v1 | kicad-cli-step | OK | 2.47 | 2.52 | 159 | 159 |
| v2-BASE | kicad-cli-step | OK | 2.52 | 2.54 | 166 | 166 |
| v2-awg | kicad-cli-step | OK | 2.53 | 2.55 | 166 | 166 |
| v2-integrated | kicad-cli-step | OK | 2.51 | 2.52 | 165 | 166 |
| v2-power | kicad-cli-step | OK | 2.54 | 2.54 | 166 | 166 |
| v2-power3 | kicad-cli-step | OK | 2.52 | 2.54 | 166 | 167 |
| v2-refcal | kicad-cli-step | OK | 2.53 | 2.54 | 167 | 167 |
| v2-scope2east | kicad-cli-step | OK | 2.53 | 2.55 | 165 | 166 |
| v1 | kicad-cli-render | OK | 1.70 | 1.72 | 306 | 306 |
| v2-BASE | kicad-cli-render | OK | 2.39 | 2.40 | 326 | 326 |
| v2-awg | kicad-cli-render | OK | 2.37 | 2.38 | 326 | 326 |
| v2-integrated | kicad-cli-render | OK | 2.36 | 2.37 | 326 | 326 |
| v2-power | kicad-cli-render | OK | 2.36 | 2.39 | 326 | 327 |
| v2-power3 | kicad-cli-render | OK | 2.37 | 2.43 | 326 | 327 |
| v2-refcal | kicad-cli-render | OK | 2.39 | 2.40 | 328 | 328 |
| v2-scope2east | kicad-cli-render | OK | 2.38 | 2.39 | 326 | 326 |
| v1 | sexpr-parse | OK | 0.08 | 0.08 | 17 | 17 |
| v2-BASE | sexpr-parse | OK | 0.12 | 0.13 | 22 | 22 |
| v2-awg | sexpr-parse | OK | 0.12 | 0.13 | 22 | 22 |
| v2-integrated | sexpr-parse | OK | 0.12 | 0.12 | 22 | 22 |
| v2-power | sexpr-parse | OK | 0.12 | 0.12 | 22 | 22 |
| v2-power3 | sexpr-parse | OK | 0.12 | 0.12 | 22 | 22 |
| v2-refcal | sexpr-parse | OK | 0.12 | 0.13 | 23 | 23 |
| v2-scope2east | sexpr-parse | OK | 0.12 | 0.12 | 22 | 22 |
| v1 | editor-roundtrip | OK | 0.45 | 0.45 | 132 | 132 |
| v2-BASE | editor-roundtrip | OK | 0.59 | 0.61 | 144 | 145 |
| v2-awg | editor-roundtrip | OK | 0.59 | 0.60 | 144 | 145 |
| v2-integrated | editor-roundtrip | OK | 0.58 | 0.58 | 143 | 144 |
| v2-power | editor-roundtrip | OK | 0.60 | 0.61 | 144 | 145 |
| v2-power3 | editor-roundtrip | OK | 0.60 | 0.61 | 145 | 145 |
| v2-refcal | editor-roundtrip | OK | 0.60 | 0.60 | 145 | 145 |
| v2-scope2east | editor-roundtrip | OK | 0.59 | 0.60 | 144 | 145 |
| v1 | erc-v1-schematic | OK | 6.53 | 6.55 | 1299 | 1299 |
| - | ngspice-rc-ladder | OK | 0.16 | 0.16 | 25 | 25 |
| v1+v2 | netlib-text-v1v2 | OK | 0.10 | 0.10 | 27 | 27 |
| v1 | old-v1-build_pcb | OK | 4.29 | 4.33 | 193 | 193 |
| v1 | old-v1-check-pcb | OK | 44.13 | 44.32 | 1433 | 1449 |
| v1 | old-v1-fence_check | OK | 0.34 | 0.35 | 117 | 117 |
| v1 | schematic-build-v1 | OK | 1.86 | 1.89 | 204 | 204 |
| v1 | board-build-v1 | OK | 3.98 | 4.04 | 193 | 193 |
| v1 | sim-v1-scope-dc | OK | 20.92 | 20.92 | 38 | 39 |
| v2 | sim-v2-powercal | OK | 15.20 | 15.42 | 110 | 110 |
| v2-awg | old-v2-lr_check | OK | 7.12 | 7.20 | 1413 | 1425 |
| v2-awg | new-v2-check | OK | 0.99 | 1.00 | 137 | 138 |
| v2-integrated | old-v2-lr_check | OK | 6.99 | 7.02 | 1388 | 1401 |
| v2-integrated | new-v2-check | OK | 0.97 | 0.99 | 137 | 137 |
| v2-power | old-v2-lr_check | OK | 7.30 | 7.32 | 1403 | 1422 |
| v2-power | new-v2-check | OK | 1.10 | 1.10 | 137 | 138 |
| v2-power3 | old-v2-lr_check | OK | 7.30 | 7.38 | 1410 | 1436 |
| v2-power3 | new-v2-check | OK | 1.11 | 1.11 | 138 | 138 |
| v2-refcal | old-v2-lr_check | OK | 7.19 | 7.24 | 1400 | 1419 |
| v2-refcal | new-v2-check | OK | 1.12 | 1.13 | 138 | 138 |
| v2-scope2east | old-v2-lr_check | OK | 7.29 | 7.32 | 1402 | 1425 |
| v2-scope2east | new-v2-check | OK | 1.10 | 1.11 | 138 | 138 |
| v2-awg | old-v2-fence_check | OK | 0.43 | 0.44 | 129 | 130 |
| v2-awg | new-v2-fence | OK | 0.59 | 0.62 | 143 | 144 |
| v2-power | old-v2-fence_check | OK | 0.44 | 0.44 | 129 | 129 |
| v2-power | new-v2-fence | OK | 0.60 | 0.61 | 143 | 145 |
| v2-power3 | old-v2-fence_check | OK | 0.45 | 0.46 | 129 | 130 |
| v2-power3 | new-v2-fence | OK | 0.61 | 0.62 | 144 | 145 |
| v2-refcal | old-v2-fence_check | OK | 0.44 | 0.44 | 129 | 130 |
| v2-refcal | new-v2-fence | OK | 0.60 | 0.61 | 144 | 145 |
| v2-scope2east | old-v2-fence_check | OK | 0.44 | 0.45 | 128 | 130 |
| v2-scope2east | new-v2-fence | OK | 0.60 | 0.61 | 143 | 144 |
| v2-integrated | old-v2-cap | OK | 65.01 | 65.04 | 273 | 274 |
| v2-integrated | new-v2-cap | OK | 41.77 | 41.95 | 523 | 523 |
| v2-integrated | old-v2-lr_check-mutate | OK | 10.44 | 10.53 | 1409 | 1422 |
| v2-integrated | new-v2-check-mutate | OK | 2.39 | 2.41 | 137 | 137 |
| v2-sch | old-v2-schematic-check | OK | 168.13 | 168.61 | 1298 | 1298 |
| v2-sch | new-v2-schematic-check | OK | 210.15 | 212.09 | 1298 | 1298 |
| v2-sch | old-v2-build_sch | OK | 2.58 | 2.60 | 193 | 193 |
| v2-sch | new-v2-schematic-build | OK | 2.15 | 2.16 | 200 | 200 |
| v1 | old-v1-lr_check | OK | 6.15 | 6.19 | 1396 | 1414 |
| v1 | new-v1-check | OK | 6.56 | 6.61 | 1394 | 1404 |
| v1 | old-v1-lr_check-mutate | OK | 12.42 | 12.68 | 1400 | 1420 |
| v1 | new-v1-check-mutate | OK | 7.14 | 7.19 | 1364 | 1389 |
| - | old-v2-awg | OK | 20.88 | 21.00 | 95 | 96 |
| - | new-v2-awg | OK | 21.48 | 21.58 | 97 | 97 |
| - | old-v2-scope | OK | 91.81 | 92.87 | 207 | 207 |
| - | new-v2-scope | OK | 87.04 | 88.30 | 86 | 86 |

## Old / new, interleaved

Measured alternately (old, new, old, new, ...) in one run so machine load hits both arms alike: **quote the ratios, not the absolute wall times**. Load, as measured: 1-minute load average 1.14 before and 1.14 after the last run on 8 CPUs (montreal5). Ratio = old / new, so above 1 the new tool is faster or smaller.

| board | old | new | wall ratio median (min–max) | peak RSS ratio |
|---|---|---|---|---|
| v2-awg | old-v2-lr_check | new-v2-check | 7.26 (7.03–7.27) | 10.28 |
| v2-integrated | old-v2-lr_check | new-v2-check | 7.19 (7.08–7.24) | 10.11 |
| v2-power | old-v2-lr_check | new-v2-check | 6.64 (6.63–6.65) | 10.22 |
| v2-power3 | old-v2-lr_check | new-v2-check | 6.61 (6.51–6.67) | 10.25 |
| v2-refcal | old-v2-lr_check | new-v2-check | 6.42 (6.37–6.43) | 10.17 |
| v2-scope2east | old-v2-lr_check | new-v2-check | 6.64 (6.53–6.69) | 10.19 |
| v2-awg | old-v2-fence_check | new-v2-fence | 0.73 (0.69–0.75) | 0.90 |
| v2-power | old-v2-fence_check | new-v2-fence | 0.73 (0.72–0.75) | 0.90 |
| v2-power3 | old-v2-fence_check | new-v2-fence | 0.75 (0.72–0.75) | 0.89 |
| v2-refcal | old-v2-fence_check | new-v2-fence | 0.73 (0.72–0.75) | 0.89 |
| v2-scope2east | old-v2-fence_check | new-v2-fence | 0.73 (0.72–0.75) | 0.90 |
| v2-integrated | old-v2-cap | new-v2-cap | 1.55 (1.55–1.56) | 0.52 |
| v2-integrated | old-v2-lr_check-mutate | new-v2-check-mutate | 4.39 (4.31–4.41) | 10.29 |
| v2-sch | old-v2-schematic-check | new-v2-schematic-check | 0.80 (0.79–0.80) | 1.00 |
| v2-sch | old-v2-build_sch | new-v2-schematic-build | 1.20 (1.19–1.21) | 0.97 |
| v1 | old-v1-lr_check | new-v1-check | 0.94 (0.93–0.94) | 1.00 |
| v1 | old-v1-lr_check-mutate | new-v1-check-mutate | 1.76 (1.73–1.78) | 1.03 |
| - | old-v2-awg | new-v2-awg | 0.97 (0.96–0.98) | 0.98 |
| - | old-v2-scope | new-v2-scope | 1.06 (1.03–1.08) | 2.41 |
