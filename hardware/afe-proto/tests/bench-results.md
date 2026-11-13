# AFE tool bench

image `sha256:d59d5…` installed `a64aa4f285c5…` · machine jerry-x1gen7 · KiCad 10.0.8 · ngspice 45.2 · Python 3.14.4 · numpy 2.3.5 · 5 runs per step, first dropped by index

| board | tool | status | wall median (s) | wall max (s) | peak RSS median (MB) | peak max (MB) |
|---|---|---|---|---|---|---|
| v1 | pcbnew-load | OK | 0.29 | 0.31 | 149 | 150 |
| v2-BASE | pcbnew-load | OK | 0.34 | 0.34 | 156 | 156 |
| v2-awg | pcbnew-load | OK | 0.34 | 0.34 | 156 | 157 |
| v2-integrated | pcbnew-load | OK | 0.33 | 0.33 | 155 | 155 |
| v2-power | pcbnew-load | OK | 0.34 | 0.35 | 156 | 157 |
| v2-power3 | pcbnew-load | OK | 0.34 | 0.35 | 156 | 156 |
| v2-refcal | pcbnew-load | OK | 0.33 | 0.34 | 157 | 157 |
| v2-scope2east | pcbnew-load | OK | 0.33 | 0.35 | 157 | 157 |
| v1 | boardio-read | OK | 0.53 | 0.56 | 168 | 170 |
| v2-BASE | boardio-read | OK | 0.59 | 0.63 | 176 | 177 |
| v2-awg | boardio-read | OK | 0.59 | 0.60 | 175 | 175 |
| v2-integrated | boardio-read | OK | 0.58 | 0.60 | 177 | 178 |
| v2-power | boardio-read | OK | 0.60 | 0.61 | 175 | 176 |
| v2-power3 | boardio-read | OK | 0.60 | 0.64 | 175 | 176 |
| v2-refcal | boardio-read | OK | 0.58 | 0.59 | 175 | 176 |
| v2-scope2east | boardio-read | OK | 0.59 | 0.61 | 176 | 177 |
| v1 | kicad-cli-step | OK | 2.56 | 2.58 | 204 | 205 |
| v2-BASE | kicad-cli-step | OK | 2.63 | 2.67 | 210 | 211 |
| v2-awg | kicad-cli-step | OK | 2.61 | 2.68 | 209 | 211 |
| v2-integrated | kicad-cli-step | OK | 2.67 | 2.67 | 209 | 211 |
| v2-power | kicad-cli-step | OK | 2.67 | 2.70 | 211 | 212 |
| v2-power3 | kicad-cli-step | OK | 2.64 | 2.71 | 211 | 211 |
| v2-refcal | kicad-cli-step | OK | 2.70 | 2.74 | 211 | 211 |
| v2-scope2east | kicad-cli-step | OK | 2.64 | 2.67 | 210 | 212 |
| v1 | kicad-cli-render | OK | 1.73 | 1.74 | 344 | 344 |
| v2-BASE | kicad-cli-render | OK | 2.45 | 2.45 | 364 | 365 |
| v2-awg | kicad-cli-render | OK | 2.44 | 2.47 | 363 | 364 |
| v2-integrated | kicad-cli-render | OK | 2.40 | 2.43 | 364 | 364 |
| v2-power | kicad-cli-render | OK | 2.43 | 2.49 | 363 | 365 |
| v2-power3 | kicad-cli-render | OK | 2.47 | 2.49 | 364 | 365 |
| v2-refcal | kicad-cli-render | OK | 2.45 | 2.46 | 366 | 366 |
| v2-scope2east | kicad-cli-render | OK | 2.47 | 2.50 | 363 | 364 |
| v1 | sexpr-parse | OK | 0.09 | 0.09 | 19 | 20 |
| v2-BASE | sexpr-parse | OK | 0.13 | 0.13 | 25 | 25 |
| v2-awg | sexpr-parse | OK | 0.13 | 0.13 | 24 | 25 |
| v2-integrated | sexpr-parse | OK | 0.13 | 0.14 | 24 | 25 |
| v2-power | sexpr-parse | OK | 0.13 | 0.14 | 25 | 25 |
| v2-power3 | sexpr-parse | OK | 0.13 | 0.14 | 25 | 25 |
| v2-refcal | sexpr-parse | OK | 0.13 | 0.14 | 25 | 25 |
| v2-scope2east | sexpr-parse | OK | 0.13 | 0.13 | 25 | 25 |
| v1 | editor-roundtrip | OK | 0.61 | 0.63 | 179 | 180 |
| v2-BASE | editor-roundtrip | OK | 0.77 | 0.80 | 192 | 193 |
| v2-awg | editor-roundtrip | OK | 0.78 | 0.79 | 192 | 192 |
| v2-integrated | editor-roundtrip | OK | 0.74 | 0.78 | 192 | 192 |
| v2-power | editor-roundtrip | OK | 0.76 | 0.78 | 190 | 192 |
| v2-power3 | editor-roundtrip | OK | 0.80 | 0.81 | 192 | 193 |
| v2-refcal | editor-roundtrip | OK | 0.79 | 0.80 | 193 | 194 |
| v2-scope2east | editor-roundtrip | OK | 0.78 | 0.80 | 191 | 192 |
| v1 | erc-v1-schematic | OK | 6.58 | 6.62 | 1332 | 1333 |
| - | ngspice-rc-ladder | OK | 0.30 | 0.34 | 32 | 32 |
| v1+v2 | netlib-text-v1v2 | OK | 0.27 | 0.28 | 35 | 35 |
