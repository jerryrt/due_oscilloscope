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
#include "analog.h"
#include "gen.h"

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


/*
 * `g`'s two arms. Tracks B and C share them because they share this
 * file, the board support under it and the pin: the LED is PB27 on
 * both, and neither track has an abstraction between it and PIOB.
 *
 * The loop lives here rather than in the shared body because each
 * iteration is a register write, and invariant 3 keeps those with the
 * track. `n` and the timing around it come from console_cmd_gpio_cost().
 */
#define LED_MASK (1u << 27)   /* pin 13 = PB27 */

void console_port_toggle_direct(uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		PIOB->PIO_SODR = LED_MASK;
		PIOB->PIO_CODR = LED_MASK;
	}
}

void console_port_toggle_bsp(uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		led_on();
		led_off();
	}
}

const char *console_port_toggle_bsp_name(void)
{
	return "via bsp led";
}


/*
 * The software-triggered analog surface `r`, `s` and `x` speak
 * through. Thin, like the acquisition names above: this track spells
 * them adc_read/adc_read_pair/dac_write in analog.h, Track A spells
 * them acq_read_one/acq_read_pair/gen_write_dac, and neither header is
 * reachable from shared code.
 */
uint16_t console_port_adc_read(unsigned ch)
{
	return adc_read(ch);
}

void console_port_adc_read_pair(unsigned cha, unsigned chb,
                                uint16_t *a, uint16_t *b)
{
	adc_read_pair(cha, chb, a, b);
}

void console_port_dac_write(unsigned ch, uint16_t code)
{
	dac_write(ch, code);
}


/*
 * The generator on its own timebase, which is what `d`, `j` and `k`
 * measure the DACC with. Thin, like the rest of this file: the shared
 * bodies decide the ladder, the dwell and the arithmetic, and every
 * name below ends at a register in drivers/gen.c.
 */
void console_port_gen_init(void)
{
	gen_init();
}

bool console_port_gen_start_independent(uint32_t dac_hz)
{
	return gen_start_independent(dac_hz);
}

void console_port_gen_stop(void)
{
	gen_stop();
}

uint32_t console_port_gen_endtx_count(void)
{
	return gen_endtx_count;
}

uint32_t console_port_gen_configured_rc(void)
{
	return gen_configured_rc();
}

uint32_t console_port_gen_table_len(void)
{
	return GEN_TABLE_LEN;
}
