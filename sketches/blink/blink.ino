/*
 * Track A bring-up oracle: minimal blink.
 *
 * Purpose is to prove the toolchain and flash path end to end, nothing
 * more. If this does not run, the problem is the host setup or the
 * board, not any firmware under development.
 *
 * LED is pin 13 = PB27 on the SAM3X8E.
 */

void setup()
{
	pinMode(LED_BUILTIN, OUTPUT);
}

void loop()
{
	digitalWrite(LED_BUILTIN, HIGH);
	delay(200);
	digitalWrite(LED_BUILTIN, LOW);
	delay(800);
}
