/*
 * Track C's console port: the seam, implemented for an RTOS build.
 *
 * console_port.h is the boundary lib/due_shared/src/console.c speaks
 * through, and a port per application is exactly what it is for.
 * Track B's port (drivers/console_port.c) includes stream.h and reaches
 * the whole capture and USB stack; Track C at stage C1 has no sample
 * path at all, so it implements the seam against the UART directly.
 *
 * That is not a simplification to be undone later. When C2 brings the
 * five services up as tasks, what changes here is
 * console_port_stream_start() and nothing else - which is the
 * property the seam exists to give.
 *
 * console_write is NOT fputs(s, stdout). That was the shape on Track B
 * until issue #49, and it is what pulled findfp and therefore the heap
 * into an image whose call sites had all been migrated away from
 * printf. Writing to the UART directly is what keeps
 * tests/test_no_heap.py green here from the first commit rather than
 * after a migration.
 */
#include <stdbool.h>
#include <stdint.h>

#include "bsp.h"
#include "console_port.h"

void console_write(const char *s)
{
	uart_puts_polled(s);
}

void console_flush(void)
{
	uart_flush();
}

bool console_port_stream_start(uint32_t trigger_hz)
{
	/*
	 * Refuse rather than pretend. C1 is build-and-boot only: there is
	 * no acquisition task, so a stream cannot start, and answering
	 * "started" to a host that then waits for frames would be worse
	 * than answering "refused".
	 *
	 * A track that does not implement something says so - the same
	 * rule the control protocol applies with CTL_ERR_OPCODE, where a
	 * body of zeroes is forbidden because zero is a measurement and a
	 * host cannot otherwise tell it from "not counted here".
	 */
	(void)trigger_hz;
	return false;
}
