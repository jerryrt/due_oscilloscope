/*
 * See chipid.h. Register addresses are spelled here rather than through
 * the CMSIS device header so this file compiles the same way on every
 * track's include path; there are three of them and nothing else.
 */
#include "chipid.h"

#define EEFC0_FCR     (*(volatile uint32_t *)0x400E0A04u)
#define EEFC0_FSR     (*(volatile uint32_t *)0x400E0A08u)
#define IFLASH0_BASE  ((volatile const uint32_t *)0x00080000u)

#define FCR_FKEY      (0x5Au << 24)
#define FCMD_STUI     0x0Eu   /* start read unique identifier */
#define FCMD_SPUI     0x0Fu   /* stop read unique identifier */
#define FSR_FRDY      0x1u

/*
 * Everything between the two commands executes from SRAM: the function
 * body, the polls, the four loads. noinline keeps a flash caller from
 * pulling the body into itself; the plain loops keep the compiler from
 * emitting a call to memcpy, which lives in flash.
 */
__attribute__((section(".ramfunc"), noinline, used))
static void chipid_read_ram(volatile uint32_t out[4])
{
	uint32_t primask;
	__asm__ volatile ("mrs %0, primask\n\tcpsid i" : "=r"(primask) :: "memory");

	EEFC0_FCR = FCR_FKEY | FCMD_STUI;
	/* FRDY FALLS when the identifier is exposed (datasheet, EEFC). */
	while (EEFC0_FSR & FSR_FRDY) { }

	for (unsigned i = 0; i < 4u; i++)
		out[i] = IFLASH0_BASE[i];

	EEFC0_FCR = FCR_FKEY | FCMD_SPUI;
	/* and rises again once the program is back. */
	while (!(EEFC0_FSR & FSR_FRDY)) { }

	__asm__ volatile ("msr primask, %0" :: "r"(primask) : "memory");
}

void chipid_read(uint32_t out[4])
{
	volatile uint32_t tmp[4];
	chipid_read_ram(tmp);
	for (unsigned i = 0; i < 4u; i++)
		out[i] = tmp[i];
}
