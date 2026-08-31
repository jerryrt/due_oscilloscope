/*
 * The debug console's command surface, shared by both tracks.
 *
 * Why this is here rather than written twice, and it is issue #13's
 * finding rather than a preference: the 2026-08-27 rescope moved the
 * frame layout, the CRC and the whole control-protocol parser into this
 * library and did not move the console. Every console command was
 * therefore written twice by hand or existed on one track only, and a
 * diff of the two dispatchers found **29 commands shared, 8 on Track B
 * only, 4 on Track A only**. Divergence was the default state rather
 * than an oversight.
 *
 * It cost a measurement. Running the metric pipeline on Track A the
 * board hit objective 0c - the macOS close() wedge - and Track A had no
 * `Z`, the software unplug that releases it, because `Z` had been
 * written where the wedge was being chased. Two metrics are missing
 * from docs/metric-baseline-macos-track-a.md for that reason.
 *
 * The split is the one the control channel already uses and that
 * invariant 3 asks for: **the surface is shared, the handlers are
 * not.** Which letters exist, what arguments they take, what the help
 * says and what happens to a letter this track has not got - all one
 * definition, here. What a letter *does* touches registers and stays
 * two independent programmings, because that is what makes a
 * behavioural divergence point at one of them.
 *
 * The one behaviour worth naming, because it is what the old
 * arrangement could not do. A command in the table that this track has
 * not bound is **answered, not ignored** - "not implemented on this
 * track". That is the console's CTL_ERR_OPCODE, and for the same
 * reason: silence is a measurement. Typing `Z` at Track A used to look
 * exactly like typing `Z` at a board that had detached and come back.
 */
#ifndef CONSOLE_H
#define CONSOLE_H

#include <stdarg.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * The parsed arguments of "=<a>[,<b>[,<c>]]", zero for anything the
 * user did not type. Three because that is what the longest command
 * takes (=<shape>,<pts>,<amp>W) and this is bare metal: fixed and known
 * at build time, invariant 7.
 */
#define CONSOLE_NARGS  3u

/*
 * A command's body. Per track, because every one of them ends at a
 * register.
 */
typedef void (*console_fn)(const uint32_t *arg);

typedef struct {
	char        key;
	console_fn  fn;
} console_binding_t;

/*
 * What this track implements. Defined by each track, terminated by a
 * zero key, and scanned rather than indexed so the two tracks may list
 * their commands in whatever order reads best - the shared table below
 * decides the help's order, and a binding table that had to match it
 * positionally would be a second place to get the list wrong.
 *
 * A letter absent from here is answered as unimplemented. A letter
 * absent from the shared table is ignored in silence, which is what
 * makes stray CR, LF and spaces free.
 */
extern const console_binding_t console_bindings[];

/*
 * One byte from the debug port. Holds the "=" argument entry across
 * calls; a command letter consumes the arguments and closes it.
 *
 * Bounded and constant-time, like everything on the working path: the
 * scan is over a table of about forty entries and no input can make it
 * longer.
 */
void console_feed(int c);

/*
 * The command list, one line per entry, in table order. Each track's
 * banner prints its own identity and hardware lines and then calls
 * this, so the two boards answer `h` with the same list of commands and
 * their own facts about themselves.
 */
void console_help(void);

/*
 * Which commands this track has not bound, as one line - the parity
 * report, computed rather than written down. Empty means the two
 * command sets are the same set.
 *
 * It is here because issue #13's count was produced by diffing two
 * dispatchers by hand, and a number arrived at that way goes stale the
 * first time either track moves.
 */
void console_missing(void);

/*
 * The identity line, built once for both tracks.
 *
 * `# id: track=B fw=0.2.0 ctlver=3 framever=3 mck=...` is what
 * `measure.parse_identity` reads and what a host refuses a pairing on,
 * so the format string and the order of its ten arguments are wire
 * contract. They were written twice - printf in Track B's main.c,
 * snprintf plus Serial.println in Track A's sketch - identical
 * argument for argument, differing only in how the line reached the
 * wire, which is exactly what console_write() is for.
 *
 * `track` and `mck_hz` are passed rather than reached for. FW_TRACK is
 * deliberately the one per-track constant (fw_version.h says so and
 * does not include it), and SystemCoreClock lives in each track's
 * device headers, which shared code cannot include on Track A. Passing
 * two values keeps both out of console_port.h - the seam does not grow
 * for this.
 *
 * The build stamp is now this file's rather than each track's. Every
 * build is a full build and a test enforces it, so the shared object is
 * recompiled every time and the stamp still says when the image was
 * built - and now says it once instead of twice.
 */
void console_identity(char track, unsigned long mck_hz);

/*
 * Handler bodies that are application logic, in console_cmds.c.
 *
 * They live behind the same rule as everything else here: what they
 * reach outside themselves is named in a port header, and nothing they
 * do touches a register. A handler that programs one stays in its
 * track's own source - see the note at the top of console_cmds.c for
 * which, and why the split is drawn by measurement rather than taste.
 */
void console_trigger_fault(void);
void console_gen_report(void);

/*
 * `1`..`5`: start a capture stream and say what it will be doing.
 *
 * Shared because its two copies had one defect between them. Issue #41:
 * both printed the banner *after* starting, capture is device-driven so
 * the ring was filling while the console blocked for 17.9-20.2 ms
 * against 8.96 ms of runway, and exactly 3 frames were gone before the
 * first transfer - on three benches and three hosts. The fix was an
 * ordering, applied by hand to both tracks; one body is why it cannot
 * come apart again.
 */
void console_cmd_stream(uint32_t trigger_hz);

/*
 * The TC -> ADC -> PDC rate sweep. One implementation for both
 * tracks; the merge of the two that preceded it, and why each half
 * was chosen, is in console_cmds.c. Issue #45.
 */
void console_cmd_play(uint32_t dac_hz);
void console_cmd_loop(uint32_t dac_hz, uint32_t adc_hz, unsigned nch);

void console_cmd_rate_sweep(unsigned n_channels);

/*
 * The crosstalk settle wait. Shared so the two tracks cannot drift
 * apart on it - issue #16 measures what happens between conversions,
 * so a differing wait changes the measurement. See console_cmds.c.
 */
void console_bleed_settle(uint32_t ms);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_H */
