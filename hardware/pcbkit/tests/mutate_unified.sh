#!/bin/bash
# Break each shared check on purpose in a copy of the package and require its tests to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [two_way_margin_zero]="rules.py|    return d_own + margin > d_other + eps|    return d_own > d_other + eps"
  [two_way_eps_sign]="rules.py|    return d_own + margin > d_other + eps|    return d_own + margin > d_other - eps"
  [two_way_never_too_near]="rules.py|    return d_own + margin > d_other + eps|    return False"
  [anchor_kinds_ignored]="rules.py|(kinds[p] != 'P' and kinds[q] != kinds[p])|False"
  [kind_first_prefix]="rules.py|if ref.startswith(p) and len(p) > len(best):|if ref.startswith(p):"
  [step1_not_nearest]="rules.py|min(s1, key=lambda f: f[0]) if s1 else None|s1[-1] if s1 else None"
  [step2_not_nearest]="rules.py|min(s2, key=lambda f: f[0]) if s2 else None|s2[-1] if s2 else None"
  [baseline_threshold]="rules.py|> 0.5 * min(ya1 - ya0, yb1 - yb0)|> 5.0 * min(ya1 - ya0, yb1 - yb0)"
  [region_margin_plus_eps]="outlines.py|covered(_grow(label, margin - eps), mine)|covered(_grow(label, margin + eps), mine)"
  [region_margin_zero]="outlines.py|covered(_grow(label, margin - eps), mine)|covered(_grow(label, 0.0), mine)"
  [stray_rule_dropped]="outlines.py|    if ref in strays:|    if False:"
  [edge_part_not_free]="outlines.py|    if not outline or block not in outline:|    if not outline:"
  [outline_crossing_unseen]="outlines.py|                probs.append('segment %s crosses something|                pass; _x = ('segment %s crosses something"
  [outline_break_clearance]="outlines.py|g0 > lo_min - bc + tol|False"
  [bnc_text_own_label]="labels/placer.py|labels.setdefault(key[3:], []).append(box)|labels.setdefault(key, []).append(box)"
  [skip_part_not_attributed]="labels/placer.py|who = p_ if p_ not in skip else x[1]|who = p_"
  [skip_part_step1_judged]="labels/placer.py|        if p_ not in skip:|        if True:"
  [search_read_margin_zero]="labels/placer.py|rules.too_near(d_own, min(G.gap(L, b) for b in s.solid[o]), c.READ_MARGIN, c.EPS)|rules.too_near(d_own, min(G.gap(L, b) for b in s.solid[o]), 0.0, c.EPS)"
)
fail=0
for name in "${!M[@]}"; do
  IFS='|' read -r file old new <<< "${M[$name]}"
  tmp=$(mktemp -d); cp -r "$kit/pcbkit" "$tmp/pcbkit"
  python3 - "$tmp/pcbkit/$file" "$old" "$new" <<'PY' || { echo "MUTATION NOT APPLIED: $name"; fail=1; rm -rf "$tmp"; continue; }
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) == 1, 'mutation site not found exactly once: ' + old
open(p, 'w').write(s.replace(old, new))
PY
  if PCBKIT_ROOT="$tmp" python3 -m pytest -q -p no:cacheprovider -c "$here/pytest.ini" "$here" >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  rm -rf "$tmp"
done
exit $fail
