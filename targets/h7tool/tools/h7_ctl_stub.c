/* Test stubs for fw/ctl_h7.c: the image's hooks, backed by plain variables, so the dispatcher can be compiled on the
 * host and driven with the project's own Python control parser (tools/test_h7_ctl.py). */
#include <stdint.h>
#include <string.h>
#include "ctl_h7.h"

static h7_config_t cfg = { 200, 800, 1, 0, 0, 3, 2036, 0 };
static int running, playing;
uint32_t stub_now_us = 123456;

uint32_t h7_us(void) { return stub_now_us; }
uint32_t h7_ms(void) { return stub_now_us / 1000u; }
uint32_t h7_build_id(void) { return 13; }
void h7_get_config(h7_config_t *c) { *c = cfg; }
int h7_set_config(const h7_config_t *c)
{
	if (running) return -1;
	if (c->adc_period < 80 || c->dac_period < 40 || c->chmask < 1 || c->chmask > 3 || c->gain1 > 7 || c->gain2 > 7) return -2;
	cfg = *c; return 0;
}
int h7_run(int on) { running = on; return running; }
int h7_play(int cmd, unsigned prime) { if (cmd && (prime < 1 || prime > 8)) return -1; playing = cmd; return playing; }
void h7_get_status(h7_status_t *s)
{
	memset(s, 0, sizeof *s);
	s->running = (uint8_t)running; s->playing = (uint8_t)playing; s->chmask = cfg.chmask;
	s->adc_period = cfg.adc_period; s->dac_period = cfg.dac_period; s->frames = 1000; s->sent = 998; s->lost = 2; s->build = 13;
}
