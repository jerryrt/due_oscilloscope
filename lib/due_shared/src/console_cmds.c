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
#include <stdio.h>

#include "console.h"
#include "console_port.h"
#include "console_out.h"
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

/*
 * `1`..`5`: start a capture stream, and say what it is about to do.
 *
 * BANNER FIRST, THEN START. Issue #41, and the order is the whole
 * point of this function existing once.
 *
 * Capture is device-driven: the ring fills from the moment the timer
 * runs and nothing has to ask it to. Invariant 8 prices a console line
 * at 13-20 ms of blocked main loop - this banner is ~160 characters and
 * was measured at 17.9-20.2 ms - while the ring holds STREAM_NBUF
 * frames, which at 453,488 Hz is 8.96 ms of runway. Printing after the
 * start spent the whole runway before the first drain and everything
 * past it was gone: exactly 3 frames, nine runs of nine, on three
 * benches and three hosts, with zero growth afterwards because the loss
 * is spent before the first transfer rather than leaking.
 *
 * The shape is h_mimic's, which already printed before starting for
 * this reason and is the preset whose zero-at-every-rate localised the
 * defect. The banner announces intent; a refusal follows it if the
 * start fails. No host reads the banner as success - measure.py takes
 * success as the *absence* of "refused" - so the refusal arriving
 * second changes nothing above it.
 *
 * Two sites are NOT hazards and must not be "fixed": h_play prints
 * after a host-driven start that flows nothing until fed, and
 * cmd_stream_uart has 2019 ms of margin. docs/debugging.md carries the
 * table.
 *
 * The generator half needs no port: ctl_port_gen_get() already returns
 * the shape, points and sync that the two copies read out of their own
 * file-scope globals, and gen_shape_name()/gen_hz_for() have been
 * shared since the control channel landed. Only the start is per track.
 */
void console_cmd_stream(uint32_t trigger_hz)
{
	ctl_gen_t g;
	bool have_gen = ctl_port_gen_get(&g);

	con_str("# streaming: trigger "); con_u32(trigger_hz);
	con_str(" Hz, "); con_u32(trigger_hz * 2u);
	con_str(" sps aggregate");
	if (have_gen) {
		con_str(", "); con_str(gen_shape_name(g.shape)); con_ch(' ');
		con_u32(gen_hz_for(trigger_hz, g.points, g.sync));
		con_str(" Hz ("); con_u32(g.points);
		con_str(" pts/cycle)");
	}
	con_nl();

	if (have_gen)
		console_write(g.sync == GEN_SYNC_OFF
		              ? "# DAC1 holds mid scale: A1 must read flat, "
		                "or demux is wrong\n"
		              : "# DAC1 carries the sync: A1 must show a "
		                "square, not the waveform\n");
	console_flush();

	if (!console_port_stream_start(trigger_hz)) {
		con_str("# refused: "); con_u32(trigger_hz);
		con_str(" Hz is past the measured ADC ceiling"); con_nl();
		console_flush();
	}
}
