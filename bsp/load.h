/*
 * Main-loop load, measured continuously and cheaply.
 *
 * Everything this project exports about how hard the board is working
 * is after the fact: underruns, overruns, a ring that ran dry. All of
 * them say the loop was too slow *somewhere*, and none of them says
 * when, for how long, or whether it is close to the edge on a run that
 * happens to pass. The wedge in objective 0c is diagnosed today by
 * reading endpoint registers over the programming port, which a
 * deployed board does not have.
 *
 * So: count main-loop passes and time each one, and let the host
 * difference two snapshots. A blocked loop is then a low pass rate and
 * a large maximum, visible while it is happening rather than inferred
 * from the damage afterwards.
 *
 * WHY THE CYCLE COUNTER AND NOT micros().
 *
 * micros() costs 869 ns, measured by `Q` on this board - it does a
 * runtime division. The idle loop is about 4 us a pass, so sampling
 * micros() once per pass would tax the loop it is measuring by more
 * than a fifth. An instrument that changes what it measures by 20% is
 * not an instrument.
 *
 * DWT's cycle counter is one load from a free-running 32-bit register:
 * no division, no critical section, no wrap handling beyond unsigned
 * subtraction, and cycle rather than microsecond resolution. It costs
 * what `Q` says it costs, which is the point - load_tick() is profiled
 * by the same command that condemned micros().
 *
 * CYCCNT is optional in the Cortex-M3 architecture. If this part did
 * not have it every delta would read zero, which a host would read as
 * an infinitely fast loop rather than as a broken instrument, so
 * load_available() is checked at init and travels with every report.
 */

#ifndef LOAD_H
#define LOAD_H

#include <stdint.h>
#include <stdbool.h>

/* Buckets are floor(log2(cycles)), so 32 covers every 32-bit delta and
 * the hot path needs no clamp. At 78 MHz bucket 13 is ~105 us and
 * bucket 20 is ~13 ms. */
/*
 * LOAD_BUCKETS and load_report_t are the wire, not the monitor.
 * CTL_OP_LOAD sends the struct verbatim and host/control.py parses
 * it as "<IIIIBB2x32I", so it is a contract with the host and
 * belongs beside the other CTL payloads rather than in this
 * track's private header. See docs/shared-source.md.
 */
#include "ctl_wire.h"


/* Hot-path state. Public because load_tick() is inline: this runs on
 * every pass of the main loop and a call would cost more than the
 * measurement. Nothing outside this file may write them. */
extern uint32_t load_max_cycles;
extern uint32_t load_hist[LOAD_BUCKETS];
extern uint32_t load_prev_cycles;

#define LOAD_DWT_CTRL   (*(volatile uint32_t *)0xE0001000u)
#define LOAD_DWT_CYCCNT (*(volatile uint32_t *)0xE0001004u)
#define LOAD_DWT_CYCCNTENA (1u << 0)

/*
 * Call once at the top of every main-loop pass.
 *
 * No branch and no call: an unavailable cycle counter is reported by
 * load_available() rather than tested here, because the test would cost
 * as much as the measurement and would run a quarter of a million times
 * a second to answer a question settled once at boot.
 */
/*
 * Compiled out entirely, for an A/B against an uninstrumented loop.
 *
 * It earned its place. `Q` reported load_tick at 410 ns of a 7900 ns
 * pass and the arithmetic said that was 5%, which was enough to suspect
 * it of the loop-mode test failures at the full-rate pair. Building it
 * out and reading the loop rate over the control channel said
 * otherwise: 128.1 k passes/s with it against 127.4 k without, the
 * difference in the noise and the wrong way round.
 *
 * So `Q` over-reports a cheap inline by several times - it calls it in
 * a tight loop where every iteration serially depends on the previous
 * DWT read, while the real loop has 7.8 us of other work between them
 * and hides the cost in peripheral-read stalls. Price anything this
 * small by A/B on the loop rate, never by `Q` alone.
 */
#ifndef LOAD_TICK_DISABLED
#define LOAD_TICK_DISABLED 0
#endif

__attribute__((always_inline))
static inline void load_tick(void)
{
#if LOAD_TICK_DISABLED
	return;
#else
	uint32_t now = LOAD_DWT_CYCCNT;
	uint32_t d = now - load_prev_cycles;

	load_prev_cycles = now;
	if (d > load_max_cycles)
		load_max_cycles = d;
	/* No pass counter: the histogram already holds one, and its sum
	 * is exact. A separate counter would be a load, an add and a
	 * store on every pass to hold a number that is derivable - which
	 * is a quarter of a million redundant memory accesses a second in
	 * a loop this is supposed to leave alone. */
	/*
	 * floor(log2(d)). __builtin_clz rather than CMSIS's __CLZ so this
	 * header needs no CMSIS include - it is pulled in from a main loop
	 * that may include things in any order, and one CLZ instruction is
	 * what both compile to. The |1 keeps a zero delta in bucket 0
	 * rather than making the result undefined.
	 */
	load_hist[31u - (uint32_t)__builtin_clz(d | 1u)]++;
#endif
}


void load_init(void);
bool load_available(void);
void load_sample(load_report_t *out);
void load_clear(void);
void load_dump(void);            /* console; never from an ISR */

#endif /* LOAD_H */
