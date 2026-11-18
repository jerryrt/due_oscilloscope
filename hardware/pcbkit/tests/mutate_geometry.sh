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
  [exc_stale_allowed]="rules.py|        if len(hit) != 1:|        if len(hit) == 0:"
  [exc_net_ignored]="rules.py|if kind != rule or len(t) < 2 or t[1].lstrip('/') != str(net).lstrip('/'):|if kind != rule:"
  [exc_rule_ignored]="rules.py|if kind != rule or len(t) < 2 or|if len(t) < 2 or"
  [exc_place_radius_huge]="rules.py|return math.hypot(x - where[0], y - where[1]) <= 0.5|return True"
  [exc_ref_prefix_any]="rules.py|(w.startswith(where + '.') and '.' not in where)|w.startswith(where)"
  [exc_reason_not_needed]="rules.py|if len(e) != 4 or not str(e[3]).strip():|if len(e) != 4:"
  [exc_not_applied]="rules.py|    out = [f for f in out if id(f) not in gone]|    pass"
  [reach_ignored]="rules.py|if not fine and c.TRACK_BREAKOUT_REACH > 0 and len(pa['rows']):|if False:"
  [reach_any_net]="rules.py|for h in np.flatnonzero((pa['net'] == b.s_net[s]) \& (np.array(|for h in np.flatnonzero((pa['net'] >= 0) \& (np.array("
  [reach_any_pitch]="rules.py|(np.array([pitch.get(int(f), math.inf) for f in pa['fp']]) <= c.TRACK_FINE_PITCH + 1e-9)):|(np.array([pitch.get(int(f), math.inf) for f in pa['fp']]) <= 9e9)):"
  [reach_infinite]="rules.py|if (np.hypot(E[:, 0] - pa['cx'][h], E[:, 1] - pa['cy'][h]) <= c.TRACK_BREAKOUT_REACH).any():|if True:"
  [rough_layers_ignored]="rules.py|        if lay in c.FILL_ROUGH_LAYERS:|        if False:"
  [rough_link_ignored_rule]="rules.py|link=c.FILL_ROUGH_LINK)|link=2.0)"
  [rough_tol_ignored_rule]="rules.py|tol=c.FILL_ROUGH_TOL, link|tol=0.15, link"
  [rough_not_counted_in_ok]="rules.py|    kinds = ('narrow', 'dead_end', 'rough', 'thermal', 'solid')|    kinds = ('narrow', 'dead_end', 'thermal', 'solid')"
  [pads_one_per_pin]="rules.py|    r = np.arange(len(b.p_x))\n    return dict(rows=r|    r = pads(b).rows\n    return dict(rows=r"
  [dangling_tolerance_extra]="rules.py|pad_dist(p, h) <= w / 2 + 1e-9|pad_dist(p, h) <= w / 2 + 0.1"
  [dangling_center_only]="rules.py|pad_dist(p, h) <= w / 2 + 1e-9|pad_dist(p, h) <= 1e-9"
  [dangling_any_net_pad]="rules.py|for h in np.flatnonzero((pa['net'] == net) \& ((pa['mask'] \& (1 << layer)) > 0)):|for h in np.flatnonzero(((pa['mask'] \& (1 << layer)) > 0)):"
  [dangling_via_ignored]="rules.py|return bool(len(via_xy) and (np.hypot(via_xy[:, 0] - p[0], via_xy[:, 1] - p[1]) <= b.v_dia / 2 + w / 2 + 1e-9)[b.v_net == net].any())|return False"
  [dangling_track_ignored]="rules.py|            if len(at[k]) < 2:|            if True:"
  [turn_limit_ignored]="rules.py|        if at_ and turn > c.TRACK_MAX_TURN + c.TRACK_ANGLE_TOL:|        if False:"
  [turn_window_infinite]="rules.py|if d0 - 1e-9 <= d <= d0 + c.TRACK_TURN_WINDOW + 1e-9]|if d0 - 1e-9 <= d]"
  [turn_not_through_junction]="rules.py|                    parent2[find2(lst[a_][0])] = find2(lst[b_][0])|                    pass"
  [ratio_ignored]="rules.py|if length >= c.TRACK_DETOUR_MIN_LEN and length > c.TRACK_DETOUR_RATIO * short + 1e-6:|if False:"
  [ratio_min_len_ignored]="rules.py|if length >= c.TRACK_DETOUR_MIN_LEN and length > c.TRACK_DETOUR_RATIO * short + 1e-6:|if length > c.TRACK_DETOUR_RATIO * short + 1e-6:"
  [octile_as_euclid]="rules.py|    return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)|    return math.hypot(dx, dy)"
  [spur_min_ignored]="rules.py|            if ln < c.TRACK_SPUR_MIN - 1e-9:|            if False:"
  [spur_angle_ignored]="rules.py|            if min(abs(a - 90.0), abs(a - 45.0), abs(a - 135.0)) > c.TRACK_ANGLE_TOL:|            if False:"
  [spur_clear_ignored]="rules.py|            if nd < c.TRACK_SPUR_CLEAR - 1e-9:|            if False:"
  [spur_other_junctions_ignored]="rules.py|[(q[2] / 1000, q[3] / 1000) for q, l2 in juncs.items() if q != k and any(orig[i2] == o for i2, _ in l2)]|[]"
  [junction_at_bend_ignored]="rules.py|        if trunk is None:|        if False:"
  [wide_limit_ignored]="rules.py|            if lim is not None and b.s_w[i] > lim + c.TRACK_WIDTH_TOL:|            if False:"
  [wide_star_ignored]="rules.py|rules_w.get(nm.lstrip('/'), rules_w.get('*'))|rules_w.get(nm.lstrip('/'))"
  [wide_tol_ignored]="rules.py|b.s_w[i] > lim + c.TRACK_WIDTH_TOL|b.s_w[i] > lim"
  [reach_stops_at_collinear]="rules.py|            if cosang < math.cos(math.radians(c.TRACK_ANGLE_TOL)):|            if True:"
  [reach_never_stops]="rules.py|            if cosang < math.cos(math.radians(c.TRACK_ANGLE_TOL)):|            if False:"
  [cap_tap_ignored]="rules.py|                    if geom.seg_seg_dist(S0[j0:j0 + 1], np.array([[p[0], p[1], p[0], p[1]]]))[0, 0] <= wid[i] / 2 + b.s_w[j0] / 2 + 1e-9:|                    if False:"
  [cap_tap_body_only]="rules.py|                if d > b.s_w[i] / 2 + b.s_w[j] / 2 + 1e-9:|                if d > b.s_w[j] / 2 + 0.005:"
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
