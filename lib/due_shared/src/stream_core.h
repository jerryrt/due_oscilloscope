/*
 * stream_core.h - the shared framer.
 *
 * Frame building, sequencing, overrun accounting and the resync rule,
 * written once. Each track's stream file wraps this with its own
 * transport shims, bench arms and reporting - those stay per track on
 * purpose: the bench numbers are each file's own, and the reports are
 * per-track surface. Dependencies are declared in stream_port.h and
 * nowhere else.
 */
#ifndef STREAM_CORE_H
#define STREAM_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
	bool     active;
	uint32_t started_us;              /* for a report's raw elapsed */
	uint32_t frames, bytes, run_us;   /* run_us: 0 unless active */
	uint32_t rate_hz;
	uint32_t resync, pending_overrun;
	uint32_t write_fail, short_write; /* CPU path only */
	uint32_t usb_us, usb_bytes;       /* CPU path only */
	uint32_t dma_frames, dma_stalls;
} stream_core_stats_t;

/*
 * usb selects the transport the caller wired stream_port_write to:
 * true arms endpoint DMA for the duration (the sample path), false is
 * the CPU-copied fallback (UART). with_gen brackets the internal
 * generator around the capture; the host-fed loop passes false and
 * drives the DAC from play instead.
 */
bool stream_core_start(uint32_t trigger_hz, bool with_gen,
                       unsigned n_channels, bool usb);
void stream_core_stop(void);
void stream_core_service(void);
bool stream_core_active(void);
void stream_core_get_stats(stream_core_stats_t *out);

#ifdef __cplusplus
}
#endif

#endif /* STREAM_CORE_H */
