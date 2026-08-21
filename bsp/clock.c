#include "sam.h"
#include "clock.h"

#define XTAL_HZ 12000000u

bool clock_set_mck(uint32_t mula)
{
	uint32_t plla = XTAL_HZ * (mula + 1u);

	/* Table 46-22: FOUT must be 96-192 MHz. */
	if (plla < 96000000u || plla > 192000000u)
		return false;

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

	PMC->PMC_MCKR = PMC_MCKR_PRES_CLK_2 | PMC_MCKR_CSS_MAIN_CLK;
	while (!(PMC->PMC_SR & PMC_SR_MCKRDY))
		{ }
	PMC->PMC_MCKR = PMC_MCKR_PRES_CLK_2 | PMC_MCKR_CSS_PLLA_CLK;
	while (!(PMC->PMC_SR & PMC_SR_MCKRDY))
		{ }

	/*
	 * Everything downstream reads SystemCoreClock, so UART baud, SysTick
	 * and timer compare values all follow provided they are initialised
	 * after this call.
	 */
	SystemCoreClock = plla / 2u;
	return true;
}
