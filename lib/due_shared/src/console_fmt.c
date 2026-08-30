/*
 * A bounded, allocation-free formatter for the debug console.
 *
 * Issue #49. This exists because libc gives you a choice of two things
 * and neither is acceptable here:
 *
 *   printf    formats to a FILE. newlib's findfp allocates that
 *             stream's buffer with _malloc_r on first use and never
 *             frees it, so the image links a heap. The owner's rule is
 *             that it must not, and tests/test_no_heap.py enforces it.
 *
 *   snprintf  formats into your buffer through a fake FILE on the
 *             stack, so it allocates nothing - but it still drags the
 *             whole engine (_printf_i 652 B, _svfiprintf_r 556 B,
 *             _printf_common 292 B) and is still variable-time.
 *
 * So neither the size nor the determinism is available from libc at
 * any setting, which is why this is written rather than configured.
 *
 * **A different name is not cosmetic.** If this were called printf the
 * ban could not be spelled; because it is not, the guard can say "no
 * libc stdio in the image at all" and that is checkable with nm rather
 * than by review.
 *
 * Shared, because it is application logic touching no register, and
 * both tracks already reach the wire through console_write(). Same
 * argument that moved the identity line.
 *
 * WHAT IT SUPPORTS, and the list is measured rather than chosen: every
 * conversion in the firmware today is one of
 *
 *   %d %i %u %x %X %s %c %p %%   with an optional l, flags - + 0 and
 *                                space, and a numeric field width
 *
 * There is **no floating point anywhere in this codebase** - grepped,
 * zero hits for %f %g %e - and adding it would drag in the very
 * machinery this replaces. A float conversion is not silently ignored:
 * it emits the format character so the output shows what was asked for
 * and nobody reads a wrong number.
 *
 * WHY IT IS BOUNDED. Every conversion has a worst case known at build
 * time: 10 digits for a 32-bit unsigned, 11 with a sign, 8 for hex,
 * and a width clamped to FMT_WIDTH_MAX. `%s` is the only unbounded
 * input, and it is truncated at the destination rather than trusted -
 * which is the difference between "usually fast" and "worst case known",
 * and the whole point of the exercise.
 *
 * It returns the length it WOULD have written, like snprintf, so a
 * caller can append at the offset it gets back. play_report_format()
 * already needs that.
 */
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>

#include "console.h"

/* A field width beyond this is a typo, not a layout. Bounding it is
 * what keeps the worst case a constant. */
#define FMT_WIDTH_MAX 32u

/* 32 bits is 10 decimal digits, plus a sign. */
#define FMT_DIGITS_MAX 11u

/* The longest %s this will measure. Longer strings are truncated in the
 * count as well as the output, which is a documented limit rather than
 * an accident: the alternative is walking a pointer that may not be
 * terminated. Nothing in the firmware formats a string near this. */
#define FMT_STR_MAX 256u

struct out {
	char *buf;
	unsigned n;      /* capacity including the NUL */
	unsigned len;    /* what would have been written */
};

static void put(struct out *o, char c)
{
	if (o->len + 1u < o->n)
		o->buf[o->len] = c;
	o->len++;
}

static void pad(struct out *o, char c, unsigned count)
{
	while (count--)
		put(o, c);
}

/*
 * One integer, already made positive, into a fixed scratch array.
 * Returns the digit count. Never loops more than FMT_DIGITS_MAX times,
 * because the value is 32 bits and the base is at least 8.
 */
static unsigned digits(uint32_t v, unsigned base, bool upper, char *tmp)
{
	static const char lo[] = "0123456789abcdef";
	static const char up[] = "0123456789ABCDEF";
	const char *d = upper ? up : lo;
	unsigned n = 0;

	do {
		tmp[n++] = d[v % base];
		v /= base;
	} while (v && n < FMT_DIGITS_MAX);
	return n;
}

int console_vfmt(char *buf, unsigned n, const char *fmt, va_list ap)
{
	struct out o = { buf, n, 0 };

	for (; *fmt; fmt++) {
		bool left = false, zero = false, plus = false, space = false;
		bool lng = false, upper = false, neg = false;
		unsigned width = 0, base = 10, ndig;
		char tmp[FMT_DIGITS_MAX];
		uint32_t uv;
		const char *s;

		if (*fmt != '%') {
			put(&o, *fmt);
			continue;
		}
		fmt++;

		for (;; fmt++) {
			if (*fmt == '-')      left = true;
			else if (*fmt == '0') zero = true;
			else if (*fmt == '+') plus = true;
			else if (*fmt == ' ') space = true;
			else                  break;
		}
		while (*fmt >= '0' && *fmt <= '9') {
			if (width < FMT_WIDTH_MAX)
				width = width * 10u + (unsigned)(*fmt - '0');
			fmt++;
		}
		/* `l` and `ll` are the same here: this is a 32-bit machine
		 * and nothing in the firmware formats a 64-bit value. */
		while (*fmt == 'l' || *fmt == 'h') {
			lng = true;
			fmt++;
		}

		switch (*fmt) {
		case '%':
			put(&o, '%');
			continue;
		case 'c':
			put(&o, (char)va_arg(ap, int));
			continue;
		case 's':
			s = va_arg(ap, const char *);
			if (!s)
				s = "(null)";
			/*
			 * Bounded by FMT_STR_MAX, NOT by the destination.
			 *
			 * Some limit is required or an unterminated pointer
			 * makes the worst case unknowable, which is the
			 * property this whole file exists for. But it must
			 * not be `n`: the return value is the length that
			 * WOULD have been written, callers append at that
			 * offset, and clamping the measurement to the buffer
			 * makes the count wrong exactly when the caller most
			 * needs it. The differential test caught this - ours
			 * returned 8 where snprintf returned 14.
			 */
			{
				unsigned l = 0;
				while (s[l] && l < FMT_STR_MAX)
					l++;
				if (!left)
					pad(&o, ' ', width > l ? width - l : 0);
				for (unsigned i = 0; i < l; i++)
					put(&o, s[i]);
				if (left)
					pad(&o, ' ', width > l ? width - l : 0);
			}
			continue;
		case 'p':
			uv = (uint32_t)(uintptr_t)va_arg(ap, void *);
			put(&o, '0');
			put(&o, 'x');
			base = 16u;
			width = 8u;
			zero = true;
			break;
		case 'X':
			upper = true;
			/* fall through */
		case 'x':
			base = 16u;
			uv = lng ? va_arg(ap, unsigned long)
			         : va_arg(ap, unsigned int);
			break;
		case 'u':
			uv = lng ? va_arg(ap, unsigned long)
			         : va_arg(ap, unsigned int);
			break;
		case 'd':
		case 'i': {
			long v = lng ? va_arg(ap, long) : va_arg(ap, int);
			neg = v < 0;
			uv = neg ? (uint32_t)(-(v + 1)) + 1u : (uint32_t)v;
			break;
		}
		default:
			/* Including every float conversion. Emit what was
			 * asked for rather than a number that was not
			 * computed - a silently dropped %f reads as a
			 * missing field, which is worse than a visible one. */
			put(&o, '%');
			if (*fmt)
				put(&o, *fmt);
			else
				fmt--;
			continue;
		}

		ndig = digits(uv, base, upper, tmp);
		{
			unsigned sign = (neg || plus || space) && base == 10;
			unsigned body = ndig + sign;
			unsigned fill = width > body ? width - body : 0;

			if (!left && !zero)
				pad(&o, ' ', fill);
			if (sign)
				put(&o, neg ? '-' : (plus ? '+' : ' '));
			if (!left && zero)
				pad(&o, '0', fill);
			while (ndig--)
				put(&o, tmp[ndig]);
			if (left)
				pad(&o, ' ', fill);
		}
	}

	if (n)
		o.buf[o.len < n ? o.len : n - 1u] = '\0';
	return (int)o.len;
}

int console_fmt(char *buf, unsigned n, const char *fmt, ...)
{
	va_list ap;
	int r;

	va_start(ap, fmt);
	r = console_vfmt(buf, n, fmt, ap);
	va_end(ap);
	return r;
}
