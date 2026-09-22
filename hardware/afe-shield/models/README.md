# Manufacturer simulation models

`afe-models.lib` contains only pin-order adapters. The archives and extracted
files in `vendor/` are unchanged manufacturer downloads; keep their license
and disclaimer text. Source URLs, retrieval dates and SHA-256 hashes are in
[`docs/reference/sources.json`](../../../docs/reference/sources.json).

| schematic | exact selection | model |
|---|---|---|
| U1, all five units | MCP6024-E/SL, SOIC-14 | Four instances of Microchip MCP6021 family model, revision B, 2006-08-27 |
| D1 | LM4040AIM3-3.0/NOPB, A-grade, SOT-23 | TI LM4040_NA3P0, nominal TOL=0, 2013-04-10 |

U1 wrapper terminals are physical pins 1 through 14. Each Microchip instance
takes **+input, -input, +supply, -supply, output**. D1 wrapper terminals are
**cathode (1), anode (2), unused (3)**. On the selected LM4040-N, pin 3 may
float or connect to the anode; the schematic leaves it floating. The generic
KiCad LM4040DBZ symbol has the compatible pin layout; its library name alone
does not specify the ordered part. Use the schematic's MPN field.

Run with ngspice **PSpice compatibility**, `ngspice -n -D ngbehavior=ps`.
The unmodified files load in ngspice 47, including their PSpice TABLE syntax.
The wrapper's relative includes resolve from the model library directory.

These are behavioral models, not proof of accuracy, stability, distortion,
temperature performance or ADC settling on a physical board. The quad is
four independent channels, without a package-level crosstalk model. Nominal
models do not apply worst-case tolerance automatically. Microchip's included
license limits model use to Microchip products; do not substitute another
manufacturer's op-amp behind this model.

## Evaluation candidate, not an approved substitution

`candidates.lib` wraps TI's OPAx350 model 1.5 (2022-06-01) as a physical
SOIC-14 OPA4350. `vendor/ti/SBOM071.zip` and the extracted library retain
the original bytes and disclaimer. The SOIC-14 pin assignment agrees
with U1's current mapping; the SSOP-16 version does not use that mapping.

The integrated candidate screen has not established a valid operating
point in ngspice 47. Do not infer candidate performance from aborted
analyses or replace the active schematic model. The OPA4350 also requires
a power-budget review: its datasheet specifies 5.2 mA typical quiescent
current per amplifier, before output loading. The active BOM remains
MCP6024-E/SL. See [screening method](../sim/README.md).
