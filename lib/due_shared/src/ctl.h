/*
 * The native port's control channel: framing and dispatch.
 *
 * Why this exists at all is in docs/control-protocol.md, and the short
 * version is that a deployed board is one cable and that cable is the
 * native port, so a control path behind the programming port does not
 * exist in deployment. The transport is a second CDC function
 * (usb_ctl_read/usb_ctl_write); this is the protocol on top of it.
 *
 * The wire format is a contract shared with Track A, which reaches it
 * through different code. It is defined here and in the document, and
 * changing one without the other is what the --track=both tests exist
 * to catch.
 */

#ifndef CTL_H
#define CTL_H

/*
 * The wire format itself is shared: lib/due_shared/src/ctl_wire.h,
 * compiled by both tracks. What is left here is this track's device
 * side - the parser's entry point and its counters.
 */
#include "ctl_wire.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Pump the channel. Call from the main loop.
 *
 * Also what keeps the command endpoint drained: an allocated bulk OUT
 * that nobody reads NAKs forever and hangs the host in close(), so this
 * must keep being called even when no host is talking.
 */
void ctl_service(void);

/* Counters, for `u`. Frames that arrived, frames rejected, and
 * responses that could not be written because the host stopped
 * reading - the last one is the only way a dropped answer is visible,
 * since the protocol's own rule is that silence is never valid. */
extern volatile uint32_t ctl_rx_frames;
extern volatile uint32_t ctl_rx_bad;
extern volatile uint32_t ctl_tx_dropped;

/* Print them, for `u`. Never from an ISR and never while streaming. */
void ctl_dump(void);

#ifdef __cplusplus
}
#endif

#endif /* CTL_H */
