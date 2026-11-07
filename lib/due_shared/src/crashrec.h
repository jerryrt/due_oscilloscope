/*
 * A fault record that survives a reset, and the reset cause beside it.
 *
 * Without a debug probe an unhandled fault is a silent lockup, and the
 * register dump the HardFault handler prints goes to a UART nobody may
 * be reading (bsp/fault.c). This keeps the same frame in a RAM block the
 * start-up code does not clear, resets the part, and reports it at the
 * next boot.
 *
 * Survives a processor/peripheral reset, which is where the fault path
 * ends; not a power cycle, when SRAM is undefined. A block that fails its
 * magic or CRC is empty, never a fault. Constant memory and time
 * (invariant 7): one fixed struct; crashrec_store() runs in fault context
 * and calls nothing but the CRC. The block lives in `.noinit`.
 */
#ifndef CRASHREC_H
#define CRASHREC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CRASHREC_MAGIC     0xC4A5E001u
#define CRASHREC_VERSION   1u

/* Faults in a row, with no healthy period between, after which the
 * handler stops resetting and blinks instead: a fault in early boot
 * would otherwise reset for ever and hide behind a "working" board. */
#define CRASHREC_MAX_STREAK  3u

/* How long the main loop must have run before the streak is cleared. */
#define CRASHREC_HEALTHY_MS  5000u

struct crashrec {
	uint32_t magic;
	uint32_t version;
	uint32_t count;       /* faults since the block was last initialised */
	uint32_t streak;      /* consecutive faults, cleared by _healthy()   */
	uint32_t pending;     /* 1 until reported by _take()                 */
	uint32_t frame[8];    /* r0 r1 r2 r3 r12 lr pc xpsr as stacked       */
	uint32_t cfsr, hfsr, mmfar, bfar;
	uint32_t sp;          /* the frame's address                         */
	uint32_t crc;         /* over every word above                       */
};

/* What this boot found. Filled by crashrec_boot(). */
struct crashrec_boot_info {
	uint32_t rstc_sr;     /* RSTC_SR as read at start-up                 */
	int      had_fault;   /* a pending record was found and consumed     */
	struct crashrec rec;  /* the block as found (count/streak always)    */
};

/* Fault context. Records the stacked frame and the fault registers. */
void crashrec_store(const uint32_t *frame, uint32_t cfsr, uint32_t hfsr,
		    uint32_t mmfar, uint32_t bfar);

/* True while the handler should reset instead of blinking. Call after
 * crashrec_store(), which has already counted this fault. */
int crashrec_should_reset(void);

/* First thing in main(): read the block, consume a pending record, keep
 * the reset cause. Must run before anything can fault again. */
void crashrec_boot(uint32_t rstc_sr);

/* What crashrec_boot() found. Valid for the life of the boot. */
const struct crashrec_boot_info *crashrec_info(void);

/* The main loop calls this every pass; it clears the streak once
 * `uptime_ms` has passed CRASHREC_HEALTHY_MS. Cheap and idempotent. */
void crashrec_healthy(uint32_t uptime_ms);

/* RSTC_SR's RSTTYP field as a word. Never NULL. */
const char *crashrec_reset_name(uint32_t rstc_sr);

#ifdef __cplusplus
}
#endif

#endif /* CRASHREC_H */
