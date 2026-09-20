/*
 * newlib retargeting.
 *
 * printf ultimately calls _write; the rest are stubs the linker demands
 * even when unused. Built with -specs=nano.specs and -specs=nosys.specs
 * would supply weak versions, but defining them here keeps _write
 * pointed at our UART and avoids surprises.
 */

#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "bsp.h"

/*
 * NEWLIB'S NAMES AND THE LINKER SCRIPT'S, NOT OURS. clang-tidy reports
 * every identifier below as reserved in the global namespace, and it is
 * right about the rule: a leading underscore there belongs to the
 * implementation. These are the implementation's own - `_heap_start`
 * and `_heap_end` come from the linker script, and `_write`, `_read`,
 * `_sbrk` and the stubs are the entry points newlib links against by
 * name. Renaming one does not rename the symbol; it stops answering
 * for it, and the link fails or, worse, silently takes a weak stub.
 *
 * Suppressed per site, never by threshold or config, so a reserved name
 * this project invented would still be reported.
 */
/* NOLINTNEXTLINE(bugprone-reserved-identifier) - linker script's */
extern char _heap_start;
/* NOLINTNEXTLINE(bugprone-reserved-identifier) - linker script's */
extern char _heap_end;

#undef errno
extern int errno;

/*
 * `ptr` cannot become `const char *`, though cppcheck correctly sees
 * that nothing writes through it: this signature is newlib's, and the
 * library declares it. Changing it here does not change the contract,
 * it breaks agreement with it. The finding stands.
 */
/* NOLINTNEXTLINE(bugprone-reserved-identifier) - newlib's entry point */
int _write(int file, char *ptr, int len)
{
	(void)file;
	for (int i = 0; i < len; i++) {
		/* The host expects CRLF on a raw terminal. */
		if (ptr[i] == '\n')
			uart_putc_polled('\r');
		uart_putc_polled(ptr[i]);
	}
	return len;
}

/* NOLINTNEXTLINE(bugprone-reserved-identifier) - newlib's entry point */
int _read(int file, char *ptr, int len)
{
	(void)file;
	if (len <= 0)
		return 0;
	int c = uart_getc();
	if (c < 0)
		return 0;
	ptr[0] = (char)c;
	return 1;
}

/* NOLINTNEXTLINE(bugprone-reserved-identifier) - newlib's entry point */
caddr_t _sbrk(int incr)
{
	static char *heap = &_heap_start;
	char *prev = heap;

	/* comparePointers again, and the same answer as the startup file:
	 * `heap` walks a region whose end the linker script names, and
	 * that relationship exists nowhere in the C. */
	if (heap + incr > &_heap_end) {
		errno = ENOMEM;
		return (caddr_t)-1;
	}
	heap += incr;
	return (caddr_t)prev;
}

/* NOLINTBEGIN(bugprone-reserved-identifier) - newlib's entry points */
int _close(int file)                    { (void)file; return -1; }
int _isatty(int file)                   { (void)file; return 1; }
int _lseek(int file, int p, int d)      { (void)file; (void)p; (void)d; return 0; }
int _getpid(void)                       { return 1; }
int _kill(int pid, int sig)             { (void)pid; (void)sig; errno = EINVAL; return -1; }
void _exit(int status)                  { (void)status; for (;;) { } }

int _fstat(int file, struct stat *st)
{
	(void)file;
	st->st_mode = S_IFCHR;
	return 0;
}
/* NOLINTEND(bugprone-reserved-identifier) */
