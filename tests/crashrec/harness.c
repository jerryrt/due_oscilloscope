/*
 * Host harness for lib/due_shared/src/crashrec.c.
 *
 * Includes the source so it can reach the static block and play the part
 * of "RAM that a reset does not clear": the block persists across calls to
 * crashrec_boot(), which stands in for a restart.
 */
#define CRASHREC_SECTION
#include CRASHREC_SRC
#include <stdio.h>
#include <string.h>

static int failures;

#define CHECK(cond, msg) do { if (!(cond)) { \
	printf("FAIL: %s\n", msg); failures++; } } while (0)

static void garbage(void)
{
	volatile uint32_t *p = (volatile uint32_t *)&rec;
	for (unsigned i = 0; i < sizeof(rec) / 4u; i++)
		p[i] = 0xA5A5A5A5u ^ (i * 2654435761u);
}

int main(void)
{
	uint32_t frame[8] = { 1, 2, 3, 4, 5, 0x08001235u, 0x08002468u, 0x01000000u };
	const struct crashrec_boot_info *in;

	/* 1. Power-on garbage is empty, never a fault. */
	garbage();
	crashrec_boot(0x0u);
	in = crashrec_info();
	CHECK(!in->had_fault, "garbage block reported as a fault");
	CHECK(in->rec.count == 0 && in->rec.streak == 0, "garbage block kept a count");
	CHECK(!rec.pending, "garbage block left a pending record");

	/* 2. A stored fault survives a restart and is reported once. */
	crashrec_store(frame, 0x00020000u, 0x40000000u, 0xDEAD0001u, 0xBEEF0002u);
	CHECK(crashrec_should_reset(), "first fault should reset");
	crashrec_boot(0x00000300u);
	in = crashrec_info();
	CHECK(in->had_fault, "stored fault not found after restart");
	CHECK(in->rec.frame[6] == 0x08002468u, "PC not carried through");
	CHECK(in->rec.frame[5] == 0x08001235u, "LR not carried through");
	CHECK(in->rec.cfsr == 0x00020000u && in->rec.hfsr == 0x40000000u,
	      "fault status registers not carried through");
	CHECK(in->rec.mmfar == 0xDEAD0001u && in->rec.bfar == 0xBEEF0002u,
	      "fault address registers not carried through");
	CHECK(in->rec.count == 1 && in->rec.streak == 1, "count/streak wrong after one fault");
	CHECK(in->rstc_sr == 0x300u, "reset cause not kept");

	/* 3. Reported once: the next restart finds nothing, keeps the count. */
	crashrec_boot(0x00000300u);
	in = crashrec_info();
	CHECK(!in->had_fault, "fault reported twice");
	CHECK(in->rec.count == 1, "count lost after consumption");

	/* 4. One flipped bit makes the block empty, not a fault. */
	crashrec_store(frame, 0, 0, 0, 0);
	((volatile uint32_t *)&rec)[7] ^= 0x1u;
	crashrec_boot(0);
	in = crashrec_info();
	CHECK(!in->had_fault, "corrupted block reported as a fault");
	CHECK(in->rec.count == 0, "corrupted block kept its count");

	/* 5. Wrong version or magic: empty. */
	crashrec_store(frame, 0, 0, 0, 0);
	rec.version = 99; rec_seal();
	crashrec_boot(0);
	CHECK(!crashrec_info()->had_fault, "wrong version reported as a fault");

	/* 6. Streak: reset twice, then stop; healthy clears it. */
	garbage(); crashrec_boot(0);
	crashrec_store(frame, 0, 0, 0, 0);
	CHECK(crashrec_should_reset(), "fault 1 of 3 should reset");
	crashrec_store(frame, 0, 0, 0, 0);
	CHECK(crashrec_should_reset(), "fault 2 of 3 should reset");
	crashrec_store(frame, 0, 0, 0, 0);
	CHECK(!crashrec_should_reset(), "fault 3 in a row must not reset (loop guard)");
	crashrec_healthy(CRASHREC_HEALTHY_MS - 1u);
	CHECK(rec.streak == 3, "streak cleared before the healthy time");
	crashrec_healthy(CRASHREC_HEALTHY_MS);
	CHECK(rec.streak == 0, "streak not cleared after the healthy time");
	CHECK(rec.count == 3, "healthy must not clear the lifetime count");
	crashrec_store(frame, 0, 0, 0, 0);
	CHECK(crashrec_should_reset(), "fault after a healthy period should reset again");

	/* 7. Reset names. */
	CHECK(!strcmp(crashrec_reset_name(0x000), "power-on"), "name 0");
	CHECK(!strcmp(crashrec_reset_name(0x100), "backup"), "name 1");
	CHECK(!strcmp(crashrec_reset_name(0x200), "watchdog"), "name 2");
	CHECK(!strcmp(crashrec_reset_name(0x300), "software"), "name 3");
	CHECK(!strcmp(crashrec_reset_name(0x400), "user-pin"), "name 4");
	CHECK(!strcmp(crashrec_reset_name(0x700), "unknown"), "name 7");

	puts(failures ? "FAILED" : "PASS");
	return failures ? 1 : 0;
}
