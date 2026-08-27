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
 * ---------------------------------------------------------------------
 * The per-opcode data.
 *
 * These exist because of a build fact rather than a design preference,
 * and the fact is worth stating: **a file inside the shared library
 * cannot include a header from a track's own folder.** arduino-cli
 * compiles a library with the library's include path, so ctl.c living
 * here cannot reach acq.h, play.h, stream.h or track_id.h on Track A -
 * measured, as `track_id.h: No such file or directory`.
 *
 * So the split is not "protocol versus hardware", which is where this
 * started, but "what every board does the same versus what a board has
 * to look up locally". Framing, the CRC, header validation, the receive
 * state machine, the idle timeout, dispatch and every error path are
 * the same everywhere and stay shared - about two thirds of the file.
 * Filling in a response body means reading this track's counters, and
 * that is here.
 *
 * The wire layout of each struct is still one definition in
 * ctl_wire.h, so a track can get a field wrong but cannot get the
 * *format* wrong, and tests/test_control.py checks the values against a
 * real board on both tracks.
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
 * These two are worth a note, because finding it out is what set the
 * rule below. Their payloads carry `usb_reset`, `usb_setup`,
 * `usb_stall`, `usb_configured`, `usb_devisr`, `usb_ep0isr` and
 * `usb_devimr` - counters kept by *Track B's own USB stack*. Track A
 * enumerates through the Arduino core and has no such numbers. So these
 * are not universal protocol; they are one track's internals that the
 * control channel happens to carry.
 *
 * **The rule: an opcode a track does not implement is answered with
 * CTL_ERR_OPCODE, never with a body of zeroes.** Zero is a
 * measurement - "the counter is there and it read nothing" - and a host
 * cannot tell that from "this firmware does not count that" unless the
 * device says so. The same rule covers the load monitor and the rate
 * trace.
 */
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
 * Flush the debug console. Only ctl_dump() uses this, it is never
 * called while the sample path is running, and a track whose console
 * needs no flushing implements it empty.
 */
/*
 * CTL_OP_GEN. The whole per-track part of the generator command: four
 * lines each, calling that track's own gen driver.
 *
 * The driver stays two independent implementations - invariant 3 names
 * gen among the register programming the tracks must not share, because
 * two programmings of one converter is what makes a divergence point at
 * one of them. What is shared is the command's meaning, which is not
 * register programming and had no business being written twice.
 *
 * A track with no generator returns false from get(), and the opcode
 * then answers CTL_ERR_OPCODE rather than a body of zeroes.
 */
bool ctl_port_gen_get(ctl_gen_t *out);
void ctl_port_gen_set(uint8_t shape, uint16_t points, uint8_t sync);

void ctl_port_console_flush(void);

#ifdef __cplusplus
}
#endif

#endif /* CTL_PORT_H */
