/* Main-loop load monitor. See load.h for why it is the cycle counter. */

#include "load.h"
#include "bsp.h"
#include "sam.h"
#include <stdio.h>
#include <string.h>

uint32_t load_max_cycles;
uint32_t load_hist[LOAD_BUCKETS];
uint32_t load_prev_cycles;

static bool available;

void load_init(void)
{
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
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
	out->dev_us      = micros();
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
	printf("# load available=%u passes=%lu max=%lu cyc (%lu us)\n",
	       (unsigned)r.available,
	       (unsigned long)r.passes,
	       (unsigned long)r.max_cycles,
	       (unsigned long)(r.max_cycles / per_us));
	uart_flush();

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
		printf("#   %2u: %10lu passes  %lu-%lu cyc  %lu-%lu us\n",
		       i, (unsigned long)load_hist[i],
		       (unsigned long)lo, (unsigned long)hi,
		       (unsigned long)(lo / per_us),
		       (unsigned long)(hi / per_us));
		uart_flush();
	}
}
