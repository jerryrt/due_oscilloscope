/*
 * Debug console output: typed emitters with stated budgets, no format
 * string. A format string is parsed at runtime, which makes the cost of
 * a call a function of the string as well as the values, and it carries
 * flags and widths that exist to satisfy a standard nothing here needs
 * to satisfy.
 *
 * ================= THE BUDGETS, WHICH ARE THE POINT ==================
 *
 * MEMORY. Zero heap - the image links no allocator and
 * tests/test_no_heap.py fails if one appears. Zero static buffers.
 * Stack per call is one digit scratch plus a frame: CON_SCRATCH bytes,
 * 12 on this target. There is deliberately no line buffer, so nothing
 * here scales with how long a line is and a caller cannot overflow one.
 *
 * TIME. Every emitter's worst case is a constant plus the UART time of
 * the bytes it emits, and the byte count is bounded per call:
 *
 *     con_ch          1 byte
 *     con_str         <= CON_STR_MAX, truncated, never walks further
 *     con_u32         <= 10 bytes
 *     con_i32         <= 11 bytes
 *     con_hex32       exactly the digits asked for, <= 8
 *     con_pad         exactly n, n <= CON_PAD_MAX
 *     con_nl          1 byte, 2 on the wire after CRLF
 *
 * At 115200 8N1 a byte is 86.8 us, so the byte count IS the time
 * budget: the arithmetic is a small fraction of it and the wire is the
 * rest, which is why this file does not try to be clever about the
 * conversion.
 *
 * WHAT IS NOT HERE, and will not be added: floating point, %n,
 * positional arguments, dynamic width. Each of those is either
 * unbounded or drags back the libc engine this replaces.
 *
 * Still debug-only. Invariant 6 - never from an ISR - and invariant 8 -
 * printf is a debug method and not an instrument - both stand
 * unchanged. Nothing here makes console output cheap; it makes its cost
 * knowable.
 */
#ifndef CONSOLE_OUT_H
#define CONSOLE_OUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 32 bits is 10 decimal digits, 11 with a sign, and a NUL. */
#define CON_SCRATCH   12u

/* The longest string an emitter will walk. A pointer that is not
 * terminated stops here rather than making the worst case unknowable. */
#define CON_STR_MAX  256u

/* Padding beyond this is a layout mistake, not a layout. */
#define CON_PAD_MAX   32u

void con_ch(char c);
void con_str(const char *s);
void con_u32(uint32_t v);
void con_i32(int32_t v);
void con_hex32(uint32_t v, unsigned digits);
void con_pad(char c, unsigned n);

/*
 * A number in a field of `width`, filled with `fill` on the left.
 * Bounded like everything else: width clamps to CON_PAD_MAX, and a
 * value too wide for its field is printed in full rather than
 * truncated - a clipped number is a wrong number, where a misaligned
 * column is only ugly. Emits at most max(width, 10) bytes.
 */
void con_u32w(uint32_t v, unsigned width, char fill);

/* The same, padded on the RIGHT: `%-4lu`. Emits at most max(width, 10)
 * bytes. */
void con_u32l(uint32_t v, unsigned width);

/*
 * A string in a field of `width`, padded on the RIGHT: `%-22s`.
 * cmd_profile's label column. Emits at most max(width, CON_STR_MAX).
 */
void con_strl(const char *s, unsigned width);
void con_nl(void);

/*
 * The two composites that earn their place, because every console line
 * in the firmware is a list of them and writing the pieces out at 300
 * call sites would be its own defect.
 *
 *   con_kv_u32("frames", 12)   ->  "frames=12"
 *   con_kvs("track", "B")      ->  "track=B"
 *
 * Bounded by their parts, so the budget above still holds.
 */
void con_kv_u32(const char *key, uint32_t v);
void con_kvs(const char *key, const char *val);

#ifdef __cplusplus
}
#endif

#endif /* CONSOLE_OUT_H */
