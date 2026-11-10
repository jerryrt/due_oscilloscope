#!/bin/bash
# Does a recipe change leave the firmware alone?
#
#   docker/compare-revisions.sh OLD_COMMIT OLD_IMAGE
#
# verify-image.sh compares a from-scratch build with a reference of the SAME
# recipe. When the Dockerfile changes, run.sh refuses the old image for the
# new tree (its recipe label differs), so that check cannot span a change.
# This one can: it builds the three tracks at OLD_COMMIT, in a throwaway
# worktree, with OLD_IMAGE; builds the current tree with the current image;
# and compares the binaries.
#
# PASS: same sizes, and every differing byte lies inside a build-identity
# string, the short commit the tree was built at ("build=" and the Track C
# task name carry it). Anything else differing is a finding about the image,
# and is FAIL. DID NOT RUN: an image absent, a tree dirty (the identity then
# carries a delta hash this script does not model), or a build failed.
set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname "$here")
old=${1:?usage: compare-revisions.sh OLD_COMMIT OLD_IMAGE}
old_image=${2:?usage: compare-revisions.sh OLD_COMMIT OLD_IMAGE}
bins=(build/track_b_bringup.bin build-a/track_a_bringup.bin build-c/track_c_bringup.bin)

docker image inspect "$old_image" >/dev/null 2>&1 || { echo "DID NOT RUN: image $old_image is absent" >&2; exit 2; }
git -C "$root" rev-parse --verify -q "$old^{commit}" >/dev/null || { echo "DID NOT RUN: $old is not a commit" >&2; exit 2; }
[ -z "$(git -C "$root" status --porcelain)" ] || { echo "DID NOT RUN: the working tree is dirty" >&2; exit 2; }

wt=$(mktemp -d -t compare-revisions.XXXXXX)
trap 'git -C "$root" worktree remove --force "$wt" >/dev/null 2>&1; rm -rf "$wt"' EXIT
git -C "$root" worktree add -q --detach "$wt" "$old" || { echo "DID NOT RUN: no worktree at $old" >&2; exit 2; }

DUE_BUILD_IMAGE=$old_image "$wt/docker/run.sh" docker/build-firmware.sh >/dev/null ||
    { echo "DID NOT RUN: the build at $old with $old_image failed" >&2; exit 2; }
"$here/run.sh" docker/build-firmware.sh >/dev/null ||
    { echo "DID NOT RUN: the build of the current tree failed" >&2; exit 2; }

old_rev=$(git -C "$wt" rev-parse --short HEAD)
new_rev=$(git -C "$root" rev-parse --short HEAD)
python3 - "$wt/docker/out" "$here/out" "$old_rev" "$new_rev" "${bins[@]}" <<'PY'
import sys
a_dir, b_dir, old_rev, new_rev, *bins = sys.argv[1:]
old_rev, new_rev = old_rev.encode(), new_rev.encode()
bad = False
for b in bins:
    x = open("%s/%s" % (a_dir, b), "rb").read()
    y = open("%s/%s" % (b_dir, b), "rb").read()
    if len(x) != len(y):
        print("FAIL: %s is %d bytes against %d" % (b, len(x), len(y)))
        bad = True
        continue
    allowed = set()
    i = x.find(old_rev)
    while i >= 0:
        if y[i:i + len(new_rev)] == new_rev:
            allowed.update(range(i, i + len(old_rev)))
        i = x.find(old_rev, i + 1)
    diff = [i for i in range(len(x)) if x[i] != y[i]]
    stray = [i for i in diff if i not in allowed]
    print("%s: %d bytes, %d differ, %d outside the build identity" % (b, len(x), len(diff), len(stray)))
    bad = bad or bool(stray)
print("FAIL: firmware differs beyond the build identity" if bad
      else "PASS: %d firmware images equal but for the build identity" % len(bins))
sys.exit(1 if bad else 0)
PY
