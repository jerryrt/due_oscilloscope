# Keeping the build image buildable

The firmware build image must build from nothing on any bench, years
after it was first built, and every image in use must be identifiable.
Neither held: `docker/build-image.sh` fails on a clean bench because
one input comes from a moving archive, and the tag names only the
compiler, so two different images can carry one name.

## Findings

| fact | evidence |
|---|---|
| A from-scratch build fails at the first `apt-get install` | the live Ubuntu archive offers `ca-certificates` 20260816ubuntu0.24.04.2 and 20240203; the pin `20260601~24.04.1` is no longer served there |
| The pinned version is still served by the dated snapshot | `snapshot.ubuntu.com/.../20260901T000000Z` lists `20260601~24.04.1` in noble-updates and noble-security |
| The live archive is needed only to obtain trust roots | the snapshot redirects to HTTPS, and the bare base image has no roots |
| Installing any current `ca-certificates`, switching to the snapshot, then installing the pinned version with `--allow-downgrades` ends at the pinned version | run in a clean container on the pinned base digest; `dpkg` reports `20260601~24.04.1` |
| The existing image is unaffected | it was built 2026-09-15 and is cached; only a rebuild fails |
| Nothing but the compiler version names an image | tag `due-build:15.2.1-1.1`; `.Id` is a build event, the content hash is not human-readable |

## What the certificate bundle can and cannot affect

It is used at build time for the HTTPS fetches from the snapshot and
from GitHub. Package contents are checked by apt against the Ubuntu
keyring and the compiler by a pinned SHA-256, so a stale bundle makes a
build fail loudly and cannot make it wrong. It does not touch a finished
image. The failure to expect is a server moving to a root the bundle
lacks.

## Decisions

| decision | reason |
|---|---|
| Bootstrap trust from the live archive unpinned, then pin from the snapshot | the final package set depends only on the snapshot, which does not expire |
| An image revision, `due-build:<xpack>-r<N>`, bumped by hand when the Dockerfile changes image content | the tag then says which image, not only which compiler |
| The image carries its recipe as labels: revision and the sha256 of the Dockerfile it was built from | a stale or foreign image is detected from inputs, which two benches can agree on, rather than from layer hashes, which they may not |
| `docker/image-revisions.json` records each revision: date, snapshot, base digest, Dockerfile hash, content hash | one place that answers which image a figure came from |
| `docker/run.sh` refuses an image whose Dockerfile-hash label differs from the tree's Dockerfile | the image would then not be the one this commit asks for |
| `docker/verify-image.sh` builds with `--no-cache` and compares firmware bytes from the new image against the recorded ones | bit-identical firmware is the property the image exists to give |
| Upgrade once a year, and run the verification monthly | a pin that stops resolving is found weeks before it is needed |

## Steps and gates

| step | change | gate |
|---|---|---|
| 1 | Dockerfile: bootstrap then snapshot pin | a `--no-cache` build completes and `dpkg` reports the pinned version |
| 2 | Revision tag, labels, manifest, `run.sh` check; a shared `docker/image-content.sh` | `run.sh` accepts the matching image and refuses a mutated Dockerfile hash, a missing row and a foreign tag |
| 3 | Measure whether two from-scratch builds agree | content hash of both reported; if they differ the check stays on the labels and the content hash is provenance only |
| 4 | Firmware from the new image against the old one | `track_b_bringup.bin` and the other tracks byte-identical; any difference is reported and blocks the other bench |
| 5 | Tests with mutants, docs, the upgrade procedure | each new guard fails when broken on purpose |
| 6 | Tell the other bench | after 1 to 5 are pushed to `main` |

## Measured

| question | answer |
|---|---|
| Does a from-scratch build reproduce the old content hash (`667e5767…`)? | No. Three builds of one recipe gave three layer hashes |
| Does it change the firmware? | No. The old image and two from-scratch builds give byte-identical firmware on all three tracks from one tree |
| What identifies an image across benches? | The recipe hash, not the layer hash |
| Does the old image still run? | Yes, accepted by name; the first image of the scheme is revision 1 |
