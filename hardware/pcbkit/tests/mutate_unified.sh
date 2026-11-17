#!/bin/bash
# Break each shared check on purpose in a copy of the package and require its tests to fail (PCB image, from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [two_way_ignores_the_margin]="rules.py|if dp + m > dq + eps and|if False and"
  [two_way_step2_dropped]="rules.py|if own + m > do + eps and|if False and"
  [anchor_kinds_ignored]="rules.py|(kinds[p] != 'P' and kinds[q] != kinds[p])|False"
  [baseline_threshold]="rules.py|> 0.5 * min(ya1 - ya0, yb1 - yb0)|> 5.0 * min(ya1 - ya0, yb1 - yb0)"
  [stray_rule_dropped]="outlines.py|    if ref in strays:|    if False:"
  [edge_part_not_free]="outlines.py|    if not outline or block not in outline:|    if not outline:"
  [outline_crossing_unseen]="outlines.py|                probs.append('segment %s crosses something|                pass; _x = ('segment %s crosses something"
  [outline_break_clearance]="outlines.py|g0 > lo_min - bc + tol|False"
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
  if PCBKIT_ROOT="$tmp" python3 -m pytest -q -p no:cacheprovider -c "$here/pytest.ini" "$here/test_unified_checks.py" "$here/test_labels.py" >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  rm -rf "$tmp"
done
exit $fail
