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

extern char _heap_start;
extern char _heap_end;

#undef errno
extern int errno;

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

caddr_t _sbrk(int incr)
{
	static char *heap = &_heap_start;
	char *prev = heap;

	if (heap + incr > &_heap_end) {
		errno = ENOMEM;
		return (caddr_t)-1;
	}
	heap += incr;
	return (caddr_t)prev;
}

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
