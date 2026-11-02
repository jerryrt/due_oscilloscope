/*
 * Wire frame, version 4: the 16-bit sample stream of the H7-TOOL target.
 * See targets/h7tool/docs/06-plan.md.
 *
 * Version 3 (lib/due_shared/src/frame.h) carries 12-bit samples whose
 * upper bits hold the channel tag. A 16-bit converter has no spare
 * bits, so version 4 changes what the payload is and leaves everything
 * else alone: the same 32-byte header, the same field order, the same
 * magic and CRC, the same 4096-byte frame of whole 512-byte packets.
 * That is deliberate - the host's frame splitter finds a frame by its
 * magic and length, so one splitter serves both, and a host that sees
 * the wrong `version` for its board refuses the pairing, as it does for
 * any mismatch.
 *
 * What differs from version 3:
 *   - version is 4;
 *   - each payload word is an unsigned 16-bit converter code, offset
 *     binary, with NO channel tag in it;
 *   - the channel of a word is its position, and the payload is PLANAR:
 *     with k channels set in `channel_mask`, each owns one contiguous
 *     block of FRAME_SAMPLES / k samples, lowest channel index first
 *     (two DMA streams cannot interleave halfwords, and the host
 *     does the reshaping); `sample_rate_hz` is per channel, so a frame
 *     spans FRAME_SAMPLES / k / sample_rate_hz seconds;
 *   - `channel_mask` indexes the target's own channels, not Arduino
 *     ADC channels: bit 0 = scope CH1, bit 1 = scope CH2 *(check)*;
 *   - `play_consumed` stays in place and is 0 until the generator
 *     reports through it.
 *
 * Not decided here: the code-to-volts mapping. It depends on range and
 * calibration, which the host applies from the control channel, so no
 * header field is spent on it.
 *
 * The CRC and the header struct are the shared ones; this file adds a
 * version and assertions and no second copy of either.
 */

#ifndef FRAME16_H
#define FRAME16_H

#include "frame.h"

#define FRAME16_VERSION 4

FRAME_STATIC_ASSERT(FRAME16_VERSION != FRAME_VERSION,
                    "version 4 must not read as version 3");
FRAME_STATIC_ASSERT(FRAME_SAMPLES * 2u + FRAME_HDR_BYTES == 4096u,
                    "version 4 keeps the 4096-byte frame");

#endif /* FRAME16_H */
