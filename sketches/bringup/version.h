/*
 * Firmware identity: which track, and which build of it.
 *
 * Shared verbatim between Track A and Track B, like frame.h - two
 * copies by invariant 3, kept byte-identical apart from FW_TRACK, which
 * is the whole point of the file. Track B's copy is
 * drivers/version.h.
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
 * By hand, in both copies, in the same commit as the change:
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

#ifndef VERSION_H
#define VERSION_H

#define FW_VERSION_MAJOR 0
#define FW_VERSION_MINOR 1
#define FW_VERSION_PATCH 0
#define FW_VERSION_STR   "0.1.0"

/* 'A' = arduino-cli reference oracle, 'B' = CMake bare metal. The one
 * line that differs between the two copies of this file. */
#define FW_TRACK 'A'

/*
 * The identity line, emitted by the banner and by the `v` command on
 * both tracks, in this exact format.
 *
 * One line, key=value, same keys and same order everywhere, so a host
 * reads one regular expression instead of matching prose. `build=` is
 * last because it is the only value containing spaces.
 *
 * `v` exists separately from the banner because the banner is 89 ms of
 * blocked main loop (invariant 8) and this is one short line. Asking
 * "what are you" should not cost a measurement.
 */
#define FW_ID_FORMAT \
	"# id: track=%c fw=%s ctlver=%u framever=%u mck=%lu adcclk=%lu " \
	"framebytes=%u framesamples=%u build=%s %s"

#endif /* VERSION_H */
