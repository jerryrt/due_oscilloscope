/*
 * Main-loop load monitor. See load.h for why it is the cycle counter.
 *
 * Shared by both tracks. This is an instrument, not register
 * programming: the only register it touches is DWT's cycle counter,
 * which is core rather than peripheral and is the same counter on both
 * builds by construction. Invariant 3 keeps usb, acq, adc, dac, gen,
 * play, clock and fault independent per track because two programmings
 * of one peripheral is what makes a divergence point at one of them -
 * an argument that does not transfer to a counter neither track
 * configures differently, and would only buy two places for the
 * histogram arithmetic to be wrong.
 *
 * micros() and the console come from the track, through the seams that
 * already exist for them: ctl_port_micros() and console_write().
 */

#include <stdio.h>
#include <string.h>

#include "load.h"
#include "ctl_port.h"
#include "console_port.h"
#include "console_out.h"

/*
 * The CMSIS global, declared rather than included. Both tracks define
 * it - it is the standard name and system_sam3xa.c sets it on each -
 * and a shared file cannot reach either track's sam.h or Arduino.h.
 */
extern uint32_t SystemCoreClock;

uint32_t load_max_cycles;
uint32_t load_hist[LOAD_BUCKETS];
uint32_t load_prev_cycles;

static bool available;

void load_init(void)
{
	/*
	 * TRCENA in CoreDebug's DEMCR, spelled out rather than reached
	 * through CMSIS. This file is compiled into an Arduino sketch as
	 * well as a bare-metal image and a shared file cannot include a
	 * track's headers; the address is architectural on Cortex-M3 and
	 * does not vary between the two builds.
	 */
	LOAD_DEMCR |= LOAD_DEMCR_TRCENA;
	LOAD_DWT_CYCCNT = 0;
	LOAD_DWT_CTRL |= LOAD_DWT_CYCCNTENA;

	/*
	 * Prove it counts rather than assume it. CYCCNT is optional on
	 * Cortex-M3, and a counter stuck at zero would report a loop with
	 * no passes longer than one cycle - a wrong answer that looks like
	 * a very good one, which is the worst kind for an instrument whose
	 * whole job is to be believed.
	 */
	{
		uint32_t a = LOAD_DWT_CYCCNT;
		uint32_t spin = 0;

		while (spin < 64u)
			spin++;
		available = LOAD_DWT_CYCCNT != a;
	}

	load_clear();
}

bool load_available(void)
{
	return available;
}

void load_clear(void)
{
	load_max_cycles = 0;
	memset(load_hist, 0, sizeof(load_hist));
	load_prev_cycles = LOAD_DWT_CYCCNT;
}

void load_sample(load_report_t *out)
{
	uint32_t passes = 0;

	for (unsigned i = 0; i < LOAD_BUCKETS; i++)
		passes += load_hist[i];

	memset(out, 0, sizeof(*out));
	out->dev_us      = ctl_port_micros();
	out->passes      = passes;
	out->max_cycles  = load_max_cycles;
	out->mck_hz      = SystemCoreClock;
	out->available   = available ? 1u : 0u;
	out->buckets     = (uint8_t)LOAD_BUCKETS;
	memcpy(out->hist, load_hist, sizeof(out->hist));
}

void load_dump(void)
{
	load_report_t r;
	uint32_t per_us = SystemCoreClock / 1000000u;

	load_sample(&r);
	con_str("# load ");
	con_kv_u32("available", r.available);   con_ch(' ');
	con_kv_u32("passes", r.passes);         con_ch(' ');
	con_kv_u32("max", r.max_cycles);        con_str(" cyc (");
	con_u32(r.max_cycles / per_us);         con_str(" us)");
	con_nl();

	/*
	 * Only the occupied buckets, and in microseconds as well as
	 * cycles. A histogram nobody can read at a glance is a histogram
	 * nobody reads.
	 */
	for (unsigned i = 0; i < LOAD_BUCKETS; i++) {
		uint32_t lo, hi;

		if (!load_hist[i])
			continue;
		lo = 1u << i;
		hi = (i < 31u) ? (1u << (i + 1u)) - 1u : 0xffffffffu;
		con_str("#   ");  con_u32w(i, 2, ' ');
		con_str(": ");    con_u32w(load_hist[i], 10, ' ');
		con_str(" passes  ");
		con_u32(lo); con_ch('-'); con_u32(hi); con_str(" cyc  ");
		con_u32(lo / per_us); con_ch('-');
		con_u32(hi / per_us); con_str(" us");
		con_nl();
	}
	console_flush();
}
