/* Differential harness: console_fmt against libc snprintf. */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>

int console_fmt(char *buf, unsigned n, const char *fmt, ...);

static int fails = 0, checks = 0;

#define CHECK(fmt, ...) do {                                            \
    char a[128], b[128];                                                \
    int ra = console_fmt(a, sizeof a, fmt, __VA_ARGS__);                \
    int rb = snprintf(b, sizeof b, fmt, __VA_ARGS__);                   \
    checks++;                                                           \
    if (strcmp(a, b) || ra != rb) {                                     \
        fails++;                                                        \
        printf("MISMATCH  fmt=%-12s ours=%-24s libc=%-24s (%d vs %d)\n",\
               fmt, a, b, ra, rb);                                      \
    }                                                                   \
} while (0)

int main(void)
{
    static const long sv[] = {0, 1, -1, 7, -7, 42, -42, 999, -999,
                              65535, 100000, 2147483647L, -2147483647L};
    static const unsigned long uv[] = {0, 1, 7, 42, 255, 4095, 65535,
                                       1000000, 4294967295UL, 78000000UL};

    for (unsigned i = 0; i < sizeof sv / sizeof sv[0]; i++) {
        CHECK("%d", (int)sv[i]);      CHECK("%ld", sv[i]);
        CHECK("%+d", (int)sv[i]);     CHECK("% d", (int)sv[i]);
        CHECK("%5d", (int)sv[i]);     CHECK("%-5d", (int)sv[i]);
        CHECK("%05d", (int)sv[i]);
    }
    for (unsigned i = 0; i < sizeof uv / sizeof uv[0]; i++) {
        CHECK("%u", (unsigned)uv[i]); CHECK("%lu", uv[i]);
        CHECK("%x", (unsigned)uv[i]); CHECK("%X", (unsigned)uv[i]);
        CHECK("%08lx", uv[i]);        CHECK("%04x", (unsigned)uv[i]);
        CHECK("%5lu", uv[i]);         CHECK("%-8lu", uv[i]);
        CHECK("%2lu", uv[i]);         CHECK("%9lu", uv[i]);
        CHECK("%03lu", uv[i]);        CHECK("%6u", (unsigned)uv[i]);
    }
    CHECK("%s", "");                  CHECK("%s", "hello");
    CHECK("%10s", "hi");              CHECK("%-10s|", "hi");
    CHECK("%c", 'x');                 CHECK("%c%c", 'a', 'b');
    CHECK("plain %s and %lu", "text", 12345UL);
    CHECK("# id: track=%c fw=%s ctlver=%u", 'B', "0.2.0", 3u);
    CHECK("%s", "0123456789012345678901234567890123456789");

    /* Truncation: the return must be the would-be length, like snprintf. */
    {
        char a[8], b[8];
        int ra = console_fmt(a, sizeof a, "%s", "abcdefghijklmn");
        int rb = snprintf(b, sizeof b, "%s", "abcdefghijklmn");
        checks++;
        if (strcmp(a, b) || ra != rb) {
            fails++;
            printf("MISMATCH truncation ours=%s(%d) libc=%s(%d)\n",
                   a, ra, b, rb);
        }
    }
    /*
     * %p is NOT differential. The C standard leaves the pointer format
     * implementation-defined, and glibc prints "0x1234" where this
     * prints "0x00001234" - a difference in libc, not a defect here.
     * So it is checked against the documented format instead, and the
     * documented format is 0x followed by eight hex digits because a
     * fixed width is what makes an address column line up in a console
     * table.
     */
    {
        char a[32];
        int r = console_fmt(a, sizeof a, "%p", (void *)0x20070123u);
        checks++;
        if (strcmp(a, "0x20070123") || r != 10) {
            fails++;
            printf("MISMATCH  %%p ours=%s(%d) want=0x20070123(10)\n", a, r);
        }
        r = console_fmt(a, sizeof a, "%p", (void *)0u);
        checks++;
        if (strcmp(a, "0x00000000") || r != 10) {
            fails++;
            printf("MISMATCH  %%p zero ours=%s(%d)\n", a, r);
        }
    }

    printf("%d checks, %d mismatches\n", checks, fails);
    return fails != 0;
}
