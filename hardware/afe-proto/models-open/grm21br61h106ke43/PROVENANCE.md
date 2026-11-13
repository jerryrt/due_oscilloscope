# Murata GRM21BR61H106KE43L (10 uF, X5R, 50 V, 0805; LCSC C440198): DC-bias and ESR data NOT obtained

Written 2026-11-12. No dcbias.csv or esr.csv is committed here because no number could be read from a source.
Inventing or scaling a curve is excluded by the project's rule; do not use Samsung's curve as a stand-in.

Routes tried, all 2026-11-12, generic client, no login:
- https://ds.murata.com/simsurfing/mlcc.html (part page, HTTP 200): the page is a shell. Its script
  (lib/murata-simgraph.min.js) fetches data from https://ds.murata.com/simserve/auth, /characteristics,
  /characsvdownload and /graphimage. These sit behind an authentication handshake; I did not call them. Reverse-engineering
  a vendor's token flow is not within the rule against circumventing access controls. STOPPED on this route.
- Murata datasheet PDF (murata.com/en-us/products/productdata/.../GRM21BR61H106KE43.pdf): HTTP 500.
- https://pim.murata.com/en-us/pim/details/?partNum=GRM21BR61H106KE43%23: returned empty content to the fetch tool (JS page).
- Third-party datasheet copies (e.g. static.chipdip.ru DOC031971932.pdf) appeared in search; their DC-bias graph is an image,
  and the fetch tool returns no numbers from it. Not read.
Murata forbids redistribution of its files, so even a successful read would commit only derived numbers.

What a reader with a browser should do: open SimSurfing for GRM21BR61H106KE43, tab "Capacitance change vs DC bias", read
the curve at 2.06, 3.4 and 5 V, and the "Impedance / ESR" tab; record the figures here with (check) and the uncertainty.
Datasheet-level fact only (search snippet, copy not opened): temperature characteristic X5R, +-15 % over -55..85 C (check).
