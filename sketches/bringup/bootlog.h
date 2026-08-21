/*
 * Boot and state logging.
 *
 * Added after several debugging sessions were spent *inferring* firmware
 * state from indirect evidence. A benchmark once reported 0.27 MB/s for
 * a transfer the host had clocked at 3.05 MB/s, and working out why took
 * many iterations of guesswork; the actual cause was the board silently
 * resetting when the control port was opened, which a boot counter would
 * have shown immediately.
 *
 * The rule this encodes: never infer firmware state that the firmware
 * can simply report.
 *
 * The boot counter lives in a general purpose backup register, which
 * survives a reset, so repeated resets are visible as an increasing
 * count rather than having to be deduced from an uptime that looks
 * wrong.
 */

#ifndef BOOTLOG_H
#define BOOTLOG_H

#include <stdint.h>

void        boot_log(void);          /* call once, right after UART init */
uint32_t    boot_count(void);
const char *reset_cause(void);
void        state_log(const char *what);   /* key state transitions */

#endif /* BOOTLOG_H */
