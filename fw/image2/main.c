/* Image 2: USB-less test image with a self-timed return to the boot loader.
 *
 * Build with -DTEST_TVCC to also drive TVCC (PC13 enable, MCP4018 at 0x5E on
 * soft I2C PI7=SCL / PF15=SDA, as the stock V2.33 code does on this board).
 * Without it the image only waits and returns to the boot loader, to prove
 * that path first. Core stays on its reset clock (HSI, 64 MHz). */
#include <stdint.h>

#define RCC_AHB4ENR  (*(volatile uint32_t *)0x58024540u)
#define GPIOC_MODER  (*(volatile uint32_t *)0x58020800u)
#define GPIOC_BSRR   (*(volatile uint32_t *)0x58020818u)
#define GPIOF_MODER  (*(volatile uint32_t *)0x58021400u)
#define GPIOF_OTYPER (*(volatile uint32_t *)0x58021404u)
#define GPIOF_IDR    (*(volatile uint32_t *)0x58021410u)
#define GPIOF_BSRR   (*(volatile uint32_t *)0x58021418u)
#define GPIOI_MODER  (*(volatile uint32_t *)0x58022000u)
#define GPIOI_OTYPER (*(volatile uint32_t *)0x58022004u)
#define GPIOI_BSRR   (*(volatile uint32_t *)0x58022018u)
#define SYST_CSR     (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR     (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR     (*(volatile uint32_t *)0xE000E018u)
#define SCB_AIRCR    (*(volatile uint32_t *)0xE000ED0Cu)
#define BOOT_REQ     (*(volatile uint32_t *)0x20000000u)

#define BOOT_MAGIC   0x5AA51234u
#define CPU_HZ       64000000u                /* HSI at reset *(check)* */

#ifndef RUN_MS
#define RUN_MS       8000u                    /* time before returning to the boot loader */
#endif

/* TVCC: code 5 -> 1.346 V, code 100 -> 4.265 V in this unit's calibration
 * (V = 1.1922 + 0.030731 * code). The Due's A0, a 3.3 V pin, sits on TVCC:
 * never allow more than CODE_MAX. */
#define TVCC_CODE    7u
#define CODE_MIN     5u
#define CODE_MAX     20u                      /* ~1.81 V */

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

static void delay_ms(uint32_t ms)
{
	while (ms--) {
		uint32_t start = SYST_CVR;
		while (((start - SYST_CVR) & 0xFFFFFFu) < CPU_HZ / 1000u) { }
	}
}

static void delay_us(uint32_t us)
{
	uint32_t start = SYST_CVR, n = us * (CPU_HZ / 1000000u);
	while (((start - SYST_CVR) & 0xFFFFFFu) < n) { }
}

static void return_to_boot_loader(void)
{
	GPIOC_BSRR = 1u << (13 + 16);            /* TVCC off first */
	BOOT_REQ = BOOT_MAGIC;
	__asm volatile ("dsb sy" ::: "memory");
	SCB_AIRCR = 0x05FA0004u;                 /* SYSRESETREQ */
	for (;;) { }
}

#ifdef TEST_TVCC
/* Open-drain soft I2C. SCL = GPIOI bit 7, SDA = GPIOF bit 15 (BSRR set = bit,
 * reset = bit + 16), idle high through the board's pull-ups. */
#define SCL_H()  (GPIOI_BSRR = 1u << 7)
#define SCL_L()  (GPIOI_BSRR = 1u << (7 + 16))
#define SDA_H()  (GPIOF_BSRR = 1u << 15)
#define SDA_L()  (GPIOF_BSRR = 1u << (15 + 16))
#define SDA_RD() ((GPIOF_IDR >> 15) & 1u)
#define T_I2C()  delay_us(5)

static void i2c_start(void) { SDA_H(); SCL_H(); T_I2C(); SDA_L(); T_I2C(); SCL_L(); T_I2C(); }
static void i2c_stop(void)  { SDA_L(); T_I2C(); SCL_H(); T_I2C(); SDA_H(); T_I2C(); }

static int i2c_write(uint8_t b)               /* returns 1 if ACKed */
{
	for (int i = 7; i >= 0; i--) {
		if (b & (1u << i)) SDA_H(); else SDA_L();
		T_I2C(); SCL_H(); T_I2C(); SCL_L(); T_I2C();
	}
	SDA_H(); T_I2C(); SCL_H(); T_I2C();
	int ack = !SDA_RD();
	SCL_L(); T_I2C();
	return ack;
}

static int tvcc_start(uint32_t code)
{
	if (code < CODE_MIN) code = CODE_MIN;
	if (code > CODE_MAX) code = CODE_MAX;
	GPIOC_BSRR = 1u << (13 + 16);            /* stays off while the pot is written */
	i2c_start();
	int ok = i2c_write(0x5E) && i2c_write((uint8_t)code);
	i2c_stop();
	if (!ok) return 0;                       /* never enable on a failed write */
	GPIOC_BSRR = 1u << 13;
	return 1;
}
#endif

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;

	SYST_RVR = 0xFFFFFFu;
	SYST_CSR = 5u;                           /* enable, core clock, no interrupt */

#ifdef TEST_TVCC
	RCC_AHB4ENR |= (1u << 2) | (1u << 5) | (1u << 8);   /* GPIOC, GPIOF, GPIOI */
	(void)RCC_AHB4ENR;
	GPIOC_BSRR = 1u << (13 + 16);
	GPIOC_MODER = (GPIOC_MODER & ~(3u << 26)) | (1u << 26);          /* PC13 output */
	GPIOI_OTYPER |= 1u << 7;  GPIOI_BSRR = 1u << 7;
	GPIOF_OTYPER |= 1u << 15; GPIOF_BSRR = 1u << 15;
	GPIOI_MODER = (GPIOI_MODER & ~(3u << 14)) | (1u << 14);          /* PI7 output OD */
	GPIOF_MODER = (GPIOF_MODER & ~(3u << 30)) | (1u << 30);          /* PF15 output OD */
	delay_ms(500);
	(void)tvcc_start(TVCC_CODE);
#endif
	delay_ms(RUN_MS);
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
