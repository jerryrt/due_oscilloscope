/*
 * Which track this image is, and nothing else.
 *
 * The one fact about a firmware image that is legitimately per-track,
 * so it is the one thing left with a copy in each track's own tree -
 * three of them: this one, drivers/track_id.h, and
 * apps/rtos_bringup/track_id.h. Everything else that used to live
 * beside it in version.h is now one shared file,
 * lib/due_shared/src/fw_version.h, which does NOT include this: each
 * track includes its own track_id.h alongside it instead.
 *
 * 'A' = CMake + this project's own arm-gcc, built from the Arduino
 * core sources (enumeration only; arduino-cli is not invoked).
 * 'B' = CMake bare metal, the project. 'C' is a third track, FreeRTOS
 * on Track B's own drivers - see apps/rtos_bringup/track_id.h.
 * This copy is Track A.
 *
 * See docs/shared-source.md for where the boundary is drawn and why.
 */
#ifndef TRACK_ID_H
#define TRACK_ID_H

/*
 * Guarded, because a track must not be decided by include-path
 * proximity: ctl_port.c includes "track_id.h" and lives in drivers/,
 * so the compiler finds drivers/track_id.h first even when linking a
 * different track's copy. So the build states it, and -DFW_TRACK wins
 * over whichever header the include path reached.
 */
#ifndef FW_TRACK
#define FW_TRACK  'A'
#endif

#endif /* TRACK_ID_H */
