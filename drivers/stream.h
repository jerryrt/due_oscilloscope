#ifndef STREAM_H
#define STREAM_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

bool stream_start(uint32_t trigger_hz);
bool stream_start_uart(uint32_t trigger_hz);
void stream_stop(void);
void stream_service(void);
void stream_report(void);

/* Transport benchmarks, decoupled from the converters. */
void stream_flood_start(void);   /* IN  : device -> host */
void stream_sink_start(void);    /* OUT : host -> device */
void stream_duplex_start(void);  /* both at once, the real target */
void stream_bench_report(void);
#endif
