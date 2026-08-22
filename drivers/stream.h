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
void stream_service(void);
void stream_report(void);

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
