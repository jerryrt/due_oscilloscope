/*
 * Track B's half of the console seam. See lib/due_shared/src/console.h
 * for what is shared and why, and console_port.h for the rule that
 * keeps this file two functions long.
 */

#include <stdio.h>

#include "sam.h"          /* SystemCoreClock */
#include "bsp.h"
#include "acq.h"
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

/* ------------------------------------------------------------------ */
/* The acquisition surface console_cmd_rate_sweep() speaks through.    */
/*                                                                     */
/* Thin by design: a port name that computed something would be        */
/* application logic hiding on the wrong side of the seam. The sweep's  */
/* logic is shared (issue #45); these are the register reaches it      */
/* cannot make for itself, and Track A implements the same eight names */
/* against its own acq.c.                                              */
/* ------------------------------------------------------------------ */

uint32_t console_port_mck_hz(void)
{
	return (uint32_t)SystemCoreClock;
}

void console_port_acq_init(void)
{
	acq_init();
}

bool console_port_acq_start(uint32_t trigger_hz, unsigned n_channels)
{
	return acq_start(trigger_hz, n_channels);
}

void console_port_acq_stop(void)
{
	acq_stop();
}

uint32_t console_port_acq_buffers_done(void)
{
	return acq_buffers_done;
}

uint32_t console_port_acq_configured_rc(void)
{
	return acq_configured_rc();
}

uint32_t console_port_acq_buf_samples(void)
{
	return ACQ_BUF_SAMPLES;
}

uint32_t console_port_acq_min_rc(unsigned n_channels)
{
	return ACQ_MIN_RC_FOR(n_channels);
}

void console_port_acq_overruns(uint32_t *rxbuff, uint32_t *govre)
{
	*rxbuff = acq_rxbuff_overruns;
	*govre  = acq_govre;
}
