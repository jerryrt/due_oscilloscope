/*
 * CRC-32, the one both tracks use, in one place.
 *
 * This was two independent copies of the same polynomial loop:
 * drivers/stream.c had `frame_crc32_update` plus a `frame_crc32`
 * wrapper, and sketches/bringup/stream.cpp had `frame_crc32` with the
 * loop inlined and no resumable form at all. Same polynomial, same
 * answer, written twice - and frame.h's own comment on the resumable
 * one already said why that is a bad idea: "a second copy of the
 * polynomial loop is a second thing to get wrong".
 *
 * The copies had already diverged in capability rather than in result.
 * Track A never had `frame_crc32_update`, which is the form the control
 * protocol needs, because its checksum covers the bytes on either side
 * of the field it sits in and so cannot be taken over one contiguous
 * run. Giving Track A a control channel meant either writing that
 * function a third time or doing this.
 *
 * Bitwise rather than table-driven, and that is deliberate: a 1 KB
 * table would buy speed on a path that only ever checksums frame
 * headers and control frames - tens of bytes at a time - and this is a
 * part with 96 KB of SRAM where the capture ring's placement is already
 * a design constraint.
 */
#include "frame.h"

uint32_t frame_crc32_update(uint32_t c, const uint8_t *data, size_t len)
{
	while (len--) {
		c ^= *data++;
		for (int k = 0; k < 8; k++)
			c = (c >> 1) ^ (0xedb88320u & (uint32_t)(-(int32_t)(c & 1u)));
	}
	return c;
}

uint32_t frame_crc32(const uint8_t *data, size_t len)
{
	return ~frame_crc32_update(0xffffffffu, data, len);
}
