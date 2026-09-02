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
 * play_consumed is paid for out of fields that never varied:
 * bits_per_sample was always 12, packing always 0, and n_samples always
 * ACQ_BUF_SAMPLES - the frame is a fixed 4096 bytes because that is
 * 8 x 512 and one DMA sends whole packets, so its sample count is
 * architecture, not data. Growing the header to fit play_consumed
 * instead - taking samples out of the payload - measurably increases
 * ramp-test failures, so this geometry is load-bearing; leave it alone.
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
 * The frame's geometry, which is the wire contract and therefore lives
 * here rather than in each track's acq.h.
 *
 * FRAME_HDR_BYTES is *derived* from the struct rather than a separate
 * hand-maintained constant: a field added to the header cannot leave a
 * stale size behind, which would otherwise make the payload overlap it.
 * The static assert below travels with it, so the check lives where the
 * constant does.
 */
#ifdef __cplusplus
#define FRAME_STATIC_ASSERT(c, m) static_assert(c, m)
#else
#define FRAME_STATIC_ASSERT(c, m) _Static_assert(c, m)
#endif

#define FRAME_SAMPLES     2032u
#define FRAME_HDR_BYTES   ((unsigned)sizeof(frame_header_t))
#define FRAME_BYTES       (FRAME_HDR_BYTES + FRAME_SAMPLES * 2u)

FRAME_STATIC_ASSERT(sizeof(frame_header_t) == 32,
                    "the frame header is 32 bytes; the payload starts "
                    "immediately after it and both tracks size buffers "
                    "from FRAME_HDR_BYTES");
FRAME_STATIC_ASSERT(FRAME_BYTES % 512u == 0,
                    "a frame must be a whole number of 512-byte packets");

/*
 * The channel tag values, which are wire contract because the host
 * demultiplexes by them: every sample carries its channel index and the
 * header carries `channel_mask` over the same indices.
 *
 * They are not obvious numbers and that is the point. Arduino's A0..A7
 * labels map to ADC channels in DESCENDING order, so A0 is AD7 and code
 * assuming A0 == AD0 reads the wrong pin:
 *
 *   A0 = PA16 = AD7      A4 = PA6  = AD3      A8  = PB17 = AD10
 *   A1 = PA24 = AD6      A5 = PA4  = AD2      A9  = PB18 = AD11
 *   A2 = PA23 = AD5      A6 = PA3  = AD1      A10 = PB19 = AD12
 *   A3 = PA22 = AD4      A7 = PA2  = AD0      A11 = PB20 = AD13
 *
 * The sequencer converts in ascending channel-index order, which is not
 * label order either, so this table is load-bearing for anyone
 * extending the channel set.
 *
 * Only the three currently in use are defined. The rest are deliberately
 * absent rather than written out: an unused constant is a claim nothing
 * checks.
 */
#define FRAME_CH_A0       7u
#define FRAME_CH_A1       6u
#define FRAME_CH_A2       5u

/*
 * C linkage, because this header is shared and the two tracks are not
 * the same language: Track B is C throughout, Track A is C++. Without
 * this the shared crc32.c would export mangled symbols that Track A's
 * C++ callers cannot link against. Every shared header that declares a
 * function needs this.
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
