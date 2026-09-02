/*
 * Firmware identity: which track, and which build of it.
 *
 * One copy, compiled by both tracks (see docs/shared-source.md); only
 * FW_TRACK is legitimately per-track, and it lives in each track's own
 * track_id.h beside this file.
 *
 * Three versions exist and none substitutes for another:
 *
 *   FRAME_VERSION  (frame.h)   sample-stream wire format; a host refuses
 *                              a pairing on mismatch.
 *   CTL_VERSION    (ctl.h)     control-channel wire format; same rule.
 *   FW_VERSION_*   (here)      which build this is, when both wire
 *                              formats are unchanged - a host *reports*
 *                              this rather than refusing on it.
 *
 * Bump FW_VERSION by hand, in the same commit as the change:
 *
 *   PATCH  a fix or a measurement-affecting change with no new command
 *   MINOR  a new command, counter, or capability on either track
 *   MAJOR  reserved; nothing has earned it yet
 *
 * Which build of a version an image is comes from FW_GIT_REV, not from
 * here: the commit the image was built from, plus the working-tree
 * delta hash when the tree was dirty. It reaches the `v` identity line
 * and the control channel's IDENTITY, and cmake/fw_git_rev.cmake writes
 * it before every firmware build of every track.
 *
 * A commit rather than a wall clock, because the two questions a build
 * stamp is asked are both graph questions. "Which source produced this
 * image" is answered by stating the commit; inferring it from wall-clock
 * proximity to a flash-log entry needs a comparison window and a
 * timezone the stamp does not carry. "Is this image stale" is whether
 * the newest commit touching that track's firmware source is reachable
 * from the image's commit - no clock, no slack, and nothing that moves
 * when the reader's zone does. host/provenance.py asks both.
 *
 * A commit does not distinguish two builds of one source state, and it
 * does not have to: the build is byte-reproducible, so two builds of
 * one clean tree ARE one image. tools/reproducible.py holds that.
 */

#ifndef FW_VERSION_H
#define FW_VERSION_H

/*
 * FW_TRACK is deliberately *not* here, and this file does not include
 * the header that defines it.
 *
 * Each track's per-subsystem headers (track_id.h among them) are
 * independent implementations, not one shared header living in a
 * different folder - invariant 3 keeps register programming un-shared,
 * and the two tracks' headers differ in shape as well as content. A
 * shared header that reached back into one track's own folder would
 * compile against exactly one track.
 *
 * It also should not: which track built an image is a fact about the
 * image, and this file is the wire contract - FW_TRACK never appears as
 * a token here. Each track includes its own track_id.h beside this one:
 * drivers/track_id.h, sketches/bringup/track_id.h and
 * apps/rtos_bringup/track_id.h.
 */

#define FW_VERSION_MAJOR 0
#define FW_VERSION_MINOR 2
#define FW_VERSION_PATCH 0

/*
 * Derived, never typed: a hand-maintained string can silently disagree
 * with the numeric fields, and the two reach different consumers -
 * CTL_OP_IDENTITY sends the numbers, the `v` console line sends the
 * string.
 */
#define FW__STR2(x) #x
#define FW__STR(x)  FW__STR2(x)
#define FW_VERSION_STR  FW__STR(FW_VERSION_MAJOR) "." FW__STR(FW_VERSION_MINOR) "." FW__STR(FW_VERSION_PATCH)

/* The identity line itself is emitted key by key in console_identity()
 * (console.c), not from a format macro here - keep it that way, or an
 * unused copy of the wire format becomes a second home that can drift
 * silently. */

#endif /* FW_VERSION_H */
