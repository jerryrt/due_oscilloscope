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
#define FRAME_VERSION 3

#define FRAME_FLAG_OVERRUN     (1u << 0)
#define FRAME_FLAG_BURST_FIRST (1u << 1)
#define FRAME_FLAG_BURST_LAST  (1u << 2)
#define FRAME_FLAG_CONTINUOUS  (1u << 3)

/*
 * play_consumed is paid for out of fields that never varied.
 *
 * bits_per_sample was always 12, packing always 0, and n_samples always
 * ACQ_BUF_SAMPLES - the frame is a fixed 4096 bytes because that is
 * 8 x 512 and one DMA sends whole packets, so its sample count is
 * architecture, not data. Four bytes of constants bought the one field
 * that is neither.
 *
 * The alternative was to grow the header and take two samples out of
 * the payload. That was tried, and moving ACQ_BUF_SAMPLES off 2032
 * cost the ramp test 4 runs in 15 against 0 in 15 before it. The
 * geometry is load-bearing; leave it alone.
 *
 * sample_rate_hz stays, because it is the one field here that genuinely
 * varies run to run and cannot be reconstructed from a recording.
 */
typedef struct __attribute__((packed)) {
	uint8_t  magic[4];
	uint8_t  version;
	uint8_t  flags;
	uint16_t channel_mask;     /* ADC channel indices, not A-labels */
	uint32_t seq;
	uint32_t sample_rate_hz;   /* per channel */
	uint32_t timestamp_us;
	uint32_t overrun_count;
	uint32_t play_consumed;    /* playback buffers the DAC has taken */
	uint32_t header_crc32;     /* over the preceding 28 bytes */
} frame_header_t;

/*
 * C linkage, because this header is shared and the two tracks are not
 * the same language. Track B is C throughout; Track A is C++ - every
 * sketch translation unit is .cpp or .ino. Without this the shared
 * crc32.c would export unmangled symbols that Track A's callers cannot
 * link against, and the failure arrives at link time with a mangled
 * name in it rather than at the include. Every shared header that
 * declares a function needs this; see docs/shared-source.md.
 */
#ifdef __cplusplus
extern "C" {
#endif

/*
 * Deliberately no payload CRC. USB already provides a per-packet CRC-16
 * with hardware retry, and computing one here would make the CPU read
 * the whole sample stream, which is the one thing the architecture
 * forbids.
 */
uint32_t frame_crc32(const uint8_t *data, size_t len);

/*
 * The same CRC, resumable. The control protocol's checksum covers the
 * bytes on either side of the field it sits in, so it cannot be taken
 * over one contiguous run - and a second copy of the polynomial loop is
 * a second thing to get wrong. Start at 0xffffffff, finish with ~c.
 */
uint32_t frame_crc32_update(uint32_t c, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* FRAME_H */
