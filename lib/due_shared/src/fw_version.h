/*
 * Firmware identity: which track, and which build of it.
 *
 * **One copy, compiled by both tracks.** This file used to be two -
 * drivers/version.h and sketches/bringup/version.h, kept byte-identical
 * by hand apart from FW_TRACK. That arrangement is what
 * docs/shared-source.md exists to end, and this file is the first thing
 * it moved: the wire contract is shared source, and only FW_TRACK is
 * legitimately per-track. It lives in each track's own track_id.h.
 *
 * ## Why this exists
 *
 * Nothing on the board could say which track it was running except a
 * prose line in the console banner ("Track A bring-up oracle"), matched
 * host-side as a substring. That is dev-only - the banner costs 89 ms
 * of blocked main loop and lives on the programming port, which a
 * deployed board does not have - and it carried no version at all. A
 * board and a host could disagree about the firmware entirely and the
 * only symptom would be a measurement that looked wrong.
 *
 * ## The three versions, and what each is for
 *
 * They are deliberately separate and none substitutes for another:
 *
 *   FRAME_VERSION  (frame.h)   the sample-stream wire format. Bump when
 *                              a receiver written for the old one would
 *                              misparse the new one.
 *   CTL_VERSION    (ctl.h)     the control-channel wire format. Same
 *                              rule, different channel.
 *   FW_VERSION_*   (here)      which build of the firmware this is,
 *                              when both wire formats are unchanged.
 *
 * A host refuses a pairing on the first two. It *reports* the third,
 * and uses it to know whether a measurement is comparable with one
 * taken last week.
 *
 * ## When to bump FW_VERSION
 *
 * By hand - once, now - in the same commit as the change:
 *
 *   PATCH  a fix or a measurement-affecting change with no new command
 *   MINOR  a new command, counter, or capability on either track
 *   MAJOR  reserved; nothing has earned it yet
 *
 * The build date and time travel alongside it and are what distinguish
 * two builds of the same version - which is the common case during a
 * session, and the reason __DATE__/__TIME__ are not being replaced.
 * There is deliberately no git SHA: baking one in means the two
 * toolchains need build plumbing that can silently disagree, and the
 * date already answers "is this the image I just flashed".
 */

#ifndef FW_VERSION_H
#define FW_VERSION_H

/*
 * FW_TRACK is deliberately *not* here and this file does not include
 * the header that defines it.
 *
 * It cannot: arduino-cli compiles a library with the library's own
 * include path, not the sketch's, so a shared header reaching back for
 * a per-track one fails to resolve on Track A - measured, it is a
 * "track_id.h: No such file or directory" from inside this file.
 *
 * It also should not. This file is the wire contract; which track built
 * an image is a fact about the image, and nothing here needs it -
 * FW_TRACK reaches FW_ID_FORMAT as a printf argument, never as a token
 * in this file. So each track includes its own track_id.h beside this
 * one: drivers/track_id.h and sketches/bringup/track_id.h.
 */

#define FW_VERSION_MAJOR 0
#define FW_VERSION_MINOR 2
#define FW_VERSION_PATCH 0

/*
 * Derived, never typed, and that is the whole point of the change that
 * brought this file here.
 *
 * bf791f3 bumped FW_VERSION_MINOR from 1 to 2 and left the string at
 * "0.1.0". The two disagreed in every build since, and they reach
 * different consumers: the numbers go to CTL_OP_IDENTITY
 * (drivers/ctl.c), the string to the `v` console line - which
 * measure.parse_identity documents as interchangeable with it. So the
 * board answered "which firmware are you" with 0.1.0 or 0.2.0 depending
 * which channel was asked. tests/baseline.json says 0.2.0 and the
 * control channel was right; the console had been under-reporting.
 *
 * Hand-copying the file between tracks kept the two copies in perfect
 * agreement - at the wrong value. One representation cannot drift from
 * itself.
 */
#define FW__STR2(x) #x
#define FW__STR(x)  FW__STR2(x)
#define FW_VERSION_STR  FW__STR(FW_VERSION_MAJOR) "." FW__STR(FW_VERSION_MINOR) "." FW__STR(FW_VERSION_PATCH)

/*
 * The identity line used to be a printf format string here,
 * FW_ID_FORMAT. It is now emitted key by key in console_identity()
 * (lib/due_shared/src/console.c), which is still its one and only
 * home - issue #49 removed the formatter from the shared tree, not the
 * contract.
 *
 * The macro is deliberately not left behind as documentation. An
 * unused copy of a wire format is exactly the second home this seam
 * exists to prevent: it would drift silently, because nothing compiles
 * it and nothing tests it.
 *
 * `v` exists separately from the banner because the banner is 89 ms of
 * blocked main loop (invariant 8) and the identity is one short line.
 * Asking "what are you" should not cost a measurement.
 */

#endif /* FW_VERSION_H */
