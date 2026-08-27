/*
 * What the control protocol needs from the track that hosts it.
 *
 * `ctl.c` is 526 lines of framing, CRC and dispatch that touch no
 * register - grep it for UOTGHS, DACC, ADC->, PIO or REG_ and the count
 * is zero. What kept it from being shared was not hardware but four
 * names it reached for directly: usb_ctl_read/usb_ctl_write from
 * drivers/usb_cdc.h, micros() from bsp.h, load_sample() from
 * bsp/load.h, and uart_flush() in the debug dump. Three of those
 * headers do not exist on Track A.
 *
 * So name the dependency instead of inheriting it. Each track provides
 * these five functions; the protocol calls nothing else outside itself
 * and the shared wire header. See docs/shared-source.md.
 *
 * **This is not an abstraction layer and must not grow into one.** It
 * exists so one parser can serve two tracks, and every function here
 * earns its place by being something a track genuinely does
 * differently. A subsystem accessor that both tracks spell identically
 * - acq, stream, play - is called directly, because a wrapper around it
 * would be indirection bought with nothing.
 */
#ifndef CTL_PORT_H
#define CTL_PORT_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#include "ctl_wire.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Bytes waiting on the command endpoint, up to `max`. Returns 0 when
 * there is nothing, never blocks.
 *
 * The protocol polls this from the main loop and the endpoint must be
 * drained whether or not anything is talking: an allocated bulk OUT
 * that nobody reads NAKs for ever and hangs the host in close(). Track
 * A learned that the expensive way - see the 2026-08-26 entry in
 * docs/HANDOFF.md, where a writer stalled at 48 KB.
 */
size_t ctl_port_read(uint8_t *dst, size_t max);

/*
 * One response, one write. Returns the number of bytes accepted, which
 * the caller compares against what it offered - a short write is a
 * dropped answer and is counted, because the protocol's own rule is
 * that silence is never a valid reply.
 */
size_t ctl_port_write(const uint8_t *src, size_t len);

/*
 * Microseconds, free-running and allowed to wrap. Every comparison in
 * the protocol is an unsigned subtraction for that reason.
 */
uint32_t ctl_port_micros(void);

/*
 * Milliseconds since boot, for the one field that reports uptime rather
 * than measuring an interval. Separate from ctl_port_micros() because
 * both tracks already have both, and deriving one from the other would
 * either overflow sooner or cost a division on a path that does not
 * need one.
 */
uint32_t ctl_port_millis(void);

/*
 * How many main-loop passes have taken the bulk-OUT drain branch.
 *
 * A transport statistic and therefore per-track: the two tracks drive
 * the endpoint through different code and count it under different
 * names. It is in CTL_OP_COUNTERS because it is the witness that
 * separates "the device stopped draining" from "the host stopped
 * sending" - which is objective 0c's whole question, and was answered
 * by reading this counter during a wedge.
 */
uint32_t ctl_port_out_drain_polls(void);

/*
 * Fill in a load report. False means this track has no load monitor,
 * and CTL_OP_LOAD is answered with CTL_ERR_OPCODE rather than with
 * zeroes - a host must be able to tell "not measured here" from
 * "measured, and idle".
 */
bool ctl_port_load_sample(load_report_t *out);

/*
 * Flush the debug console. Only ctl_dump() uses this, it is never
 * called while the sample path is running, and a track whose console
 * needs no flushing implements it empty.
 */
void ctl_port_console_flush(void);

#ifdef __cplusplus
}
#endif

#endif /* CTL_PORT_H */
