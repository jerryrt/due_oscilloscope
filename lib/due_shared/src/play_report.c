#include <stdio.h>

#include "play_report.h"

/*
 * One format string, one field order, one home.
 *
 * Adding a field here adds it to both tracks in the same position by
 * construction, which is the entire reason this function exists rather
 * than two printf calls that agree by inspection. It costs about a
 * dozen bytes of UART on `B` - invariant 8's rule is that a console
 * command costs the bytes it puts on the wire, and this is a debug
 * command already measured at 13.14 ms.
 */
int play_report_format(char *buf, unsigned n, const play_report_t *r)
{
	return snprintf(buf, n,
			"# play: in=%lu produced=%lu consumed=%lu under=%lu "
			"isr=%lu endtx=%lu svc=%lu spans=%lu partial=%lu "
			"occmin=%lu",
			(unsigned long)r->bytes_in,
			(unsigned long)r->produced,
			(unsigned long)r->consumed,
			(unsigned long)r->underruns,
			(unsigned long)r->isr_calls,
			(unsigned long)r->endtx_seen,
			(unsigned long)r->svc_calls,
			(unsigned long)r->spans,
			(unsigned long)r->partial,
			(unsigned long)r->occ_min);
}
