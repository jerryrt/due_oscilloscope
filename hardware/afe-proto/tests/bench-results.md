# AFE tool bench (PROVISIONAL: locally built r3, not the pulled digest)

image `c3fcbf1aeb95…` installed `a64aa4f285c5…` · machine jerry-x1gen7 · KiCad 10.0.8 · ngspice 45.2 · Python 3.14.4 · numpy 2.3.5 · 5 runs per step, first dropped by index

| board | tool | status | wall median (s) | wall max (s) | peak RSS median (MB) | peak max (MB) |
|---|---|---|---|---|---|---|
| v1 | pcbnew-load | OK | 0.29 | 0.30 | 150 | 150 |
| v2-BASE | pcbnew-load | OK | 0.35 | 0.36 | 156 | 158 |
| v2-awg | pcbnew-load | OK | 0.33 | 0.34 | 156 | 156 |
| v2-integrated | pcbnew-load | OK | 0.33 | 0.34 | 155 | 156 |
| v2-power | pcbnew-load | OK | 0.34 | 0.35 | 156 | 157 |
| v2-power3 | pcbnew-load | OK | 0.35 | 0.35 | 156 | 157 |
| v2-refcal | pcbnew-load | OK | 0.34 | 0.38 | 156 | 157 |
| v2-scope2east | pcbnew-load | OK | 0.34 | 0.35 | 156 | 157 |
| v1 | boardio-read | OK | 0.52 | 0.55 | 168 | 170 |
| v2-BASE | boardio-read | OK | 0.61 | 0.65 | 175 | 176 |
| v2-awg | boardio-read | OK | 0.60 | 0.63 | 175 | 176 |
| v2-integrated | boardio-read | OK | 0.59 | 0.60 | 176 | 178 |
| v2-power | boardio-read | OK | 0.59 | 0.60 | 176 | 177 |
| v2-power3 | boardio-read | OK | 0.60 | 0.60 | 176 | 177 |
| v2-refcal | boardio-read | OK | 0.59 | 0.61 | 176 | 178 |
| v2-scope2east | boardio-read | OK | 0.59 | 0.60 | 174 | 177 |
| v1 | kicad-cli-step | OK | 2.55 | 2.56 | 203 | 205 |
| v2-BASE | kicad-cli-step | OK | 2.61 | 2.64 | 210 | 212 |
| v2-awg | kicad-cli-step | OK | 2.64 | 2.64 | 210 | 211 |
| v2-integrated | kicad-cli-step | OK | 2.60 | 2.65 | 209 | 211 |
| v2-power | kicad-cli-step | OK | 2.64 | 2.69 | 210 | 210 |
| v2-power3 | kicad-cli-step | OK | 2.64 | 2.68 | 210 | 211 |
| v2-refcal | kicad-cli-step | OK | 2.63 | 2.72 | 210 | 211 |
| v2-scope2east | kicad-cli-step | OK | 2.67 | 2.69 | 210 | 211 |
| v1 | kicad-cli-render | OK | 1.73 | 1.75 | 344 | 345 |
| v2-BASE | kicad-cli-render | OK | 2.43 | 2.46 | 364 | 365 |
| v2-awg | kicad-cli-render | OK | 2.43 | 2.44 | 364 | 364 |
| v2-integrated | kicad-cli-render | OK | 2.40 | 2.46 | 363 | 364 |
| v2-power | kicad-cli-render | OK | 2.47 | 2.47 | 364 | 364 |
| v2-power3 | kicad-cli-render | OK | 2.43 | 2.47 | 363 | 365 |
| v2-refcal | kicad-cli-render | OK | 2.42 | 2.47 | 364 | 366 |
| v2-scope2east | kicad-cli-render | OK | 2.47 | 2.53 | 363 | 364 |
| v1 | erc-v1-schematic | OK | 6.75 | 6.88 | 1333 | 1334 |
| - | ngspice-rc-ladder | OK | 0.29 | 0.30 | 32 | 32 |
| v1+v2 | netlib-text-v1v2 | OK | 0.27 | 0.29 | 35 | 35 |
