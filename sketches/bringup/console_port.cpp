/*
 * Track A's half of the console seam. See lib/due_shared/src/console.h
 * for what is shared and why, and console_port.h for the rule that
 * keeps this file two functions long.
 */

#include <Arduino.h>

#include "console_port.h"
#include "stream.h"

/*
 * LF becomes CRLF on the way out, which Track B has always done and
 * this track never did.
 *
 * bsp/syscalls.c does it for Track B - "the host expects CRLF on a raw
 * terminal" - so every line Track B puts on the wire ends \r\n. Track A
 * got the same result for its own output by accident, because
 * Serial.println() appends CRLF itself, but **anything routed through
 * the shared console path did not**: console_identity(), console_help()
 * and every console_cmds.c body end their lines with con_nl(), which is
 * console_write("\n"), which was a bare LF here.
 *
 * So the two tracks have been emitting different bytes for the same
 * shared line, and nothing noticed because the host parsers are
 * whitespace-tolerant.
 *
 * It stopped being invisible when issue #49's migration moved Track A's
 * own bodies onto the emitters too: measure_printf, which times 20
 * lines and whose figure this project quotes, read **3533 us** against
 * Track B's 3618. That is not a speed difference - it is 41 characters
 * against 42, at 86.1 us each, because println was sending CRLF and
 * con_nl() was sending LF. 41 x 86.1 = 3530; 42 x 86.1 = 3616.
 *
 * Translating here rather than in con_nl() keeps the emitters
 * platform-free: the newline convention is a property of the wire, and
 * the port is the only thing that knows about the wire.
 *
 * Bounded like everything else on this seam - one pass over a string
 * whose length con_str() has already capped at CON_STR_MAX.
 */
void console_write(const char *s)
{
	const char *run = s;

	for (const char *p = s; *p; p++) {
		if (*p != '\n')
			continue;
		if (p > run)
			Serial.write((const uint8_t *)run, (size_t)(p - run));
		Serial.write((const uint8_t *)"\r\n", 2);
		run = p + 1;
	}
	if (*run)
		Serial.print(run);
}

void console_flush(void)
{
	Serial.flush();
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
