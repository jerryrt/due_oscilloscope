#!/bin/bash
# Break pcbkit.reroute on purpose in a copy of the package and require the whole kit suite to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [legs_unconstrained]="reroute.py|if run < (1 if (first and start_exempt) else N):|if run < 1:"
  [final_leg_unconstrained]="reroute.py|(first or run >= N or goal_exempt)|True"
  [no_clearance]="reroute.py|clear + safety + hw, hw + 0.05, False|hw, hw + 0.05, False"
  [own_pads_not_blocked]="reroute.py|_pad_poly(pa, h, m_own if own else m_other)|_pad_poly(pa, h, 0.0 if own else m_other)"
  [entry_lateral_x_ignored]="reroute.py|(np.abs(v) + hwx <= sy2 + entry_tol)|True"
  [entry_lateral_y_ignored]="reroute.py|(np.abs(u) + hwx <= sx2 + entry_tol)|True"
  [entry_any_direction]="reroute.py|if rules._dev(ang - pa['rot'][h], 180.0) <= 0.01:|if True:"
  [spur_has_no_goal]="reroute.py|goal_masks, goal_exempt = {d: own for d in range(8)}, False|goal_masks, goal_exempt = {d: np.zeros((H, W), bool) for d in range(8)}, False"
  [tap_not_recognised]="reroute.py|<= b.s_w[q] / 2 + 1e-3:|<= -1.0:"
  [other_nets_pads_overlapped]="reroute.py|(pa['net'] == chain.net) \\& ((pa['mask'] \\& (1 << chain.layer)) > 0)):|((pa['mask'] \\& (1 << chain.layer)) > 0)):"
  [end_pads_overlapped]="reroute.py|            if int(h) not in skip:|            if True:"
  [no_neck_down]="reroute.py|if not any(v.any() for v in m.values()) and hw > MIN_WIDTH / 2 + 1e-9:|if False:"
  [neck_not_recorded]="reroute.py|LAST_NECKS.append((which, e.pad))|pass"
  [neck_start_not_cut]="reroute.py|cuts.add(min(neck_len, L))|cuts.add(L)"
  [neck_goal_not_cut]="reroute.py|cuts.add(max(L - neck_len, 0.0))|cuts.add(0.0)"
  [neck_width_is_track_width]="reroute.py|out.append((at(a0), at(b0), MIN_WIDTH if narrow else width))|out.append((at(a0), at(b0), width))"
  [chain_not_followed]="reroute.py|                cur, kk = nxt[0], kn|                cur, kk = cur, kn"
)
#!/bin/bash
# Break the track-geometry and fill-quality rules on purpose in a copy of the package and require the whole kit suite to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
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
