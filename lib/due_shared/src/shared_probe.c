#include "shared_probe.h"

/*
 * Deliberately a function and not just the macro: a macro proves the
 * header was found, and this proves the translation unit was compiled
 * and linked by both build systems, which is the actual question.
 */
uint32_t shared_probe_magic(void)
{
	return SHARED_PROBE_MAGIC;
}
