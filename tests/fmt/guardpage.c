/*
 * The string bound, held against a guard page.
 *
 * con_str and con_strl walk an untrusted pointer and stop at
 * CON_STR_MAX, and a walk that tests the index after dereferencing it
 * reads one byte past the bound it exists to enforce. That over-read
 * returns a byte and carries on, so nothing downstream can see it: the
 * output is right, the budget is met, and the only evidence is a page
 * the process was never entitled to touch.
 *
 * So the evidence is arranged. The string is placed at the very end of a
 * writable page whose successor is unreadable, with no NUL in it: the
 * last legal byte is s[CON_STR_MAX - 1] and s[CON_STR_MAX] is the guard.
 * A walk that stays inside its bound returns; one that steps past it
 * dies, and the test reads the exit status.
 *
 * console_write is provided here, counting instead of transmitting, so
 * a bound that is held by truncating too early fails as well.
 */
/* mmap, mprotect and MAP_ANONYMOUS are hidden from a strict -std=c11
 * translation unit, and the harness is built with the same flags as the
 * budget one. */
#if !defined(_WIN32) && !defined(_DEFAULT_SOURCE)
#define _DEFAULT_SOURCE 1
#endif

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#if defined(_WIN32)
#include <windows.h>
#else
#include <unistd.h>
#include <sys/mman.h>
#endif

#include "console_out.h"

static unsigned emitted;

void console_write(const char *s)
{
    emitted += (unsigned)strlen(s);
}

/*
 * Two pages: the first writable, the second unreadable. What comes back
 * is the first byte of the second page, so a caller subtracts to place
 * its data hard against the boundary.
 */
static char *guarded_end(void)
{
#if defined(_WIN32)
    SYSTEM_INFO si;
    DWORD old;
    char *base;

    GetSystemInfo(&si);
    base = VirtualAlloc(NULL, (SIZE_T)si.dwPageSize * 2,
                        MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!base)
        return NULL;
    if (!VirtualProtect(base + si.dwPageSize, si.dwPageSize,
                        PAGE_NOACCESS, &old))
        return NULL;
    return base + si.dwPageSize;
#else
    long page = sysconf(_SC_PAGESIZE);
    char *base;

    if (page <= 0)
        return NULL;
    base = mmap(NULL, (size_t)page * 2, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED)
        return NULL;
    if (mprotect(base + page, (size_t)page, PROT_NONE) != 0)
        return NULL;
    return base + page;
#endif
}

int main(int argc, char **argv)
{
    const char *mode = argc > 1 ? argv[1] : "";
    char *edge = guarded_end();
    char *s;

    if (!edge) {
        printf("no guard page\n");
        return 2;
    }
    s = edge - CON_STR_MAX;
    memset(s, 'x', CON_STR_MAX);

    if (!strcmp(mode, "str")) {
        /* No NUL anywhere in the window, so the walk stops on its
         * bound - and the bound is the last byte it may read. */
        con_str(s);
    } else if (!strcmp(mode, "strl")) {
        /* con_strl walks for itself before it delegates, so this
         * reaches its own bound. The width is padding, clamped
         * elsewhere; it does not gate the walk. */
        con_strl(s, 8u);
    } else if (!strcmp(mode, "terminated")) {
        /* One shorter, terminated on the last legal byte. This is the
         * console_write fast path against the same boundary: a bound
         * kept by refusing to look is still wrong if the emitter then
         * hands a walker something it may not walk. */
        s[CON_STR_MAX - 1] = '\0';
        con_str(s);
    } else {
        printf("usage: guardpage str|strl|terminated\n");
        return 2;
    }

    printf("emitted %u\n", emitted);
    return 0;
}
