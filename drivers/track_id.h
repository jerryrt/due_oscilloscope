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

/*
 * Guarded, because a track must not be decided by include-path
 * proximity.
 *
 * drivers/ctl_port.c does `#include "track_id.h"` and lives in
 * drivers/, so the compiler finds drivers/track_id.h first - even
 * when the image being built is a different track that links that
 * same file. Track C hit exactly that: its console reported
 * track=C from apps/rtos_bringup/track_id.h while its CONTROL
 * CHANNEL reported track=b from this one, and CLAUDE.md's rule is
 * that a deployed board is asked over the control channel. A
 * board that answers "which firmware are you" two ways is the
 * defect FW_VERSION_STR already taught this project once.
 *
 * So the build may state it, and a -DFW_TRACK wins over whichever
 * header the include path happened to reach.
 */
#ifndef FW_TRACK
#define FW_TRACK  'B'
#endif

#endif /* TRACK_ID_H */
