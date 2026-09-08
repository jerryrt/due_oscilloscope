/*
 * The loop diagnostic behind `D`, for the tracks that run this
 * drivers/ stack.
 *
 * NOT in lib/due_shared, and not shareable: every snapshot is a read of
 * DACC's PDC registers and the ADC's conversion data registers, which
 * invariant 3 keeps with the track. It is here rather than in a main()
 * for the reason usb_cdc_endpoint_state() is - Track C links this
 * driver unchanged and needs the same answer, and a copy in Track C's
 * main() would be the hand-copy invariant 3 was rescoped over. Track A
 * keeps its own, over its own registers.
 *
 * The cost of having it is one load and one branch per main-loop pass,
 * inline - diag_armed() rather than a call into diag_service() that
 * returns on a bool, for the reason load.h gives about load_tick():
 * this runs a hundred and forty thousand times a second, and a call
 * that does nothing costs more than the question it answers.
 */
#ifndef DIAG_H
#define DIAG_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Hot-path state. Public because the guard is inline; nothing outside
 * diag.c may write it. */
extern volatile bool diag_run;

/* The per-pass question. `if (diag_armed()) diag_service();` is how a
 * main loop carries this. */
static inline bool diag_armed(void)
{
	return diag_run;
}

/* Arm one run of twelve snapshots. Prints after the last of them, not
 * during: a printf mid-run would stall the very loops being observed. */
void diag_start(void);

/* Every main-loop pass. Returns immediately unless armed. */
void diag_service(void);

#ifdef __cplusplus
}
#endif

#endif /* DIAG_H */
