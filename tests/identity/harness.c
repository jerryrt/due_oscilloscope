/*
 * The identity line, emitted by the firmware's own source on a host.
 *
 * console_identity() is the one home of the `# id:` line - the wire
 * contract measure.parse_identity reads and a host refuses a pairing
 * on. It reaches no register, so the real file can be compiled and run
 * here, which is the only way to see what a board would say without a
 * board.
 *
 * Three symbols are all it needs outside itself: the two console_port.h
 * names, and this track's command table. The table is empty because
 * nothing here dispatches a command.
 */
#include <stdio.h>

#include "console.h"

void console_write(const char *s)
{
	fputs(s, stdout);
}

void console_flush(void)
{
	fflush(stdout);
}

const console_binding_t console_bindings[] = {
	{ 0, 0 },
};

int main(void)
{
	/*
	 * 'B' and 78 MHz are what apps/baremetal_bringup/main.c passes.
	 * Every other field is a compiled-in constant, which is the point:
	 * the test reads them out of the source it just built rather than
	 * repeating them.
	 */
	console_identity('B', 78000000UL);
	return 0;
}
