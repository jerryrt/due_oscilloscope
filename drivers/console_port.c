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
	 * fputs rather than printf: the shared layer passes literal text
	 * that may contain a '%', and a format string taken from data is
	 * a defect waiting for the first help line that mentions one.
	 */
	fputs(s, stdout);
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
