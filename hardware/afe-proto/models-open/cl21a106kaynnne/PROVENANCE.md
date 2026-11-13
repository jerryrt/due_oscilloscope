# Samsung CL21A106KAYNNN (10 uF, X5R, 25 V, 0805; C15850) data points

dcbias.csv: DC-bias curve (applied voltage, capacitance change in percent); esr.csv: ESR vs frequency (Hz, ohm).
Extracted from Samsung's product page (CL21A106KAYNNN_product_page.html, sha256 4b7cf7d8e24b0af8cb7f0d2118a8077c6b512ade8c0662c6b0ab1a4bb4f27c24,
the page the earlier PW-2 and LM27762 studies were pinned to; the site serves different bytes today, so the page itself is not
reproducible and is NOT committed: Samsung's file). These are numbers read from its embedded chart data (variable
datasheetData: graphType DCBias and |Z|_R), by whatif/lm27762/samsung.py (the parser the studies used).
Derived by that parser: ESR at 2 MHz = 4.04 mohm; ESL (median of (X + 1/(w C)) / w over 3-10 MHz, C = 10 uF) = 0.373 nH;
effective capacitance factor k(V) = 1 + dcbias(|V|)/100 (the studies also applied -10 % tolerance on top: TOL = 0.9).
Not verified against Samsung's datasheet PDF: mark (check) when quoting.
