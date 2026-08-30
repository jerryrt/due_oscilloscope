/*
 * Track B's half of the console seam. See lib/due_shared/src/console.h
 * for what is shared and why, and console_port.h for the rule that
 * keeps this file two functions long.
 */

#include <stdio.h>

#include "bsp.h"
#include "console_port.h"
#include "stream.h"

void console_write(const char *s)
{
	/*
	 * Straight to the UART, not through stdio (issue #49).
	 *
	 * This was fputs(s, stdout), which is correct about the thing it
	 * was worried about - a format string taken from data is a defect
	 * waiting for the first help line containing a '%' - and wrong
	 * about the heap. `stdout` is a real FILE, so fputs pulls
	 * newlib's findfp exactly as printf does, and findfp allocates
	 * that stream's buffer with _malloc_r on first use.
	 *
	 * So migrating the console's callers off printf would not have
	 * removed the heap on its own: the port they migrate *to* was
	 * pulling it in. Found by reading this file after writing the
	 * formatter, not by the guard, which cannot say why.
	 *
	 * The CRLF translation moves here with it. It was in _write()
	 * because that was the only path to the wire; now this is, and a
	 * host on a raw terminal still wants both characters.
	 */
	for (; *s; s++) {
		if (*s == '\n')
			uart_putc_polled('\r');
		uart_putc_polled(*s);
	}
}

void console_flush(void)
{
	uart_flush();
}

/*
 * The one name console_cmd_stream() needs from this track. The rate
 * ceiling is a measured floor per channel count, which is why the
 * decision stays here and only the wording is shared.
 */
bool console_port_stream_start(uint32_t trigger_hz)
{
	return stream_start(trigger_hz);
}
