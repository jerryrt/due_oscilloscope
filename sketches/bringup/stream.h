#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stddef.h>

bool stream_start(uint32_t trigger_hz);
bool stream_start_capture_only(uint32_t trigger_hz);
bool stream_start_uart(uint32_t trigger_hz);
void stream_stop(void);
bool stream_active(void);
bool stream_out_in_use(void);   /* a bench mode is consuming bulk OUT */
void stream_service(void);
void stream_report(char *buf, size_t n);

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
 * Track B's G/T/Y run the same three over endpoint DMA. Track A cannot:
 * the Arduino CDC stack copies into the endpoint FIFO a byte at a time
 * and never programs a UOTGHS DMA channel. The counterparts exist so
 * the key still answers, and say so rather than silently doing the
 * manual-FIFO thing under a DMA name.
 */
void stream_dma_unavailable(char *buf, size_t n);

#endif /* STREAM_H */
