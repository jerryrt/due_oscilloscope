/*
 * Which track this image is, and nothing else.
 *
 * The one fact about a firmware image that is legitimately per-track,
 * so it is the one thing left with a copy in each track's own tree.
 * Everything else that used to live beside it in version.h is now one
 * shared file, lib/due_shared/src/fw_version.h, which includes this.
 *
 * 'A' = arduino-cli reference oracle, 'B' = CMake bare metal.
 * This copy is Track B: CMake bare metal.
 *
 * See docs/shared-source.md for where the boundary is drawn and why.
 */
#ifndef TRACK_ID_H
#define TRACK_ID_H

#define FW_TRACK 'B'

#endif /* TRACK_ID_H */
