/*
 * What the debug console needs from the track that hosts it.
 *
 * `console.c` is the console's *application layer* - the argument
 * parser, the command list, the help text and the dispatch. It touches
 * no register and knows nothing about either track's drivers; grep it
 * for UOTGHS, DACC, ADC->, PIO or REG_ and the count is zero.
 *
 * **This is not an abstraction layer.** It is a *record* of exactly
 * what the shared console code reaches outside itself - the same shape
 * as stream_port.h, and for the same reason: "a seam that cannot grow
 * without a test failing".
 *
 * It used to say "two functions, and no more", and that rule was
 * rescoped on 2026-08-30 (issue #45). The count was a proxy for the
 * property that actually matters, and it stopped being the right proxy
 * the moment the ruling on #45 said the application layer is shared
 * maximally: moving a handler body down means shared code calling
 * stream_start(), which cannot be reached by include on Track A and so
 * must be named here. Under the old rule that growth was forbidden;
 * under this one it is allowed and *checked*.
 *
 * The difference is that "no more than two" is only countable, while
 * "exactly what the shared code calls" is testable - and the test is
 * what stops a seam becoming an abstraction layer. Adding a name here
 * that nothing calls fails; calling something not named here fails to
 * link. Neither is a matter of anybody's restraint.
 *
 * What still does NOT belong here: anything a track genuinely does
 * *differently*. A name in this header is a contract both tracks
 * implement with the same meaning, which is invariant 3's peer
 * requirement made checkable at compile time. Two independent register
 * programmings behind one name is the point; one programming reached
 * through a wrapper is not.
 *
 * The build fact that shapes it, the same one ctl_port.h records: a
 * file inside the shared library cannot include a header from a
 * track's own folder. arduino-cli compiles a library with the library's
 * include path, so console.c cannot reach acq.h, gen.h, stream.h or
 * play.h on Track A. That build fact is why a moved handler needs its
 * dependencies *named here* rather than included - it is the mechanism
 * that forces the seam to be explicit, and it is the reason this header
 * is a record rather than a convenience.
 */
#ifndef CONSOLE_PORT_H
#define CONSOLE_PORT_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * One line to the debug console, without a trailing newline - the
 * caller supplies it, because the help text is a list of lines and
 * building it a line at a time is what keeps the shared buffer small.
 *
 * Track B is printf over the programming-port UART; Track A is
 * Serial.print. Both end at the same wire and neither is on the sample
 * path: invariant 8 says printf is a debug method and not an
 * instrument, and everything reached through here is debug-only.
 */
void console_write(const char *s);

/*
 * Block until what has been written is on the wire.
 *
 * Called once at the end of a dispatched command rather than after
 * every line, because the cost of a console command is the bytes it
 * puts on the wire - measured, invariant 8 - and flushing per line does
 * not change the byte count.
 */
void console_flush(void);

/*
 * Start a capture stream at `trigger_hz`; false if the rate is past
 * this track's measured ADC ceiling.
 *
 * The one name console_cmd_stream() needs that is not already shared.
 * Everything else it says - the shape name, the output frequency, the
 * sync wording - comes from ctl_wire.h and ctl_port_gen_get(), which
 * were shared before this.
 *
 * The rate ceiling is per track by construction: ACQ_MIN_RC_FOR() is a
 * measured floor and each track measures its own, which is why this is
 * a port name and not a shared function. Track B currently accepts one
 * to three channels and Track A one or two - see issue #46.
 */
bool console_port_stream_start(uint32_t trigger_hz);

/*
 * The acquisition surface the rate sweep needs.
 *
 * `cmd_rate_sweep` is application logic - it decides which ladder to
 * walk, how long to dwell, what to compute and what to print - and the
 * owner ruled on issue #45 that application logic is shared. What it
 * cannot be is a direct caller of acq.h: a file inside the shared
 * library cannot include a header from a track's own folder, which is
 * the build fact this whole header exists to record.
 *
 * So the eight names below. Each is a contract both tracks implement
 * with the same meaning, and the register programming behind each stays
 * two independent implementations - invariant 3 intact, because what
 * moved is the sweep's logic and not its hardware.
 *
 * They are deliberately thin. A port name that computed something would
 * be application logic hiding on the wrong side of the seam.
 */
/*
 * MCK, which shared code cannot reach for itself.
 *
 * SystemCoreClock lives behind each track's own device header, and
 * console_identity() already works around that by taking mck_hz as a
 * parameter. The sweep needs it twice - to derive the trigger a divisor
 * gives, and to print the clock it divided - so it takes a port name
 * rather than three arguments.
 *
 * Issue #52 measures MCK at about -11 ppm from the nominal 78 MHz, so
 * what this returns is the register-derived figure and a reader should
 * treat it as such.
 */
uint32_t console_port_mck_hz(void);

void     console_port_acq_init(void);
bool     console_port_acq_start(uint32_t trigger_hz, unsigned n_channels);
void     console_port_acq_stop(void);
uint32_t console_port_acq_buffers_done(void);
uint32_t console_port_acq_configured_rc(void);
uint32_t console_port_acq_buf_samples(void);

/*
 * The measured per-channel RC floor. Per track by construction and by
 * measurement - each track measures its own, and Track B accepts one to
 * three channels where Track A accepts one or two (issue #46).
 */
uint32_t console_port_acq_min_rc(unsigned n_channels);

/* The two overrun counters, read together so a row cannot mix a
 * reading of one with a later reading of the other. */
void     console_port_acq_overruns(uint32_t *rxbuff, uint32_t *govre);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_PORT_H */
