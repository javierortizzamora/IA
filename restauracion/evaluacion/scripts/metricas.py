import sys, os, glob, json, csv, numpy as np, cv2, torch, pyiqa, warnings
warnings.filterwarnings("ignore"); torch.set_num_threads(2)
var = sys.argv[1]; que = sys.argv[2] if len(sys.argv) > 2 else "todo"
D = f"ex/{var}"
caras = json.load(open("caras_original.json"))
if que in ("todo", "frames"):
    ms = {n: pyiqa.create_metric(n, device="cpu") for n in ["niqe", "musiq", "clipiqa"]}
    with open(f"res_frames_{var}.csv", "w", buffering=1) as fo:
        w = csv.writer(fo); w.writerow(["frame"] + list(ms))
        for p in sorted(glob.glob(f"{D}/frames/*.jpg")):
            x = pyiqa.utils.imread2tensor(p).unsqueeze(0)
            with torch.no_grad(): w.writerow([os.path.basename(p)[:-4]] + [round(float(m(x)), 4) for m in ms.values()])
if que in ("todo", "caras"):
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
    app.prepare(ctx_id=-1, det_size=(320, 320), det_thresh=0.3)
    fq = pyiqa.create_metric("topiq_nr-face", device="cpu")
    def emb(img):
        f = app.get(img)
        if not f: return None
        f = max(f, key=lambda a: (a.bbox[2]-a.bbox[0])*(a.bbox[3]-a.bbox[1])); return f.normed_embedding
    def textura(img):  # energía de alta frecuencia en la región central de la cara, a 256 px
        g = cv2.cvtColor(cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
        c = g[64:192, 64:192]; return float(cv2.Laplacian(c, cv2.CV_32F).var())
    with open(f"res_caras_{var}.csv", "w", buffering=1) as fo:
        w = csv.writer(fo); w.writerow(["frame", "j", "ancho_orig", "coseno_vs_orig", "topiq_face", "textura", "textura_orig"])
        for p in sorted(glob.glob(f"{D}/caras/*.jpg")):
            b = os.path.basename(p)[:-4]; fr, j = b.split("_"); fr = int(fr); j = int(j)
            box = caras[str(fr)][j]; ancho = box[2] - box[0]
            if os.environ.get("SOLO_PEQ") and ancho >= 120: continue
            if os.environ.get("MUESTRA_GRANDES") and ancho >= 120 and fr % 20 != 0: continue
            img = cv2.imread(p); ref = cv2.imread(f"ex/ORIG/caras/{b}.jpg")
            if ref is None: continue
            ref = cv2.resize(ref, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_AREA)
            e1, e0 = emb(img), emb(ref)
            cos = float(np.dot(e1, e0)) if e1 is not None and e0 is not None else ""
            try:
                x = torch.from_numpy(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).permute(2, 0, 1)[None].float()/255.
                with torch.no_grad(): q = round(float(fq(x)), 4)
            except Exception: q = ""
            w.writerow([fr, j, round(ancho, 1), cos if cos == "" else round(cos, 4), q, round(textura(img), 2), round(textura(ref), 2)])
print("ok", var, que)
