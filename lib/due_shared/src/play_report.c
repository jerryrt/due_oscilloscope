#include "play_report.h"
#include "console_out.h"

/*
 * One format string, one field order, one home: adding a field here
 * adds it to both tracks in the same position by construction, rather
 * than two printf calls that have to agree by inspection.
 */
void play_report_print(const play_report_t *r)
{
	con_str("# play: ");
	con_kv_u32("in", r->bytes_in);        con_ch(' ');
	con_kv_u32("produced", r->produced);  con_ch(' ');
	con_kv_u32("consumed", r->consumed);  con_ch(' ');
	con_kv_u32("under", r->underruns);    con_ch(' ');
	con_kv_u32("isr", r->isr_calls);      con_ch(' ');
	con_kv_u32("endtx", r->endtx_seen);   con_ch(' ');
	con_kv_u32("svc", r->svc_calls);      con_ch(' ');
	con_kv_u32("spans", r->spans);        con_ch(' ');
	con_kv_u32("partial", r->partial);    con_ch(' ');
	con_kv_u32("occmin", r->occ_min);
}
