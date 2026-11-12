"""C15850 (Samsung CL21A106KAYNNNE) data, parsed as in sim/powercal/run.py samsung_c15850()."""
import hashlib, json, numpy as np, os
HERE = os.path.dirname(os.path.abspath(__file__))
SAM_FILE = os.path.join(HERE, "../../models/cl21a106kaynnne/CL21A106KAYNNN_product_page.html")
SAM_SHA = "4b7cf7d8e24b0af8cb7f0d2118a8077c6b512ade8c0662c6b0ab1a4bb4f27c24"
def load():
    raw = open(SAM_FILE, "rb").read()
    assert hashlib.sha256(raw).hexdigest() == SAM_SHA
    t = raw.decode("utf-8", "replace"); i = t.index("var datasheetData = ") + len("var datasheetData = "); d = 0
    for j in range(i, len(t)):
        if t[j] == "[": d += 1
        elif t[j] == "]":
            d -= 1
            if d == 0: break
    data = json.loads(t[i:j+1])
    z = [b for b in data if b["graphType"] == "|Z|_R"][0]["selectPartsList"][0]["chartList"]
    arr = lambda ch: (np.array([float(q["x"]) for q in ch["data"]])*1e6, np.array([float(q["y"]) for q in ch["data"]]))
    fz, Z = arr([c for c in z if c["graphSubType"] == "|Z|"][0]); fr, Rr = arr([c for c in z if c["graphSubType"] == "R"][0])
    dc = [b for b in data if b["graphType"] == "DCBias"][0]["selectPartsList"][0]["chartList"][0]["data"]
    xv = np.array([float(q["x"]) for q in dc]); yv = np.array([float(q["y"]) for q in dc]); o = np.argsort(xv)
    m = (fz >= 3e6) & (fz <= 10e6); w = 2*np.pi*fz[m]; X = np.sqrt(np.maximum(Z[m]**2 - np.interp(fz[m], fr, Rr)**2, 0))
    esl = float(np.median((X + 1/(w*10e-6))/w))
    return dict(esr=lambda f_: float(np.interp(f_, fr, Rr)), k=lambda v: 1 + float(np.interp(abs(v), xv[o], yv[o]))/100,
                esl=esl, xv=xv[o], yv=yv[o])
if __name__ == "__main__":
    S = load()
    print("DC bias points:", list(zip(S["xv"].round(2), S["yv"].round(1)))[:40])
    for v in (0, 1.65, 2.07, 2.5, 3.3, 4.0, 4.4, 5.0, 5.25, 5.5):
        print(f"{v} V: k={S['k'](v):.3f}  with -10%: {S['k'](v)*0.9:.3f}")
    print("ESR 2MHz", S["esr"](2e6), "ESL", S["esl"])
