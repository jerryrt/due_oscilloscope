#include <Arduino.h>
#include "clock.h"

#define XTAL_HZ 12000000u

/* Bus matrix master numbers, datasheet Table 7-1. */
#define MATRIX_MASTER_USBDMA 3u

uint32_t clock_plla_hz(uint32_t mula)
{
	return XTAL_HZ * (mula + 1u);
}

bool clock_set_mck(uint32_t mula)
{
	uint32_t plla = clock_plla_hz(mula);

	/* Table 46-22: FOUT must be 96-192 MHz. */
	if (plla < 96000000u || plla > 192000000u)
		return false;

	/*
	 * Flash wait states are left at the 4 that SystemInit programmed for
	 * 84 MHz. Every frequency reachable here is at or below that, so the
	 * setting stays conservative rather than becoming marginal.
	 */

	/* Move the master clock off PLLA before reprogramming it. */
	PMC->PMC_MCKR = (PMC->PMC_MCKR & ~(uint32_t)PMC_MCKR_CSS_Msk)
	              | PMC_MCKR_CSS_MAIN_CLK;
	while (!(PMC->PMC_SR & PMC_SR_MCKRDY))
		{ }

	PMC->CKGR_PLLAR = CKGR_PLLAR_ONE
	                | CKGR_PLLAR_MULA(mula)
	                | CKGR_PLLAR_PLLACOUNT(0x3fUL)
	                | CKGR_PLLAR_DIVA(1UL);
	while (!(PMC->PMC_SR & PMC_SR_LOCKA))
		{ }

	/* Prescaler first with the main clock selected, then switch source. */
	PMC->PMC_MCKR = PMC_MCKR_PRES_CLK_2 | PMC_MCKR_CSS_MAIN_CLK;
	while (!(PMC->PMC_SR & PMC_SR_MCKRDY))
		{ }
	PMC->PMC_MCKR = PMC_MCKR_PRES_CLK_2 | PMC_MCKR_CSS_PLLA_CLK;
	while (!(PMC->PMC_SR & PMC_SR_MCKRDY))
		{ }

	SystemCoreClock = plla / 2u;

	/*
	 * The USB DMA's undefined-length bursts default to "infinite" and
	 * cannot be broken, so a bulk OUT stream landing in SRAM holds the
	 * matrix long enough that the ADC's PDC reads ADC_LCDR after the
	 * next conversion has overwritten it. Measured as ADC general
	 * overruns whenever playback and capture run together: ~130 in 6 s
	 * at a 200 ksps feed, thousands at the matched rate, and none with
	 * the same DAC rate played from a device-side table. Any limited
	 * burst clears it; 16 beats is the least restrictive.
	 */
	MATRIX->MATRIX_MCFG[MATRIX_MASTER_USBDMA] = MATRIX_MCFG_ULBT(4);

	/*
	 * Anything already derived from the old frequency has to be redone.
	 * SysTick was configured by the core's init() before setup() ran, so
	 * millis() would otherwise drift by the ratio of the two clocks.
	 *
	 * The UART needs no fixing here provided Serial.begin() is called
	 * after this: UARTClass computes its divisor from the runtime
	 * SystemCoreClock, not from a constant.
	 */
	SysTick_Config(SystemCoreClock / 1000u);
	return true;
}
