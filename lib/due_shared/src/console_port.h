/*
 * What the debug console needs from the track that hosts it.
 *
 * `console.c` is the console's *application layer* - the argument
 * parser, the command list, the help text and the dispatch. It touches
 * no register and knows nothing about either track's drivers; grep it
 * for UOTGHS, DACC, ADC->, PIO or REG_ and the count is zero.
 *
 * Two functions, and no more. ctl_port.h's warning applies here word
 * for word: **this is not an abstraction layer and must not grow into
 * one.** It exists so that one command surface serves two tracks.
 * Anything a track genuinely does differently is a *handler*, bound by
 * console_bindings[] in console.h, not a function added here.
 *
 * The build fact that shapes it, the same one ctl_port.h records: a
 * file inside the shared library cannot include a header from a
 * track's own folder. arduino-cli compiles a library with the library's
 * include path, so console.c cannot reach acq.h, gen.h, stream.h or
 * play.h on Track A. That is why the handlers stay in each track's own
 * source and only their names are shared.
 */
#ifndef CONSOLE_PORT_H
#define CONSOLE_PORT_H

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

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_PORT_H */
