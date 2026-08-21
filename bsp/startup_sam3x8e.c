/*
 * Reset entry and vector table for SAM3X8E.
 *
 * Written rather than taken from Atmel so that the vector table stays
 * under this project's control. FreeRTOS integration needs SVC_Handler,
 * PendSV_Handler and SysTick_Handler routed to the kernel's handlers,
 * and doing that is a one-line change here. See docs/rtos.md.
 */

#include "sam.h"

extern uint32_t _sdata, _edata, _sbss, _ebss, _etext, _estack;

extern int main(void);
extern void __libc_init_array(void);

void Reset_Handler(void);
static void Default_Handler(void);

#define ALIAS(f) __attribute__((weak, alias(#f)))

/* Cortex-M3 system exceptions */
void NMI_Handler(void)        ALIAS(Default_Handler);
void MemManage_Handler(void)  ALIAS(Default_Handler);
void BusFault_Handler(void)   ALIAS(Default_Handler);
void UsageFault_Handler(void) ALIAS(Default_Handler);
void SVC_Handler(void)        ALIAS(Default_Handler);
void DebugMon_Handler(void)   ALIAS(Default_Handler);
void PendSV_Handler(void)     ALIAS(Default_Handler);
/* HardFault_Handler and SysTick_Handler are defined in bsp/fault.c and
 * bsp/systick.c respectively; declared here only for the table. */
void HardFault_Handler(void);
void SysTick_Handler(void);

/* SAM3X8E peripheral interrupts, IDs 0..44 */
void SUPC_Handler(void)   ALIAS(Default_Handler);
void RSTC_Handler(void)   ALIAS(Default_Handler);
void RTC_Handler(void)    ALIAS(Default_Handler);
void RTT_Handler(void)    ALIAS(Default_Handler);
void WDT_Handler(void)    ALIAS(Default_Handler);
void PMC_Handler(void)    ALIAS(Default_Handler);
void EFC0_Handler(void)   ALIAS(Default_Handler);
void EFC1_Handler(void)   ALIAS(Default_Handler);
void UART_Handler(void)   ALIAS(Default_Handler);
void SMC_Handler(void)    ALIAS(Default_Handler);
void PIOA_Handler(void)   ALIAS(Default_Handler);
void PIOB_Handler(void)   ALIAS(Default_Handler);
void PIOC_Handler(void)   ALIAS(Default_Handler);
void PIOD_Handler(void)   ALIAS(Default_Handler);
void USART0_Handler(void) ALIAS(Default_Handler);
void USART1_Handler(void) ALIAS(Default_Handler);
void USART2_Handler(void) ALIAS(Default_Handler);
void USART3_Handler(void) ALIAS(Default_Handler);
void HSMCI_Handler(void)  ALIAS(Default_Handler);
void TWI0_Handler(void)   ALIAS(Default_Handler);
void TWI1_Handler(void)   ALIAS(Default_Handler);
void SPI0_Handler(void)   ALIAS(Default_Handler);
void SPI1_Handler(void)   ALIAS(Default_Handler);
void SSC_Handler(void)    ALIAS(Default_Handler);
void TC0_Handler(void)    ALIAS(Default_Handler);
void TC1_Handler(void)    ALIAS(Default_Handler);
void TC2_Handler(void)    ALIAS(Default_Handler);
void TC3_Handler(void)    ALIAS(Default_Handler);
void TC4_Handler(void)    ALIAS(Default_Handler);
void TC5_Handler(void)    ALIAS(Default_Handler);
void TC6_Handler(void)    ALIAS(Default_Handler);
void TC7_Handler(void)    ALIAS(Default_Handler);
void TC8_Handler(void)    ALIAS(Default_Handler);
void PWM_Handler(void)    ALIAS(Default_Handler);
void ADC_Handler(void)    ALIAS(Default_Handler);
void DACC_Handler(void)   ALIAS(Default_Handler);
void DMAC_Handler(void)   ALIAS(Default_Handler);
void UOTGHS_Handler(void) ALIAS(Default_Handler);
void TRNG_Handler(void)   ALIAS(Default_Handler);
void EMAC_Handler(void)   ALIAS(Default_Handler);
void CAN0_Handler(void)   ALIAS(Default_Handler);
void CAN1_Handler(void)   ALIAS(Default_Handler);

typedef void (*vector_t)(void);

__attribute__((section(".vectors"), used))
const vector_t exception_table[] = {
	(vector_t)(&_estack),
	Reset_Handler,
	NMI_Handler,
	HardFault_Handler,
	MemManage_Handler,
	BusFault_Handler,
	UsageFault_Handler,
	0, 0, 0, 0,
	SVC_Handler,
	DebugMon_Handler,
	0,
	PendSV_Handler,
	SysTick_Handler,

	SUPC_Handler,   RSTC_Handler,   RTC_Handler,    RTT_Handler,
	WDT_Handler,    PMC_Handler,    EFC0_Handler,   EFC1_Handler,
	UART_Handler,   SMC_Handler,    0,              PIOA_Handler,
	PIOB_Handler,   PIOC_Handler,   PIOD_Handler,   0,
	0,              USART0_Handler, USART1_Handler, USART2_Handler,
	USART3_Handler, HSMCI_Handler,  TWI0_Handler,   TWI1_Handler,
	SPI0_Handler,   SPI1_Handler,   SSC_Handler,    TC0_Handler,
	TC1_Handler,    TC2_Handler,    TC3_Handler,    TC4_Handler,
	TC5_Handler,    TC6_Handler,    TC7_Handler,    TC8_Handler,
	PWM_Handler,    ADC_Handler,    DACC_Handler,   DMAC_Handler,
	UOTGHS_Handler, TRNG_Handler,   EMAC_Handler,   CAN0_Handler,
	CAN1_Handler
};

static void Default_Handler(void)
{
	for (;;) { }
}

/*
 * __libc_init_array() calls _init(), which normally comes from crti.o.
 * -nostartfiles excludes those, so supply empty stubs. Nothing in this
 * project uses .init/.fini; C++ static constructors would arrive through
 * .init_array, which __libc_init_array walks separately.
 */
void _init(void) { }
void _fini(void) { }

void Reset_Handler(void)
{
	uint32_t *src, *dst;

	/* Copy initialised data from its load address in flash. */
	src = &_etext;
	dst = &_sdata;
	while (dst < &_edata)
		*dst++ = *src++;

	/* Zero .bss. */
	dst = &_sbss;
	while (dst < &_ebss)
		*dst++ = 0;

	/* Point the VTOR at our table: the ROM bootloader left it elsewhere. */
	SCB->VTOR = (uint32_t)exception_table & SCB_VTOR_TBLOFF_Msk;

	/* Clock bring-up: 12 MHz crystal, PLLA x14 /1, MCK prescale /2,
	 * giving MCK = 84 MHz. Provided by the pinned CMSIS source. */
	SystemInit();

	__libc_init_array();

	main();

	for (;;) { }
}
