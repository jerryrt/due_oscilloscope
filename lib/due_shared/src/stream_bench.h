/*
 * stream_bench.h - the transport benchmarks, shared.
 *
 * The arms push synthetic frames so the link can be measured without
 * the converters bounding it. Policy - budgets, alternation, the
 * double-buffered DMA scheme - lives once here; the transport and the
 * registers stay per track behind stream_port.h. Reports stay per track
 * too: they read the counters through stream_bench_get_stats.
 */
#ifndef STREAM_BENCH_H
#define STREAM_BENCH_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
	STREAM_BENCH_OFF, STREAM_BENCH_FLOOD, STREAM_BENCH_SINK,
	STREAM_BENCH_DUPLEX, STREAM_BENCH_FLOOD_DMA, STREAM_BENCH_SINK_DMA,
	STREAM_BENCH_DUPLEX_DMA
} stream_bench_mode_t;

typedef struct {
	uint32_t mode;
	uint32_t in_bytes, out_bytes, elapsed_us;
	uint32_t resets, turn, dma_in_arms, dma_out_arms;
} stream_bench_stats_t;

void stream_bench_start(stream_bench_mode_t m);
void stream_bench_stop(void);        /* DMA-mode teardown + mode off */
void stream_bench_service(void);
stream_bench_mode_t stream_bench_mode(void);
void stream_bench_get_stats(stream_bench_stats_t *out);

#ifdef __cplusplus
}
#endif

#endif /* STREAM_BENCH_H */
