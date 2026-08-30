/*
 * The emitters' budgets, checked rather than asserted.
 *
 * console_out.h states a byte bound per call, and at 115200 the byte
 * count IS the time budget - 86.8 us each, with the arithmetic about 1%
 * of it. So testing the byte bound tests the time bound, and it does so
 * without a board or a clock.
 *
 * console_write is provided here, capturing instead of transmitting.
 * That is the whole port the emitters use, which is why they can be
 * tested on a host at all.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

#include "console_out.h"

static char cap[4096];
static unsigned cap_len;

void console_write(const char *s)
{
    unsigned n = (unsigned)strlen(s);
    if (cap_len + n < sizeof cap) {
        memcpy(cap + cap_len, s, n);
        cap_len += n;
    }
}

static int fails, checks;
static void reset(void) { cap_len = 0; cap[0] = 0; }

#define BOUND(label, limit, call) do {                                  \
    reset(); call; cap[cap_len] = 0;                                    \
    checks++;                                                           \
    if (cap_len > (unsigned)(limit)) {                                  \
        fails++;                                                        \
        printf("OVER BUDGET  %-14s emitted %u, budget %u  [%s]\n",      \
               label, cap_len, (unsigned)(limit), cap);                 \
    }                                                                   \
} while (0)

#define EXACT(label, want) do {                                         \
    checks++;                                                           \
    cap[cap_len] = 0;                                                   \
    if (strcmp(cap, want)) {                                            \
        fails++;                                                        \
        printf("WRONG        %-14s got [%s] want [%s]\n",               \
               label, cap, want);                                       \
    }                                                                   \
} while (0)

int main(void)
{
    static char huge[CON_STR_MAX * 2];
    memset(huge, 'x', sizeof huge - 1);
    huge[sizeof huge - 1] = 0;

    /* Budgets, at their worst cases. */
    BOUND("con_ch",     1,           con_ch('z'));
    BOUND("con_nl",     1,           con_nl());
    BOUND("con_u32",   10,           con_u32(4294967295u));
    BOUND("con_i32",   11,           con_i32(-2147483647 - 1));
    BOUND("con_hex32",  8,           con_hex32(0xffffffffu, 8));
    BOUND("con_hex32 clamp", 8,      con_hex32(0xffffffffu, 99));
    BOUND("con_pad",   CON_PAD_MAX,  con_pad('.', 9999));
    BOUND("con_str",   CON_STR_MAX,  con_str(huge));

    /* Correctness, because a bounded wrong answer is still wrong. */
    reset(); con_u32(0);            EXACT("u32 zero",   "0");
    reset(); con_u32(4294967295u);  EXACT("u32 max",    "4294967295");
    reset(); con_i32(0);            EXACT("i32 zero",   "0");
    reset(); con_i32(-1);           EXACT("i32 -1",     "-1");
    reset(); con_i32(2147483647);   EXACT("i32 max",    "2147483647");
    reset(); con_i32(-2147483647 - 1);
                                    EXACT("i32 min",    "-2147483648");
    reset(); con_hex32(0x2007dd48u, 8); EXACT("hex 8",  "2007dd48");
    reset(); con_hex32(0xabu, 2);   EXACT("hex 2",      "ab");
    reset(); con_str(NULL);         EXACT("str null",   "(null)");
    reset(); con_str("");           EXACT("str empty",  "");
    reset(); con_kv_u32("frames", 12);  EXACT("kv_u32", "frames=12");
    reset(); con_kvs("track", "B");     EXACT("kvs",    "track=B");
    reset(); con_pad('-', 3);       EXACT("pad 3",      "---");

    /* An unterminated-length string truncates rather than running on. */
    reset(); con_str(huge);
    checks++;
    if (cap_len != CON_STR_MAX) {
        fails++;
        printf("WRONG        con_str truncation: %u not %u\n",
               cap_len, CON_STR_MAX);
    }

    printf("%d checks, %d failures\n", checks, fails);
    return fails != 0;
}
