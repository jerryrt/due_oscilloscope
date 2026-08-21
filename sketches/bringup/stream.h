#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stddef.h>

void stream_start(uint32_t trigger_hz);
void stream_start_capture_only(uint32_t trigger_hz);
void stream_stop(void);
bool stream_active(void);
void stream_service(void);
void stream_report(char *buf, size_t n);

/*
 * Transport benchmarks, decoupled from the converters.
 *
 * Every streaming measurement so far was bounded by the ADC, so the link
 * ceiling is unknown: a ratio of 1.000 only proves the transport kept up
 * with what was asked of it. These push each direction with synthetic
 * data to find where the transport itself gives out.
 */
void stream_flood_start(void);      /* device -> host, as fast as accepted */
void stream_sink_start(void);       /* host -> device, drain and count */
void stream_bench_report(char *buf, size_t n);

#endif /* STREAM_H */
