/*
 * The `# play:` console line, shared by both tracks.
 *
 * The surface is shared, the handlers are not: the counters behind
 * these fields are each track's own (invariant 3's two independent
 * programmings of one peripheral), but the *line* is application
 * formatting and had no business being written twice by hand - two
 * hand-copies had already drifted a field out of step with each other
 * before this was shared.
 *
 * What genuinely is per-track trails at the end, appended by the track
 * at the offset this returns: Track A's `rebuilds`, `act-in` and
 * `act-out` are its UOTGHS DMA counters and Track B has nothing to put
 * there. A positional reader then degrades to "the fields I know"
 * rather than silently reading the wrong column.
 *
 * No I/O here. The caller owns the buffer and the sink, because the two
 * tracks reach the console through different ports - `stream_port.h`'s
 * rule and the same reason.
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
void play_report_print(const play_report_t *r);

#ifdef __cplusplus
}
#endif

#endif /* PLAY_REPORT_H */
