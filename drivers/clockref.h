/*
 * The USB host's frame clock, as a frequency reference the board always has.
 *
 * Issue #52. Every rate here descends from MCK - the ADC trigger, the DAC
 * timer, and the microsecond counter `runus` is read from - and CLAUDE.md
 * states MCK is 78 MHz as a *register-derived* figure, read back from the
 * PLL settings. It had never been measured until 2026-08-30.
 *
 * **Why this board has a reference at all.** It is USB-powered and
 * USB-connected: it cannot be running without a host, and a host emits SOF
 * every 1 ms (125 us per microframe at High Speed). So a frequency
 * reference is a standing property of the design rather than a rig
 * somebody has to attach. `UOTGHS_DEVFNUM` counts those packets in
 * hardware.
 *
 * **Why it beats measuring from the host.** `tools/clock_calib.py` compares
 * device time against host wall time and has to model ~16 ms of per-run
 * host overhead out of the answer with a two-length regression; its
 * repeatability on windows-desk is 16 ppm, dominated by the host clock's
 * ~1 ms step. Counting SOF has no host software timing in it at all, and
 * it is continuous - so it can show MCK moving *within* a run, which a
 * comparison of run totals cannot.
 *
 * **What it cannot do.** SOF is spec'd to +/-500 ppm and is only as good as
 * the host controller's crystal. This measures the device against *that
 * host*, not against truth. It buys continuity and the removal of software
 * jitter, not absolute accuracy.
 *
 * Invariants 6 and 7: one read of a read-only register per main-loop pass,
 * constant time, no ISR, no allocation, no printf. It is polled by the
 * loop rather than driven by an interrupt because the loop is where
 * bounded work belongs.
 */
#ifndef CLOCKREF_H
#define CLOCKREF_H

#include <stdbool.h>
#include <stdint.h>

/*
 * FNUM is 11 bits and wraps every 2048 frames - 2.048 s. Extending it to
 * 32 bits therefore requires a poll more often than that, and the poll
 * cannot merely assume it happened: a pass that blocks for longer loses a
 * wrap silently, and this project has measured a single print costing
 * 108 ms. So a stall long enough to be ambiguous is COUNTED rather than
 * guessed at, and the host is told.
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
bool clockref_read(uint32_t *frames, uint32_t *dev_us,
                   uint16_t *fnum, uint8_t *mfnum);

/* Polls that were too far apart to resolve a wrap. Non-zero means the
 * frame count is a lower bound, not a count. */
uint32_t clockref_ambiguous(void);

#endif /* CLOCKREF_H */
