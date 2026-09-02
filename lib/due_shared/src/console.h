/*
 * The debug console's command surface, shared by both tracks.
 *
 * The split is the one the control channel already uses and that
 * invariant 3 asks for: the surface is shared, the handlers are not.
 * Which letters exist, what arguments they take, what the help says and
 * what happens to a letter this track has not got - all one definition,
 * here. What a letter *does* touches registers and stays two
 * independent programmings, because that is what makes a behavioural
 * divergence point at one of them.
 *
 * A command in the table that this track has not bound is answered, not
 * ignored - "not implemented on this track". That is the console's
 * CTL_ERR_OPCODE, and for the same reason: silence is a measurement.
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
 * their commands in whatever order reads best.
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
 * report, computed rather than written down so it cannot go stale the
 * way a hand-diffed count would. Empty means the two command sets are
 * the same set.
 */
void console_missing(void);

/*
 * The identity line, built once for both tracks.
 *
 * `# id: track=B fw=0.2.0 ctlver=4 framever=3 mck=...` is what
 * measure.parse_identity reads and what a host refuses a pairing on, so
 * the format and the order of its arguments are wire contract - which
 * is why `mck` cannot be renamed to say what it is. It is NOMINAL:
 * register-derived, never measured; the measured figure lives in the
 * telemetry heartbeat as mck_meas_hz. The nominal is what belongs in
 * this line, since the board reports its sample rate as integer
 * division on it and a host inverting a rate back to an RC must divide
 * by the same value. See console.c, where the line is emitted.
 *
 * `track` and `mck_hz` are passed rather than reached for: FW_TRACK is
 * deliberately the one per-track constant, and SystemCoreClock lives in
 * each track's device headers, which shared code cannot include on
 * Track A. Passing two values keeps both out of console_port.h.
 */
void console_identity(char track, unsigned long mck_hz);

/*
 * Handler bodies that are application logic, in console_cmds.c. They
 * live behind the same rule as everything else here: what they reach
 * outside themselves is named in a port header, and nothing they do
 * touches a register. A handler that programs one stays in its track's
 * own source - see the note at the top of console_cmds.c for which.
 */
void console_trigger_fault(void);
void console_gen_report(void);

/*
 * `1`..`5`: start a capture stream and say what it will be doing.
 * Shared partly so its banner-before-start ordering cannot come apart
 * on one track - see console_cmds.c for why the order is load-bearing.
 */
void console_cmd_stream(uint32_t trigger_hz);

/* `=<dac>P` and `=<dac>[,<adc>[,<nch>]]L`: playback with and without
 * simultaneous capture. See console_cmds.c for the banner-ordering
 * constraint on the capture case. */
void console_cmd_play(uint32_t dac_hz);
void console_cmd_loop(uint32_t dac_hz, uint32_t adc_hz, unsigned nch);

/* The TC -> ADC -> PDC rate sweep, one implementation for both tracks;
 * see console_cmds.c for the design choices behind it. */
void console_cmd_rate_sweep(unsigned n_channels);

/*
 * The crosstalk settle wait. Shared so the two tracks cannot drift
 * apart on it - this measures what happens between conversions, so a
 * differing wait would change the measurement. See console_cmds.c.
 */
void console_bleed_settle(uint32_t ms);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_H */
