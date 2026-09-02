/*
 * The emitters. See console_out.h for the budgets, which are the whole
 * reason this file exists rather than a printf.
 *
 * Everything reaches the wire through console_write(), which is the
 * port both tracks already implement - Track B straight to the UART,
 * Track A through Serial. Nothing here knows about a register.
 *
 * The shape is: build the few bytes this emitter owns into a stack
 * scratch, terminate it, hand it over. No line buffer, so nothing
 * accumulates and nothing can overflow; the cost of a call is its own
 * bytes and not the length of the line it happens to be part of.
 */
#include "console_out.h"
#include "console_port.h"

void con_ch(char c)
{
	char b[2];

	b[0] = c;
	b[1] = '\0';
	console_write(b);
}

void con_str(const char *s)
{
	if (!s) {
		console_write("(null)");
		return;
	}
	/*
	 * console_write walks to the NUL itself, so the bound has to be
	 * applied here or it is not applied at all. A string longer than
	 * CON_STR_MAX is truncated rather than trusted - which is the
	 * difference between a worst case and a hope.
	 *
	 * The index is tested before it is read, so CON_STR_MAX is the
	 * number of bytes this may touch and s[CON_STR_MAX] is not one of
	 * them. Stopping on the bound therefore means no terminator was
	 * seen, and handing console_write a pointer it would walk past is
	 * the same over-read one call deeper.
	 */
	{
		unsigned n = 0;

		while (n < CON_STR_MAX && s[n])
			n++;
		if (n < CON_STR_MAX) {
			console_write(s);
			return;
		}
		for (unsigned i = 0; i < n; i++)
			con_ch(s[i]);
	}
}

void con_u32(uint32_t v)
{
	char b[CON_SCRATCH];
	unsigned n = 0;

	/* At most 10 iterations for 32 bits, which is the time budget. */
	do {
		b[n++] = (char)('0' + (v % 10u));
		v /= 10u;
	} while (v);

	{
		char out[CON_SCRATCH];
		unsigned i = 0;

		while (n)
			out[i++] = b[--n];
		out[i] = '\0';
		console_write(out);
	}
}

void con_i32(int32_t v)
{
	if (v < 0) {
		con_ch('-');
		/* Negate in unsigned space: -INT32_MIN is not
		 * representable as an int32_t and the obvious spelling
		 * is undefined behaviour. */
		con_u32((uint32_t)(-(v + 1)) + 1u);
		return;
	}
	con_u32((uint32_t)v);
}

void con_hex32(uint32_t v, unsigned digits)
{
	static const char hex[] = "0123456789abcdef";
	char b[9];

	if (digits == 0u || digits > 8u)
		digits = 8u;
	b[digits] = '\0';
	for (unsigned i = digits; i-- > 0;) {
		b[i] = hex[v & 0xfu];
		v >>= 4;
	}
	console_write(b);
}

void con_pad(char c, unsigned n)
{
	if (n > CON_PAD_MAX)
		n = CON_PAD_MAX;
	while (n--)
		con_ch(c);
}

void con_u32w(uint32_t v, unsigned width, char fill)
{
	uint32_t t = v;
	unsigned n = 1;

	while (t >= 10u) {
		t /= 10u;
		n++;
	}
	if (width > CON_PAD_MAX)
		width = CON_PAD_MAX;
	if (width > n)
		con_pad(fill, width - n);
	con_u32(v);
}

void con_u32l(uint32_t v, unsigned width)
{
	uint32_t t = v;
	unsigned n = 1;

	while (t >= 10u) {
		t /= 10u;
		n++;
	}
	con_u32(v);
	if (width > CON_PAD_MAX)
		width = CON_PAD_MAX;
	if (width > n)
		con_pad(' ', width - n);
}

/*
 * A string in a field of `width`, padded on the RIGHT: `%-22s`. The
 * length walk stops at CON_STR_MAX like every other, and a string wider
 * than its field is emitted in full - a clipped label is a wrong label,
 * where a misaligned column is only ugly.
 */
void con_strl(const char *s, unsigned width)
{
	unsigned n = 0;

	while (s && n < CON_STR_MAX && s[n])
		n++;
	con_str(s);
	if (width > CON_PAD_MAX)
		width = CON_PAD_MAX;
	if (width > n)
		con_pad(' ', width - n);
}

void con_nl(void)
{
	console_write("\n");
}

void con_kv_u32(const char *key, uint32_t v)
{
	con_str(key);
	con_ch('=');
	con_u32(v);
}

void con_kvs(const char *key, const char *val)
{
	con_str(key);
	con_ch('=');
	con_str(val);
}
