/* Test stub that turns the exploring opcodes on (fw/ctl_h7.c): a 64-word memory at 0x1000, test 1 returns its arguments
 * doubled, test 2 is refused. Linked with h7_ctl_stub.c by tests/test_h7_ctl.py. */
#include <stdint.h>
#include "ctl_h7.h"

static uint32_t mem[64];
int h7_explore_supported(void) { return 1; }
int h7_peek(uint32_t a, uint32_t *o, unsigned n)
{
	if (a < 0x1000u || a + 4u * n > 0x1000u + sizeof mem) return -1;
	for (unsigned i = 0; i < n; i++) o[i] = mem[(a - 0x1000u) / 4u + i];
	return 0;
}
int h7_poke(uint32_t a, uint32_t v, unsigned w)
{
	if (a < 0x1000u || a + w > 0x1000u + sizeof mem) return -1;
	uint8_t *m = (uint8_t *)mem + (a - 0x1000u);
	for (unsigned i = 0; i < w; i++) m[i] = (uint8_t)(v >> (8 * i));
	return 0;
}
int h7_explore(unsigned id, const uint32_t *a, unsigned na, uint32_t *r, unsigned *nr)
{
	if (id != 1) return -2;
	for (unsigned i = 0; i < na; i++) r[i] = a[i] * 2u;
	*nr = na; return 0;
}

/* a 240 x 320 "screen" whose byte at offset n is n * 7 + 3, and a draw count that moves on every read of the info */
static uint8_t screen[240 * 320 * 2];
static uint32_t screen_draws = 41;
const uint8_t *h7_screen(uint16_t *w, uint16_t *h, uint32_t *d)
{
	if (!screen[1]) for (unsigned i = 0; i < sizeof screen; i++) screen[i] = (uint8_t)(i * 7u + 3u);
	*w = 240; *h = 320; *d = screen_draws;
	return screen;
}
void stub_set_draws(uint32_t d) { screen_draws = d; }
