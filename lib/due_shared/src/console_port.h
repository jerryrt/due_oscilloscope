/*
 * What the debug console needs from the track that hosts it.
 *
 * `console.c` is the console's *application layer* - the argument
 * parser, the command list, the help text and the dispatch. It touches
 * no register and knows nothing about either track's drivers; grep it
 * for UOTGHS, DACC, ADC->, PIO or REG_ and the count is zero.
 *
 * This is not an abstraction layer. It is a *record* of exactly what
 * the shared console code reaches outside itself - the same shape as
 * stream_port.h, and for the same reason: a seam that cannot grow
 * without a test failing. Adding a name here that nothing calls fails;
 * calling something not named here fails to link.
 *
 * What still does NOT belong here: anything a track genuinely does
 * *differently*. A name in this header is a contract both tracks
 * implement with the same meaning, which is invariant 3's peer
 * requirement made checkable at compile time. Two independent register
 * programmings behind one name is the point; one programming reached
 * through a wrapper is not.
 *
 * The fact that shapes it, the same one ctl_port.h records: each
 * track's own headers (acq.h, gen.h, stream.h, play.h) are independent
 * implementations, not one shared header living in a different folder,
 * so console.c cannot include one directly and compile against both
 * tracks. That is why a moved handler needs its dependencies *named
 * here* rather than included - the mechanism that forces the seam to
 * stay explicit.
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
 * Serial.print. Neither is on the sample path: invariant 8 says printf
 * is a debug method and not an instrument, and everything reached
 * through here is debug-only.
 */
void console_write(const char *s);

/*
 * Block until what has been written is on the wire. Called once at the
 * end of a dispatched command rather than after every line, since the
 * cost of a console command is the bytes it puts on the wire
 * (invariant 8), and flushing per line does not change that.
 */
void console_flush(void);

/*
 * Start a capture stream at `trigger_hz`; false if the rate is past
 * this track's measured ADC ceiling.
 *
 * The rate ceiling is per track by construction: ACQ_MIN_RC_FOR() is a
 * measured floor and each track measures its own, which is why this is
 * a port name and not a shared function. Track B currently accepts one
 * to three channels, Track A one or two.
 */
bool console_port_stream_start(uint32_t trigger_hz);

/*
 * The playback and capture-only surface `P` and `L` speak through -
 * the register reaches the shared command bodies cannot make for
 * themselves.
 *
 * `console_port_play_max_hz()` exists rather than exposing PLAY_MIN_RC
 * because the constant is a driver's and the arithmetic around it -
 * (MCK/2)/RC - was written out at four call sites across the tracks. A
 * ceiling is one question and every caller asked it the same way.
 */
bool     console_port_play_start(uint32_t dac_hz);
void     console_port_play_stop(void);
uint32_t console_port_play_max_hz(void);
bool     console_port_capture_only_start(uint32_t adc_hz, unsigned nch);

/*
 * The acquisition surface the rate sweep needs. `cmd_rate_sweep` is
 * application logic - it decides which ladder to walk, how long to
 * dwell, what to compute and what to print - and is shared, but it
 * cannot call acq.h directly: each track's acq.h is an independent
 * implementation, not a shared header in a different folder.
 *
 * So the names below. Each is a contract both tracks implement with the
 * same meaning; the register programming behind each stays two
 * independent implementations, invariant 3 intact.
 *
 * They are deliberately thin. A port name that computed something would
 * be application logic hiding on the wrong side of the seam.
 */
/*
 * MCK, which shared code cannot reach for itself: SystemCoreClock lives
 * behind each track's own device header. The sweep needs it twice - to
 * derive the trigger a divisor gives, and to print the clock it
 * divided - so it takes a port name rather than three arguments. What
 * this returns is the register-derived figure, a few ppm off nominal.
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
 * three channels where Track A accepts one or two.
 */
uint32_t console_port_acq_min_rc(unsigned n_channels);

/* The two overrun counters, read together so a row cannot mix a
 * reading of one with a later reading of the other. */
void     console_port_acq_overruns(uint32_t *rxbuff, uint32_t *govre);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_PORT_H */
