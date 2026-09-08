/*
 * `D`, the loop diagnostic. See diag.h for why this is a driver rather
 * than shared code.
 */

#include <stdbool.h>
#include <stdint.h>

#include "sam.h"

#include "acq.h"
#include "bsp.h"
#include "console_out.h"
#include "diag.h"
#include "play.h"

/*
 * Loop diagnostic: periodic snapshots taken while both service loops run.
 *
 * One run separates four hypotheses that the aggregate counters cannot
 * tell apart: a stalled ring (prod/cons stop), a PDC reading a stale
 * address (tpr stops walking the slots), a starved service loop (svc
 * stops advancing), and a capture path serving stale data while the DAC
 * output actually moves (cdr7 is the ADC's live last A0 conversion, read
 * straight from the register and bypassing the ring, the framer and USB).
 *
 * Snapshots go to memory and print only after the last one, because a
 * printf mid-run would stall the very loops being observed. The reads
 * are registers and counters, not the sample stream; `next` peeks one
 * half-word at DACC_TPR to see what the PDC is about to fetch, which is
 * a diagnostic exception to the no-CPU-on-samples rule, not a data path.
 */
#define DIAG_N 12u
#define DIAG_INTERVAL_MS 150u

struct diag_snap {
	uint32_t ms, prod, cons, endtx, svc;
	uint32_t tpr, tcr, tnpr;
	uint16_t next, cdr7, cdr6;
	uint32_t aprod, acons;
};

static struct diag_snap diag[DIAG_N];
static unsigned diag_count;
static uint32_t diag_next_ms;
volatile bool   diag_run;

void diag_start(void)
{
	diag_count = 0;
	diag_next_ms = millis();
	diag_run = true;
}

void diag_service(void)
{
	if (!diag_run)
		return;

	if (diag_count < DIAG_N) {
		uint32_t now = millis();
		struct diag_snap *s;

		if ((int32_t)(now - diag_next_ms) < 0)
			return;

		s = &diag[diag_count++];
		s->ms    = now;
		s->prod  = play_produced;
		s->cons  = play_consumed;
		s->endtx = play_endtx_seen;
		s->svc   = play_svc_calls;
		s->tpr   = DACC->DACC_TPR;
		s->tcr   = DACC->DACC_TCR;
		s->tnpr  = DACC->DACC_TNPR;
		s->next  = *(volatile uint16_t *)s->tpr;
		s->cdr7  = (uint16_t)ADC->ADC_CDR[7];
		s->cdr6  = (uint16_t)ADC->ADC_CDR[6];
		s->aprod = acq_produced;
		s->acons = acq_consumed;
		diag_next_ms = now + DIAG_INTERVAL_MS;
		return;
	}

	diag_run = false;

	{
		uint32_t base = (uint32_t)play_ring_base();

		con_str("# diag: play ring base=");
		con_hex32(base, 8);
		con_str(" slot="); con_u32(PLAY_BUF_BYTES);
		con_str(" B nslots="); con_u32(PLAY_NBUF); con_nl();
		con_str("#    ms  prod  cons endtx    svc  tpr=slot+off  tcr"
		        "  next(tag,code)  cdr7 cdr6  aprod acons\n");
		for (unsigned i = 0; i < DIAG_N; i++) {
			struct diag_snap *s = &diag[i];
			uint32_t off = s->tpr - base;

			con_str("# ");
			con_u32w(s->ms - diag[0].ms, 5, ' '); con_ch(' ');
			con_u32w(s->prod, 5, ' ');            con_ch(' ');
			con_u32w(s->cons, 5, ' ');            con_ch(' ');
			con_u32w(s->endtx, 5, ' ');           con_ch(' ');
			con_u32w(s->svc, 6, ' ');             con_str("  ");
			con_u32(off / PLAY_BUF_BYTES);        con_ch('+');
			con_u32l(off % PLAY_BUF_BYTES, 4);    con_ch(' ');
			con_u32w(s->tcr, 4, ' ');             con_str("  ");
			con_hex32(s->next, 4);
			con_str("(t"); con_u32((s->next >> 12) & 3u);
			con_ch(','); con_u32w(s->next & 0x0fffu, 4, ' ');
			con_str(")  ");
			con_u32w(s->cdr7 & 0x0fffu, 4, ' ');  con_ch(' ');
			con_u32w(s->cdr6 & 0x0fffu, 4, ' ');  con_str("  ");
			con_u32w(s->aprod, 5, ' ');           con_ch(' ');
			con_u32w(s->acons, 5, ' ');           con_nl();
		}
		uart_flush();
	}
}
