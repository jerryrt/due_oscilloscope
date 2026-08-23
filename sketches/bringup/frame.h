/*
 * Wire frame for the sample stream. See docs/protocol.md.
 *
 * Shared verbatim between Track A and Track B so the host receiver
 * cannot tell them apart.
 */

#ifndef FRAME_H
#define FRAME_H

#include <stdint.h>
#include <stddef.h>

#define FRAME_MAGIC0 'D'
#define FRAME_MAGIC1 'U'
#define FRAME_MAGIC2 'E'
#define FRAME_MAGIC3 '0'
#define FRAME_VERSION 2

#define FRAME_FLAG_OVERRUN     (1u << 0)
#define FRAME_FLAG_BURST_FIRST (1u << 1)
#define FRAME_FLAG_BURST_LAST  (1u << 2)
#define FRAME_FLAG_CONTINUOUS  (1u << 3)

/*
 * play_consumed carries the rate loop's signal in loop mode.
 *
 * In play-only the host gets it from the bulk-IN status record
 * (drivers/playstat.h), but in loop mode bulk IN carries frames and the
 * endpoint is on DMA, so nothing else may write there. The frame header
 * is the only channel left, and it already carries the other half of
 * what a rate estimate needs - timestamp_us is the same device clock -
 * so this completes the pair rather than adding one.
 *
 * Zero from the bench frame builders, which acquire nothing and play
 * nothing.
 */
typedef struct __attribute__((packed)) {
	uint8_t  magic[4];
	uint8_t  version;
	uint8_t  flags;
	uint8_t  bits_per_sample;
	uint8_t  packing;          /* 0 = 12-bit right aligned in 16-bit LE */
	uint32_t seq;
	uint32_t sample_rate_hz;   /* per channel */
	uint16_t n_samples;        /* across all channels */
	uint16_t channel_mask;     /* ADC channel indices, not A-labels */
	uint32_t timestamp_us;
	uint32_t overrun_count;
	uint32_t play_consumed;    /* playback buffers the DAC has taken */
	uint32_t header_crc32;     /* over the preceding 32 bytes */
} frame_header_t;

/*
 * Deliberately no payload CRC. USB already provides a per-packet CRC-16
 * with hardware retry, and computing one here would make the CPU read
 * the whole sample stream, which is the one thing the architecture
 * forbids.
 */
uint32_t frame_crc32(const uint8_t *data, size_t len);

#endif /* FRAME_H */
