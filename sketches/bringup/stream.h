#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stddef.h>

bool stream_start(uint32_t trigger_hz);
bool stream_start_capture_only(uint32_t trigger_hz, unsigned n_channels);
bool stream_start_uart(uint32_t trigger_hz);
void stream_stop(void);
bool stream_active(void);
bool stream_in_in_use(void);    /* anything is writing bulk IN */
bool stream_out_in_use(void);   /* a bench mode is consuming bulk OUT */
void stream_service(void);
void stream_report(char *buf, size_t n);
/* Returns what snprintf did, so a caller may append to the same line
 * rather than spend another one - see cmd_stream_stats(). */
int  stream_dma_report(char *buf, size_t n);

/*
 * Transport benchmarks, decoupled from the converters.
 *
 * Every streaming measurement is bounded by the ADC, so the link ceiling
 * is not visible there: a ratio of 1.000 only proves the transport kept
 * up with what was asked of it. These push each direction with synthetic
 * data to find where the transport itself gives out.
 */
void stream_flood_start(void);      /* IN  : device -> host */
void stream_sink_start(void);       /* OUT : host -> device */
void stream_duplex_start(void);     /* both at once, the real target */
void stream_bench_report(char *buf, size_t n);

/*
 * Main-loop passes, bumped by the sketch's loop(). The DMA benches
 * re-arm at most one transfer per pass, so passes per second is the
 * ceiling on transfers per second and the first thing to check when a
 * direction comes in under the wire.
 */
extern volatile uint32_t stream_loop_passes;

/*
 * The same three over UOTGHS endpoint DMA. The Arduino core never
 * programs a DMA channel itself, so these drive the controller directly
 * while leaving enumeration to the core; see usbdma.h.
 */
void stream_flood_dma_start(void);
void stream_sink_dma_start(void);
void stream_duplex_dma_start(void);

#endif /* STREAM_H */
