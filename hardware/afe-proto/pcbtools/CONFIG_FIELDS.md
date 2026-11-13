# Board configuration fields (the shapes of `pcbtools/boards/v2.py`, canonical)

A board config is a module (or any object, e.g. `types.SimpleNamespace`) with these module-level names. `rules.py`, `check.py`,
`drc.py`, `fence.py`, `cap.py` contain no reference designator and no net name: every ref / net / pin the rules use is one of the
fields below (`tests/pcbtools/test_no_board_literals.py` enforces it). Net names are written as KiCad writes them, with the leading
`/`. A pad is `(ref, pin)` (pin a string). v1 converts its data to these shapes; there is no second shape.
Fields marked NEW were added (or reshaped) when the hard-coded literals left `rules.py`; the rest existed.

## Generic ground and nets

| field | type | v2 example | used by |
|---|---|---|---|
| `GND` NEW | net name | `'/GND'` | LR-1, LR-3, LR-4, LR-7, cap |
| `ADC_NETS` NEW | tuple of net, in report order | `('/A0', '/A1')` | LR-4 (no via, no bottom copper, lengths): the nets that reach the Due's ADC pins |
| `SENSITIVE` | tuple of net-name PREFIXES | `('/A0', '/A1', '/VREF', ...)` | LR-5 |
| `XSENS` | tuple of net-name prefixes | `('/A0', '/AREF', ...)` | LR-1 (bottom copper forbidden under) |
| `DIGITAL` | tuple of net | `('/SDA', '/SCL')` | LR-9 |
| `INV_NODES` | tuple of net | `('/AWG_FB', '/CH1_N', '/CH2_N')` | LR-4 no via / no bottom copper |
| `INV_LEN_NODES` | tuple of net | `('/AWG_FB', '/CH1_OUT', '/CH2_OUT')` | LR-4 INV_MAX |
| `POUR_NODES` / `POUR_INFO_NODES` | tuple of net | `('/AWG_FB',)` / `('/CH1_OUT', '/CH2_OUT')` | LR-4 pour keep-back: judged / reported only. See the reading below |
| `HIZ` CHANGED | tuple of net (now with the `/`) | `('/CH1_N', '/CH1_M1', ...)` | LR-3 (it was names without the `/`) |

`POUR_NODES` reading (LR-4): the rule keeps the top ground pour back (at least 0.5 mm) from the stage's inverting node, the shortest
trace of the stage. That is an inverting input with gain resistors, which on v2 is `/AWG_FB` only, so `POUR_NODES = ('/AWG_FB',)`.
The first port judged `INV_NODES` (`/AWG_FB`, `/CH1_N`, `/CH2_N`), the set the old no-via / no-bottom-copper rule used, which was
the wrong set for the pour rule: `/CHn_N` are divider nodes governed by LR-3, which asks the high-impedance sides to be guarded by
grounded copper (pour near them is wanted; LR-3's test is the extracted capacitance, `CAP_SELF` and `CAP_PAIRS`), and a follower's
inverting pin is tied to its output `/CHn_OUT`, the low-impedance node LR-4 covers through the total capacitance behind it (Riso /
stability budget), not by a keep-back. `POUR_INFO_NODES` (`/CHn_OUT`) keeps reporting its gaps and is not judged.

## Scope channels: `CHANNELS` (CHANGED: a tuple of dicts, one per channel)

Used by LR-2 (flow, output side vs divider side, channel separation) and LR-4 (output resistor at the output pin).

| key | type | v2 example (CH1) |
|---|---|---|
| `name` | str, printed in messages | `'CH1'` |
| `bnc` | pad: the BNC signal pad | `('J101', '1')` |
| `prot` | ref: first protection resistor | `'R101'` |
| `rnp` | ref: the resistor into the +IN node | `'R107'` |
| `opamp` | ref | `'U101'` |
| `riso` | ref: series isolation resistor | `'R108'` |
| `out_pin` | pad: the op-amp output pin `riso` must sit at | `('U101', '7')` |
| `adc_pad` | pad: the Due ADC header pad | `('J602', '7')` |
| `out_nets` | tuple of net: the output side, summed (LR-2) | `('/A1', '/CH1_OUT')` |
| `hiz_nets` | tuple of net: the divider side, summed (LR-2) | `('/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP')` |

`DIVIDER_GROUPS` NEW (tuple of tuple of net): the channels' divider-side nets, one group per channel; the pads of different groups
west of `DIVIDER_X_MAX` are kept 5 mm apart (LR-2), `(('/CH1_N', '/CH1_NP', '/CH1_IN'), ('/CH2_N', '/CH2_NP', '/CH2_IN'))`.
`CH_FLOW_TEXT` NEW (str): the flow order printed by LR-2, `'BNC > R1 > Rnp > U101 > Riso > ADC pad'`.

## AWG: `AWG` NEW (one dict)

Used by LR-4 (the feedback node) and LR-7 (output run, back-termination, shell).

| key | type | v2 example |
|---|---|---|
| `name` | str | `'AWG'` |
| `dac_net` | net: the DAC output | `'/DAC0'` |
| `fb_net` | net: the op-amp inverting node | `'/AWG_FB'` |
| `back_term` | tuple of ref: back-termination resistors | `('R301', 'R302')` |
| `bnc` | ref | `'J301'` |
| `shell_pin` | str: the BNC shell pin (its pads must be on `GND`) | `'2'` |

`FEED_PAD` NEW (pad): the Due 5 V feed the generator sits by, `('J601', '5')`. `BNC_REFS` NEW (tuple of ref, order printed):
every BNC the generator must be 50 mm from, `('J101', 'J201', 'J301')`. `QUIET_REFS` NEW (tuple of ref): the reference / ladder /
precision-ADC parts kept `KEEPOUT` from the generator, `('U501', 'U502', 'R501', 'R506')`. `GEN` (tuple of ref): the generator IC and
its flying capacitor, `('U401', 'C409')`; `GENERATOR_BLOCK` (set of ref): parts excused from LR-5.

## Decoupling

| field | type | v2 example |
|---|---|---|
| `DECOUP` CHANGED | list of `(cap, ic, pin)` (it was a dict cap -> (ic, pin)) | `[('C104', 'U101', '8'), ('C105', 'U101', '8'), ...]` (LR-12) |
| `SUPPLY_CAPS` NEW | list of `(cap, ic, pin)`: the LR-4 "each supply pin has its 100 nF" subset | `[('C104', 'U101', '8'), ('C305', 'U301', '8'), ('C306', 'U301', '4')]` |
| `DECOUP_MAX` | mm | `3.0` |

## Rails and the reference (LR-6, LR-8)

| field | type | v2 example |
|---|---|---|
| `GROUPS` | `{rail net: {group name: set of ref}}`: consumer groups per rail | `{'/+3V3A': {'scope': {'U101', ...}, 'awg': {...}, 'adc': {...}}, '/VNEG_G': {'awg': {...}}}` |
| `STAR` | `{rail net: [pad, ...]}`: the star pads | `{'/+3V3A': [('U401', '11'), ('C405', '1'), ...]}` |
| `BRIDGES` | list of `(ref, net a, net b)`: the 0 ohm parts; nets they join are one electrical net | `[('BR101', '/+3V3A_S', '/+3V3A_U'), ...]` (from `design.BRIDGES`) |
| `BRIDGE_PADS` | list of `(ref, pin, ref, pin)`: extra pad joins | `[('BR101', '1', 'BR101', '2')]` |
| `RAIL_TEXT` NEW | str printed when LR-6 passes | `'+3V3A and VNEG'` |
| `VREF_NET` NEW | net | `'/VREF'` |
| `VREF_SOURCE` CHANGED | list of pad (it was `['U501.2', ...]`) | `[('U501', '2'), ('C501', '1')]` |
| `VREF_BRANCHES` CHANGED | list of branches, each a list of pad | `[[('J602', '1')], [('U502', '4')], ..., [('R106', '2'), ('R509', '2'), ('BR503', '1')]]` |

## Blocks, silk, fences (LR-11, fence)

`BLOCK` `{ref: block}`, `BLOCK_OVERRIDE`, `ANALOG_BLOCKS`, `ANALOG_REFS` (set of ref), `ANALOG_FENCE` (tuple of block), `OUTLINE`
`{block: [rect, ...]}`, `LR_HUNDREDS` `{digit: block}`, `TEST_BLOCKS`, `TP_NETS` `{test point ref: net}`, `SILK_WORDS`,
`DESIGNATOR_MIN_H`, `FENCES`, `HUNDREDS`, `OWNER_OVERRIDE`, `TOL_MM`, `ZONE_PAD`. NEW: `TP_PREFIX` (`'TP'`: a ref starting with it is
a test point), `EDGE_BLOCK` (`'EDGE'`: the block with no outline of its own), `TP_PIN` (`'1'`).

## Thresholds and the rest

`HOP_MAX`, `HOP_MAX_VIAS`, `KEEPOUT`, `FB_MAX`, `INV_MAX`, `DIVIDER_X_MAX` (mm / counts, as v2). `CAP_PAIRS`, `CAP_SELF`: the
capacitance windows `(label, nets, pad, cell)` / `(net, pad, cell)`; v2's `CAP_SELF` holds `/AWG_FB` and the divider nodes `/CH1_N`,
`/CH2_N` (LR-3's N-to-everything stray, no pour and with pour), all at 0.1 mm: their windows are about 7.6 x 9 mm and 2.5 s each, far under `cap.MAX_CELLS`, so 0.2 mm was not needed. NEW `DRC_ARM` (dict): where the LR-10 mutation arm puts its
0.1 mm track, `{'ref': 'R101', 'pin': '1', 'net': '/CH1_N'}`.

## Schematic projects (`schematic.py`, `schematic_rows.py`, `spicecmp.py`; the shapes of `boards/v2_sch.py` and `boards/v2_checks.py`)

`schematic.write_all` reads `PROJECT`, `NS`, `BLOCK_ORDER`, `BLOCK_TITLE`, `PWR_FLAG_NETS`, `TITLE`, `REV`, `COMMENTS`,
`PROJECT_SYMBOLS`, `ERC_EXCLUSIONS(pin_at, uid, root)`, `SYMBOL_DIR`, and optionally `PROPS` (the hidden fields, `((part key, field
name), ...)`), `FLAG_BLOCK`, `CHECK_NC`, `LIB_GENERATOR`, `FP_LIB_TABLE`. The rows read, besides schematic_check's: `ERC_EXCLUDED`,
`MIN_NETS`, `MIN_COMPS`, `MIN_SPICE_ELEMENTS`, `COMPARE_FIELDS` `((netlist field, part key), ...)`, `FOOTPRINT_DIR`, `PROJECT_LIB_NAME`,
`FITTED_BY_BOARD_HOUSE`, `DATASHEET_PINS` `{library part: {pin: name}}`, `BLOCKDIGIT`, `KEY_PARTS`, `ROW_IDS`
(`{'numbering': (id, id), 'bridge': id}`), `BRIDGE_JOINS` `{bridge ref: (end, end)}`, `BRIDGE_SIDES` `[(end, end)]`, `BRIDGE_TEXT` (an end is
`('pin', ref, pin)` or `('fn', ref, pin name)`), `HEADER_TABLE` `{header value: {pin: net}}`, `HEADER_BLOCK`, `HEADER_PART_PREFIX`,
`HEADER_LABEL`. `spicecmp` reads `SPICE_RULES` `{block: {anchors, drop, short, esr, derate?, subckt_models}}`, `SPICE_BLOCKS`,
`BRIDGE_PREFIX`, `DIODE_PAIR_LIBS`, `AMP_LIBS`, `SPICE_IGNORE_LIBS`, `SPICE_IGNORE_VALUES`. A board's own rows and arms (v2's power and
calibration rows, its 24 arms) live in its own module and are `FlipArm`s.
