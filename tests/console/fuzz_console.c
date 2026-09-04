/*
 * The debug console, driven with arbitrary bytes.
 *
 * console.c is the other shared parser a peer feeds directly. Where
 * ctl.c consumes a framed, CRC'd, version-gated stream on the command
 * port, this one consumes raw keystrokes on the programming port: no
 * framing, no checksum and no version, so anything a serial cable can
 * put on the wire reaches console_feed() one byte at a time. It reaches
 * the outside world only through console_port.h and ctl_port.h, which
 * are records of exactly that seam, so the real files mock whole on a
 * host compiler - the same property stream_port.h gives the framer and
 * ctl_port.h gives the control parser.
 *
 * WHAT IS BEING TESTED IS INVARIANT 7, not only memory safety. "Every
 * main-loop pass has a bounded worst case that does not depend on what
 * a host chose to send." A console a malformed line can walk off the
 * end of, spin in, or make expensive by typing at it for long enough is
 * the defect this harness exists to find. So it carries five oracles,
 * and every one of them is mutation-tested by
 * tests/test_console_fuzz.py rather than trusted:
 *
 *   the arguments   an independent statement of the documented
 *                   "=<a>[,<b>[,<c>]]" grammar, kept beside the
 *                   parser's own state. Every dispatch is checked
 *                   against it, and so is the claim that a digit, a
 *                   comma and an idle poll emit nothing.
 *   the emitters    con_str and con_strl walk a peer-supplied pointer
 *                   to CON_STR_MAX. The string here is a heap block of
 *                   exactly that size, so the byte after it is ASan's
 *                   redzone: a bound tested after the dereference
 *                   faults instead of returning a value nobody can see.
 *   the arg array   arg[CONSOLE_NARGS] is file-scope in console.c, so
 *                   running off it is a global-buffer-overflow rather
 *                   than a silent write into whatever static follows.
 *   bounded work    bytes, console_write() calls and calls into the
 *                   mocked world are counted PER console_feed() call
 *                   and capped. One keystroke is one main-loop pass,
 *                   and the cost of a pass may not depend on what
 *                   arrived before it. The world call is counted rather
 *                   than only the clock because a spin need not read a
 *                   clock: the rate sweep's wait loops poll a DMA
 *                   counter, and a guard removed from one of those
 *                   hangs without ever asking the time.
 *   the output      every line the console emits begins with '#', and
 *                   nothing handed to console_write() is longer than
 *                   CON_STR_MAX. A host reads console output by line
 *                   and by that prefix.
 *
 * THE FIRST THREE BYTES ARE THE WORLD, not the wire, exactly as they
 * are in tests/ctl/fuzz_ctl.c. Byte 0 is what the track's ports answer
 * - whether there is a generator, whether a start succeeds, whether the
 * acquisition ever completes a buffer - because the refusal arms are
 * half of console_cmds.c. Byte 1 is the generator's own settings, which
 * the shared arithmetic in ctl_wire.h then divides by. Byte 2 seeds how
 * many idle polls fall between keystrokes, which is what the main loop
 * really does. Everything from byte 3 is what somebody typed.
 *
 * WHAT THE HARNESS DELIBERATELY DOES NOT BIND, and why none of them is
 * a gap this could close:
 *
 *   console_trigger_fault() jumps to 0x20000000 to prove the fault
 *   handler. On a host that is a crash with no finding in it.
 *
 *   console_bleed_settle(ms) spins until the clock has advanced by ms.
 *   The wait IS the command - it measures what happens between two
 *   conversions - so its duration is its argument by design, and
 *   invariant 7 exempts debug-only commands. The harness binds it with
 *   a clamped argument so the poll oracle measures the parser rather
 *   than the wait.
 *
 *   console_cmd_rate_sweep() is bound the way both tracks that carry it
 *   bind it, `a[2] ? a[2] : 2u`. It divides by its argument and does
 *   not check it, so binding it raw would report a divide-by-zero no
 *   track can reach - and a control that produces the nuisance instead
 *   of the signal is worse than none.
 *
 * Two entry points, one body: libFuzzer drives LLVMFuzzerTestOneInput,
 * and the standalone main() replays files, runs the built-in corpus or
 * grinds a deterministic pseudo-random stream. The board-free tier runs
 * the second; a campaign runs the first.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "console.h"
#include "console_out.h"
#include "console_port.h"
#include "ctl.h"
#include "ctl_port.h"
#include "ctl_wire.h"
#include "frame.h"

#define WORLD_BYTES 3u

/*
 * The clock the mocked ports hand out. Fixed and coarse on purpose: the
 * rate sweep's two wait loops are bounded by a 2 s guard measured on
 * this clock, so the step decides how many polls that guard costs when
 * a buffer never completes. At 1000 us that is about two thousand polls
 * a loop, comfortably inside CAP_PORT - and an unguarded loop is
 * unbounded whatever the step, which is the difference the oracle
 * exists to see.
 */
#define CLOCK_STEP_US  1000u

/*
 * The per-keystroke caps. The standalone driver prints the high water
 * marks the corpus actually reached, so a cap that has drifted close to
 * the real maximum is visible rather than silently generous.
 */
#define CAP_WRITES  4096u
#define CAP_BYTES  32768u
#define CAP_PORT  1000000u

/* --- the world --------------------------------------------------- */

#define W_NO_GEN         (1u << 0)
#define W_STREAM_FAILS   (1u << 1)
#define W_PLAY_FAILS     (1u << 2)
#define W_CAPTURE_FAILS  (1u << 3)
#define W_ACQ_STALLED    (1u << 4)   /* no buffer ever completes */
#define W_ACQ_REFUSES    (1u << 5)
#define W_ACQ_ZERO_RC    (1u << 6)   /* the configured RC reads back 0 */
#define W_ACQ_NO_SAMPLES (1u << 7)

static uint8_t  w_world;
static uint8_t  w_gen;

static uint32_t now_us;
static uint32_t port_this_feed;
static uint32_t writes_this_feed;
static uint32_t bytes_this_feed;
static uint32_t violations;

/* High water marks, reported by the standalone driver. */
static uint32_t max_writes, max_bytes, max_port;

static void violation(const char *what)
{
	violations++;
	fprintf(stderr, "console fuzz: %s\n", what);
}

/*
 * Every call into the mocked world passes through here. A console that
 * stops making progress does not necessarily stop asking the world
 * something - the rate sweep's wait loops poll a DMA counter - so the
 * liveness check has to sit at the seam rather than at the clock, and
 * it has to end the process rather than return, because a loop that
 * does not terminate gives nothing else a turn.
 */
static void note_port(void)
{
	if (++port_this_feed > CAP_PORT) {
		violation("console_feed() stopped making progress");
		fflush(stderr);
		abort();
	}
}

/* --- the output oracle -------------------------------------------- */

/*
 * Lines are assembled here because a line is not a call: con_ch() emits
 * one byte and a help line is five calls, so the prefix a host parses
 * on can only be checked where the newline arrives.
 */
#define LINE_MAX 4096u

static char     line[LINE_MAX];
static unsigned line_len;
static bool     checking_lines; /* off while the emitters are driven raw */

static size_t bounded_len(const char *s, size_t max)
{
	size_t n = 0;

	while (n < max && s[n])
		n++;
	return n;
}

static void line_end(void)
{
	/* An empty line has no first character to check, and con_nl() on
	 * its own is legal. */
	if (line_len && line[0] != '#')
		violation("a console line that does not begin with '#'");
	line_len = 0;
}

void console_write(const char *s)
{
	size_t n, i;

	writes_this_feed++;
	n = bounded_len(s, (size_t)CON_STR_MAX + 1u);
	if (n > CON_STR_MAX)
		violation("console_write handed a string longer than "
		          "CON_STR_MAX");
	bytes_this_feed += (uint32_t)n;

	for (i = 0; i < n; i++) {
		char c = s[i];

		if (c == '\n') {
			if (checking_lines)
				line_end();
			else
				line_len = 0;
			continue;
		}
		if (checking_lines && c != '\t' &&
		    ((unsigned char)c < 0x20u || (unsigned char)c == 0x7fu))
			violation("a control byte in console output");
		if (line_len < LINE_MAX)
			line[line_len++] = c;
	}
}

void console_flush(void) { }

/* --- the mocked clock --------------------------------------------- */

uint32_t ctl_port_micros(void)
{
	note_port();
	now_us += CLOCK_STEP_US;
	return now_us;
}

uint32_t ctl_port_millis(void) { note_port(); return now_us / 1000u; }

/* --- the mocked console_port.h ------------------------------------ */

static uint32_t acq_buffers;

bool console_port_stream_start(uint32_t trigger_hz)
{
	(void)trigger_hz;
	note_port();
	return !(w_world & W_STREAM_FAILS);
}

bool console_port_play_start(uint32_t dac_hz)
{
	(void)dac_hz;
	note_port();
	return !(w_world & W_PLAY_FAILS);
}

void console_port_play_stop(void) { note_port(); }

uint32_t console_port_play_max_hz(void) { note_port(); return 1392857u; }

bool console_port_capture_only_start(uint32_t adc_hz, unsigned nch)
{
	(void)adc_hz;
	(void)nch;
	note_port();
	return !(w_world & W_CAPTURE_FAILS);
}

uint32_t console_port_mck_hz(void) { note_port(); return 78000000u; }

void console_port_acq_init(void) { note_port(); acq_buffers = 0; }

bool console_port_acq_start(uint32_t trigger_hz, unsigned n_channels)
{
	(void)trigger_hz;
	(void)n_channels;
	note_port();
	return !(w_world & W_ACQ_REFUSES);
}

void console_port_acq_stop(void) { note_port(); }

uint32_t console_port_acq_buffers_done(void)
{
	/* Stalled means the DMA never completes one, which is exactly the
	 * condition the sweep's 2 s guard defends against. */
	note_port();
	if (w_world & W_ACQ_STALLED)
		return 0u;
	return ++acq_buffers;
}

uint32_t console_port_acq_configured_rc(void)
{
	note_port();
	return (w_world & W_ACQ_ZERO_RC) ? 0u : 86u;
}

uint32_t console_port_acq_buf_samples(void)
{
	note_port();
	return (w_world & W_ACQ_NO_SAMPLES) ? 0u : 1016u;
}

uint32_t console_port_acq_min_rc(unsigned n_channels)
{
	note_port();
	return n_channels == 1u ? 44u : 86u;
}

void console_port_acq_overruns(uint32_t *rxbuff, uint32_t *govre)
{
	note_port();
	*rxbuff = acq_buffers;
	*govre  = 0u;
}

/* --- the mocked ctl_port.h ---------------------------------------- */

/*
 * ctl.c is linked because the shared generator arithmetic and
 * ctl_gen_describe() live in it and console_cmds.c calls them. Its own
 * parser is fuzzed next door; what it needs here is the rest of its
 * seam, answered plainly.
 */

size_t ctl_port_read(uint8_t *dst, size_t max)
{
	(void)dst;
	(void)max;
	return 0u;
}

size_t ctl_port_write(const uint8_t *src, size_t len)
{
	(void)src;
	return len;
}

uint32_t ctl_port_out_drain_polls(void) { return 0u; }

uint32_t ctl_port_capabilities(void) { return 0xffffffffu; }

uint32_t ctl_port_mck_hz(void) { return 78000000u; }

void ctl_port_console_flush(void) { }

void ctl_port_heartbeat_timer(uint32_t period_ms) { (void)period_ms; }

void ctl_port_identity(ctl_identity_t *out)
{
	memset(out, 0, sizeof(*out));
	out->track       = 'F';
	out->frame_bytes = 2064u;
	out->mck_hz      = 78000000u;
	memcpy(out->build, "fuzz", 5u);
}

void ctl_port_counters(ctl_counters_t *out)
{
	memset(out, 0, sizeof(*out));
}

bool ctl_port_load_sample(load_report_t *out)
{
	memset(out, 0, sizeof(*out));
	return true;
}

bool ctl_port_stream_stats(ctl_stream_stats_t *out)
{
	memset(out, 0, sizeof(*out));
	return true;
}

bool ctl_port_bench(ctl_bench_t *out)
{
	memset(out, 0, sizeof(*out));
	return true;
}

int ctl_port_occupancy(uint8_t *body, size_t max)
{
	(void)body;
	(void)max;
	return -1;
}

int ctl_port_rate_page(uint8_t *body, size_t max, uint16_t offset)
{
	(void)body;
	(void)max;
	(void)offset;
	return -1;
}

/*
 * The generator the console reports and streams against. Its fields
 * come from the world byte because the shared arithmetic divides by
 * them: gen_hz_for() divides by the point count and gen_shape_name()
 * indexes on the shape.
 */
bool ctl_port_gen_get(ctl_gen_t *out)
{
	note_port();
	if (w_world & W_NO_GEN)
		return false;
	memset(out, 0, sizeof(*out));
	out->shape  = (uint8_t)(w_gen & 0x0fu);
	out->sync   = (uint8_t)((w_gen >> 4) & 0x03u);
	out->points = (uint16_t)(1u << (((w_gen >> 6) & 0x03u) * 3u));
	out->amp    = (uint16_t)((unsigned)w_gen + 1u);
	return true;
}

void ctl_port_gen_set(uint8_t shape, uint16_t points, uint8_t sync,
                      uint16_t amp, uint16_t sync_amp)
{
	(void)shape;
	(void)points;
	(void)sync;
	(void)amp;
	(void)sync_amp;
}

int ctl_port_temp(ctl_temp_t *out, uint16_t samples)
{
	memset(out, 0, sizeof(*out));
	out->samples = samples;
	return CTL_TEMP_OK;
}

int ctl_port_sof(uint32_t *frames, uint64_t *dev_us, uint32_t *ambiguous,
                 uint32_t *restarts)
{
	*frames    = 0u;
	*dev_us    = now_us;
	*ambiguous = 0u;
	*restarts  = 0u;
	return 0;
}

/* --- the argument model ------------------------------------------- */

/*
 * console.h's grammar, stated again here rather than reached for. The
 * point is not a second copy of the code: it is that this says what the
 * documented behaviour IS - "=" opens an entry, digits and commas are
 * argument text while one is open, a letter closes it and consumes the
 * arguments, and a negative value is the main loop's idle poll and
 * changes nothing - so a console.c that stops matching its own
 * documentation fails here even when it is perfectly self-consistent.
 */
static uint32_t m_arg[CONSOLE_NARGS];
static unsigned m_idx;
static bool     m_entry;

/* What the model expects of the keystroke currently being fed. */
static bool     m_quiet;      /* it must emit nothing */
static bool     m_dispatch;   /* it may run a bound handler */
static uint32_t m_expect[CONSOLE_NARGS];

static void model_feed(int c)
{
	unsigned i;

	m_quiet    = true;
	m_dispatch = false;

	if (c < 0)
		return;
	if (c == '=') {
		for (i = 0; i < CONSOLE_NARGS; i++)
			m_arg[i] = 0;
		m_idx = 0;
		m_entry = true;
		return;
	}
	if (m_entry && c >= '0' && c <= '9') {
		if (m_idx < CONSOLE_NARGS)
			m_arg[m_idx] = m_arg[m_idx] * 10u + (uint32_t)(c - '0');
		return;
	}
	if (m_entry && c == ',') {
		if (m_idx < CONSOLE_NARGS)
			m_idx++;
		return;
	}
	m_entry    = false;
	m_quiet    = false;
	m_dispatch = true;
	for (i = 0; i < CONSOLE_NARGS; i++) {
		m_expect[i] = m_arg[i];
		m_arg[i] = 0;
	}
	m_idx = 0;
}

/* Every bound handler goes through this before it does anything else. */
static void note_dispatch(const uint32_t *a)
{
	unsigned i;

	if (!m_dispatch) {
		violation("a command dispatched where the grammar says the "
		          "byte was argument text");
		return;
	}
	for (i = 0; i < CONSOLE_NARGS; i++)
		if (a[i] != m_expect[i]) {
			violation("a handler saw arguments the grammar does "
			          "not predict");
			return;
		}
}

/* --- what this track binds ---------------------------------------- */

static void h_help(const uint32_t *a)    { note_dispatch(a); console_help(); }
static void h_missing(const uint32_t *a) { note_dispatch(a);
                                           console_missing(); }

static void h_ident(const uint32_t *a)
{
	note_dispatch(a);
	console_identity('F', 78000000ul);
}

static void h_gen(const uint32_t *a)  { note_dispatch(a);
                                        console_gen_report(); }

static void h_s50(const uint32_t *a)  { note_dispatch(a);
                                        console_cmd_stream(50000u); }
static void h_s100(const uint32_t *a) { note_dispatch(a);
                                        console_cmd_stream(100000u); }
static void h_s200(const uint32_t *a) { note_dispatch(a);
                                        console_cmd_stream(200000u); }
static void h_s400(const uint32_t *a) { note_dispatch(a);
                                        console_cmd_stream(400000u); }
static void h_smax(const uint32_t *a) { note_dispatch(a);
                                        console_cmd_stream(453488u); }
static void h_stop(const uint32_t *a) { note_dispatch(a); }

static void h_play(const uint32_t *a)
{
	note_dispatch(a);
	console_cmd_play(a[0] ? a[0] : 200000u);
}

static void h_loop(const uint32_t *a)
{
	note_dispatch(a);
	console_cmd_loop(a[0] ? a[0] : 200000u,
	                 a[1] ? a[1] : 200000u,
	                 a[2] ? a[2] : 2u);
}

static void h_ratesweep(const uint32_t *a)
{
	note_dispatch(a);
	/* Bound as both tracks bind it. See the note at the top. */
	console_cmd_rate_sweep(a[2] ? a[2] : 2u);
}

static void h_xtalk(const uint32_t *a)
{
	note_dispatch(a);
	/* Clamped: the wait is the command, not a parser property. */
	console_bleed_settle(a[1] % 4u);
}

/*
 * The table. It carries all four arms console.c can take, because each
 * is a different piece of code:
 *
 *   a bound letter          dispatches
 *   a letter bound to NULL  refused, "not implemented on this track"
 *   a table letter absent   the same refusal, reached the other way
 *   anything else           silence, which is what makes CR, LF and
 *                           spaces free
 */
const console_binding_t console_bindings[] = {
	{ 'h', h_help },      { 'v', h_ident },     { 'w', h_gen },
	{ '1', h_s50 },       { '2', h_s100 },      { '3', h_s200 },
	{ '4', h_s400 },      { '5', h_smax },      { '0', h_stop },
	{ 'P', h_play },      { 'L', h_loop },      { 't', h_ratesweep },
	{ 'x', h_xtalk },     { 'D', h_missing },

	/* Present, unbound: bound() returns NULL and the refusal follows. */
	{ 'O', 0 },           { 'V', 0 },

	{ 0, 0 },
};

/* --- one keystroke ------------------------------------------------ */

static void feed(int c)
{
	port_this_feed   = 0;
	writes_this_feed = 0;
	bytes_this_feed  = 0;

	model_feed(c);
	console_feed(c);

	if (writes_this_feed > max_writes)
		max_writes = writes_this_feed;
	if (bytes_this_feed > max_bytes)
		max_bytes = bytes_this_feed;
	if (port_this_feed > max_port)
		max_port = port_this_feed;

	if (writes_this_feed > CAP_WRITES)
		violation("one keystroke cost more console_write() calls "
		          "than the cap");
	if (bytes_this_feed > CAP_BYTES)
		violation("one keystroke put more bytes on the wire than "
		          "the cap");
	if (m_quiet && bytes_this_feed)
		violation("output from a byte the grammar says is silent");
}

/* --- the emitter arm ---------------------------------------------- */

/*
 * console_out.c's two bounded walks, driven at the bound.
 *
 * The string is a heap block of exactly CON_STR_MAX bytes, so s[0] to
 * s[CON_STR_MAX-1] are the whole allocation and s[CON_STR_MAX] is
 * ASan's redzone. A walk that tests its index after dereferencing it
 * reads that byte and returns a perfectly ordinary answer; here it
 * faults. The terminator's position is the peer's, and "nowhere at all"
 * is one of the positions.
 *
 * The emitters are driven here rather than through console_feed(),
 * and that is a statement about the call sites rather than a
 * shortcut: every string the console prints today is a literal or a
 * table entry, so no peer-supplied pointer reaches one. The bound is
 * console_out.h's contract, not console.c's, and it holds for whoever
 * calls next.
 *
 * The line oracle is off here: these calls emit fragments rather than
 * console lines, and the '#' prefix is a claim about what console.c
 * writes, not about what an emitter can be asked to write.
 */
static void emitters_over(const char *s, unsigned width, uint32_t v)
{
	con_str(s);
	con_strl(s, width);
	con_kvs(s, s);
	con_u32(v);
	con_i32((int32_t)v);
	con_hex32(v, width % 12u);
	con_pad('.', width);
	con_u32w(v, width, ' ');
	con_u32l(v, width);
	con_kv_u32(s, v);
	con_nl();
}

static void emitter_arm(const uint8_t *data, size_t size)
{
	char *s;
	unsigned i, term, width;
	uint32_t v;

	if (!size)
		return;
	s = malloc(CON_STR_MAX);
	if (!s)
		return;
	for (i = 0; i < CON_STR_MAX; i++)
		s[i] = (char)('a' + (data[i % size] % 26u));

	width = data[size / 2u];
	v = ((uint32_t)data[0] << 24) | ((uint32_t)data[size / 3u] << 16) |
	    ((uint32_t)data[size / 2u] << 8) | (uint32_t)data[size - 1u];

	checking_lines = false;

	/*
	 * The boundary case first, and unconditionally: CON_STR_MAX bytes
	 * with no terminator anywhere in them. That is the only input an
	 * off-by-one in the walk can be seen on, so leaving it to the
	 * peer's choice of terminator would make the seed corpus'
	 * detection of one a matter of luck - and a mutation the corpus
	 * catches only sometimes is one the fast tier does not catch.
	 */
	emitters_over(s, width, v);

	/* Then wherever the peer chose to put the NUL, CON_STR_MAX-1
	 * included - the last position where the fast path is legal. */
	term = ((unsigned)data[0] * 251u + (unsigned)data[size - 1u])
	       % CON_STR_MAX;
	s[term] = '\0';
	emitters_over(s, width, v);

	con_str(NULL);
	con_strl(NULL, width);
	con_ch((char)data[0]);
	con_nl();

	checking_lines = true;
	line_len = 0;

	free(s);
}

/* --- one input ---------------------------------------------------- */

int console_fuzz_one(const uint8_t *data, size_t size);

int console_fuzz_one(const uint8_t *data, size_t size)
{
	uint32_t before = violations;
	uint32_t idle;
	size_t i;
	unsigned k;

	if (size < WORLD_BYTES)
		return 0;

	w_world = data[0];
	w_gen   = data[1];
	idle    = (uint32_t)data[2] + 1u;

	/*
	 * A fresh parser for every input, reached the way the firmware
	 * reaches it: any letter the table does not carry closes an open
	 * argument entry and clears the arguments, and '\r' is the
	 * cheapest of those. Nothing here touches console.c's statics, so
	 * a crash file means the same thing whatever ran before it.
	 */
	m_entry = false;
	m_idx = 0;
	for (k = 0; k < CONSOLE_NARGS; k++)
		m_arg[k] = 0;
	checking_lines = true;
	line_len = 0;
	feed('\r');

	for (i = WORLD_BYTES; i < size; i++) {
		/*
		 * The main loop feeds its UART read unconditionally, so the
		 * negative "nothing arrived" is most of what console_feed()
		 * ever sees - and it must not close an open argument entry,
		 * because a user types "=200000" and "L" as two keystrokes
		 * with thousands of empty polls between them.
		 */
		idle = idle * 1103515245u + 12345u;
		for (k = 0; k < (unsigned)((idle >> 16) % 3u); k++)
			feed(-1);
		feed((int)data[i]);
	}

	emitter_arm(data, size);

	if (violations != before) {
		fflush(stderr);
		abort();
	}
	return 0;
}

#ifdef CONSOLE_FUZZ_LIBFUZZER

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
	return console_fuzz_one(data, size);
}

#else

/* --- the built-in corpus ------------------------------------------ */

/*
 * Seeds, not tests. Their job is to put a fuzzer inside the grammar so
 * a campaign spends its budget on the console rather than rediscovering
 * that "=" starts an argument, and to give the board-free tier a
 * deterministic run that reaches every arm. The same bytes are written
 * out for libFuzzer by --write-seeds, so the corpus has one definition.
 */
#define SEED_MAX 512u

struct seed {
	char    name[48];
	uint8_t buf[SEED_MAX];
	size_t  len;
};

static struct seed corpus[96];
static size_t      corpus_n;

static void seed_of(struct seed *s, const char *name, uint8_t world,
                    uint8_t gen, uint8_t idle, const char *keys)
{
	size_t n = strlen(keys);

	snprintf(s->name, sizeof(s->name), "%s", name);
	s->buf[0] = world;
	s->buf[1] = gen;
	s->buf[2] = idle;
	if (n > SEED_MAX - WORLD_BYTES)
		n = SEED_MAX - WORLD_BYTES;
	memcpy(s->buf + WORLD_BYTES, keys, n);
	s->len = WORLD_BYTES + n;
}

static size_t build_corpus(struct seed *out, size_t max)
{
	/* Every letter the shared table carries, in one string: the bound
	 * ones dispatch, the rest take the refusal, and the space is the
	 * silent arm. */
	static const char every[] =
		"hvpgfrsxdjkt12345 0?wuEFRXGTYBLPMVDOWJNICeAQlSKZzq";
	size_t n = 0;

#define SEED(name, world, gen, idle, keys)                              \
	do {                                                            \
		if (n < max)                                            \
			seed_of(&out[n++], (name), (uint8_t)(world),    \
			        (uint8_t)(gen), (uint8_t)(idle),        \
			        (keys));                                \
	} while (0)

	SEED("every-letter",       0x00u, 0x00u, 0u, every);
	SEED("every-letter-nogen", W_NO_GEN, 0x00u, 0u, every);
	SEED("every-letter-fails",
	     W_STREAM_FAILS | W_PLAY_FAILS | W_CAPTURE_FAILS | W_ACQ_REFUSES,
	     0x11u, 0u, every);

	SEED("help",               0x00u, 0x00u, 0u, "h");
	SEED("identity",           0x00u, 0x00u, 0u, "v");
	SEED("missing",            0x00u, 0x00u, 0u, "D");
	SEED("gen-report",         0x00u, 0x22u, 0u, "w");
	SEED("gen-report-none",    W_NO_GEN, 0x00u, 0u, "w");

	SEED("loop-args",          0x00u, 0x00u, 0u, "=200000,200000,2L");
	SEED("loop-refused",       W_PLAY_FAILS, 0u, 0u, "=200000,200000,2L");
	SEED("loop-cap-refused",   W_CAPTURE_FAILS, 0u, 0u,
	                           "=200000,900000,3L");
	SEED("play",               0x00u, 0x00u, 0u, "=1000000P");
	SEED("play-refused",       W_PLAY_FAILS, 0u, 0u, "=1000000P");

	SEED("sweep-2ch",          0x00u, 0x00u, 0u, "=,,2t");
	SEED("sweep-1ch",          0x00u, 0x00u, 0u, "=,,1t");
	SEED("sweep-refused",      W_ACQ_REFUSES, 0u, 0u, "=,,2t");
	SEED("sweep-stalled",      W_ACQ_STALLED, 0u, 0u, "=,,1t");
	SEED("sweep-zero-rc",      W_ACQ_ZERO_RC, 0u, 0u, "=,,2t");
	SEED("sweep-no-samples",   W_ACQ_NO_SAMPLES, 0u, 0u, "=,,2t");

	SEED("digits-overflow",    0x00u, 0x00u, 0u,
	     "=99999999999999999999,99999999999999999999,"
	     "99999999999999999999L");
	SEED("commas",             0x00u, 0x00u, 0u, "=,,,,,,,,,,,,,,,,,,,,L");
	/* Past the last comma the parser accepts, then a digit: the one
	 * shape that reaches arg[CONSOLE_NARGS] if the index guard on the
	 * digit branch is ever dropped. Four commas, not three, because
	 * the comma branch has its own guard and stops the index there. */
	SEED("commas-then-digit",  0x00u, 0x00u, 0u, "=,,,,9L");
	SEED("equals-run",         0x00u, 0x00u, 0u, "========1");
	SEED("bare-digits",        0x00u, 0x00u, 0u, "12345");
	SEED("digits-no-equals",   0x00u, 0x00u, 0u, "200000L");
	SEED("args-then-nothing",  0x00u, 0x00u, 0u, "=1,2,3");
	SEED("args-abandoned",     0x00u, 0x00u, 0u, "=1,2,3\r\n =4,5,6L");
	SEED("idle-heavy",         0x00u, 0x00u, 250u, "=200000L");
	SEED("whitespace",         0x00u, 0x00u, 0u, "\r\n\t  \r\n");
	SEED("unbound-letters",    0x00u, 0x00u, 0u, "OVOVOV");
	SEED("high-bytes",         0x00u, 0x00u, 0u, "\x80\xff\xfe\x01\x7f");

	SEED("gen-points-1",       0x00u, 0x00u, 0u, "1");
	SEED("gen-points-8",       0x00u, 0x40u, 0u, "1");
	SEED("gen-points-64",      0x00u, 0x80u, 0u, "1");
	SEED("gen-points-512",     0x00u, 0xc0u, 0u, "1");
	SEED("gen-shape-high",     0x00u, 0x0fu, 0u, "1");
	SEED("gen-sync-per-wrap",  0x00u, 0x2fu, 0u, "1");
#undef SEED
	return n;
}

static void report(void)
{
	printf("high water: %u writes, %u bytes, %u port calls per "
	       "keystroke (caps %u/%u/%u)\n",
	       (unsigned)max_writes, (unsigned)max_bytes, (unsigned)max_port,
	       (unsigned)CAP_WRITES, (unsigned)CAP_BYTES, (unsigned)CAP_PORT);
}

static int run_builtin(void)
{
	size_t i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	for (i = 0; i < corpus_n; i++)
		console_fuzz_one(corpus[i].buf, corpus[i].len);
	printf("builtin %u seeds, 0 violations\n", (unsigned)corpus_n);
	report();
	return 0;
}

static int write_seeds(const char *dir)
{
	size_t i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	for (i = 0; i < corpus_n; i++) {
		char path[512];
		FILE *f;

		snprintf(path, sizeof(path), "%s/%s.bin", dir, corpus[i].name);
		f = fopen(path, "wb");
		if (!f) {
			fprintf(stderr, "cannot write %s\n", path);
			return 2;
		}
		fwrite(corpus[i].buf, 1u, corpus[i].len, f);
		fclose(f);
	}
	printf("wrote %u seeds to %s\n", (unsigned)corpus_n, dir);
	return 0;
}

/*
 * A deterministic pseudo-random grind. No coverage feedback, so it is a
 * weaker instrument than a campaign and is not offered as a substitute
 * for one - but it is what a bench without clang can run, and it is
 * what makes this cost a second in the board-free tier.
 */
static uint64_t rng_state;

static uint32_t rng_next(void)
{
	rng_state = rng_state * 6364136223846793005ull
	            + 1442695040888963407ull;
	return (uint32_t)(rng_state >> 33);
}

static int run_random(unsigned long runs, unsigned long seed)
{
	static uint8_t buf[SEED_MAX];
	unsigned long i;

	corpus_n = build_corpus(corpus, sizeof(corpus) / sizeof(corpus[0]));
	rng_state = (uint64_t)seed * 6364136223846793005ull + 12345u;
	for (i = 0; i < runs; i++) {
		size_t len, k, edits;

		if ((rng_next() & 1u) && corpus_n) {
			const struct seed *s = &corpus[rng_next() % corpus_n];

			len = s->len;
			memcpy(buf, s->buf, len);
			edits = rng_next() % 8u + 1u;
			for (k = 0; k < edits && len; k++)
				buf[rng_next() % len] = (uint8_t)rng_next();
		} else {
			len = rng_next() % 120u + 1u;
			for (k = 0; k < len; k++)
				buf[k] = (uint8_t)rng_next();
		}
		console_fuzz_one(buf, len);
	}
	printf("random %lu inputs from seed %lu, 0 violations\n", runs, seed);
	report();
	return 0;
}

static int replay(int argc, char **argv)
{
	static uint8_t buf[1u << 20];
	int i;

	for (i = 1; i < argc; i++) {
		FILE *f = fopen(argv[i], "rb");
		size_t n;

		if (!f) {
			fprintf(stderr, "cannot read %s\n", argv[i]);
			return 2;
		}
		n = fread(buf, 1u, sizeof(buf), f);
		fclose(f);
		console_fuzz_one(buf, n);
		printf("replayed %s (%u bytes)\n", argv[i], (unsigned)n);
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc == 2 && !strcmp(argv[1], "--builtin"))
		return run_builtin();
	if (argc == 3 && !strcmp(argv[1], "--write-seeds"))
		return write_seeds(argv[2]);
	if (argc == 4 && !strcmp(argv[1], "--random"))
		return run_random(strtoul(argv[2], NULL, 10),
		                  strtoul(argv[3], NULL, 10));
	if (argc >= 2)
		return replay(argc, argv);
	printf("usage: fuzz_console --builtin | --random RUNS SEED"
	       " | --write-seeds DIR | FILE...\n");
	return 2;
}

#endif /* CONSOLE_FUZZ_LIBFUZZER */
