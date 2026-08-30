/*
 * Debug console output: typed emitters with stated budgets.
 *
 * Issue #49, second design. The first was a printf-compatible
 * formatter, chosen so the 130-odd call sites could migrate by rename.
 * That optimised for the migration rather than for the property the
 * issue is about, and the owner's direction is the other way round:
 * clean house, deterministic time and memory, no obligation to the
 * printf feature set, call sites rewritten to suit.
 *
 * So there is no format string here. A format string is parsed at
 * runtime, which makes the cost of a call a function of the string as
 * well as the values, and it carries flags and widths that exist to
 * satisfy a standard nothing here needs to satisfy.
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
 * budget: the arithmetic is ~1% of it and the wire is the rest. That
 * is measured - a 42-byte line costs 3618 us against 3646 us of pure
 * transmission - and it is why this file does not try to be clever
 * about the conversion.
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
