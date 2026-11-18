#!/bin/bash
# Break the track-geometry and fill-quality rules on purpose in a copy of the package and require the whole kit suite to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [angle_tolerance_ignored]="rules.py|_dev(ang[i], c.TRACK_ANGLE_STEP) > c.TRACK_ANGLE_TOL|_dev(ang[i], c.TRACK_ANGLE_STEP) > 0.0"
  [angle_tolerance_widened]="rules.py|_dev(ang[i], c.TRACK_ANGLE_STEP) > c.TRACK_ANGLE_TOL|_dev(ang[i], c.TRACK_ANGLE_STEP) > 5 * c.TRACK_ANGLE_TOL"
  [angle_step_fixed]="rules.py|_dev(ang[i], c.TRACK_ANGLE_STEP) > c.TRACK_ANGLE_TOL|_dev(ang[i], 45.0) > c.TRACK_ANGLE_TOL"
  [min_leg_ignored]="rules.py|glen[g] >= c.TRACK_MIN_LEG - 1e-9|True"
  [min_leg_fixed]="rules.py|glen[g] >= c.TRACK_MIN_LEG - 1e-9|glen[g] >= 0.6"
  [chain_not_merged]="rules.py|            parent[find(i)] = find(j)|            pass"
  [tee_is_a_bend]="rules.py|if len(lst) != 2 or lst[0][0] == lst[1][0]:|if len(lst) < 2 or lst[0][0] == lst[1][0]:"
  [pad_joint_is_a_bend]="rules.py|if len(pa['rows']) and (_in_pads(p, pa)[0] \& (pa['net'] == b.s_net[i])).any():|if False:"
  [via_joint_is_a_bend]="rules.py|if len(via_xy) and (np.hypot|if False and (np.hypot"
  [breakout_not_exempt]="rules.py|            if fine:|            if False:"
  [breakout_any_pitch]="rules.py|pitch.get(int(pa['fp'][h]), math.inf) <= c.TRACK_FINE_PITCH + 1e-9|True"
  [entry_y_axis_not_allowed]="rules.py|along_y = _dev(ang[i] - pa['rot'][h] - 90.0, 180.0) <= c.TRACK_ANGLE_TOL|along_y = False"
  [entry_x_axis_not_allowed]="rules.py|along_x = _dev(ang[i] - pa['rot'][h], 180.0) <= c.TRACK_ANGLE_TOL|along_x = False"
  [entry_corner_allowed]="rules.py|through = abs(v) + half <= pa['sy'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL|through = True"
  [entry_corner_allowed_y]="rules.py|through = abs(u) + half <= pa['sx'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL|through = True"
  [entry_track_width_ignored]="rules.py|through = abs(v) + half <= pa['sy'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL|through = abs(v) <= pa['sy'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL"
  [min_width_top_for_all]="rules.py|minw = float(c.FILL_MIN_WIDTH[lay]) if isinstance(c.FILL_MIN_WIDTH, dict) else float(c.FILL_MIN_WIDTH)|minw = float(c.FILL_MIN_WIDTH['F']) if isinstance(c.FILL_MIN_WIDTH, dict) else float(c.FILL_MIN_WIDTH)"
  [entry_round_pad_judged]="rules.py|if pa['shape'][h] == 0:|if False:"
  [entry_other_nets_judged]="rules.py|in_end[e_i] \& (pa['net'] == b.s_net[i]) \&|in_end[e_i] \&"
  [over_pad_own_part_judged]="rules.py|if int(pa['fp'][h]) in mine:|if False:"
  [over_pad_own_segment_ends_only]="rules.py|mine = run_fps[cfind(i)]|mine = {int(pa['fp'][q]) for q in np.flatnonzero(in_end[i])}"
  [over_pad_touching_counts]="rules.py|(M < -c.TRACK_OVERLAP_TOL)|(M <= c.TRACK_OVERLAP_TOL)"
  [over_pad_any_layer]="rules.py| \& ((pa['mask'][:, None] \& (1 << b.s_layer[blk][None, :].astype(int))) > 0)|"
  [thermal_inverted]="rules.py|and smd and conn != THERMAL:|and smd and conn == THERMAL:"
  [thermal_without_pads]="rules.py|if lay in c.FILL_THERMAL_LAYERS and smd and conn|if lay in c.FILL_THERMAL_LAYERS and conn"
  [thermal_through_hole_counts]="rules.py|if b.p_net[h] == gnd and b.p_smd[h] and|if b.p_net[h] == gnd and"
  [solid_ignored]="rules.py|and conn != SOLID:|and False:"
  [narrow_length_factor_off]="rules.py|minw, c.FILL_MIN_AREA, c.FILL_LENGTH_FACTOR)|minw, c.FILL_MIN_AREA, 0.0)"
  [dead_end_width_is_min_width]="rules.py|fills.thin_report(r_all, 0.0, c.FILL_DEAD_END_WIDTH,|fills.thin_report(r_all, 0.0, c.FILL_MIN_WIDTH,"
  [dead_end_every_finger]="rules.py|length_factor=c.FILL_LENGTH_FACTOR) if p.dead_end]|length_factor=c.FILL_LENGTH_FACTOR) if True]"
  [narrow_measured_with_net_items]="rules.py|r_fill = fills.net_copper(b, code, gnd, c.FILL_RASTER, with_net_items=False)|r_fill = fills.net_copper(b, code, gnd, c.FILL_RASTER, with_net_items=True)"
  [fill_layer_ignored]="rules.py|zs = [z for z in range(len(b.z_layer)) if b.z_layer[z] == code and b.z_net[z] == gnd|zs = [z for z in range(len(b.z_layer)) if b.z_net[z] == gnd"
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
  if PCBKIT_ROOT="$tmp" python3 -m pytest -q -p no:cacheprovider -c "$here/pytest.ini" "$here" >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  rm -rf "$tmp"
done
exit $fail
