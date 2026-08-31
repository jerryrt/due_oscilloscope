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
static uint32_t edge_us;       /* micros() when that edge was seen */
static uint32_t epoch_us;      /* micros() at the FIRST edge */
static bool     started;

void clockref_init(void)
{
	frames = 0u;
	ambiguous = 0u;
	last_fnum = 0u;
	last_us = 0u;
	edge_frames = 0u;
	edge_us = 0u;
	epoch_us = 0u;
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
		epoch_us = now;
		edge_us = now;
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
	if ((uint32_t)(now - last_us) > CLOCKREF_STALL_US)
		ambiguous++;

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
	if (cur != last_fnum) {
		frames += (uint32_t)((cur - last_fnum) &
		                     (CLOCKREF_FRAME_WRAP - 1u));
		edge_frames = frames;
		edge_us = now;
	}
	last_fnum = cur;
	last_us = now;
}

bool clockref_read(uint32_t *out_frames, uint32_t *out_us,
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
		*out_us = (uint32_t)(edge_us - epoch_us);
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
