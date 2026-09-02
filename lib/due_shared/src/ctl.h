/*
 * The native port's control channel: framing and dispatch.
 *
 * A deployed board is one cable and that cable is the native port, so a
 * control path behind the programming port does not exist in
 * deployment - see docs/control-protocol.md. The transport is a second
 * CDC function (usb_ctl_read/usb_ctl_write); this is the protocol on
 * top of it.
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

/*
 * Send one heartbeat. Called from the track's timer interrupt, and from
 * nowhere else.
 *
 * This is the whole application half of the feature: the frame, the
 * counters it carries, the sequence number and the CRC are one piece of
 * code that both tracks run. What differs per track is only the timer
 * that calls it - see ctl_port_heartbeat_timer().
 */
void ctl_heartbeat_emit_isr(void);

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
