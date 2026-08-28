/*
 * Track A's half of the console seam. See lib/due_shared/src/console.h
 * for what is shared and why, and console_port.h for the rule that
 * keeps this file two functions long.
 */

#include <Arduino.h>

#include "console_port.h"

void console_write(const char *s)
{
	Serial.print(s);
}

void console_flush(void)
{
	Serial.flush();
}
