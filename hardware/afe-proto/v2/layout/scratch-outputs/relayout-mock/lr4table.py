import json, math
R='/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
A={p['ref']:p for p in json.load(open(R+'dump_all.json'))['parts']}; B={p['ref']:p for p in json.load(open(R+'dump_new.json'))['parts']}
def cc(p): c=p['cy']; return ((c[0]+c[2])/2,(c[1]+c[3])/2)
def d(P,a,b,net):
    pa=[q['c'] for q in P[a]['pads'] if q['net']==net]; pb=[q['c'] for q in P[b]['pads'] if q['net']==net]
    pp=min(math.hypot(x[0]-y[0],x[1]-y[1]) for x in pa for y in pb)
    ca,cb=cc(P[a]),cc(P[b]); return pp, math.hypot(ca[0]-cb[0],ca[1]-cb[1])
rows=[('C104','U101','/+3V3A_U'),('C105','U101','/+3V3A_U'),('R108','U101','/CH1_OUT'),('R107','U101','/CH1_NP'),('R207','U101','/CH2_NP'),('R208','U101','/CH2_OUT'),
 ('C305','U301','/+3V3A'),('C306','U301','/VNEG'),('R303','U301','/AWG_FB'),('R304','U301','/AWG_FB'),('C301','U301','/AWG_FB'),('R308','U301','/AWG_OA'),('R309','U301','/AWG_OB'),('R306','U301','/AWG_BIN'),('R307','U301','/AWG_BIN'),
 ('C501','U501','/VREF'),('C502','U501','/+3V3A_R'),('C503','U502','/+3V3A'),
 ('C401','U401','/+5V_F'),('C402','U401','/+5V_F'),('C403','U401','/LM_CP'),('C404','U401','/LM_CP'),('C405','U401','/+3V3A'),('C406','U401','/+3V3A'),('C409','U401','/LM_C1N'),('C407','U401','/VNEG_G'),('C408','U401','/VNEG_G'),('R401','U401','/LM_FBP'),('R402','U401','/LM_FBP'),('R404','U401','/LM_FBN'),('R405','U401','/LM_FBN')]
print('part ic net | main pad-pin / centre | new pad-pin / centre')
for a,b,n in rows:
    m=d(A,a,b,n); w=d(B,a,b,n)
    print('%-5s %-5s %-9s | %5.2f / %5.2f | %5.2f / %5.2f %s'%(a,b,n,m[0],m[1],w[0],w[1],'  EXCEEDS main' if w[0]>m[0]+0.005 or w[1]>m[1]+0.005 else ''))
