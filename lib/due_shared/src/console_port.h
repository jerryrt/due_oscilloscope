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

/*
 * Block, for `ms`, the thing the load monitor is measuring - already
 * clamped by console_cmd_stall(), which is where that policy lives.
 *
 * This is a port name rather than a shared spin because the three
 * tracks do not agree on what "the loop" is, and the difference is the
 * whole content of the command. Tracks A and B have one loop and stall
 * it where the handler runs. Track C's console is a task of its own at
 * a priority the sample path outranks, so a spin in the handler blocks
 * the console and nothing else: load_tick() would report a normal pass,
 * the heartbeat's loop_passes would keep advancing, and every test
 * built on `S` would pass while certifying nothing. So Track C hands
 * the stall to its service task, which is the task that IS the loop.
 *
 * Same meaning on all three - "make the monitored loop miss `ms`" -
 * which is what console_port.h's own rule asks of a name in it.
 */
void     console_port_stall(uint32_t ms);

/*
 * `g`'s two arms: `n` set-and-clear pairs each, one straight at the
 * port register and one through whatever this track offers instead.
 *
 * Two names rather than one because the answer is the *difference*
 * between them, and because the tracks deliberately time different
 * things in the second arm - Track B and Track C call the board
 * support's led_on()/led_off(), Track A calls the Arduino core's
 * digitalWrite(). That is a tracked divergence and not one to settle
 * by rewriting a side, so the label travels with the arm:
 * console_port_toggle_bsp_name() is what the report calls it.
 *
 * The loop is behind the port because every iteration of it is a
 * register write. The count, the timing and the arithmetic are not,
 * and stay shared - two tracks quoting ns-per-pair figures at each
 * other must have divided by the same thing.
 */
/*
 * Software-triggered analog access: one conversion, a matched pair,
 * and one DAC code. Between runs only - `r`, `s` and `x` all refuse or
 * misread while a capture is armed, which is the converter's business
 * and stays behind these names.
 *
 * Named rather than included for the usual reason: the two tracks
 * spell them differently. Track B has adc_read/adc_read_pair/dac_write
 * in analog.h; Track A has acq_read_one/acq_read_pair in acq.h and
 * gen_write_dac in gen.h, and no analog.h at all. That is not a
 * divergence to fix - they are two independent programmings of one
 * converter, which is what the oracle is for - but it is exactly why
 * a shared body cannot include either header.
 */
/*
 * The CAPTURE-side rate trace: absolute microseconds at each completed
 * PDC buffer and the ring occupancy at that instant, which is what
 * separates a converter that fell behind from a transfer that failed
 * to collect. The frame header's timestamp_us cannot: it is taken when
 * the frame is queued for USB.
 *
 * false means this track does not build the trace at all, which is NOT
 * the same as a run that traced nothing - `O` prints the difference,
 * for the reason CTL_ERR_OPCODE exists. Nothing else in `O` needs a
 * port name: the playback half is ctl_port_occupancy() and
 * ctl_port_rate_page(), which both tracks already implement for the
 * control channel, so the console and the command port report one set
 * of numbers by construction.
 */
bool console_port_acq_rate_trace(uint32_t *n, const uint32_t **us,
                                 const uint8_t **occ);

/* `w`'s start. Separate from console_port_stream_start() because the
 * sink is the UART rather than the bulk endpoint, which is a different
 * framer path on both tracks and not a parameter of one. */
bool console_port_stream_uart_start(uint32_t trigger_hz);

/*
 * The internal generator driven on its OWN timebase - TIOA1 rather than
 * the ADC's TIOA0 - which is what `d`, `j` and `k` measure the DACC
 * with. `console_port_gen_endtx_count()` is the PDC completion counter
 * those commands time; the table length converts completions to
 * conversions and is a driver constant, not arithmetic, so it comes
 * through the port rather than being written out again.
 */
void     console_port_gen_init(void);
bool     console_port_gen_start_independent(uint32_t dac_hz);
void     console_port_gen_stop(void);
uint32_t console_port_gen_endtx_count(void);
uint32_t console_port_gen_configured_rc(void);
uint32_t console_port_gen_table_len(void);

uint16_t console_port_adc_read(unsigned ch);
void     console_port_adc_read_pair(unsigned cha, unsigned chb,
                                    uint16_t *a, uint16_t *b);
void     console_port_dac_write(unsigned ch, uint16_t code);

void        console_port_toggle_direct(uint32_t n);
void        console_port_toggle_bsp(uint32_t n);
const char *console_port_toggle_bsp_name(void);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_PORT_H */
