#!/bin/bash
# Break each tool on purpose in a copy of the package and require test_tools.py to fail (run in the PCB image from hardware/pcbkit/tests).
set -u
here=$(cd "$(dirname "$0")" && pwd); kit=$(dirname "$here")
declare -A M=(
  [proof_ignores_via_drill]="proof.py|t.GetWidth(), t.GetDrill()|t.GetWidth(), 0"
  [proof_ignores_net]="proof.py|p.GetNumber(), p.GetNetname(), p.GetPosition().x|p.GetNumber(), '', p.GetPosition().x"
  [fab_keeps_the_plot_time]="fab.py|    t = data.decode('utf8', 'replace')|    return data\n    t = data.decode('utf8', 'replace')"
  [fab_accepts_any_outline]="fab.py|return [] if abs(w - width) <= tol and abs(h - height) <= tol|return []"
  [render_skips_the_missing_check]="render.py|if missing:\n        for r, f in missing:|if False:\n        for r, f in missing:"
  [ibom_keeps_the_noise]="ibom.py|if NOISE not in l|if True"
  [ibom_swallows_a_missing_plugin]="ibom.py|return 3, None,|return 0, None,"
  [pinlabels_ignores_the_frame]="pinlabels.py|return round(x + fr[0], 6), round(fr[1] - y, 6)|return round(x, 6), round(y, 6)"
  [pinlabels_ignores_the_height]="pinlabels.py|abs(th[hit[0]] - cfg.PIN_LABEL_H) > 1e-6|False"
)
fail=0
for name in "${!M[@]}"; do
  IFS='|' read -r file old new <<< "${M[$name]}"
  tmp=$(mktemp -d); cp -r "$kit/pcbkit" "$tmp/pcbkit"
  python3 - "$tmp/pcbkit/$file" "$old" "$new" <<'PY'
import sys
p, old, new = sys.argv[1:]
old, new = old.replace('\\n', '\n'), new.replace('\\n', '\n')
s = open(p).read()
assert s.count(old) == 1, 'mutation site not found exactly once: ' + old
open(p, 'w').write(s.replace(old, new))
PY
  [ $? -eq 0 ] || { echo "MUTATION NOT APPLIED: $name"; fail=1; continue; }
  if PCBKIT_ROOT="$tmp" python3 -m pytest -q -p no:cacheprovider -c "$here/pytest.ini" "$here/test_tools.py" >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  rm -rf "$tmp"
done
exit $fail
