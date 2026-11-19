#!/bin/bash
# Break the rectangle pour on purpose and require tests/pcbtools/test_top_pour_rects.py (and test_stored_fill.py) to fail (PCB image, from hardware/afe-proto):
#   docker/pcb/run.sh -m 6g -t 3000 -c 4 bash -c 'cd hardware/afe-proto && bash tests/pcbtools/mutate_pour_rects.sh'
# Each mutant edits pcbtools/fill_clean.py or gndpads.py IN PLACE and restores it afterwards (also on an interrupt): do not run it beside another job that reads them. MUT_ONLY=regex.
set -u
cd "$(dirname "$0")/../.." || exit 2
declare -A M=(
  [old_top_zone_kept]="fill_clean.py|        elif z.GetLayer() == pcbnew.F_Cu and z.GetNetname().lstrip('/') == 'GND':|        elif False:"
  [keepouts_kept]="fill_clean.py|            if z.GetZoneName() in (KEEP_NAME, RECT_NAME):|            if z.GetZoneName() in (RECT_NAME,):"
  [orphans_kept]="fill_clean.py|    orphans = orphan_vias(src, rd)|    orphans = []"
  [orphan_inside_rect_removed]="fill_clean.py|        if _in_rect(x, y, rects, r):\n            continue\n|"
  [orphan_with_track_removed]="fill_clean.py#2|        if not tr and not pd:|        if not pd:"
  [orphan_with_pad_removed]="fill_clean.py#2|        if not tr and not pd:|        if not tr:"
  [pad_via_not_added]="fill_clean.py|gndpads.relocate(src, work, bad, add_missing=True)|gndpads.relocate(src, work, bad)"
  [pad_via_loop_off]="fill_clean.py|    for attempt in range(4):|    for attempt in range(0):"
  [stitch_off]="fill_clean.py|        stitch = rect_stitch(tmp, rd)|        stitch = []"
  [stitch_counts_nothing]="fill_clean.py|        have = [v for v in vias if _in_rect(v[0], v[1], [(x0, y0, x1, y1)], 0.3)]|        have = []"
  [stitch_spacing_ignored]="fill_clean.py#2|            work[max(0, rr - rad):rr + rad + 1, max(0, cc - rad):cc + rad + 1] = 0.0\n|            pass\n"
  [stitch_courtyards_ignored]="fill_clean.py|            if any(c[0] - court_margin <= x <= c[2] + court_margin and c[1] - court_margin <= y <= c[3] + court_margin for c in court):\n                work[max(0, rr - 20):rr + 21, max(0, cc - 20):cc + 21] = 0.0\n                continue\n            out.append((x, y))|            out.append((x, y))"
  [stitch_outside_rect]="fill_clean.py|        m[a0:a1, c0:c1] = r.mask[a0:a1, c0:c1]|        m = r.mask.copy()"
  [rect_zone_not_added]="fill_clean.py|            add_rect_zones(e, rects, clearance, spoke, gap, top_w)|            pass"
  [rect_in_wrong_frame]="fill_clean.py|    return [(x0 - FRAME[0], FRAME[1] - y1, x1 - FRAME[0], FRAME[1] - y0) for x0, y0, x1, y1 in rects]|    return [(x0 - FRAME[0], y0, x1 - FRAME[0], y1) for x0, y0, x1, y1 in rects]"
  [dispatch_off]="fill_clean.py|    if _rects:    |    if False:    "
  [project_not_required]="fill_clean.py|    if not os.path.exists(_pro):    |    if False:    "
)
fail=0
for name in "${!M[@]}"; do
  [[ -n "${MUT_ONLY:-}" && ! $name =~ $MUT_ONLY ]] && continue
  IFS='|' read -r file old new <<< "${M[$name]}"
  bak=$(mktemp); cp "pcbtools/${file%%#*}" "$bak"
  trap 'cp "$bak" "pcbtools/${file%%#*}"; rm -f "$bak"' EXIT INT TERM
  python3 - "pcbtools/$file" "$old" "$new" <<'PY' || { echo "MUTATION NOT APPLIED: $name"; fail=1; cp "$bak" "pcbtools/${file%%#*}"; rm -f "$bak"; continue; }
import sys
p, old, new = sys.argv[1:]
nth = 0
if '#' in p:
    p, nth = p.split('#'); nth = int(nth)
old, new = old.replace('\\n', '\n'), new.replace('\\n', '\n')
s = open(p).read()
if nth:
    assert s.count(old) >= nth, 'mutation site not found: ' + old
    i = -1
    for _ in range(nth):
        i = s.index(old, i + 1)
    open(p, 'w').write(s[:i] + new + s[i + len(old):])
else:
    assert s.count(old) == 1, 'mutation site not found exactly once: ' + old
    open(p, 'w').write(s.replace(old, new))
PY
  if python3 -m pytest -q -p no:cacheprovider tests/pcbtools/test_top_pour_rects.py tests/pcbtools/test_stored_fill.py >/dev/null 2>&1; then echo "SURVIVED  $name"; fail=1; else echo "killed    $name"; fi
  cp "$bak" "pcbtools/${file%%#*}"; rm -f "$bak"; trap - EXIT INT TERM
done
exit $fail
