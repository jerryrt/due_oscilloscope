/*
 * What the control protocol needs from the track that hosts it.
 *
 * `ctl.c` touches no register - grep it for UOTGHS, DACC, ADC->, PIO or
 * REG_ and the count is zero. What keeps it from being fully shared is
 * five names it reaches for directly, none spelled the same way (or at
 * all) on both tracks: usb_ctl_read/write, micros(), millis() and
 * load_sample(). Each track provides these; the protocol calls nothing
 * else outside itself and the shared wire header. See
 * docs/shared-source.md.
 *
 * This is not an abstraction layer and must not grow into one: a
 * function earns its place here by being something a track genuinely
 * does differently. A subsystem accessor both tracks spell identically
 * - acq, stream, play - is called directly; a wrapper around it would
 * be indirection bought with nothing.
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
 * that nobody reads NAKs for ever and hangs the host in close().
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
 * names. It is the witness that separates "the device stopped draining"
 * from "the host stopped sending" when reading it during a wedge.
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
 * ---------------------------------------------------------------------
 * The per-opcode data.
 *
 * These exist because of an architectural fact rather than a build
 * accident: each track's own headers (acq.h, play.h, stream.h,
 * track_id.h) are independent implementations, not one shared header
 * that happens to live in a different folder - invariant 3 keeps
 * register programming un-shared, so the two tracks' versions differ in
 * shape as well as content. A file in this library that included one
 * directly would compile against exactly one track.
 *
 * So the split is "what every board does the same versus what a board
 * has to look up locally". Framing, the CRC, header validation, the
 * receive state machine, the idle timeout, dispatch and every error
 * path are the same everywhere and stay shared. Filling in a response
 * body means reading this track's counters, and that is here.
 *
 * The wire layout of each struct is still one definition in ctl_wire.h,
 * so a track can get a field wrong but cannot get the *format* wrong,
 * and tests/test_control.py checks the values against a real board on
 * both tracks.
 * ---------------------------------------------------------------------
 */

/*
 * The identity fields only a track knows: track letter, clocks, frame
 * geometry and build stamp. The caller fills in the three version
 * numbers, which are shared and must not be answered locally.
 */
void ctl_port_identity(ctl_identity_t *out);

/* CTL_OP_COUNTERS. Every field; the caller zeroes nothing. */
void ctl_port_counters(ctl_counters_t *out);

/*
 * CTL_OP_STREAM_STATS and CTL_OP_BENCH - what `?` and the bench half of
 * `B` print. False means this track does not keep them.
 *
 * Their payloads carry `usb_reset`, `usb_setup`, `usb_stall`,
 * `usb_configured`, `usb_devisr`, `usb_ep0isr` and `usb_devimr` -
 * counters kept by Track B's own USB stack. Track A enumerates through
 * the Arduino core and has no such numbers, so these are not universal
 * protocol; they are one track's internals that the control channel
 * happens to carry.
 *
 * The rule: an opcode a track does not implement is answered with
 * CTL_ERR_OPCODE, never with a body of zeroes. Zero is a measurement -
 * "the counter is there and it read nothing" - and a host cannot tell
 * that from "this firmware does not count that" unless the device says
 * so. The same rule covers the load monitor and the rate trace.
 */
/*
 * CTL_OP_CAPABILITY: which optional opcodes this build implements, as a
 * bitmask of CTL_CAP_*. ctl_dispatch() consults this *before*
 * dispatching an optional opcode, so the capability reply and the
 * CTL_ERR_OPCODE refusal are the same fact read once - do not add a
 * second account of it.
 *
 * It answers "does this build dispatch the opcode", not "is the thing
 * working right now" - CTL_OP_LOAD's payload still carries its own
 * `available`, and a part without CYCCNT says so there.
 */
uint32_t ctl_port_capabilities(void);

bool ctl_port_stream_stats(ctl_stream_stats_t *out);
bool ctl_port_bench(ctl_bench_t *out);

/*
 * CTL_OP_OCCUPANCY. Writes the whole body - header, per-slot histogram
 * and trace - and returns its length, because the sizes come from this
 * track's PLAY_NBUF and PLAY_OCC_TRACE. Returns -1 if this track does
 * not keep the histogram, which is answered as CTL_ERR_OPCODE.
 */
int ctl_port_occupancy(uint8_t *body, size_t max);

/*
 * CTL_OP_RATE_TRACE, one page from `offset`. Same contract, and -1 is
 * the expected answer on a track built without the rate trace - Track A
 * has no PLAY_RATE_TRACE at all, and Track B compiles it out by
 * default (PLAY_RATE_TRACE_ENABLED 0).
 */
int ctl_port_rate_page(uint8_t *body, size_t max, uint16_t offset);

/*
 * CTL_OP_GEN. The per-track part of the generator command, calling that
 * track's own gen driver - the driver stays two independent
 * implementations (invariant 3) while the command's meaning is shared.
 * A track with no generator returns false from get(), answered as
 * CTL_ERR_OPCODE.
 */
bool ctl_port_gen_get(ctl_gen_t *out);
void ctl_port_gen_set(uint8_t shape, uint16_t points, uint8_t sync,
                      uint16_t amp, uint16_t sync_amp);

/*
 * CTL_OP_TEMP. Read the on-die temperature sensor, averaging `samples`
 * conversions, and fill in the report.
 *
 * Returns CTL_TEMP_OK, CTL_TEMP_UNSUPPORTED (this track does not read
 * it -> CTL_ERR_OPCODE) or CTL_TEMP_BUSY (a capture is armed and
 * switching channels would corrupt it -> CTL_ERR_BUSY). Three outcomes
 * rather than a bool because the two refusals have different remedies:
 * one never becomes true, the other is fixed by retrying.
 *
 * `samples` is a request, not a promise: the callee clamps it to
 * [CTL_TEMP_SAMPLES_MIN, CTL_TEMP_SAMPLES_MAX] and reports what it
 * actually averaged (invariant 7's bounded worst case).
 */
int ctl_port_temp(ctl_temp_t *out, uint16_t samples);

/*
 * The USB frame reference. Fills `frames` and `dev_us` from a pair
 * latched AT a SOF edge, and `ambiguous` with the count of polls too far
 * apart to resolve FNUM's 2.048 s wrap. Returns 0 when the port has
 * never been configured - and MUST NOT fill zeroes and return non-zero,
 * because zero is a measurement and a host cannot tell it from an
 * absence.
 */
int ctl_port_sof(uint32_t *frames, uint64_t *dev_us, uint32_t *ambiguous,
                 uint32_t *restarts);

/* The clock every rate here descends from, as the track knows it.
 * Shared code must not assume 78 MHz. */
uint32_t ctl_port_mck_hz(void);

/*
 * Start, retune or stop the timer that drives the heartbeat.
 * `period_ms` of 0 stops it; anything else is a cadence the caller has
 * already clamped. The track programs a spare timer channel so its
 * interrupt calls ctl_heartbeat_emit_isr() at that rate and nothing
 * else.
 *
 * Per-track by requirement, not convenience: both tracks would spell
 * the register sequence almost identically, and invariant 3 refuses
 * that anyway. The frame the interrupt sends is protocol and stays
 * shared; the registers that make it fire are not.
 *
 * Called from the main loop only, never from the interrupt it controls.
 */
void ctl_port_heartbeat_timer(uint32_t period_ms);

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
