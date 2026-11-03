import pandas as pd, numpy as np, json, os
rng=np.random.default_rng(0)
def boot(x,n=2000):
    x=np.asarray(x); x=x[~np.isnan(x)]
    if len(x)<3: return [np.nan,np.nan]
    m=[np.median(rng.choice(x,len(x))) for _ in range(n)]; return [round(float(np.percentile(m,2.5)),4),round(float(np.percentile(m,97.5)),4)]
V=[v for v in ["A-lanczos","B-general","D-unif","D20-60","D40-90","D60-120"] if os.path.exists(f"res_caras_{v}.csv")]
out={}
# 1 calidad de fotograma completo
fr={}
for v in ["ORIG"]+V:
    if os.path.exists(f"res_frames_{v}.csv"):
        d=pd.read_csv(f"res_frames_{v}.csv"); fr[v]={k:[round(float(d[k].mean()),3),round(float(d[k].std()),3)] for k in ["niqe","musiq","clipiqa"]}
out["frames"]=fr
# 2 caras por tamaño
C={v:pd.read_csv(f"res_caras_{v}.csv") for v in V}
base=C["B-general"][["frame","j","ancho_orig"]]
res={}
for v,d in C.items():
    d=d.merge(base[["frame","j"]],on=["frame","j"])
    d["tex_rel"]=d.textura/d.textura_orig
    for g,(a,b) in {"<40":(0,40),"40-60":(40,90),">=90":(90,1e9)}.items():
        x=d[(d.ancho_orig>=a)&(d.ancho_orig<b)]
        if len(x)<3: continue
        res.setdefault(v,{})[g]={"n":int(len(x)),"cos_med":round(float(x.coseno_vs_orig.median()),3),"cos_ci":boot(x.coseno_vs_orig),"topiq_med":round(float(x.topiq_face.median()),3),"tex_rel_med":round(float(x.tex_rel.median()),2),"cos_lt_0.8":round(float((x.coseno_vs_orig<0.8).mean()),3)}
out["caras"]=res
# 2b diferencias pareadas frente a D40-90 en caras pequeñas
par={}
for v in V:
    if v=="D40-90": continue
    m=C[v].merge(C["D40-90"],on=["frame","j"],suffixes=("_v","_s"))
    m=m[m.ancho_orig_v<90]
    dif=(m.coseno_vs_orig_v-m.coseno_vs_orig_s).dropna()
    par[v]={"n":int(len(dif)),"mean_dcos":round(float(dif.mean()),4),"ci_mean":[round(float(np.percentile([rng.choice(dif.values,len(dif)).mean() for _ in range(2000)],q)),4) for q in (2.5,97.5)]}
out["pareado_pequenas_vs_D40-90"]=par
# 3 temporal
T={}
for v in ["A-lanczos","B-general","D-unif","D20-60","D40-90","D60-120"]:
    if not os.path.exists(f"temporal2_{v}.csv"): continue
    d=np.genfromtxt(f"temporal2_{v}.csv",delimiter=","); _,u=np.unique(d[:,0],return_index=True); d=d[u]
    g=d[~np.isnan(d[:,1])]; f=d[~np.isnan(d[:,4])]
    T[v]={"global_mean":round(float(g[:,1].mean())*1000,3),"n_pares":int(len(g))}
    for lab,m in [("caras<40",(f[:,5]>0)&(f[:,5]<40)),("caras40-90",(f[:,5]>=40)&(f[:,5]<90)),("caras>=90",f[:,5]>=90)]:
        x=f[m,4]*1000; T[v][lab]=[round(float(x.mean()),3),int(m.sum()),[round(float(np.percentile([rng.choice(x,len(x)).mean() for _ in range(1000)],q)),3) for q in (2.5,97.5)]]
out["temporal_x1000"]=T
if os.path.exists("res_tramos.csv"):
    t=pd.read_csv("res_tramos.csv"); t["g"]=t.img.str.split("_").str[0]; t["v"]=t.img.str.split("_").str[1]
    out["tramos"]=t.groupby(["g","v"])[["niqe","musiq","clipiqa"]].mean().round(3).reset_index().to_dict("records")
json.dump(out,open("resultados.json","w"),indent=1,ensure_ascii=False); print(json.dumps(out,indent=1,ensure_ascii=False)[:6000])
