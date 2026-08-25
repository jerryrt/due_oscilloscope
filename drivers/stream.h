#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

bool stream_start(uint32_t trigger_hz);
bool stream_start_capture_only(uint32_t trigger_hz, unsigned n_channels);
bool stream_start_uart(uint32_t trigger_hz);
void stream_stop(void);
bool stream_out_in_use(void);   /* a bench mode is consuming bulk OUT */
bool stream_in_in_use(void);    /* anything is writing bulk IN */
void stream_service(void);
void stream_report(void);

/*
 * What `?` and `B` print, without printing them. Invariant 8: printf is
 * a debug method and not an instrument, and `?` alone is 24 numbers and
 * a uart_flush on a board that is streaming. The console forms stay for
 * a human at a terminal; nothing that measures may read them.
 *
 * Filled here rather than read as globals from ctl.c, because these are
 * stream.c's own counters and the control protocol is not a reason to
 * unstatic them.
 */
typedef struct {
	uint32_t dma_frames, dma_stalls;
	uint32_t frames, bytes, run_us;
	uint32_t produced, consumed, ring_overflow, resync, refused;
	uint32_t rxbuff_overruns, govre, gen_endtx;
	uint32_t usb_reset, usb_setup, usb_stall, usb_configured;
	uint32_t usb_line_state, usb_cfg_fail;
	uint32_t usb_isr, usb_devisr, usb_ep0isr, usb_devimr;
} stream_stats_t;

typedef struct {
	uint32_t mode, in_bytes, out_bytes, elapsed_us;
	uint32_t resets, turn, dma_in_arms, dma_out_arms, loop_passes;
} stream_bench_t;

void stream_get_stats(stream_stats_t *out);
void stream_get_bench(stream_bench_t *out);

/* Transport benchmarks, decoupled from the converters. */
void stream_flood_start(void);   /* IN  : device -> host */
void stream_sink_start(void);    /* OUT : host -> device */
void stream_duplex_start(void);  /* both at once, the real target */
void stream_flood_dma_start(void);
void stream_sink_dma_start(void);
void stream_duplex_dma_start(void);
void stream_bench_report(void);

/*
 * Main-loop passes, bumped by the application loop. The DMA benches
 * re-arm at most one transfer per pass, so passes per second is the
 * ceiling on transfers per second and the first thing to check when a
 * direction comes in under the wire.
 */
extern volatile uint32_t stream_loop_passes;
#endif
