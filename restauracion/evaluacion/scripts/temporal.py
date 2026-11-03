# Error de deformación temporal (warping error) de una variante 4K respecto al movimiento del original.
# Flujo óptico DIS calculado en el ORIGINAL (626x460), escalado a 1470x1080; se deforma la salida t -> t+1
# y se mide |V(t+1) - warp(V(t))| en píxeles no ocluidos (consistencia ida-vuelta). Excluye transiciones.
import sys, subprocess, json, numpy as np, cv2
CARAS = json.load(open("articulo_datos/caras_original.json"))
var, ini, n, salida = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
ORIG = "Antena 3 Noticias 28-09-1992.mp4"
TRANS = [(440,446),(589,601),(893,903),(976,985),(1128,1129),(1200,1201),(2584,2585),(2627,2640),(2747,2748),(2892,2892),(5134,5150),(5179,5180)]
def excluido(i):  # índice del original del fotograma t+1
    return any(a-2 <= i <= b+2 for a, b in TRANS)
W, H = 1470, 1080
def flujo(cmd, w, h):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w*h*3)
    while True:
        b = p.stdout.read(w*h*3)
        if len(b) < w*h*3: return
        yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
# V[k] <-> O[k+1]; se lee el original desde el fotograma ini+1 y la variante desde ini
o = flujo(["ffmpeg","-v","error","-ss",f"{(ini+1)/25:.4f}","-i",ORIG,"-vf","crop=626:460:8:10","-frames:v",str(n),"-f","rawvideo","-pix_fmt","rgb24","-"],626,460)
v = flujo(["ffmpeg","-v","error","-ss",f"{ini/25:.4f}","-i",var,"-vf",f"crop=2940:2160:450:0,scale={W}:{H}:flags=area","-frames:v",str(n),"-f","rawvideo","-pix_fmt","rgb24","-"],W,H)
dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
sx, sy = W/626, H/460
po = pv = None; filas = []; k = ini
for O, V in zip(o, v):
    if po is not None and not excluido(k+1):
        a, b = cv2.cvtColor(po, cv2.COLOR_RGB2GRAY), cv2.cvtColor(O, cv2.COLOR_RGB2GRAY)
        fb = dis.calc(b, a, None)  # t+1 -> t
        ff = dis.calc(a, b, None)  # t -> t+1
        # consistencia ida-vuelta en resolución del original
        hh, ww = a.shape; xx, yy = np.meshgrid(np.arange(ww, dtype=np.float32), np.arange(hh, dtype=np.float32))
        ff_w = cv2.remap(ff, xx+fb[...,0], yy+fb[...,1], cv2.INTER_LINEAR)
        ok = (np.linalg.norm(fb+ff_w, axis=2) < 0.5 + 0.05*(np.linalg.norm(fb,axis=2)+np.linalg.norm(ff_w,axis=2)))
        F = cv2.resize(fb, (W, H), interpolation=cv2.INTER_LINEAR); F[...,0] *= sx; F[...,1] *= sy
        M = cv2.resize(ok.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        warp = cv2.remap(pv, gx+F[...,0], gy+F[...,1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        e = np.abs(V.astype(np.float32) - warp)[M].mean()/255. if M.mean() > 0.2 else np.nan
        mov = np.linalg.norm(fb, axis=2).mean()
        # error solo dentro de las caras (cajas del fotograma muestreado más cercano), con su ancho máximo
        i5 = str((k+1) - (k+1) % 5); MC = np.zeros((H, W), bool); amax = 0
        for (x1, y1, x2, y2, sc) in CARAS.get(i5, []):
            MC[int(y1*sy):int(y2*sy), int(x1*sx):int(x2*sx)] = True; amax = max(amax, x2-x1)
        MC &= M
        ec = np.abs(V.astype(np.float32) - warp)[MC].mean()/255. if MC.sum() > 50 else np.nan
        filas.append(f"{k+1},{e:.5f},{M.mean():.3f},{mov:.3f},{ec:.5f},{amax:.1f}")
    po, pv = O, V; k += 1
open(salida, "a").write("\n".join(filas) + ("\n" if filas else ""))
print(ini, len(filas))
