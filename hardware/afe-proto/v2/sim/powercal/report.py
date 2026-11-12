#!/usr/bin/env python3
"""report.md from results/*.json (cases_*, guards_*, power, sense, sc7, refladder, coupling) and lm_results.json.  python3 -I report.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

ORDER = [("power", "1. Shared rail, PW-1, V2-2 supply rating, PR-3 (power.py)"), ("coupling", "1b. SC-9 through the shared rail, PW-2, PW-7 (coupling.py)"),
         ("refladder", "3 and 4. REF3030E roles and the ladder (refladder.py)"), ("sense", "5. Sense divider and jumper (sense.py)"), ("sc7", "6. ADS1115 and SC-7, the extrapolation (sc7.py)")]
def esc(s): return str(s).replace("|", "&#124;").replace("\n", " ")

def main():
    L = ["# AFE version 2: power, reference and calibration block (generated from results/ by report.py)", ""]
    pw = load("power")
    L += [f"AWG inputs read at run time: `../awg/design.py` sha256 `{pw['awg_design_sha'][:16]}`, `../awg/report_table.md` sha256 `{pw['awg_report_table_sha'][:16]}`; AWG values {json.dumps(pw['awg_values'], default=str)}.", "",
          "Status: PASS / FAIL / info against the stated limit; every FAIL is also in design.md. A check was trusted only after it failed on purpose (Guards table at the end).", ""]
    for name, title in ORDER:
        rows = load("cases_" + name)
        L += [f"## {title}", "", "| | ID | req | case | limit | result | margin | note |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            st = "PASS" if r["ok"] else "**FAIL**" if r["ok"] is False else "info"
            L.append(f"| {st} | {esc(r['id'])} | {esc(r['req'])} | {esc(r['case'])} | {esc(r['limit'])} | {esc(r['value'])} | {esc(r['margin'])} | {esc(r['note'])} |")
        L.append("")
    # tables from power.json
    L += ["## Rails, corners (power.py)", "", "| | V |", "|---|---|"]
    for k, v in pw["rails"].items(): L.append(f"| {k} | {v:.4f} |")
    L += ["", "R3 options (R1 120k, R2 68k, R4 100k fixed): the negative rail against the rating margin", "", "| R3 | nominal | min | max | sum with the +rail max | rating margin |", "|---|---|---|---|---|---|"]
    for a in pw["r3_options"]: L.append(f"| {a['R3']/1e3:.1f}k | {a['nom_n']:.4f} | {a['min_n']:.4f} | {a['max_n']:.4f} | {a['sum_max']:.4f} | {a['margin_rating']*1e3:+.0f} mV |")
    L += ["", "PW-1 states (IQ at the datasheet maximum; I in mA)", "", "| state | +rail V | OUT+ | OUT- | 5V pin | op-amp output |", "|---|---|---|---|---|---|"]
    for r in pw["pw1"]["rows"]: L.append(f"| {esc(r['state'])} | {r['rail']:.3f} | {r['Ip_mA']:.1f} | {r['In_mA']:.1f} | {r['Iin_mA']:.1f} | {r['i_o_mA']:+.1f} |")
    L += ["", "PR-3: bleed options (Basic 0603), the unpowered rail with both inputs at +12 V, only the resistive sinks (feedback divider + bleed)", "", "| R | LCSC | sink at 0.5 V uA | rail V | quiescent at 3.3 V mA |", "|---|---|---|---|---|"]
    for o in pw["pr3_options"]: L.append(f"| {fmt_r(o['R'])} | {o['lcsc']} | {o['sink_ua_at_0p5']:.1f} | {o['rail_v']:.3f} | {o['quiescent_ma_3p3']:.3f} |")
    sj = load("sense")
    L += ["", "## Sense chain, detail (sense.py)", "", "| case | gain % (99.9) | offset mV | worst point mV | k error % |", "|---|---|---|---|---|"]
    for k, lab in (("base", "wire on throughout, max channel match 0.1 %"), ("typ_match", "typical channel match 0.05 %"), ("no_match", "no channel mismatch"), ("wire_off_sweep", "wire off throughout (information)")):
        s = sj[k]; L.append(f"| {lab} | {s['gain_pct']:.3f} | {s['off_mV']:.2f} | {s['err_mV']:.2f} | {s['k_err_pct']:.3f} |")
    L += ["", "Structures compared (99.9th percentile, ADS1115 channel match 0.1 % max, offset 3 LSB)", "", "| structure | gain % | offset mV |", "|---|---|---|"]
    for k, lab in (("S1", "S1: tap on AIN2, B on AIN3 in the wire position only, REF on AIN0"), ("S2", "S2: B on AIN3 in both positions"), ("S3_no_rm", "S3: AIN3 = B, AIN2 - AIN3 differential, REF scale rebuilt on AIN3"), ("S3_rm", "S3 + 10k matched resistor on AIN3 (Zcm independent per input)"), ("S3_rm_common", "S3 + matched resistor, Zcm tracking between inputs")):
        s = sj["structs"][k]; L.append(f"| {lab} | {s['gain_pct']:.3f} | {s['off_mV']:.2f} |")
    L += ["", "Ablation of the shipped models (20,000 draws, 99.9th percentile; S3 = the design with 10k on AIN3, Zcm independent per input; S1 = the first structure)", "", "| case | S3 gain % | S3 offset mV | S1 gain % | S1 offset mV |", "|---|---|---|---|---|"]
    for k_, v_ in sj["ablation"].items(): L.append(f"| {k_} | {v_['S3_gain']:.3f} | {v_['S3_off']:.2f} | {v_['S1_gain']:.3f} | {v_['S1_off']:.2f} |")
    L += ["", "ADS1115 timing per level (D23: staircase 1.5 to 3 ms a level, free-running on the pair)", "", "| DR | conversion ms | step ms | conversions per level | whole inside a level | fit slope noise % | staircase s |", "|---|---|---|---|---|---|---|"]
    for t in sj["timing"]: L.append(f"| {t['DR']} | {t['conv_ms']:.2f} | {t['step_ms']:.1f} | {t['per_level']:.2f} | {t['clean_per_level']:.2f} | {t['fit_slope_noise_pct']:.4f} | {t['total_s']:.2f} |")
    L += ["", "Every header position (B tied to node X by the wire; T0 over the AWG sweep -1.95..+2.28 V; dT = change of the tap against the wire-off reading)", "", "| node | X V | T0 min | T0 max | current into ADS diodes uA | wire current uA |", "|---|---|---|---|---|---|"]
    for w in sj["wrong"]: L.append(f"| {w['node']} | {w['X']} | {w['t0_min']:.3f} | {w['t0_max']:.3f} | {w['iesd_ua']:.0f} (AIN3: {w['iesd3_ua']:.0f}) | {w['iwire_ua']:.0f} |")
    sc = load("sc7")
    L += ["", "## SC-7 sum of this block (sc7.py)", "", "| term | gain % | offset mV |", "|---|---|---|"]
    for r in sc["sum"]["rows"]: L.append(f"| {esc(r[0])} | {r[1]:.3f} | {r[2]:.1f} |")
    L += [f"| **linear sum (RSS)** | **{sc['sum']['linear']:.2f} ({sc['sum']['rss']:.2f})** | **{sc['sum']['off']:.1f}** |", ""]
    lp = os.path.join(HERE, "lm_results.json")
    L += ["## LM27762 transient runs (lm_tran.py, TI's model; the model has no LDO loop and converges by lottery)", ""]
    if os.path.exists(lp):
        d = json.load(open(lp)); L += ["| run | ok | VIN | OUT+ dc V | OUT- dc V | +rail t90 ms | -rail t90 ms | OUT+ max V | OUT- min V | bare max V | OUT+ pp mV | VIN pp mV | pump Hz |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in d.items():
            if v.get("ok"):
                L.append(f"| {k} | yes | {v.get('vin')} | {v['outp_dc']:.4f} | {v['outn_dc']:.4f} | {v['outp_t90']*1e3:.3f} | {v['outn_t90']*1e3:.3f} | {v['outp_max']:.4f} | {v['outn_min']:.4f} | {v['bare_max']:.4f} | {v['outp_pp']*1e3:.2f} | {v['vin_pp']*1e3:.1f} | {v['pump_hz']:.0f} |")
            else: L.append(f"| {k} | no: {esc(v.get('why'))} | | | | | | | | | | | |")
    else: L.append("none converged")
    L += ["", "## Guards: each check failed on purpose, then restored", "", "| guard | what | broken | restored | |", "|---|---|---|---|---|"]
    for n in ("power", "coupling", "refladder", "sense", "sc7", "parts"):
        for g in load("guards_" + n): L.append(f"| {g['id']} | {esc(g['what'])} | {g['broken']} | {g['restored']} | {'ok' if g['good'] else '**BAD**'} |")
    open(os.path.join(HERE, "report.md"), "w").write("\n".join(L) + "\n")
    print("report.md", len(L), "lines")

if __name__ == "__main__":
    main()
