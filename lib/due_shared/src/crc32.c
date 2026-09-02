/*
 * CRC-32, the one both tracks use, in one place. `frame_crc32_update`
 * is the resumable form the control protocol needs, since its checksum
 * covers the bytes on either side of the field it sits in and so cannot
 * be taken over one contiguous run.
 *
 * Bitwise rather than table-driven, deliberately: a 1 KB table would
 * buy speed on a path that only ever checksums frame headers and
 * control frames - tens of bytes at a time - on a part with 96 KB of
 * SRAM where the capture ring's placement is already a design
 * constraint.
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
