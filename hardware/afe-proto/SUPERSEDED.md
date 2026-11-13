# Files on main that the tooling does not yet fully replace

The other eleven scripts this list once carried were removed by the
commit "hardware: remove the scripts the pcbtools replace"; its body has
the file, replacement and proof for each.

| file on main | replaced by | why it stays |
|---|---|---|
| `kicad/route.py` | `docker/pcb/freeroute.sh` (Freerouting) | The replacement is a different router, not an equivalent port. `tests/test_freerouting.py` proves the Freerouting flow works end to end on a small board; nothing compares it with this grid router's output or covers its hand routes and GND vias on the v1 board. A frozen byte copy of the v2-era script is at `tests/fixtures/v2-8a1f7ac/tools/route.py`. Remove when the reviewed v1 routing is done by the new flow. |
