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
#include "play.h"

void console_write(const char *s)
{
	/*
	 * Straight to the UART, not through stdio: fputs(s, stdout) would
	 * still pull newlib's findfp on first use, which allocates that
	 * stream's buffer with _malloc_r - an unwanted heap allocation,
	 * not just a format-string risk. CRLF translation lives here for
	 * the same reason: this is the only path to the wire.
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

bool console_port_play_start(uint32_t dac_hz)
{
	return play_start(dac_hz);
}

void console_port_play_stop(void)
{
	play_stop();
}

uint32_t console_port_play_max_hz(void)
{
	return (SystemCoreClock / 2u) / PLAY_MIN_RC;
}

bool console_port_capture_only_start(uint32_t adc_hz, unsigned nch)
{
	return stream_start_capture_only(adc_hz, nch);
}

/*
 * The acquisition surface console_cmd_rate_sweep() speaks through.
 * Thin by design: a port name that computed something would be
 * application logic on the wrong side of the seam. Track A
 * implements the same eight names against its own acq.c.
 */

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
