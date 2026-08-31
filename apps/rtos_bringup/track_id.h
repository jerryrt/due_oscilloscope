/*
 * Which track this image is, and the only thing Track C copies.
 *
 * `FW_TRACK` is deliberately per-track and is the one remaining
 * per-track duplicate by design - see lib/due_shared/src/fw_version.h.
 * Everything else on the identity line comes from the shared header, so
 * a board cannot answer "which firmware are you" two ways.
 *
 * Track C is a third track by the owner's ruling on issue #45. It is
 * NOT an oracle in invariant 3's sense and must not be read as one: it
 * links Track B's drivers/, bsp/ and lib/ unchanged, so a disagreement
 * between B and C points at main() or at the kernel and never at the
 * register programming, which is the same object file. That is what
 * makes it the right experiment for the question it exists to ask -
 * does a scheduler underneath change the timing of a data path that is
 * otherwise byte-identical - and the wrong one for any question about
 * register programming.
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
#define FW_TRACK  'C'
#endif

#endif /* TRACK_ID_H */
