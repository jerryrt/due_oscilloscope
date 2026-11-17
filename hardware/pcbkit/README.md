# pcbkit

Checks and silk tools for a two-layer KiCad 10 board, driven by one configuration per board. Nothing here names a net, a part
or a coordinate of any particular design; a project supplies those in its configuration and keeps any rule that only makes
sense for its own circuit in its own tree. The AFE shield (`hardware/afe-proto`) is the first user: its `pcbtools` keeps
the rules that read its channels, reference and generator, and imports everything else from here.

The package imports nothing outside itself except numpy, scipy and, for reading a board, pcbnew. It is meant to be copied or
installed into another repository as it stands.

## What it holds

| module | purpose |
|---|---|
| `board` | read a `.kicad_pcb` into arrays (footprints, pads, tracks, vias, zones, texts), with the project's coordinate frame from the configuration |
| `geom` | the numpy and scipy kernels the checks share: distances between segments, boxes and points, rectangles, polygons |
| `rules` | the general layout rules, each a function `(board, cfg) -> Result` (table below) |
| `labels` | designator placement and the readability test: one search order, anchors first, the two-way nearest test |
| `outlines` | block rectangles: membership, named strays, breaks where a line would cross a pad or footprint silk |
| `pinlabels` | header pin names printed beside a socket, from a pin table |
| `fab` | the fabrication set (Gerbers, drills, BOM, CPL) as one deterministic zip and its manifest |
| `ibom` | the interactive HTML BOM through the pinned InteractiveHtmlBom |
| `render` | board renders that refuse to run while any 3D model file is missing |
| `proof` | "nothing moved": hashes of footprints, pads, tracks, vias and zones, and a netlist comparison |

## The general rules

| rule | what it checks | configuration it reads |
|---|---|---|
| `ground_plane` | one plane on the given layer; every SMD ground pad has its own via | `GND`, `PLANE_LAYER` |
| `bottom_hops` | signal copper on the plane layer is short hops only, outside the fenced areas, never under a sensitive net | `HOP_MAX`, `HOP_MAX_VIAS`, `FENCES`, `SENSITIVE` |
| `sensitive_nets` | the listed nets: no via, length limit, no foreign track beside them within a gap | `SENSITIVE` (net, max length, gap) |
| `pour_gap` | no copper pour within a distance of the listed nodes | `POUR_NODES`, `POUR_KEEP_BACK` |
| `keepout_ring` | listed nets stay a distance from listed parts | `KEEPOUT_RINGS` |
| `decoupling` | each listed capacitor within a distance of its IC pin | `DECOUPLING` |
| `blocks` | each block's parts inside its rectangle, named strays excepted, no part inside another block's | `BLOCK`, `OUTLINE`, `OUTLINE_STRAYS` |
| `designators` | the always-labelled kinds are on silk; every other designator is on silk and reads without doubt, or is on the fab layer | `SILK_REQUIRED_PREFIXES`, `DESIGNATOR_MIN_H`, `READ_MARGIN` |
| `test_points` | each listed block has a test point on its listed net | `TEST_BLOCKS`, `TP_NETS` |

"Reads without doubt" is the two-way nearest test: from the text, its own part is nearer than any other part, and from the
part, its own text is nearer than any other text, both by `READ_MARGIN`, measured to bodies and pads; a part of an
always-labelled kind is compared only with its own kind.

## Configuration

A configuration is a Python module or a mapping of upper-case names. `CONFIG.md` lists every name, its type, its unit and
which rule reads it; a rule that needs a name the configuration does not set is not run and says so, never a silent pass.

## Tests

Every rule is tested on boards built in the test from footprints of KiCad's own library, with no project file, and every
test of a rule breaks the board once on purpose and watches the rule fail.

## Status

Skeleton. The modules are being moved out of `hardware/afe-proto/pcbtools` one at a time; until a module is listed as moved
in `MIGRATION.md`, the AFE copy is the one in use.
