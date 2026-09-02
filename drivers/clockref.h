/*
 * The USB host's frame clock, as a frequency reference the board
 * always has: it is USB-powered and USB-connected, so a host emitting
 * SOF every 1 ms (125 us per microframe at High Speed) is a standing
 * property of the design, not a rig someone has to attach.
 * UOTGHS_DEVFNUM counts those packets in hardware.
 *
 * SOF is spec'd to +/-500 ppm and only as good as the host
 * controller's crystal, so this measures the device against *that
 * host*, not against absolute truth.
 *
 * Invariants 6 and 7: one read of a read-only register per main-loop
 * pass, constant time, no ISR, no allocation, no printf.
 */
#ifndef CLOCKREF_H
#define CLOCKREF_H

#include <stdbool.h>
#include <stdint.h>

/*
 * FNUM is 11 bits and wraps every 2048 frames - 2.048 s. Extending it
 * to 32 bits therefore requires a poll more often than that, and the
 * poll cannot merely assume it happened: a pass that blocks for
 * longer loses a wrap silently. So a stall long enough to be
 * ambiguous is COUNTED rather than guessed at, and the host is told.
 */
#define CLOCKREF_FRAME_WRAP   2048u
#define CLOCKREF_STALL_US  1500000u   /* < one wrap, with margin */

void clockref_init(void);

/* Called once per main-loop pass. Constant time: one register read, one
 * comparison, and at most one 32-bit add. */
void clockref_poll(void);

/* frames since init, extended past FNUM's 11 bits; false if the port has
 * never enumerated, in which case there is no reference and the caller
 * must say so rather than report zero. */
bool clockref_read(uint32_t *frames, uint64_t *dev_us,
                   uint16_t *fnum, uint8_t *mfnum);

/*
 * How many times the span has been restarted because a poll gap could
 * not be resolved. Non-zero is not an error - it is the metric healing
 * rather than staying dark - but it means `frames` counts from the last
 * restart and not from enumeration.
 */
uint32_t clockref_restarts(void);

/* Polls that were too far apart to resolve a wrap. Non-zero means the
 * frame count is a lower bound, not a count. */
uint32_t clockref_ambiguous(void);

#endif /* CLOCKREF_H */
