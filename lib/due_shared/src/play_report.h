/*
 * The `# play:` console line, shared by both tracks.
 *
 * Issue #13's finding applied to a status line rather than a command
 * table: **the surface is shared, the handlers are not.** The counters
 * behind these fields are each track's own - `drivers/play.c` against
 * `sketches/bringup`, two independent programmings of one peripheral,
 * which invariant 3 requires. The *line* is not. It is application
 * formatting, and it was written twice by hand.
 *
 * It had already drifted, in the way hand-copies do. Track A printed
 * `svc` between `endtx` and `spans`; Track B printed no `svc` at all,
 * though `play_svc_calls` is counted in `drivers/play.c` and was
 * already going out over its control channel. So every field after
 * `endtx` sat one position out between the tracks, and `tools/bench.py`
 * - whose regex was written against Track B - read Track A's line into
 * the wrong columns and reported an unread counter as a 100% byte
 * deficit (fixed in `412935d` by parsing names, which was right and
 * left the divergence itself in place).
 *
 * That is not a per-track capability. `CLAUDE.md` calls a capability on
 * one track and not the other debt with a date on it, and this one
 * turned out to be a missing printf argument.
 *
 * What genuinely is per-track trails at the end, appended by the track
 * at the offset this returns: Track A's `rebuilds`, `act-in` and
 * `act-out` are its UOTGHS DMA counters and Track B has nothing to put
 * there. A positional reader then degrades to "the fields I know"
 * rather than silently reading the wrong column.
 *
 * No I/O here. The caller owns the buffer and the sink, because the two
 * tracks reach the console through different ports - which is
 * `stream_port.h`'s rule and the same reason.
 */
#ifndef PLAY_REPORT_H
#define PLAY_REPORT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The counters both tracks keep. Field order here is documentation
 * only; the wire order is play_report_print()'s emit order. */
typedef struct {
	uint32_t bytes_in;    /* bytes the OUT path has received      */
	uint32_t produced;    /* buffers filled from the host feed    */
	uint32_t consumed;    /* buffers handed to the PDC            */
	uint32_t underruns;   /* buffers repeated for want of data    */
	uint32_t isr_calls;   /* PDC completion interrupts            */
	uint32_t endtx_seen;  /* ENDTX guard hits                     */
	uint32_t svc_calls;   /* play_service entries while active    */
	uint32_t spans;       /* contiguous spans handed to the PDC   */
	uint32_t partial;     /* short spans at a ring wrap           */
	uint32_t occ_min;     /* low-water mark of ring occupancy     */
} play_report_t;

/*
 * Emit the shared `# play:` prefix, with no trailing newline, so a
 * track may append the counters only it can produce and then end the
 * line itself:
 *
 *     play_report_print(&r);
 *     con_str(" rebuilds="); con_u32(usbdma_rebuilds);
 *     con_nl();
 *
 * Bounded by construction rather than by a buffer size: every emitter
 * has a compile-time worst case in bytes (console_out.h), so invariant
 * 7 holds without a caller having to size anything.
 */
/*
 * Emit the shared prefix - no newline, so a track can append the
 * counters only it can produce and then end the line itself. It was
 * play_report_format(buf, n, r) returning the length for exactly that
 * append; with emitters the offset is implicit and there is no buffer
 * to size. Issue #49.
 */
void play_report_print(const play_report_t *r);

#ifdef __cplusplus
}
#endif

#endif /* PLAY_REPORT_H */
