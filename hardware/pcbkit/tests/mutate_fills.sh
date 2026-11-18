#!/bin/bash
# Break each part of pcbkit.fills on purpose in a copy of the package and require its tests to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [opening_radius_doubled]="fills.py|core = edt >= r_px|core = edt >= 2 * r_px"
  [opening_radius_halved]="fills.py|core = edt >= r_px|core = edt >= r_px / 2"
  [no_growing_back]="fills.py|grown = ndi.distance_transform_edt(~core) <= r_px|grown = core"
  [min_area_ignored]="fills.py|for i in np.flatnonzero(areas >= min_area):|for i in range(n):"
  [holes_not_cleared]="fills.py|zm = draw(outl, 1).astype(bool) \& ~draw(hol, 1).astype(bool) if hol else draw(outl, 1).astype(bool)|zm = draw(outl, 1).astype(bool)"
  [lower_limit_ignored]="fills.py|if p.width < lo - 1e-9:|if False:"
  [dead_end_never]="fills.py|p.dead_end = len(ids) <= 1|p.dead_end = False"
  [dead_end_always]="fills.py|p.dead_end = len(ids) <= 1|p.dead_end = True"
  [anchors_not_counted]="fills.py|ids.update(('a', int(i)) for i in a)|pass"
  [thick_regions_not_counted]="fills.py|ids = {('t', int(i)) for i in ids}|ids = set()"
  [other_nets_tracks_anchor]="fills.py|(b.s_net == net) \& (b.s_layer == layer)|(b.s_layer == layer)"
  [other_nets_pads_anchor]="fills.py|rows = np.flatnonzero(b.p_net == net) if len(b.p_net) else np.zeros(0, np.int64)|rows = np.arange(len(b.p_net))"
  [covered_fraction_zero]="fills.py|out[('pad', int(i))] = bool(sub.size and sub.mean() >= frac)|out[('pad', int(i))] = bool(sub.size and sub.mean() >= 0.0)"
  [layer_ignored]="fills.py|if b.z_layer[z] == layer and b.z_net[z] == net|if b.z_net[z] == net"
  [unfilled_zone_counts]="fills.py|and b.z_filled[z] and not b.z_keepout[z]|and not b.z_keepout[z]"
  [keep_grid_ignored]="fills.py|return (np.floor(v / grid + 1e-9) if lo else np.ceil(v / grid - 1e-9)) * grid|return v"
  [keep_outline_snap_off]="fills.py|c = [t for t in cand if abs(t - v) <= snap]|c = []"
  [keep_bounds_ignored]="fills.py|if bounds is not None:|if False:"
  [keep_extra_ignored]="fills.py|        res = res | extra|        pass"
  [keep_ratio_merges_all]="fills.py|if (u[2] - u[0]) * (u[3] - u[1]) > fill_ratio * have + 1e-9:|if False:"
  [poly_no_diagonal]="fills.py|        if m >= 4:                                              # at least two full steps|        if False:"
  [poly_hole_ignored]="fills.py|if len(loops) == 1 and len(outer) == 1:|if True:"
  [poly_snap_bends_diagonals]="fills.py|if any(diag(i) or diag((i - 1) % n) for i in idx):|if False:"
  [poly_grid_offset_dropped]="fills.py|    ox, oy = int(round((r.x0 - xo) * k)), int(round((yo - r.y1) * k))|    ox, oy = 0, 0"
  [rough_single_counts]="fills.py|        if len(g) < 2:|        if len(g) < 1:"
  [rough_reach_ignored]="fills.py|if (near \& rp.mask[win[0]:win[2], win[1]:win[3]]).any():|if True:"
  [rough_link_ignored]="fills.py|if np.hypot(max(A[0] - B[2], B[0] - A[2], 0), max(A[1] - B[3], B[1] - A[3], 0)) <= link:|if np.hypot(max(A[0] - B[2], B[0] - A[2], 0), max(A[1] - B[3], B[1] - A[3], 0)) <= 1e9:"
)
fail=0
for name in "${!M[@]}"; do
  IFS='|' read -r file old new <<< "${M[$name]}"
  tmp=$(mktemp -d); cp -r "$kit/pcbkit" "$tmp/pcbkit"
  python3 - "$tmp/pcbkit/$file" "$old" "$new" <<'PY' || { echo "MUTATION NOT APPLIED: $name"; fail=1; rm -rf "$tmp"; continue; }
import sys
p, old, new = sys.argv[1:]
old, new = old.replace('\\&', '\x26'), new.replace('\\&', '\x26')
s = open(p).read()
assert s.count(old) == 1, 'mutation site not found exactly once: ' + old
open(p, 'w').write(s.replace(old, new))
PY
  if PCBKIT_ROOT="$tmp" python3 -m pytest -q -p no:cacheprovider -c "$here/pytest.ini" "$here/test_fills.py" >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  rm -rf "$tmp"
done
exit $fail
