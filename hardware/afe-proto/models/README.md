# SPICE models for the AFE prototype

**Status: model plan; no model libraries are currently present here.**
The libraries formerly under `hardware/afe-shield/models/` were removed
with that project. The corrected carrier is a physical/net reference;
it does not supply analog models for the new AFE circuit. Establish
these assets before running the [Stage A simulations](../sim/README.md).

## Candidate models and package mapping

| Planned circuit | Candidate part | Model work before use |
|---|---|---|
| U101, Stage A quad | MCP6024-E/P, socketed PDIP-14 candidate from the recipe | Obtain Microchip's MCP6021-family model; verify applicability to MCP6024, terminal order and limitations; instantiate four channels with the shared physical supply pins |
| D101, 3.0 V reference | LM4040AIM3-3.0/NOPB | Obtain the matching TI LM4040-N 3.0 V model; verify grade/tolerance interpretation and package terminal mapping |
| Alternative Stage A driver | To be selected if the candidate fails | Use the selected manufacturer's model, exact package mapping and power/load limits; rerun the same test suite |
| Stage C / Stage B | Parts selected during C1 / B1 | Add manufacturer models and ratings checks for amplifiers, switches, clamps and any inverter; mark unsupported behaviour explicitly |

The earlier design used MCP6024-E/SL, SOIC-14. The hand-build candidate is
MCP6024-E/P, PDIP-14. Verify physical pin numbering from the datasheet;
matching amplifier functionality does not make the footprints or package
parasitics interchangeable. Keep the footprint, socket and model mapping
recorded with the working schematic.

For the former MCP6021-family model, the channel terminals were
**+input, -input, +supply, -supply, output**. The former LM4040-N wrapper
mapped physical pins **1 cathode, 2 anode, 3 unused**. These are historical
adapter details to verify against the actual downloaded model and exact
ordered device, not a ready-to-use library. Use U101's physical quad pin
numbers in its adapter and preserve all four channels in integrated tests.

## Files to establish

Keep unchanged manufacturer files and license text under `models/vendor/`.
Put project-specific pin-order adapters in a separate `afe-models.lib`;
keep candidate adapters separate from the selected circuit model. These
paths are planned. Avoid embedding modified vendor text in the schematic.

For every model, record manufacturer, exact part/family and package,
original URL, retrieval date, model revision, SHA-256, license terms,
subcircuit terminal order, compatibility settings and supported effects.
The [reference manifest](../../../docs/reference/sources.json) retains
original download metadata, including the now-absent old model paths.
Restore or obtain required model files into this directory deliberately,
verify their bytes, and update the manifest with the actual new paths;
the old entries do not mean those files are available now. Datasheets and
model guidance remain in the [reference index](../../../docs/reference/README.md).

## Validate a model before testing the circuit

1. Read the model header and selected part's datasheet. Map each physical
   pin to each subcircuit terminal; check polarity and supply ordering.
2. Run a simple op-amp follower or reference-bias operating-point test at
   the intended supply, then a small transient. Check plausible voltage,
   current and load behaviour before using the complete stage.
3. Record ngspice version and any PSpice compatibility setting. Earlier
   models ran with ngspice 47 in PSpice mode; revalidate the new setup.
4. Record model omissions: independent channel instances do not represent
   package crosstalk or every shared-supply effect, and nominal models do
   not automatically include process spread, tolerance, noise or package
   inductance. Add explicit sensitivity cases where justified.

The former OPA4350 evaluation failed to establish an integrated operating
point. It is not an approved replacement or evidence of device instability.
Any renewed evaluation must first resolve model convergence, then compare
performance and power at identical conditions. A part change updates the
schematic, BOM, adapter, footprint and all affected simulations together.
