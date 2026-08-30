/*
 * Console handler bodies that are application logic, shared by both
 * tracks (issue #45).
 *
 * `console.c` is the console's *surface* - the command table, the
 * argument parser, the help text and the dispatch. This file is the
 * other half of the same rescope: the handler bodies that touch no
 * register and were therefore written twice by hand.
 *
 * Measured before it was written, because "the handlers are duplicated"
 * is true and was not specific enough to plan from. Of 48 handlers per
 * track, all 48 sharing a command letter, 17 have a paired named body:
 *
 *   4 program registers directly - cmd_crosstalk, cmd_profile,
 *     cmd_rate_sweep, measure_gpio - and STAY per track. That is
 *     invariant 3 doing its job, and no amount of tidying should move
 *     them.
 *   13 touch no register at all: 269 lines on Track B and 260 on
 *     Track A, about 529 lines expressing one logic.
 *
 * So the prize is real but smaller than a line count of the two files
 * suggests, and it is bounded by a rule rather than by taste.
 *
 * What arrives here must reach the outside world through console_port.h
 * and the other shared ports only. `printf`/`uart_flush` on Track B and
 * `Serial.print`/`Serial.flush` on Track A both become
 * console_write()/console_flush(), which is the difference that made
 * these two copies look different while saying the same thing.
 */
#include "console.h"
#include "console_port.h"
#include "ctl_port.h"
#include "ctl_wire.h"

/*
 * `f`: prove the fault handler by taking one deliberately.
 *
 * A jump to the start of SRAM, which is not executable code, so the
 * core takes an INVSTATE usage fault and the handler reports it. The
 * point is that the *reporter* works; a board that faults silently is
 * one that cannot tell you why it stopped, and this project has no
 * debug probe.
 *
 * The flush before the jump is load-bearing: the message has to be on
 * the wire before control leaves, or the evidence dies with the fault.
 */
void console_trigger_fault(void)
{
	console_write("# triggering deliberate hard fault (INVSTATE)...\n");
	console_flush();

	void (*bad)(void) = (void (*)(void))0x20000000;
	bad();

	console_write("# unreachable\n");
	console_flush();
}

/*
 * `w` with no argument: what the internal generator is set to.
 *
 * Already written to be track-agnostic before it moved - it asks
 * ctl_port_gen_get(), which is the per-track half, and answers "no
 * generator on this track" when there is none. ctl_gen_describe()
 * formats it, and ctl_wire.h notes that the description is shared while
 * the measurement behind it stays per track.
 */
void console_gen_report(void)
{
	char line[160];
	ctl_gen_t g;

	if (!ctl_port_gen_get(&g)) {
		console_write("# no generator on this track\n");
		console_flush();
		return;
	}
	ctl_gen_describe(line, sizeof(line), &g);
	console_write("# ");
	console_write(line);
	console_write("\n");
	console_flush();
}


/*
 * The crosstalk settle wait, spun on the device clock rather than any
 * track's delay().
 *
 * Shared because the two copies **must not differ**, not merely because
 * they were duplicated. Issue #16 measures what happens *between* two
 * conversions, so a wait that differs between the tracks changes the
 * thing being measured - and the two figures then are not comparable,
 * which is exactly what happened when Track B spun 400,000 iterations
 * and Track A called delay(10). Both were corrected to a micros() spin
 * and a comment on each side asked the other to stay that way.
 *
 * A comment is not a mechanism. One body is.
 *
 * ctl_port_micros() rather than a direct micros(): Track A's comes from
 * the Arduino core and Track B's from bsp.h, and the port already
 * exists to name that difference. delay() is what must not be used -
 * it calls yield() and snaps to the SysTick millisecond, so it is
 * neither the same duration nor the same activity as a spin.
 */
void console_bleed_settle(uint32_t ms)
{
	uint32_t t0 = ctl_port_micros();

	while (ctl_port_micros() - t0 < ms * 1000u)
		{ }
}
