"""Shared constants, results store, guard registry and parts registry for the version 2 power / reference / calibration block.

Every number is a datasheet figure (source in the comment: document, table or section, read from the PDF text on 2026-11-12),
a design value chosen in design.md, or an ASSUMPTION marked (check).  Nothing here is measured on a board.
Datasheets read: SNVSAF7C (LM27762), SBVS032K (REF30E), SBAS444E (ADS1115), TPH2502 Rev. A (3PEAK), and v2/jlc-basic.csv."""
import csv, hashlib, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.normpath(os.path.join(HERE, "..", ".."))
AFE = os.path.normpath(os.path.join(V2, ".."))
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)

# ---------------------------------------------------------------- datasheet figures
LM = dict(
    vfbp=(1.182, 1.200, 1.218),        # SNVSAF7C 5.5 VFB+ min/typ/max over temperature
    vfbn=(1.202, 1.220, 1.238),        # VFB- magnitude
    r_bot_min=50e3,                    # 7.2.2.1 / 7.2.2.3: R2 and R4 (the resistor to ground) no less than 50 kohm
    iq=0.39e-3,                        # 5.5 IQ typ, no load, EN tied to VIN (NO MAXIMUM IS GIVEN)
    fsw=(1.7e6, 2.0e6, 2.3e6),         # 5.5 fSW at VIN = 3.6 V
    ilim=0.5,                          # 6.3.2 input current limit 500 mA typ, output shorted
    load_reg_p=11e-6, load_reg_n=34e-6,   # V per mA, 5.5 (0 to 250 mA, Vout 1.8 V)
    line_reg_p=1.9e-3, line_reg_n=1.5e-3,  # V per V, 5.5 (VIN 2.7..5 V, 50 mA)
    psrr_p_10k_db=43.0, psrr_n_10k_db=50.0,   # 5.5, IL 100 mA, 1.8 V outputs, 10 kHz: the only PSRR figures given
    iout_max=0.250, uvlo=(2.4, 2.6),   # 5.3 / 6.3.1
    rth_ja=62.2, tj_max=125.0,         # 5.4 DSS WSON, 5.3 operating junction
    shutdown_pulldown=50e3,            # 6.4.1: in shutdown an internal 50 kohm from each OUT to ground (whether it works with VIN = 0: check)
    vin_abs=5.8,
)
TPH = dict(
    vdd_rec=(2.5, 5.5),                # Electrical Characteristics, VDD supply voltage: the only recommended-supply row there is (no separate table)
    vabs=7.0,                          # Absolute Maximum Ratings V+ - V- (its text says 7.5 V)
    iq_typ=6.5e-3, iq_max=7.5e-3,      # IQ per amplifier
    isupply_abs=60e-3,                 # abs max, current at supply pins +-60 mA
    psrr_dc_db=(80.0, 120.0),          # PSRR min / typ, a DC figure; no PSRR(f) curve is given
    note3_max=10e-3,                   # note 3: input current beyond 0.5 V past a supply limited to 10 mA
)
REF = dict(
    vout=3.000, tol=0.001,             # SBVS032K 6.5 REF30E: 2.997 / 3 / 3.003 V
    tc_typ=5e-6, tc_max=15e-6,         # ppm/K, 0 to 70 C
    load_src=15e-6, load_snk=150e-6,   # ppm/mA max (typ 3): source 0..10 mA, sink 0..-10 mA
    iload=(-10e-3, 10e-3),             # 6.3 recommended load current (REF30xxE)
    vin_min_off=0.2, vin_max=5.75,     # 6.3: VIN >= VOUT + 0.2 V (REF30xxE)
    line_reg=240e-6,                   # V/V max, VOUT+300 mV <= VIN <= 5.75 V
    iq=(27e-6, 37e-6),                 # typ 25 C / max over temperature
    cl=(0.1e-6, 22e-6), esr=(10e-3, 500e-3),
    isc=35e-3,
    turnon_s=2e-3,                     # to 0.1 % with CL = 1 uF
    hyst_ppm=(25, 100), lt_ppm=40,     # thermal hysteresis typ / max; long-term 0..1000 h
    noise_uvrms=51.0,                  # 10 Hz..10 kHz
)
ADS = dict(
    lsb=125e-6,                        # Table 7-1: FSR +-4.096 V, LSB = FSR/2^16
    noise_rms=125e-6,                  # Table 6-1: 125 uVrms (125 uVpp) at 8..128 SPS, FSR +-4.096 V (equal to one LSB: the table is quantisation-limited)
    inl_lsb=1.0,                       # 5.5 INL 1 LSB max, 8 SPS, FSR +-2.048 V, best fit over 99 % of FS (NOT given at +-4.096 V: check)
    off_err_lsb=3.0, off_match_lsb=3.0,   # 5.5, FSR +-2.048 V (LSB of that range; at +-4.096 V the LSB is 125 uV: check)
    gain_err=(0.0001, 0.0015),         # 5.5 gain error 0.01 % typ, 0.15 % max (includes PGA and reference)
    gain_ch_match=(0.0005, 0.001),     # 5.5 "Gain channel match, any two inputs" 0.05 % typ, 0.1 % max
    gain_drift_ppm=(5, 40),            # 5.5 ppm/C typ, max
    zcm=6e6, zdiff=15e6,               # 5.5 at FSR +-4.096 V: common mode 6 Mohm, differential 15 Mohm (typ only)
    v_common=0.7,                      # 7.3.2: the sampling capacitors discharge to about 0.7 V
    iq=(150e-6, 200e-6, 300e-6),       # 5.5 operating: typ, 25 C max, over temperature max
    vabs=(-0.3, 0.3),                  # 5.1: AIN GND - 0.3 V .. VDD + 0.3 V
    i_in_abs=10e-3,                    # 5.1: continuous input current, any pin except supply
    vdd=(2.0, 5.5),
    sps=(8, 860),
)
DUE = dict(v5=(4.5, 5.25), adc_pin_leak=0.5e-6)   # PW-6 minimum 4.50 V; afe.md PA-9 leakage 0.5 uA over temperature

REQ = dict(pw1_ma=100.0, pw1_total_ma=450.0, due_ma=300.0, pw2_ripple_mv=20.0, pr2=(-0.2, 3.45), sc9_lsb=2.0, aw6_uv=100.0,
           sc6_mv=0.2, fit_share=0.001, sc10_ohm=5e3, pr3_ua=100.0, pr3_rail_v=0.5, sc7_pct=0.5, sc7_mv=5.0)

# ---------------------------------------------------------------- the Basic parts table (V2-3), read from jlc-basic.csv
def _val(s):
    s = s.strip()
    for u, m in (("R", 1.0), ("k", 1e3), ("M", 1e6)):
        if s.endswith(u):
            return float(s[:-1]) * m
    return float(s)

def basic_rows():
    return list(csv.DictReader(open(os.path.join(V2, "jlc-basic.csv"))))

def basic_resistors(package="0603"):
    """{ohms: lcsc} of the Basic resistors of one package (0 ohm excluded)."""
    return {_val(r["value"]): r["lcsc"] for r in basic_rows()
            if r["kind"] == "resistor" and r["basic"] == "yes" and r["package"] == package and _val(r["value"]) > 0}

def lookup(lcsc):
    """The jlc-basic.csv row of an LCSC number, or None (not a Basic passive)."""
    for r in basic_rows():
        if r["lcsc"] == lcsc:
            return r
    return None

def fmt_r(x):
    return f"{x/1e6:g}M" if x >= 1e6 else f"{x/1e3:g}k" if x >= 1e3 else f"{x:g}R"

def par(*r):
    return 1.0 / sum(1.0 / x for x in r)

# ---------------------------------------------------------------- results and case registry
def save(name, obj):
    json.dump(obj, open(os.path.join(RES, name + ".json"), "w"), indent=1, default=float, sort_keys=True)

def load(name):
    return json.load(open(os.path.join(RES, name + ".json")))

class Cases:
    """Rows of a report: id, requirement, limit, value, margin, ok (True / False / None = information)."""
    def __init__(self, name):
        self.name, self.rows = name, []
    def add(self, cid, req, case, limit, value, margin, ok, note="", sect=""):
        self.rows.append(dict(id=cid, req=req, case=case, limit=limit, value=value, margin=margin, ok=ok, note=note, sect=sect))
        return ok
    def save(self):
        save("cases_" + self.name, self.rows)

class Guards:
    """A check is trusted only after it has failed on purpose.  add(): the check was run on a deliberately broken input (it must
    report FAIL, broken_ok False) and on the restored input (it must pass)."""
    def __init__(self, name):
        self.name, self.rows = name, []
    def add(self, gid, what, broken_ok, restored_ok):
        broken_ok, restored_ok = bool(broken_ok), bool(restored_ok)
        good = (broken_ok is False) and (restored_ok is True)
        self.rows.append(dict(id=gid, what=what, broken="fails" if broken_ok is False else "PASSES (guard void)",
                              restored="passes" if restored_ok else "FAILS", good=bool(good)))
        return good
    def save(self):
        save("guards_" + self.name, self.rows)

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
