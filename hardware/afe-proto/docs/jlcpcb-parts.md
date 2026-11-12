# JLCPCB / LCSC parts for the AFE shield: C-numbers, library class, stock

Companion to `jlcpcb.md` (Economic PCBA: $3.07 loading fee per Extended
part type, Basic free, one side, 0603 minimum). Gathered 2026-11-11.

## How to read this, and what was NOT obtained

The fetch tool used here returns a summary of a page, not the live page.
JLCPCB and LCSC part pages came back **without stock or price tiers in
every case**. So:

- **Stock**: only figures quoted in search-result snippets are given, with
  the source, and they are undated snapshots (the snippet's own date is
  unknown) and often contradict each other. Everything else is
  *(check)*: read the live quote tool before freezing the BOM.
- **Unit price at qty 5-10 and 100**: not read for any part, so every
  price cell is *(check)*. Exceptions are single figures quoted in a
  snippet, marked with their quantity.
- **Class** (Basic/Extended) is given only where a fetched JLCPCB page
  showed the label (marked "page") or a search snippet stated it
  (marked "snippet"). Otherwise *(check)*. Treat a part as Extended
  ($3.07 each) until its page says Basic.
- Stock under 500 is flagged **LOW**. No stock figure under 500 was
  actually read, but the OPA354 snippet gave 224 for one source.

## ICs and discretes

| part | package | LCSC # | class | stock seen | price qty 5-10 / 100 | URL |
|---|---|---|---|---|---|---|
| OPA354AIDBVR | SOT-23-5 | C36384 | *(check)* | 2,646 on one LCSC snapshot, **224 LOW** on another; conflict | *(check)* | <https://www.lcsc.com/product-detail/C36384.html> |
| OPA365AIDBVR | SOT-23-5 | C96626 | Extended (page) | ~12,650 JLC / 15,948 LCSC in a search summary, secondhand | qty 1 ~$0.45 (secondhand); 5-10 / 100 *(check)* | <https://jlcpcb.com/partdetail/TexasInstruments-OPA365AIDBVR/C96626> |
| LM27762DSSR | WSON-12 | C473398 | Extended (page) | not read; `jlcpcb.md` records 2,845 to 8,585 across snapshots | *(check)* | <https://jlcpcb.com/partdetail/TexasInstruments-LM27762DSSR/C473398> |
| REF3030AIDBZR | SOT-23 | C38423 | *(check)* | not read | *(check)* | <https://www.lcsc.com/product-detail/C38423.html> |
| MCP3564-E/ST | TSSOP-20 | C1012816 | *(check)* | not read | *(check)* | <https://www.lcsc.com/product-detail/C1012816.html> |
| DAC8551IDGKR | VSSOP-8 (JLC says MSOP-8) | C477934 | Extended (snippet) | 1,612 and 3,092 on two LCSC snapshots | qty 1 ~$2.50 (snippet); 5-10 / 100 *(check)* | <https://jlcpcb.com/partdetail/DAC8551IDGKR/C477934> |
| TMUX1119DBVR | SOT-23-6 | C2877615 | *(check)*; no JLCPCB page found | not read | *(check)* | <https://www.lcsc.com/product-detail/C2877615.html> |
| BAT54S (SMC/Sangdest) | SOT-23 | C171786 | **Extended** (page) | ~5,305 in a search snippet | *(check)* | <https://jlcpcb.com/partdetail/C171786> |
| BAT54S (WPMtek) | SOT-23 | C2688221 | *(check)* | not read | *(check)* | <https://jlcpcb.com/partdetail/2793359-BAT54S/C2688221> |
| BAT54S (JF) | SOT-23 | C501650 | Extended (snippet) | not read | *(check)* | <https://jlcpcb.com/partdetail/JF-BAT54S/C501650> |
| Ferrite bead GZ1608D601TF, 600R@100MHz | 0603 | C1002 | **Basic** (page) | 430,275 (from `jlcpcb.md`, earlier read) | free as Basic | <https://jlcpcb.com/partdetail/C1002> |

No Basic BAT54S/BAT54-class Schottky was found; every listing seen is
Extended or unconfirmed. A BAT54-class diode costs one $3.07 type.

## Resistors 0603, 0.1 % and <= 10 ppm/K thin film

Library class of all thin-film parts below is *(check)*: no page showing
the label was read, but 0.1 % thin film is not in the Basic list seen in
`jlcpcb.md`, so plan on Extended ($3.07 each type). Stock and price are
*(check)* unless a snippet figure is quoted.

| value | result | LCSC # | detail | URL |
|---|---|---|---|---|
| 768k | **NONE FOUND at 10 ppm.** Closest: FH TD03G7683BT, 0.1 %, **25 ppm/K**, Extended (snippet). RESI PTFR0603B768RN9 is 768 ohm, not 768k | C667248 (25 ppm) | not a 10 ppm part | <https://jlcpcb.com/partdetail/696548-TD03G7683BT/C667248> |
| 340k | **NONE FOUND.** TE RN73C1J340KBTD meets the spec but no LCSC listing was seen. LCSC hits were 340 ohm 25 ppm, or through-hole | none | | <https://www.lcsc.com/product-detail/C667473.html> is 340 ohm, wrong value |
| 953R | **No confirmed 10 ppm.** Viking ARG03BTC9530 is 0.1 % 0603 thin film, tempco not shown. TE RQ73C1J953RBTD is 10 ppm but no LCSC number seen | C2686437 (tempco unverified) | | <https://www.lcsc.com/product-detail/C2686437.html> |
| 249R | found: RESI PTFR0603B249RN9, 0.1 %, 10 ppm | C2692731 | stock not read | <https://lcsc.com/product-detail/Chip-Resistor-Surface-Mount_RESI-PTFR0603B249RN9_C2692731.html> |
| 13.7k | found: TT PCF0603-12-13K7BT1 (10 ppm); also TE RQ73C1J13K7BTD | C7256564; C2083616 | stock not read | <https://www.lcsc.com/product-detail/C7256564.html> |
| 15.8k | found: Panasonic ERA-3ARB1582V, 10 ppm per snippet | C1705888 | stock not read | <https://www.lcsc.com/product-detail/C1705888.html> |
| 23.7k | **NONE FOUND at 10 ppm in 0603.** 25 ppm: Viking AR03BTCX2372 C2984335, FH TD03G2372BT C667074. 15 ppm: Vishay TNPW060323K7BXEN C1727968. 10 ppm exists in 0805 only (Yageo RT0805BRB0723K7L C864211) | none | | <https://www.lcsc.com/product-detail/C2984335.html> |
| 191R | **NONE FOUND.** Yageo RT0603CRD07191RL is 0.25 %, 25 ppm, out of stock. RESI PTFR0603B191KN9 is 191k, wrong value | none | | <https://www.lcsc.com/product-detail/C2133086.html> |
| 105R | found: RESI PTFR0603B105RN9, 0.1 %, 10 ppm | C5382618 | stock not read | <https://lcsc.com/product-detail/Chip-Resistor-Surface-Mount_RESI-PTFR0603B105RN9_C5382618.html> |
| 150R | **NONE FOUND at 10 ppm.** RESI PTFR0603B150RP9 is **25 ppm** (P9). TE RQ73C1J150RBTD meets it but no LCSC number seen | C351680 (25 ppm) | | <https://lcsc.com/product-detail/Chip-Resistor-Surface-Mount_RESI-PTFR0603B150RP9_C351680.html> |
| 604R | **NONE FOUND.** Only 604R thick film 1 % (Vishay C2076695, Yageo C859459); TE CPF0603B604KE1 is 604k, 25 ppm | none | | <https://www.lcsc.com/product-detail/C2076695.html> |
| 100k | **NONE FOUND in the searches run**, but this search was weak (a combined query that surfaced 150k and 10k). Neighbours of the same RESI N9 family exist: 10k C394535, 200k C394540, 150k C2692873; Yageo RT0603BRB07150KL (150k, 10 ppm) C860126, 80 in stock at the snippet. Re-search 100k before concluding | none | | <https://www.lcsc.com/product-detail/C394535.html> |

Pattern: RESI PTFR0603B...N9 (0.1 %, 10 ppm) covers 105R, 249R, 768R, 10k,
150k and 200k, so a 0.1 %/10 ppm choice is one of its members or it is
absent. 768k, 340k, 953R (unconfirmed), 23.7k, 191R, 150R, 604R and
(unconfirmed) 100k are the gaps. These gaps reopen the design choice:
either relax to 25 ppm/K (FH TD03G...BT family exists at 768k, 953R-class
values to be checked) or use a different E96 value that does exist at
10 ppm, or accept a larger package.

### 49.9R 0.1 %

| package | result | LCSC # | URL |
|---|---|---|---|
| 2010 | **NONE FOUND** at 0.1 % thin film (only 1 % thick film: Yageo RC2010FK-0749R9L, FH RS-10K49R9FT) | none | <https://www.lcsc.com/product-detail/C326716.html> |
| 1206 | found: Yageo RT1206BRB0749R9L, 0.1 %, 10 ppm, 250 mW; $0.052 at 300+ (snippet, not 5-10 or 100). Also FH TF06E49R9BT on JLCPCB, 10 ppm | C869759; C778446 | <https://www.lcsc.com/product-detail/C869759.html>, <https://jlcpcb.com/partdetail/827090-TF06E49R9BT/C778446> |
| 0603 (for reference) | Vishay TNPW060349K9BEEA is 49.9k not 49.9R; RESI PTFR0402B49R9P9 0402, 25 ppm | | |

## Cheap 1 % 0603 thick film, Basic candidates

| value | part | LCSC # | class | stock | URL |
|---|---|---|---|---|---|
| 680R | UNI-ROYAL 0603WAF6800T5E | C23228 | page showed a "Basic" heading only, not a clear label *(check)*; snippet said Basic | not read | <https://jlcpcb.com/partdetail/C23228> |
| 22R | UNI-ROYAL 0603WAF220JT5E | C23345 | **Basic** label on page; page says 1 % but part code "J" normally means 5 %, *(check)* | not read | <https://jlcpcb.com/partdetail/C23345> |
| 20R | **NONE FOUND in 0603** (only 0805 0805W8F200JT5E C17544) | | | | <https://jlcpcb.com/partdetail/0805W8F200JT5E/C17544> |
| 4.7k | UNI-ROYAL 0603WAF4701T5E | C23162 | Basic (snippet) | 2,538,972 (LCSC snippet) | <https://jlcpcb.com/partdetail/0603WAF4701T5E/C23162> |
| 6.8k | UNI-ROYAL 0603WAF6801T5E | C23212 | *(check)* heading only; snippet said Basic | not read | <https://jlcpcb.com/partdetail/C23212> |
| 10k | UNI-ROYAL 0603WAF1002T5E | C25804 | *(check)* (third-party lists only) | not read | `jlcpcb.md` |
| 1R | UNI-ROYAL 1 ohm 0603, ordering code not confirmed | C22936 (LCSC page title "1R 1%") | *(check)* | not read | <https://lcsc.com/product-detail/Chip-Resistor-Surface-Mount-UniOhm_1R-1R00-1_C22936.html> |
| 1k (reference) | UNI-ROYAL 0603WAF1001T5E | C21190 | *(check)* | not read | <https://jlcpcb.com/partdetail/0603WAF1001T5E/C21190> |

## Resistor array, calibration ladder

| part | package | LCSC # | class | stock | price qty 5-10 / 100 | URL |
|---|---|---|---|---|---|---|
| 330R x 4, 5 %, +/-200 ppm/K, 1/16 W per element, UNI-ROYAL 4D03WGJ0331T5E | 0603x4 (8 pins) | C12018 | page says **Extended** (read 2026-11-11); treated as **Basic on the owner's ruling** | not on the page read *(check)* | *(check)* | <https://jlcpcb.com/partdetail/C12018> |

Two per board, the ladder's only part type (PA-9, D11). It replaced the
4 x 1 kohm C20197, whose 1.31 kohm worst tap failed the pin-leakage check
(`sim/powercal` C2-c). If the quote tool charges it as Extended, it costs
one $3.07 type; confirm the class there before freezing the BOM *(check)*.

## Capacitors

| part | package | LCSC # | class | stock | URL |
|---|---|---|---|---|---|
| 10 pF C0G, Samsung CL10C100GB8NNNC (+/-2 %) | 0603 | C14852 | **Extended** (page) | not read | <https://jlcpcb.com/partdetail/C14852> |
| 10 pF C0G, Samsung CL10C100JB8NNNC (+/-5 %) | 0603 | C-number not found | snippet said Basic *(check)* | not read | search only |
| 10 pF C0G, Yageo CC0603JRNPO9BN100 | 0603 | C106245 | *(check)* | not read | <https://jlcpcb.com/partdetail/CC0603JRNPO9BN100/C106245> |
| 12 pF C0G, Samsung CL10C120JB8NNNC | 0603 | C-number not found | snippet said Basic *(check)* | not read | search only |
| 33 pF C0G, Yageo CC0603JRNPO9BN330 | 0603 | C107047 | **Extended** (page) | not read | <https://jlcpcb.com/partdetail/C107047> |
| 39 pF C0G, Samsung CL10C390JB8NNNC | 0603 | C53278 | *(check)*; LCSC marks it discontinued | not read | <https://jlcpcb.com/partdetail/C53278> |
| 39 pF NP0, Yageo CC0603JRNPO9BN390 | 0603 | C107049 | *(check)* | not read | <https://lcsc.com/product-detail/Multilayer-Ceramic-Capacitors-MLCC-SMD-SMT_YAGEO-CC0603JRNPO9BN390_C107049.html> |
| 47 pF C0G, Samsung CL10C470JB8NNNC | 0603 | C1671 | *(check)* | not read | <https://jlcpcb.com/partdetail/2023-CL10C470JB8NNNC/C1671> |
| 47 pF NP0, Yageo CC0603JRNPO9BN470 | 0603 | C105622 | *(check)* | not read | <https://lcsc.com/product-detail/Multilayer-Ceramic-Capacitors-MLCC-SMD-SMT_YAGEO-CC0603JRNPO9BN470_C105622.html> |
| 100 nF 50 V X7R CC0603KRX7R9BB104 | 0603 | C14663 | **Basic** (`jlcpcb.md`) | not read | <https://jlcpcb.com/partdetail/CC0603KRX7R9BB104/C14663> |
| 1 uF 50 V X7R, FH 0603B105K500NT | 0603 | C90540 | *(check)* | not read | <https://jlcpcb.com/partdetail/0603B105K500NT/C90540> |
| 1 uF 16 V X7R, Samsung CL10B105KO8NNNC | 0603 | C59782 | *(check)* | not read | <https://jlcpcb.com/partdetail/60834-CL10B105KO8NNNC/C59782> |
| 1 uF 50 V X5R, Samsung CL10A105KB8NNNC (not X7R) | 0603 | C15849 | *(check)* | not read | <https://jlcpcb.com/partdetail/CL10A105KB8NNNC/C15849> |
| 10 uF 25 V **X5R**, Samsung CL21A106KAYNNNE | 0805 | C15850 | **Basic** (page) | not read | <https://jlcpcb.com/partdetail/C15850> |

No Basic 10 uF X7R was confirmed. No C0G in 12/10 pF Basic C-number was
captured, so the Basic claim for the Samsung J-grade parts is unproved.
All C0G values other than possibly 10 pF and 12 pF are Extended or
unconfirmed, i.e. each distinct C0G value is a potential $3.07 type.

## Summary for the design

- **No suitable 0.1 %/10 ppm 0603 part found:** 768k, 340k, 953R
  (tempco unverified), 23.7k, 191R, 150R, 604R, 100k (weak search).
  49.9R 0.1 % does not exist in 2010 (found in 1206 only).
- **Found at 0.1 %/10 ppm 0603:** 249R, 105R, 13.7k, 15.8k.
- **Basic confirmed on a page:** ferrite C1002, 22R C23345 (value/tolerance
  caveat), 10 uF X5R 0805 C15850; 100 nF C14663 (earlier read).
  **Basic by snippet only:** 4.7k C23162.
- **Extended confirmed on a page:** OPA365 C96626, LM27762 C473398,
  BAT54S C171786, 10 pF C14852, 33 pF C107047; DAC8551 by snippet.
- **Stock under 500:** none read; OPA354 showed 224 on one snapshot.
  Every price and nearly every stock is *(check)* in the live quote tool.

## Status read 2026-11-11

Read on 2026-11-11 by fetching each part's raw JLCPCB page
(`https://jlcpcb.com/partdetail/<C-number>`) rather than a summary of it.
The page carries the part's record as embedded data, and from it were read
the library class (`componentLibraryType`: `base` = Basic, `expand` =
Extended, agreeing with the badge rendered on the same page in every case),
JLC stock (`overseasStockCount`) and JLC's price tiers, of which the tier
containing qty 20 and the one containing qty 100 are given. Each part was
also looked up in the JLC parts search (the API behind
<https://jlcpcb.com/parts>), which gave the same class and stock, and in
LCSC's product record (`lcsc.com/product-detail/<C-number>.html`), whose
prices agree with JLC's to within a few percent.

- **Preferred / promotional Extended**: the part page does not carry it
  (its flag is unset even on a part the search marks preferred). The JLC
  parts search does, and the field can fire: it reads `true` on
  C1595 (1.5 nF X7R). **None of the parts below is flagged preferred.**
- **Currency**: JLC's price fields carry no currency; they match LCSC's
  USD figures, so they are taken as USD *(check)*.
- Stock and price move daily. These are one day's reading, not a
  commitment; re-read in the quote tool before ordering.
- Stock under 500 is flagged **LOW**, zero **NONE**. Where the part asked
  for is unstocked or low, the stocked alternative found by the JLC parts
  search is listed under it (marked "alt"), with its own read.

| part | C-number | class | stock (JLC) | price qty 20 / 100 | source URL |
|---|---|---|---|---|---|
| 330R x 4 array, 5 %, 4D03WGJ0331T5E | C12018 | **Extended** | 54,271 | 0.0213 / 0.0213 | <https://jlcpcb.com/partdetail/C12018> |
| 1k x 4 array, 5 %, 4D03WGJ0102T5E | C20197 | **Basic** | 510,747 | 0.0095 / 0.0095 | <https://jlcpcb.com/partdetail/C20197> |
| 680R 1 % 0603, 0603WAF6800T5E | C23228 | **Basic** | 1,498,786 | 0.0021 / 0.0021 | <https://jlcpcb.com/partdetail/C23228> |
| 22R 1 % 0603, 0603WAF220JT5E (page describes it as +/-1 %) | C23345 | **Basic** | 5,594,588 | 0.0017 / 0.0017 | <https://jlcpcb.com/partdetail/C23345> |
| 4.7k 1 % 0603, 0603WAF4701T5E | C23162 | **Basic** | 14,882,631 | 0.0028 / 0.0028 | <https://jlcpcb.com/partdetail/C23162> |
| 10k 1 % 0603, 0603WAF1002T5E | C25804 | **Basic** | 43,718,169 | 0.0022 / 0.0022 | <https://jlcpcb.com/partdetail/C25804> |
| 1R 1 % 0603, 0603WAF100KT5E (+/-400 ppm/K) | C22936 | **Basic** | 497,564 | 0.0031 / 0.0031 | <https://jlcpcb.com/partdetail/C22936> |
| 1k 1 % 0603, 0603WAF1001T5E | C21190 | **Basic** | 26,003,002 | 0.0017 / 0.0017 | <https://jlcpcb.com/partdetail/C21190> |
| 768k 0.1 % 25 ppm 0603, FH TD03G7683BT | C667248 | Extended | **0 NONE** | 0.0481 / 0.0481 | <https://jlcpcb.com/partdetail/C667248> |
| alt: 768k 0.1 % **50 ppm** 0603, TC0350B7683T5F (no stocked 0603 at <= 25 ppm found) | C50670506 | Extended | **53 LOW** | 0.0185 / 0.0185 | <https://jlcpcb.com/partdetail/C50670506> |
| 330k 0.1 % 25 ppm 0603, RESI PTFR0603B330KP9 | C351655 | Extended | 21,847 | 0.1164 / 0.0924 | <https://jlcpcb.com/partdetail/C351655> |
| 330k 0.1 % 10 ppm 0603, Yageo RT0603BRB07330KL | C860332 | Extended | **76 LOW** | 0.1732 / 0.1480 | <https://jlcpcb.com/partdetail/C860332> |
| 953R 0.1 % 0603, Viking ARG03BTC9530 (page: 25 ppm) | C2686437 | Extended | **91 LOW** | 0.0255 / 0.0255 | <https://jlcpcb.com/partdetail/C2686437> |
| alt: 953R 0.1 % 25 ppm 0603, Viking AR03BTCX9530 | C2984375 | Extended | 4,141 | 0.0290 / 0.0290 | <https://jlcpcb.com/partdetail/C2984375> |
| 249R 0.1 % 10 ppm 0603, RESI PTFR0603B249RN9 | C2692731 | Extended | 3,875 | 0.1727 / 0.1370 | <https://jlcpcb.com/partdetail/C2692731> |
| 13.7k 0.1 % 10 ppm 0603, TT PCF0603-12-13K7BT1 | C7256564 | Extended | **0 NONE** | 0.4615 / 0.4615 | <https://jlcpcb.com/partdetail/C7256564> |
| alt: 13.7k 0.1 % 25 ppm 0603, Yageo RT0603BRD0713K7L | C861119 | Extended | 2,026 | 0.0457 / 0.0457 | <https://jlcpcb.com/partdetail/C861119> |
| alt: 13.7k 0.1 % 25 ppm 0603, Vishay TNPW060313K7BEEA | C2075559 | Extended | 4,668 | 0.0939 / 0.0734 | <https://jlcpcb.com/partdetail/C2075559> |
| 15.8k 0.1 % 10 ppm 0603, Panasonic ERA-3ARB1582V | C1705888 | Extended | **0 NONE** | 0.3956 / 0.3842 | <https://jlcpcb.com/partdetail/C1705888> |
| alt: 15.8k 0.1 % 25 ppm 0603, Yageo RT0603BRD0715K8L | C861143 | Extended | 6,049 | 0.0546 / 0.0546 | <https://jlcpcb.com/partdetail/C861143> |
| 49.9R 0.1 % 10 ppm 1206, Yageo RT1206BRB0749R9L | C869759 | Extended | 1,552 | 0.1238 / 0.1079 | <https://jlcpcb.com/partdetail/C869759> |
| 100k 0.1 % 10 ppm 0603, RESI PTFR0603B100KN9 | C394537 | Extended | 85,131 | 0.1734 / 0.1377 | <https://jlcpcb.com/partdetail/C394537> |
| 174k 0.1 % 25 ppm 0603, Yageo RT0603BRD07174KL (every 10 ppm listing seen had 0 stock) | C861163 | Extended | 8,074 | 0.0421 / 0.0421 | <https://jlcpcb.com/partdetail/C861163> |
| 12 pF C0G 5 % 50 V 0603, Samsung CL10C120JB8NNNC | C38523 | **Basic** | 570,516 | 0.0068 / 0.0068 | <https://jlcpcb.com/partdetail/C38523> |
| 20 pF C0G 5 % 50 V 0603, Samsung CL10C200JB8NNNC | C1648 | **Basic** | 1,904,977 | 0.0088 / 0.0088 | <https://jlcpcb.com/partdetail/C1648> |
| 39 pF C0G 5 % 50 V 0603, FH 0603CG390J500NT (no Basic 39 pF in a Basic-only search) | C1666 | Extended | 54,858 | 0.0048 / 0.0048 | <https://jlcpcb.com/partdetail/C1666> |
| 39 pF NP0 5 % 50 V 0603, Yageo CC0603JRNPO9BN390 | C107049 | Extended | 445,356 | 0.0037 / 0.0037 | <https://jlcpcb.com/partdetail/C107049> |
| 1.6 nF C0G 5 % 50 V 0603, Murata GRM1885C1H162JA01D (no Basic 1.6 nF or 1.5 nF found) | C437532 | Extended | 4,387 | 0.0466 / 0.0466 | <https://jlcpcb.com/partdetail/C437532> |
| 4.7 nF **X7R** 10 % 50 V 0603, FH 0603B472K500NT (the Basic 4.7 nF; a C0G one was not searched) | C53987 | **Basic** | 818,069 | 0.0052 / 0.0052 | <https://jlcpcb.com/partdetail/C53987> |
| 100 nF X7R 50 V 0603, Yageo CC0603KRX7R9BB104 | C14663 | **Basic** | 37,556,828 | 0.0062 / 0.0062 | <https://jlcpcb.com/partdetail/C14663> |
| 1 uF **X5R** 50 V 0603, Samsung CL10A105KB8NNNC (the only Basic 1 uF 0603 found) | C15849 | **Basic** | 12,398,112 | 0.0112 / 0.0112 | <https://jlcpcb.com/partdetail/C15849> |
| 10 uF X5R 25 V 0805, Samsung CL21A106KAYNNNE | C15850 | **Basic** | 8,838,502 | 0.0314 / 0.0314 | <https://jlcpcb.com/partdetail/C15850> |
| OPA354AIDBVR, SOT-23-5 | C36384 | Extended | 1,927 | 1.9076 / 1.3519 | <https://jlcpcb.com/partdetail/C36384> |
| OPA365AIDBVR, SOT-23-5 | C96626 | Extended | 17,111 | 2.5402 / 2.1528 | <https://jlcpcb.com/partdetail/C96626> |
| LM27762DSSR, WSON-12 | C473398 | Extended | 40,829 | 0.7912 / 0.5934 | <https://jlcpcb.com/partdetail/C473398> |
| REF3030AIDBZR, SOT-23 | C38423 | Extended | 82,595 | 0.3809 / 0.2698 | <https://jlcpcb.com/partdetail/C38423> |
| MCP3564-E/ST, TSSOP-20 | C1012816 | Extended | **42 LOW** | 8.5359 / 6.8490 | <https://jlcpcb.com/partdetail/C1012816> |
| MCP3564R-E/ST, TSSOP-20 | C1020032 | Extended | **0 NONE** | 5.0706 / 4.8581 | <https://jlcpcb.com/partdetail/C1020032> |
| MCP3564RT-E/ST, TSSOP-20 (tape and reel) | C5227404 | Extended | **14 LOW** | 7.0354 / 5.7179 | <https://jlcpcb.com/partdetail/C5227404> |
| TMUX1119DBVR, SOT-23-6 | C2877615 | Extended | **12 LOW** | 2.2035 / 1.8455 | <https://jlcpcb.com/partdetail/C2877615> |
| alt: TMUX1119DCKR, SC-70-6 (different footprint) | C2673327 | Extended | 7,222 | 2.1185 / 1.6739 | <https://jlcpcb.com/partdetail/C2673327> |
| BAT54S, SOT-23, KL4 (no BAT54S in a Basic-only search) | C8592 | Extended | 217,926 | 0.0239 / 0.0239 | <https://jlcpcb.com/partdetail/C8592> |
| BAT54S,215, SOT-23, Nexperia | C47546 | Extended | 267,005 | 0.0223 / 0.0223 | <https://jlcpcb.com/partdetail/C47546> |
| Ferrite bead 600R@100 MHz 0603, GZ1608D601TF | C1002 | **Basic** | 414,125 | 0.0115 / 0.0115 | <https://jlcpcb.com/partdetail/C1002> |

Two readings change what the sections above say. **C12018, the ladder's
330R array, reads Extended** on its own page, in the search and in the
rendered badge, so on this reading it costs one $3.07 loading fee; the
1 kohm array C20197 it replaced reads Basic. And the Basic-only search
returns no Schottky in SOT-23 at all (its Schottky entries are SS14-class
rectifiers in SMA, SOD-123 and SOD-323), so the BAT54S is an Extended type.

## Basic and preferred alternatives, read 2026-11-11

Asked: does any of the 15 Extended types (OPA365, OPA354, LM27762,
REF3030, MCP3564, TMUX1119, BAT54S, the six 0.1 % resistors, 39 pF and
1.6 nF C0G) have a Basic or a Preferred Extended replacement?

### What "Preferred Extended" means for the fee

JLCPCB's own pages, read raw on 2026-11-11:

- PCB Assembly FAQs, item 7,
  <https://jlcpcb.com/help/article/pcb-assembly-faqs>:
  "'Preferred Extended Parts' refers to some of the components that are
  manually loaded onto the P&P (Pick and Place) machines for assembly.
  These parts were previously classified as Basic parts, but they have
  now been categorized as Extended (Preferred) parts. The advantage of
  Preferred Extended Parts is that they are exempt from the Feeders
  Loading fee for Economic PCB assembly." (The same page's item 6 still
  says "$3 per extended component"; the price page below says $3.07.)
- Basic parts listing, <https://jlcpcb.com/parts/basic_parts>: the
  category is titled "Basic & Promotional Extended Components (1586)",
  and "All parts in this category (Basic & Promotional Extended) qualify
  for $0 Feeder Loading Fees in Economic PCBA". Each preferred row there
  carries "Promotional Extended Parts, they will not be charged Feeders
  Loading fee for Economic PCB assembly." So "preferred" and
  "promotional extended" are one class under two names.
- PCBA price page, <https://jlcpcb.com/help/article/pcb-assembly-price>
  (record updated 2026-10): "Feeder Loading | $3.07 Extend | $1.53
  Basic/Extend" for Economic / Standard, and "Feeder Loading Fee: For
  Standard PCBA orders, all basic and extended components require feeder
  loading on pick-and-place machines. An additional labor fee applies."
  JLC's blog <https://jlcpcb.com/blog/reduce-pcb-assembly-cost-prototype>
  says the same in one line: Economic is "$3.07 per unique Extended part
  (Basic and Preferred Extended parts are free)", Standard "$1.53 per
  unique part, Basic or Extended".

So a preferred part costs nothing to load on **Economic** and $1.53 on
**Standard**, the same as a Basic part.

**Pre-ordering into "My Parts" does not remove the fee.** The pre-order
pages (<https://jlcpcb.com/help/article/what-is-jlcpcb-parts-pre-order-service>,
<https://jlcpcb.com/help/article/How-to-build-your-own-parts-library-in-JLCPCB>)
say the private library has "no inventory cost when using for assembly
orders", an "Inventory loss equals 0.03% of minimum package each year",
in-stock Extended parts can be pre-ordered with no minimum quantity,
non-stock ones need a minimum, the parts can only be used for JLC
assembly, and pickup carries inventory and pickup fees. Neither page, nor
the FAQ or the price page, exempts a pre-ordered or consigned part from
the loading fee: the fee is for mounting a feeder, and the price page
ties it to the part class, not to who owns the reel. What pre-ordering
buys is stock security (MCP3564, TMUX1119DBVR), not a fee waiver. Not
asked of JLC support *(check)* if it matters.

A separate fee the same price page lists: "X-ray inspection is required
for components such as BGA, QFN, and other leadless packages",
1-10 pcs $1.64/pc. The LM27762 is WSON-12, leadless.

### How the classes were read

The JLC parts search API (the one behind <https://jlcpcb.com/parts>,
`POST .../shoppingCart/smtGood/selectSmtComponentList`) takes
`componentLibraryType: "base"` and `preferredComponentFlag: true` as
filters, and each record carries `componentLibraryType`,
`preferredComponentFlag`, stock, price tiers and the LCSC parameter
table. With an empty keyword:

- `componentLibraryType: "base"` returns **351** parts, all `base`, none
  flagged preferred;
- `preferredComponentFlag: true` returns **1,235** parts, all `expand`,
  all flagged preferred.

351 + 1,235 = **1,586**, the count JLC's Basic & Promotional page shows,
so the two lists together are the whole fee-free set. Both were dumped in
full and searched by category and value, and every C-number below was
cross-checked: the known Basic parts in this design (C23162, C38523,
C15849, C20197, ...) are all in the Basic dump, and the raw part page of
each Basic candidate below reads `componentLibraryType: base`. Named
searches without a filter (below) were run as a second route. Prices are
the JLC tier containing qty 20, currency as in the status section.

Every named alternative suggested for this check is **Extended and not
preferred**: TLV9061/9062, TLV9001/9002, TLV9051/9052, OPA365/OPA2365
variants, OPA322/OPA2322, OPA355/356/357, SGM8261/8262, SGM8291/8292,
LMV721/LMV7219, GS8091/8092, LMH6611, LMH6639, ADA4891, AD8051, AD8091,
TLV3541, TLV6741, OPA837, OPA863; LM4040 (incl. AIM3-3.0, BIM3-3.0),
LM4041, TL431 (TI and others), REF3030/3130/3330, REF2030, ADR3430;
SGM3157, 74LVC1G3157, BL1551, TS5A3157, RS2105, RS2103, TMUX1219,
TMUX1101, SGM3005; TPS60400/401/403, LM2776, LM27761, LM2662, SGM3204,
LM828, TPS7A39; MCP3561/3562, ADS1115/1220/1256. Only CJ431 (Basic),
ICL7660A (preferred) and BAT54C (preferred) of the names searched are in
the fee-free set.

### What the fee-free set contains, by role

The Basic and preferred **op-amps** are, in full: NE5532DR C7426, LM358DR2G
C7950, LM324DT C71035, TL072CDT C6961, OP07CDR C7433 (Basic); MCP6002T-I/SN
C7377, LMV321IDBVR C7972, LM2904DR2G C18229 (preferred). The highest GBW
is 10 MHz. There is **no ADC**, no **voltage reference other than CJ431**,
no **SPDT analog switch**, one **charge pump** (ICL7660A) and no negative
or low-noise LDO. There is **no resistor tighter than 1 %** (182 Basic and
111 preferred chip resistors, every one +/-1 %). C0G stops at 330 pF in
0603 and 2.2 nF in 0805.

### Per Extended type

| our part | best fee-free candidate | C-number | class | pref | stock | $ qty 20 | specs (JLC/LCSC parameter record) | what it misses |
|---|---|---|---|---|---|---|---|---|
| OPA365 (AWG, ref, Vmid buffers) | MCP6002T-I/SN, dual | C7377 | Extended | **yes** | 73,658 | 0.3085 | 1 MHz GBW, RRIO, 1.8-6 V, 28 nV/rtHz @1 kHz, Vos 4.5 mV | GBW 50x short of the OPA365's 50 MHz, which rules out the AWG stage and makes the Vmid buffers' 50 mohm target unlikely *(check)*; 6x the noise density; 4.5 mV offset; SOIC-8. The reference buffer is the only role where it might serve, and only after a re-simulation |
| | LMV321IDBVR | C7972 | Extended | **yes** | 82,648 | 0.113 | 1 MHz, rail-to-rail **output only**, 2.7-5.5 V, 46 nV/rtHz, Vos 7 mV | as above, and input not rail-to-rail |
| | NE5532DR, dual | C7426 | **Basic** | no | 266,923 | 0.1068 | 10 MHz, 5 nV/rtHz, Vos 0.5 mV, +/-15 V class, not rail-to-rail | not specified for a 3.3 V / 5.4 V supply; not rail-to-rail; 16 mA |
| | LM2904 C18229 (pref), LM358 C7950, LM324 C71035, TL072 C6961 (6 V min), OP07 C7433 (400 kHz) | | | | | | | GBW <= 4 MHz, none rail-to-rail |
| OPA354 (scope, 250 MHz) | **none** | | | | | | | best is NE5532 at 10 MHz, which cannot run on these rails. Every 100 MHz+ part found (GS8091 C157724, 195 MHz, $0.389) is Extended |
| LM27762 (+3.3 V LDO and ~-2.07 V) | ICL7660AIBAZA-T | C7881 | Extended | **yes** | 18,075 | 0.8026 | inverting charge pump, 1.5-12 V, output resistance 97 ohm, switching 8 kHz | unregulated (gives about -VIN, no -2.07 V regulation), 97 ohm against LM27762's 2.5 ohm, switching inside the signal band; no Basic or preferred negative LDO to follow it; SOIC-8 |
| | XC6206P332MR-G (positive half only) | C5446 | **Basic** | no | 481,224 | 0.1261 | 3.3 V fixed, 200 mA, 6 V max in | fixed 3.3 V, not the 174k/100k-set 3.288 V; no noise or PSRR in the record; covers only the positive rail |
| REF3030 (3.0 V, 0.2 %) | CJ431 | C3113 | **Basic** | no | 575,876 | 0.0365 | adjustable shunt 2.5-36 V, +/-0.5 %, 50 ppm/K, I_K min 1 mA | 0.5 % against 0.2 %; needs a divider (0.1 % types already in the BOM) to make 3.0 V and a bias resistor; a shunt, so the OPA365 buffer stays; -25 to +85 C; noise not stated. Zeners (254 preferred) are not references |
| MCP3564 (24-bit, 8 SE, SPI) | **none** | | | | | | | no ADC of any kind is Basic or preferred |
| TMUX1119 (SPDT, ~6 pF off) | CD4052BM96 | C6521 | Extended | **yes** | 43,813 | 0.2729 | dual 4:1, Ron 125 ohm, Con 18 pF, 3-20 V | Ron 125 ohm (supply condition not in the record *(check)*) in the range-switch gain path; 18 pF against ~6 pF; 3.3 V is near its 3 V minimum; SOIC-16 |
| | CD4051BM96 | C21379 | Extended | **yes** | 14,727 | 0.2673 | 8:1, Ron 125 ohm, Con 30 pF | as above, 30 pF |
| BAT54S (dual series Schottky) | **BAT54S, hongjiacheng** | C7420333 | Extended | **yes** | 514,643 | 0.0129 | SOT-23, series pair, 30 V, 200 mA, Vf 400 mV @10 mA, Ir 2 uA @30 V | **drop-in**; same pinout class as C8592/C47546 *(check the pinout on its datasheet)* |
| | 1N5819WS (one per rail) | C191023 | **Basic** | no | 4,055,743 | 0.0124 | SOD-323 single, 40 V, 1 A, Vf 600 mV @1 A, Ir 500 uA @40 V | different footprint; Vf at the ~20 mA rail current not in the record, so AW-1 headroom and P1-a must be re-read; leakage far higher (irrelevant on a rail) |
| 330k, 100k, 174k, 953R, 249R 0.1 % 0603; 49.9R 0.1 % 1206 | **none** | | | | | | | every Basic and preferred resistor is +/-1 % thick film |
| 39 pF C0G 0603 | 20 pF + 20 pF, both C1648 (already in the BOM) | C1648 | **Basic** | no | 1,904,229 | 0.0088 | C0G 5 % 50 V | 40 pF, +2.6 %; two placements per channel; the sim's 39 pF/12 pF flattest case must be re-run (36 pF gave +5.6 %). No new type at all |
| | 12 pF C38523 (Basic, in BOM) + 27 pF CC0603JRNPO9BN270 | C107045 | Extended | **yes** | 414,404 | 0.0033 | NP0 5 % 50 V | exactly 39 pF; two placements; the 27 pF is a new, fee-free type |
| | 33 pF CL10C330JB8NNNC + 6 pF 0603CG6R0C500NT | C1663 + C37474 | Basic + Extended pref | no / **yes** | 1,282,333 / 243,839 | 0.0091 / 0.0053 | C0G | 39 pF; two new fee-free types |
| 1.6 nF C0G 0603 | 5 x 330 pF CL10C331JB8NNNC | C1664 | **Basic** | no | 627,079 | 0.018 | C0G 5 % 50 V 0603 | 1.65 nF, +3.1 %; five placements per buffer, ten in all |
| | 2.2 nF CL21C222JBFNNNE | C28260 | **Basic** | no | 372,281 | 0.0368 | C0G 5 % 50 V **0805** | +37.5 % (HF feedback corner moves down); 0805 |
| | 1.5 nF 0603B152K500NT | C1595 | Extended | **yes** | 227,436 | 0.0045 | **X7R** 10 % 50 V 0603 | -6 %, X7R not C0G (tempco and voltage coefficient); would need the Vmid sim re-run |

### Beyond the 15: BAV99

The BOM counts **BAV99** (AWG output clamp, three packages) as a 16th
Extended type on the strength of `jlcpcb.md`. **BAV99,215 Nexperia C2500
is Basic** (search record and raw page both `base`; 1,958,628 in stock,
$0.0111 at qty 20; 100 V, 125 mA, series pair, SOT-23), and a preferred
one exists too, C7420336 (hongjiacheng, 70 V, 200 mA, 1,510,129, $0.0114).
Either removes the BAV99 fee.

### What it changes

Fee-free substitutions that need no redesign: **BAT54S -> C7420333** and
**BAV99 -> C2500**, two types. With a re-simulation and extra placements:
**39 pF** (20 pF + 20 pF, no new type) and **1.6 nF** (5 x 330 pF C0G),
two more. That is up to 4 of the Appr stage's 16 Extended types,
$12.28 per Economic order. The ICs (OPA365, OPA354, LM27762, REF3030
unless a 0.5 % CJ431 is accepted, MCP3564, TMUX1119) and all six 0.1 %
resistors have no fee-free part that meets their role.

## X-ray and leaded negative-rail options, read 2026-11-11

Asked: what JLCPCB charges for X-ray inspection and what triggers it;
which BOM parts trigger it; and whether the LM27762 (the only candidate)
can be replaced by leaded parts at a saving. JLCPCB pages were read raw
with curl, part records through the JLC parts search API and the raw
`partdetail` pages, as in the two sections above. Datasheets were read
from TI's site (`https://www.ti.com/lit/ds/symlink/<part>.pdf`); the
ADP7182 and XC6206 datasheets did not download, so their figures are the
JLC parameter record only. **No simulation was run for this section.**

### The X-ray fee

PCBA price page, <https://jlcpcb.com/help/article/pcb-assembly-price>
("Last updated on Oct 22, 2026"), fee table, row "X-ray Inspection
(Component Quantity)". The row carries identical tiers in the
**Economic PCBA** and the **Standard PCBA** column:

| pieces | price per piece |
|---|---|
| 1-10 | $1.64 |
| 11-50 | $0.82 |
| 51-200 | $0.49 |
| 201-500 | $0.33 |
| 501-1,000 | $0.25 |
| 1,001-3,000 | $0.16 |
| 3,001-99,999 | $0.082 |

What triggers it, same page: "X-ray Inspection Fee: To ensure solder
joint quality, X-ray inspection is required for components such as BGA,
QFN, and other leadless packages whose solder joints are not visible
after SMT assembly."

- **Charged per component piece**, not per board or per part type: the
  row is headed "(Component Quantity)" and priced "/pc". So an order
  pays for (leadless parts per board) x (boards). The page does not say
  whether the whole quantity is priced at the tier it falls in or each
  tier is filled in turn; both readings are computed below *(check in
  the quote tool)*.
- **Applies to Economic and Standard alike** (same tiers in both
  columns).
- **Package types named by JLCPCB:** BGA, QFN, "other leadless
  packages" (price page); "bottom-terminated components such as BGA,
  QFN, and LGA" (SMT inspection page,
  <https://jlcpcb.com/help/article/smt-inspection-and-testing-capabilities>,
  section "4. X-Ray Inspection", updated Sep 09, 2026); "bottom-terminated
  packages (such as BGA, LGA, and QFN)" (X-ray report guide,
  <https://jlcpcb.com/help/article/x-ray-inspection-report-interpretation-guide>).
  DFN, WSON and SON are not named on any of these pages; they are
  leadless and bottom-terminated, so they fall under "other leadless
  packages". The guide also says how it is applied: "Our system normally
  identifies such package types and recommends X-Ray inspection.
  However, the system cannot guarantee 100% accurate identification".
  Whether an exposed-pad package with visible leads (HVSSOP, MSOP-EP)
  is flagged is not stated *(check)*; the options below avoid them.

### Which BOM parts are leadless

Package as JLC's record gives it (search API, `componentSpecificationEn`),
read 2026-11-11:

| part | C-number | JLC package | leadless? |
|---|---|---|---|
| LM27762DSSR | C473398 | WSON-12-EP(2x3) | **yes: the only one** |
| OPA354AIDBVR | C36384 | SOT-23-5 | no |
| OPA365AIDBVR | C96626 | SOT-23-5 | no |
| REF3030AIDBZR | C38423 | SOT-23 (3-pin) | no |
| MCP3564-E/ST | C1012816 | TSSOP-20 | no |
| TMUX1119DCKR | C2673327 | SC-70-6 (gull-wing) | no |
| BAT54S | C8592 / C47546 / C7420333 | SOT-23 | no |
| BAV99 | C2500 / C7420336 | SOT-23 | no |
| chip R and C, 0603/0805/1206 | | end terminations, visible | no |

So X-ray is one piece per board: 20 pieces on a 20-board order
($0.82 x 20 = **$16.40**, or $24.60 if the tiers fill in turn) and 100
on a 100-board order ($0.49 x 100 = **$49.00**, or $73.70). The
LM27762's own leaded-family siblings do not help: LM27761 is
WFDFN-8-EP, and every LM27762 listing is WSON-12.

### Leaded replacements for the LM27762

The LM27762 is a 2 MHz inverting charge pump followed by a negative
LDO, plus a positive LDO from VIN (datasheet SNVSAF7C: VFB- -1.238 to
-1.202 V, VFB+ 1.182 to 1.218 V, 22 uVrms per output 10 Hz-100 kHz,
PSRR 50 dB OUT- / 43 dB OUT+ at 10 kHz, PFM below light load). A leaded
replacement is the same three blocks as three parts.

**No leaded regulated inverter reaches -2.07 V from stock.** LTC1983-3
(TSOT-23-6, C580473, fixed -3 V, 92 in stock, $8.07) is too negative for
the 5.5 V budget; MAX889 (SOIC-8, C132638, 400 in stock, $3.03) regulates
only to -2.5 V per its record; MAX1673 (SOIC-8) and LM2687 (MSOP-8, 10 mA)
have 0-9 in stock. So the negative rail is an unregulated inverter plus a
negative LDO.

Parts read (JLC class, stock and price at the qty-20 / qty-100 tiers;
USD as in the status section). Every one is **Extended, not preferred**,
except XC6206P332MR-G and AMS1117-3.3 (Basic) and ICL7660A (preferred):

| role | part | C-number | package | stock | $ q20 / q100 | key specs (datasheet unless noted) |
|---|---|---|---|---|---|---|
| inverter | **LM2776DBVR** | C69527 | SOT-23-6 | 22,645 | 0.5689 / 0.4316 | VIN 2.7-5.5 V (abs 6 V), 200 mA, ROUT 2.5 ohm typ, **2 MHz** (1.7-2.3), **PFM below 40 mA, can drop under 1 kHz unloaded**; the same inverter core and the same frequency as the LM27762 |
| inverter | **TPS60403DBVR** | C11338 | SOT-23-5 | 24,143 | 0.5983 / 0.4463 | VIN 1.8-**5.25 V** recommended (abs 5.5 V), 60 mA (abs 80 mA), 12-15 ohm, **250 kHz fixed (150-300)**, 15 mVpp at 5 mA with 1 uF |
| inverter | **LM2664M6X/NOPB** | C108573 | SOT-23-6 | 161,106 | 0.3335 / 0.2578 | VIN 1.8-5.5 V, 40 mA, ROUT 12 typ / 25 max ohm, switching **40-80 kHz** (half the oscillator) |
| inverter | TPS60401DBVR | C29006 | SOT-23-5 | 4,072 | 1.0854 / 0.8304 | 20 kHz, in band; not pursued |
| inverter | LM828M5X/NOPB | C484729 | SOT-23-5 | 2,892 | 0.9596 / 0.7422 | 25 mA, 12 kHz: under PW-3's 30 mA short |
| inverter | ICL7660AIBAZA-T | C7881 | SOIC-8 | 18,075 | 0.8026 / 0.5999 | **preferred** (fee-free), but 97 ohm and 8 kHz: at 35 mA from 4.33 V it gives about -0.9 V, below what a -2.07 V LDO needs. Excluded |
| neg. LDO | **TPS72301DBVR** | C34678 | SOT-23-5 | 31,910 | 0.8778 / 0.6849 | VIN -2.7 to -10 V, 200 mA, VFB -1.186 V; **two dies sold under one number**: legacy VFB -1.210/-1.162, adjustable accuracy **+/-3 %**, IFB 1 uA max, start-up 1 ms; new die +/-1.6 %, IFB 0.1 uA, start-up 8 ms. 60 uVrms (fixed -2.5 V, 10 nF NR; not given for the adjustable), PSRR 65 dB 1 kHz / 48 dB 10 kHz / 40 dB 100 kHz, none given at 2 MHz |
| neg. LDO | ADP7182AUJZ-R7 | C514358 | TSOT-23-5 | 4,039 | 2.5059 / 2.0727 | JLC record: -1.22 to -27 V adj., 200 mA, 18 uVrms, 66 dB at 10 kHz; accuracy not read *(check)* |
| neg. LDO | LT1964ES5-BYP#TRPBF | C107776 | SOT-23-5 | 2,616 | 3.6256 / - | JLC record: -1.22 V reference (the LM27762's, so the existing R3/R4 would serve), 200 mA, 30 uVrms; accuracy not read *(check)* |
| neg. LDO | TPS72325DBVR | C69932 | SOT-23-5 | 12,277 | 0.5787 / - | fixed **-2.5 V**: 3.342 + 2.5 is over 5.5 V. Excluded |
| neg. LDO | TPS7A3001DGNR | C33835 | HVSSOP-8 (exposed pad) | 11,609 | 2.0368 / 1.6379 | 15 uVrms; exposed pad, X-ray status unknown. Not pursued |
| +3.3 V | **TPS7A2033PDBVR** | C2862740 | SOT-23-5 | 114,162 | 0.2081 / 0.1589 | fixed 3.3 V **+/-1.5 %**, VIN 1.6-6.0 V (abs 6.5), 300 mA, **7-10 uVrms**, PSRR 95 dB 1 kHz / 75 dB 100 kHz / **45 dB at 1 MHz** (20 mA), start-up 0.75-1.15 ms |
| +3.3 V | LP5907MFX-3.3/NOPB | C80670 | SOT-23-5 | 64,768 | 0.1648 / 0.1271 | fixed, **+/-2 %**, VIN 2.2-5.5 V (abs 6), 250 mA, 10 uVrms, PSRR 60 dB 100 kHz, **5 % start-up overshoot** |
| +3.3 V | **XC6206P332MR-G** | C5446 | SOT-23-3 | 481,224 | 0.1261 / 0.0996 | **Basic**. JLC record: fixed 3.3 V, 200 mA, 6 V max in; accuracy, noise and PSRR not in the record and the datasheet was not obtained *(check)* |
| +3.3 V | TPS73601DBVR | C59200 | SOT-23-5 | 20,885 | 0.7667 / 0.5967 | adjustable, VFB 1.204 V, **+/-1 %** overall; keeps 174k/100k (3.299 V); VIN 1.7-5.5 V, 500 mA; noise 27 x VOUT uVrms without NR (about 89 uV), PSRR 37 dB at 10 kHz |
| +3.3 V | AMS1117-3.3 | C6186 | SOT-223 | 1,500,494 | 0.1938 / 0.1485 | **Basic**, but 1.1 V dropout at 800 mA (1.3 V max) against 1.03 V of headroom at PW-6's 4.33 V. Excluded |

**The 5.5 V budget is what separates them.** Today the bare rails reach
5.445 V at the LM27762's maxima. Rails at their datasheet maxima, a
-2.069 V target and 0.1 % dividers:

- negative, TPS72301 legacy die (+/-3 %): about **-2.135 V**; new die
  (+/-1.6 %): -2.106 V. JLC's record does not say which die ships, so the
  legacy figure governs.
- with TPS7A2033 (+3.3495 V): **5.485 V**, 15 mV under 5.5 V (today 55 mV).
- with TPS73601 and 174k/100k (about +3.339 V): 5.474 V.
- with LP5907 (+3.366 V): **5.501 V, fails**; XC6206 the same if its
  accuracy is +/-2 % *(check)*.
- the weak corner for AW-1: -2.069 x 0.97 = about -2.007 V, 36 mV inside
  AW-1's -1.971 V edge.

**The negative divider changes.** The legacy die needs R1 + R2 <= VOUT /
(100 x IFB) = about 20.7 kohm (datasheet eq. 5), so the present
330k/100k divider (45 kohm Thevenin, about 300 kohm total) is out. From
existing 0.1 % types: **R1 = 953R, R2 = 953R + (953R || (249R + 249R))**,
-2.0690 V, 2.23 kohm, 0.93 mA, five placements (found by searching
series-parallel nets of existing types). It replaces the five-part 4 x 330k + 100k divider, and with a
fixed +3.3 V LDO the 174k and one 100k (the +3.3 V feedback) leave too.
Under +C the 953R type otherwise leaves the BOM, so there this divider
keeps one Extended type alive. The LT1964 alternative keeps the present
divider unchanged but costs $3.63.

Capacitors: the LM27762's were never counted (bom.md "Not counted"); the
three-part version needs about the same number (inverter in/fly/out, an
LDO output each), all of which can be Basic (1 uF C15849, 10 uF C15850,
100 nF C14663). Not costed below.

### Cost per order

Removed per board: LM27762, the 4 x 330k + 100k negative divider, 174k
and the +3.3 V feedback 100k: $1.6457 at the qty-20 tier, $1.2805 at
qty 100. Added: the three ICs and the 953R/249R divider ($0.4324 /
$0.3610). Extended types counted against the LM27762 (1) and 174k (1).
X-ray at the whole-quantity reading; the graduated reading adds $8.20
(20 boards) or $24.70 (100) to every saving.

| rank | option | Ext. types vs today | fees / order | parts / order, 20 | net saving, 20 | parts / order, 100 | net saving, 100 |
|---|---|---|---|---|---|---|---|
| 1 | **A: LM2776 + TPS72301 + TPS7A2033** | +1 | +$3.07 | +$8.83 | **+$4.50** | +$35.59 | **+$10.34** |
| 2 | C: LM2664 + TPS72301 + TPS7A2033 | +1 | +$3.07 | +$4.12 | +$9.21 | +$18.21 | +$27.72 |
| 3 | B: TPS60403 + TPS72301 + TPS7A2033 | +1 | +$3.07 | +$9.42 | +$3.91 | +$37.06 | +$8.87 |
| 4 | D: LM2776 + TPS72301 + XC6206 (Basic) | 0 | $0 | +$7.19 | +$9.21 | +$29.66 | +$19.34 |
| - | E: LM2776 + TPS72301 + TPS73601 (keeps 174k/100k) | +2 | +$6.14 | +$24.31 | -$14.05 | +$97.35 | -$54.49 |

Net saving = X-ray saved - fees added - parts added; positive is cheaper
than the LM27762. The ranking is technical risk first, money second:

- **A** is the LM27762 taken apart: the same inverter core, the same
  2 MHz (and the same PFM behaviour), 200 mA for PR-4's fault current.
  What moves is the rails' noise (negative LDO 60 uVrms class against
  22, positive 7-10 against 22) and the 5.5 V margin (15 mV).
- **C** saves most, but 40 mA is under PR-4's fault current (the AWG
  op-amp's 65 mA rating) and its 40-80 kHz line lands where the LDO's
  PSRR is 40-48 dB; no light-load behaviour is stated.
- **B**: 250 kHz is a fixed line (PW-2 likes that), but its 5.25 V
  recommended maximum equals PW-6's top with no margin, and 60 mA is
  close to PR-4's fault.
- **D** is fee-neutral and cheap, but the XC6206's accuracy, noise and
  PSRR are not read, and at +/-2 % it breaks 5.5 V.

At these quantities the money is small either way (single dollars at 20
boards); the case for leaded parts is inspection and rework, not cost.

### What would need re-running

- `sim/powercal` **P1-a/P1-b/P2-b** (start-up and shut-down under
  5.5 V): three independent start-ups instead of one chip - TPS723
  1 ms or 8 ms by die, TPS7A20 0.75-1.15 ms, LP5907 5 % overshoot - and
  the bare-rail maximum moves from 5.445 to about 5.485 V.
- **P4-a/P4-b and PW-2** (ripple at the pins and AWG output): the
  supply model is behavioural with the LM27762's numbers; it needs the
  inverter's line (2 MHz, 250 kHz or 40-80 kHz) and the TPS72301's
  PSRR, which the datasheet gives only to 100 kHz *(check at 2 MHz)*.
- **AN-5 / AW-6** (79.4 uV simulated against 100 uV) and the scope's
  SC-6 path: rail noise 60 uVrms class on the negative LDO against 22.
- **P3-a/P3-c** (PW-1 current and PR-4's fault): the LDOs' ground
  currents and the inverter's current limit (40/60/200 mA by option).
- **P6-a** (PW-6 at 4.33 V): inverter drop at 35 mA (LM2776 about
  0.09 V, TPS60403 0.53 V, LM2664 0.88 V) plus the LDO's dropout.
- **AW-1** 50 ohm row: the negative rail's weak corner moves from
  -2.040 V to about -2.007 V with the legacy die.
