/* See crashrec.h. */
#include <stddef.h>
#include "crashrec.h"
#include "frame.h"          /* frame_crc32() */

#ifndef CRASHREC_SECTION
#define CRASHREC_SECTION __attribute__((section(".noinit")))
#endif

/* The one block, in RAM the start-up code leaves alone. */
static volatile struct crashrec rec CRASHREC_SECTION;

static struct crashrec_boot_info boot_info;

static uint32_t rec_crc(const volatile struct crashrec *r)
{
	struct crashrec copy;
	const volatile uint32_t *s = (const volatile uint32_t *)r;
	uint32_t *d = (uint32_t *)&copy;

	for (unsigned i = 0; i < sizeof(copy) / 4u; i++)
		d[i] = s[i];
	return frame_crc32((const uint8_t *)&copy, offsetof(struct crashrec, crc));
}

static int rec_valid(void)
{
	return rec.magic == CRASHREC_MAGIC && rec.version == CRASHREC_VERSION &&
	       rec.crc == rec_crc(&rec);
}

static void rec_seal(void)
{
	rec.crc = rec_crc(&rec);
}

static void rec_init(void)
{
	volatile uint32_t *p = (volatile uint32_t *)&rec;

	for (unsigned i = 0; i < sizeof(rec) / 4u; i++)
		p[i] = 0;
	rec.magic = CRASHREC_MAGIC;
	rec.version = CRASHREC_VERSION;
	rec_seal();
}

void crashrec_store(const uint32_t *frame, uint32_t cfsr, uint32_t hfsr,
		    uint32_t mmfar, uint32_t bfar)
{
	if (!rec_valid())
		rec_init();

	rec.count++;
	rec.streak++;
	rec.pending = 1;
	for (unsigned i = 0; i < 8u; i++)
		rec.frame[i] = frame[i];
	rec.cfsr = cfsr;
	rec.hfsr = hfsr;
	rec.mmfar = mmfar;
	rec.bfar = bfar;
	rec.sp = (uint32_t)(uintptr_t)frame;
	rec_seal();
}

int crashrec_should_reset(void)
{
	return rec_valid() && rec.streak < CRASHREC_MAX_STREAK;
}

void crashrec_boot(uint32_t rstc_sr)
{
	const volatile uint32_t *s;
	uint32_t *d;

	boot_info.rstc_sr = rstc_sr;
	boot_info.had_fault = 0;

	if (!rec_valid())
		rec_init();          /* garbage or power-on: empty, not a fault */

	s = (const volatile uint32_t *)&rec;
	d = (uint32_t *)&boot_info.rec;
	for (unsigned i = 0; i < sizeof(rec) / 4u; i++)
		d[i] = s[i];

	if (rec.pending) {
		boot_info.had_fault = 1;
		rec.pending = 0;      /* reported once; count and streak stay */
		rec_seal();
	}
}

const struct crashrec_boot_info *crashrec_info(void)
{
	return &boot_info;
}

void crashrec_healthy(uint32_t uptime_ms)
{
	if (uptime_ms >= CRASHREC_HEALTHY_MS && rec.streak != 0 && rec_valid()) {
		rec.streak = 0;
		rec_seal();
	}
}

const char *crashrec_reset_name(uint32_t rstc_sr)
{
	switch ((rstc_sr >> 8) & 7u) {      /* RSTTYP */
	case 0: return "power-on";
	case 1: return "backup";
	case 2: return "watchdog";
	case 3: return "software";
	case 4: return "user-pin";
	default: return "unknown";
	}
}
