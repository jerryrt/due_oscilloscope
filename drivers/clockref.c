/*
 * See clockref.h. UOTGHS_DEVFNUM, extended to 32 bits by the main loop.
 */

#include "clockref.h"

#include "sam.h"
#include "bsp.h"
#include "usb_cdc.h"

static uint32_t frames;        /* extended count since the first poll */
static uint32_t ambiguous;     /* polls too far apart to resolve a wrap */
static uint16_t last_fnum;
static uint32_t last_us;
static uint32_t edge_frames;   /* frames at the last observed SOF edge */
static uint64_t elapsed_us;    /* accumulated, wrap-safe: see the poll */
static uint64_t edge_elapsed;  /* elapsed_us latched at the last clean edge */
static uint32_t restarts;      /* spans abandoned after an unresolvable gap */
static bool     started;

void clockref_init(void)
{
	frames = 0u;
	ambiguous = 0u;
	last_fnum = 0u;
	last_us = 0u;
	edge_frames = 0u;
	elapsed_us = 0u;
	edge_elapsed = 0u;
	restarts = 0u;
	started = false;
}

void clockref_poll(void)
{
	uint32_t fn, now;
	uint16_t cur;

	/*
	 * No host, no frames. Reporting zero here would be a measurement -
	 * the same error CLAUDE.md's per-track rule forbids for an opcode a
	 * track does not implement - so the unstarted state is carried and
	 * clockref_read() refuses instead.
	 *
	 * CONFIGURED, not ready. usb_cdc_ready() also requires DTR, because
	 * a writer must not push at a host that is not reading - but SOF
	 * arrives from the moment the host configures the device, and this
	 * was written against ready() first: the reference reported
	 * "unavailable" on a board that was enumerated and running, because
	 * nothing happened to have the native port open. A clock that stops
	 * when an application closes a serial port is useless for the long
	 * unattended runs it exists to serve.
	 */
	if (!usb_cdc_configured()) {
		started = false;
		return;
	}

	fn = UOTGHS->UOTGHS_DEVFNUM;
	cur = (uint16_t)((fn & UOTGHS_DEVFNUM_FNUM_Msk) >>
	                 UOTGHS_DEVFNUM_FNUM_Pos);
	now = micros();

	if (!started) {
		started = true;
		last_fnum = cur;
		last_us = now;
		/*
		 * The epoch, and it is the whole reason this is not a bug.
		 * `frames` counts from here; if dev_us were reported as an
		 * ABSOLUTE micros() the pair would have two different
		 * origins and the ratio would carry all the time between
		 * boot and enumeration. Measured before this line existed:
		 * +2947 ppm at one minute, falling to +2947*0.7 by ninety
		 * seconds - a fixed offset divided by a growing window,
		 * which is exactly what a wrong epoch looks like.
		 */
		return;
	}

	/*
	 * The wrap is inferred from the counter going backwards, which is
	 * only sound while polls are closer together than one wrap. A pass
	 * that blocked for longer than CLOCKREF_STALL_US cannot be resolved
	 * - the counter may have wrapped any number of times - so the
	 * ambiguity is COUNTED and the host is told the frame total is a
	 * lower bound. Guessing here would be the same mistake as a
	 * classifier with two outcomes for a three-outcome world.
	 */
	/*
	 * An unresolvable gap RESTARTS the span rather than poisoning it.
	 *
	 * The first version counted the ambiguity and left `frames` a lower
	 * bound for ever, so mck_meas_hz went dark permanently. Found by
	 * leaving a board up for seven hours: two gaps in 25 million frames
	 * and the figure never came back. That is the wrong behaviour for a
	 * health metric - it should heal.
	 *
	 * The ambiguity is still counted and still reported, because a
	 * reader must be able to see that a restart happened; what changes
	 * is that the NEXT span is clean and usable.
	 */
	if ((uint32_t)(now - last_us) > CLOCKREF_STALL_US) {
		ambiguous++;
		restarts++;
		frames = 0u;
		edge_frames = 0u;
		elapsed_us = 0u;
		edge_elapsed = 0u;
		last_fnum = cur;
		last_us = now;
		return;
	}

	/*
	 * 64-bit, accumulated from small wrap-safe deltas.
	 *
	 * micros() is uint32 and wraps every 71.6 minutes. Reporting
	 * `edge_us - epoch_us` is correct across ONE wrap and wrong across
	 * two, which a seven-hour soak duly demonstrated: 25,499,813 frames
	 * - 7.08 h, correct - against a dev_us of 4,025,307,502, which is
	 * 7.08 h modulo 2^32 and reads as 1.12 h. Every delta added here is
	 * one poll apart, so each is tiny and each subtraction is safe.
	 */
	elapsed_us += (uint64_t)(uint32_t)(now - last_us);

	/*
	 * Latch the pair AT a frame edge, not at read time.
	 *
	 * Read at an arbitrary moment, the frame count is quantised to 1 ms
	 * while dev_us is not, so a 30 s interval carries +/-1 frame = 33
	 * ppm - measured, before this: 10 s read +0.0 ppm and 30 s read
	 * -33.1, which is one frame short and nothing else. Sampling the
	 * microsecond count when the frame counter is SEEN to advance moves
	 * the quantisation onto the loop period instead, ~8 us here, which
	 * is 0.27 ppm over 30 s.
	 */
	{
		uint32_t step = (uint32_t)((cur - last_fnum) &
		                           (CLOCKREF_FRAME_WRAP - 1u));

		frames += step;
		/*
		 * Latch only on a SINGLE-frame advance.
		 *
		 * The latch is worth having because it bounds the edge by
		 * the poll interval - but only when the poll SAW that one
		 * frame. If two or more elapsed, the pass was longer than a
		 * frame and the edge could have been anywhere in it, so the
		 * pair would be stale by up to the pass length.
		 *
		 * This is not hypothetical on this track: the load monitor
		 * measures a worst-case pass of 13 ms here, thirteen frames.
		 * Before this line Track B read +9.7 to +24.1 ppm while
		 * Track A - same board, same minute, its own programming of
		 * the same register - read +13.67 to +13.72, a spread of
		 * 0.05. The frames themselves are never lost; only the
		 * timestamp is refused.
		 */
		if (step == 1u) {
			edge_frames = frames;
			edge_elapsed = elapsed_us;
		}
	}
	last_fnum = cur;
	last_us = now;
}

bool clockref_read(uint32_t *out_frames, uint64_t *out_us,
                   uint16_t *out_fnum, uint8_t *out_mfnum)
{
	uint32_t fn;

	if (!started)
		return false;

	fn = UOTGHS->UOTGHS_DEVFNUM;
	/* The latched pair, so frames and dev_us describe the same instant -
	 * and dev_us is ELAPSED SINCE THE EPOCH, so both count from the same
	 * origin. */
	if (out_frames)
		*out_frames = edge_frames;
	if (out_us)
		*out_us = edge_elapsed;
	if (out_fnum)
		*out_fnum = (uint16_t)((fn & UOTGHS_DEVFNUM_FNUM_Msk) >>
		                       UOTGHS_DEVFNUM_FNUM_Pos);
	if (out_mfnum)
		*out_mfnum = (uint8_t)((fn & UOTGHS_DEVFNUM_MFNUM_Msk) >>
		                       UOTGHS_DEVFNUM_MFNUM_Pos);
	return true;
}

uint32_t clockref_ambiguous(void)
{
	return ambiguous;
}

uint32_t clockref_restarts(void)
{
	return restarts;
}
