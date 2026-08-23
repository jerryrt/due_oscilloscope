/*
 * Playback status on bulk IN: the carrier for the host's rate loop.
 *
 * Objective 0i needs the host to know what the converter is actually
 * consuming, and the console cannot carry it. Polling `B` at 20 Hz took
 * RC 65 from 6 underruns to 30 when the ring was short, because a
 * printf holds the main loop for milliseconds against a 0.95 us
 * conversion. So the signal goes out on the native port's bulk IN,
 * which is idle in play-only.
 *
 * Play-only, and nowhere else. In loop mode bulk IN carries capture
 * frames and the IN endpoint is on DMA; mixing the FIFO path with DMA
 * on one endpoint is a documented way to wedge it (see stream.c), and
 * splicing these records into a frame stream would corrupt framing.
 * The emitter checks stream_in_in_use() and stays silent. Loop mode
 * gets the same numbers from the capture frame header's spare fields
 * instead - it has room and costs nothing.
 *
 * dev_us is sampled at emit time rather than taken from play_run_us,
 * which play_service updates and which can therefore be a main-loop
 * pass stale. The host differences consecutive records, so it needs the
 * timestamp paired with the counter, not the run total.
 *
 * The magic differs from FRAME_MAGIC deliberately, and the record
 * carries a CRC: a host parser that meets one of these in a stream it
 * did not expect must reject it rather than half-read it.
 */

#ifndef PLAYSTAT_H
#define PLAYSTAT_H

#include <stdint.h>

#define PLAYSTAT_MAGIC0 'D'
#define PLAYSTAT_MAGIC1 'U'
#define PLAYSTAT_MAGIC2 'E'
#define PLAYSTAT_MAGIC3 'P'
#define PLAYSTAT_VERSION 1

/* Emit interval. The outer loop the host closes on is deliberately
 * slow - much longer than the pipeline delay - so this only has to be
 * fine enough to average, not to track. */
#define PLAYSTAT_MS 20u

typedef struct __attribute__((packed)) {
	uint8_t  magic[4];
	uint8_t  version;
	uint8_t  pad[3];
	uint32_t consumed;     /* buffers handed to the PDC */
	uint32_t underruns;    /* buffers repeated for want of data */
	uint32_t bytes_in;     /* bytes the OUT DMA has received */
	uint32_t dev_us;       /* device micros() at emit time */
	uint32_t crc32;        /* over everything above */
} playstat_t;

#endif /* PLAYSTAT_H */
