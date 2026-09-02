/*
 * Four defects, one per sanitizer check the native harnesses rely on.
 *
 * A sanitizer that is not actually linked in looks exactly like clean
 * code: the harnesses pass, the tier is green, and nothing says the
 * instrumentation was absent. So the flags are proven rather than
 * assumed - tests/test_sanitizers.py builds this file five times with
 * the same flags every other native harness is built with, and requires
 * the clean build to exit 0 and each defect to be caught.
 *
 * DEFECT=3 is the one that guards -fno-sanitize-recover=all rather than
 * -fsanitize=undefined: a signed overflow is diagnosed either way, and
 * without that flag UBSan prints its line and lets the program run on
 * to return 0. A harness whose findings do not change its exit status
 * is a harness nobody's exit-status check can read.
 *
 * Everything the defects touch is volatile, because a defect the
 * optimiser deleted certifies nothing - and at -O1 gcc will happily
 * delete all four.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef DEFECT
#define DEFECT 0
#endif

static volatile int one = 1;
static volatile int big = 2147483647;

int main(void)
{
#if DEFECT == 1
	/* ASan: heap-buffer-overflow, one byte past a malloc'd block -
	 * the shape a length field taken from a peer produces. */
	size_t n = (size_t)one * 16u;
	volatile char *p = malloc(n);

	if (!p)
		return 2;
	p[n] = 'x';
	printf("wrote %c past the block\n", p[n]);
	free((void *)p);
#elif DEFECT == 2
	/* ASan: heap-use-after-free. */
	volatile char *p = malloc(16);

	if (!p)
		return 2;
	p[0] = 'a';
	free((void *)p);
	printf("read %c after free\n", p[0]);
#elif DEFECT == 3
	/* UBSan: signed integer overflow, and the exit status that
	 * -fno-sanitize-recover=all turns it into. */
	int v = big + one;

	printf("overflowed to %d\n", v);
#elif DEFECT == 4
	/* UBSan: a misaligned load, which is what a wire buffer read
	 * through a non-packed struct pointer would be. */
	static volatile char buf[16];
	volatile char *raw = buf + one;
	uint32_t v;

	memcpy((void *)buf, "0123456789abcdef", 16);
	v = *(volatile uint32_t *)(void *)raw;
	printf("loaded %u through a misaligned pointer\n", (unsigned)v);
#else
	printf("clean\n");
#endif
	return 0;
}
