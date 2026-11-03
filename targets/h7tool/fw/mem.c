/* The few libc routines the freestanding images need (we link with -nostdlib). Written as byte loops with loop-pattern
 * recognition turned off, so the compiler cannot turn them back into calls to themselves. */
#include <stddef.h>

#define NOPAT __attribute__((optimize("no-tree-loop-distribute-patterns")))

NOPAT void *memcpy(void *d, const void *s, size_t n) { unsigned char *a = d; const unsigned char *b = s; while (n--) *a++ = *b++; return d; }
NOPAT void *memset(void *d, int c, size_t n) { unsigned char *a = d; while (n--) *a++ = (unsigned char)c; return d; }
NOPAT size_t strlen(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
int memcmp(const void *a, const void *b, size_t n)
{
	const unsigned char *x = a, *y = b;
	for (; n; n--, x++, y++) if (*x != *y) return *x < *y ? -1 : 1;
	return 0;
}
