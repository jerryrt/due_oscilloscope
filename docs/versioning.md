# Versioning

One project, one version, [Semantic Versioning 2.0.0](https://semver.org). The
version names a **release** of the whole tree: the Due firmware, the H7
firmware, the daemon and the GUI. It is typed once.

## What the number is, and is not

| number | what it answers | where it lives |
|---|---|---|
| **project version** `X.Y.Z` | which release is this | `lib/due_shared/src/fw_version.h` (`FW_VERSION_*`) |
| `FRAME_VERSION`, `FRAME16_VERSION`, `CTL_VERSION`, daemon `protocol` | will these two ends understand each other | their own headers; a host refuses a pairing on them |
| `build=` in the identity, `h7-build-N` | which exact image is on the board | the image itself (`docs/shared-source.md`) |

None substitutes for another. The project version says nothing about which
commit a board runs - `build=` does - and a wire version moving is a reason to
bump the project version, never the other way round. Everything that shows a
version derives it from the header: the identity line, `hello`'s `version`
(`host/version.py`), the tag. A second typed copy is the disagreement that
file exists to prevent.

## Rules

- **Pre-1.0 (`0.Y.Z`).** The instrument has a re-validation debt and an
  out-of-specification clock default, so it stays `0.x`. `1.0.0` needs those
  closed or named in the notes. While `0.x`, MINOR may break compatibility.
- **MINOR** (`0.Y.0`): a new capability or target, a changed default, or any
  change to a wire or protocol version. The notes say which.
- **PATCH** (`0.Y.Z`): fixes and measurement or documentation corrections that
  change no behaviour a client depends on.
- **MAJOR** (`X.0.0`, from 1.0): an incompatible change to a contract.

The header holds the **last released** version and changes only in the release
commit. Between releases, `build=` identifies what runs; the version does not.

## Releasing

1. All components say the release's version: `FW_VERSION_*` and the H7's
   `H7_FW_*` in `targets/h7tool/fw/ctl_h7.c`. The H7 may lag between releases;
   it may not at one. Bumping it is a firmware change, so rebuild and reflash
   that unit, and record its `h7-build-N`.
2. Build in the container, run the board-free tier, and run the smoke tier on
   the bench the notes will name.
3. `python3 tools/release.py check vX.Y.Z` - versions agree, the tag is free,
   the tree is clean and at the commit to be tagged.
4. Annotated tag `vX.Y.Z` on that commit on `main`.
5. `python3 tools/release.py sums <the container's output directory>` writes `SHA256SUMS`; attach it,
   the three Due images, `build-env.json` and, when it changed, the H7 image.
6. GitHub release: **title is the tag, `vX.Y.Z`** - the sidebar shows about 25
   characters and cuts a sentence. The headline is the first line of the notes.

Notes use fixed headings: *Highlights*, *Compatibility* (wire and protocol
versions, MCK default and any out-of-specification warning), *Measured* (every
figure with its bench and date), *Not yet measured / known failures*, *Upgrade
notes*, and the commit and `build=` string.

## History

`v0.2.0` is the release first published as `release-2026-10-31-mck90`: its
images say `fw=0.2.0`. That tag name predates this rule and was retired.
