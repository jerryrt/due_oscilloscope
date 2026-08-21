#include <Arduino.h>
#include "bootlog.h"

const char *reset_cause(void)
{
	uint32_t t = (RSTC->RSTC_SR & RSTC_SR_RSTTYP_Msk) >> RSTC_SR_RSTTYP_Pos;

	switch (t) {
	case 0: return "power-up";
	case 1: return "backup";
	case 2: return "watchdog";
	case 3: return "software";
	case 4: return "NRST pin";   /* the 16U2 asserting reset */
	default: return "unknown";
	}
}

uint32_t boot_count(void)
{
	return GPBR->SYS_GPBR[0];
}

void boot_log(void)
{
	/* Backup registers survive reset, so this counts real boots. */
	GPBR->SYS_GPBR[0] = GPBR->SYS_GPBR[0] + 1u;

	Serial.println("#");
	Serial.print("# BOOT #");
	Serial.print(GPBR->SYS_GPBR[0]);
	Serial.print("  cause=");
	Serial.println(reset_cause());
	Serial.print("# MCK=");
	Serial.print(SystemCoreClock);
	Serial.print(" F_CPU=");
	Serial.print((uint32_t)F_CPU);
	Serial.print(" SysTick_LOAD=");
	Serial.print(SysTick->LOAD);
	Serial.print(" ADCclk=");
	Serial.println(SystemCoreClock / 4u);
	if ((uint32_t)F_CPU != SystemCoreClock)
		Serial.println("# WARNING: F_CPU != SystemCoreClock, micros() is wrong");
	Serial.flush();
}

void state_log(const char *what)
{
	Serial.print("# STATE ");
	Serial.print(millis());
	Serial.print("ms boot#");
	Serial.print(GPBR->SYS_GPBR[0]);
	Serial.print(" ");
	Serial.println(what);
	Serial.flush();
}
