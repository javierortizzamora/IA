# Extrae, de una variante 4K (o del original), recortes de caras (máx. 512 px) y fotogramas completos
# (área activa a 1470x1080) para medir calidad e identidad. Índices en fotogramas del ORIGINAL (V[k] <-> O[k+1]).
import sys, json, subprocess, numpy as np, cv2, os
var, nombre, ini, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
base = os.path.join("articulo_datos", "extraccion", nombre); os.makedirs(base+"/caras", exist_ok=True); os.makedirs(base+"/frames", exist_ok=True)
caras = json.load(open("articulo_datos/caras_original.json"))
es_orig = var == "ORIG"
if es_orig:
    W0, H0 = 626, 460
    cmd = ["ffmpeg","-v","error","-ss",f"{ini/25:.4f}","-i","Antena 3 Noticias 28-09-1992.mp4","-vf","crop=626:460:8:10","-frames:v",str(n),"-f","rawvideo","-pix_fmt","bgr24","-"]
    off = 0
else:
    W0, H0 = 2940, 2160
    cmd = ["ffmpeg","-v","error","-ss",f"{max(ini-1,0)/25:.4f}","-i",var,"-vf","crop=2940:2160:450:0","-frames:v",str(n),"-f","rawvideo","-pix_fmt","bgr24","-"]
    off = 1
s = W0/626.0
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=W0*H0*3)
i = ini if es_orig else max(ini-1,0)+off
cuenta = 0
while True:
    b = p.stdout.read(W0*H0*3)
    if len(b) < W0*H0*3: break
    f = np.frombuffer(b, np.uint8).reshape(H0, W0, 3)
    if i % 50 == 25:
        g = cv2.resize(f, (1470, 1080), interpolation=cv2.INTER_AREA if not es_orig else cv2.INTER_CUBIC)
        cv2.imwrite(f"{base}/frames/{i:05d}.jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 95])
    for j, (x1, y1, x2, y2, sc) in enumerate(caras.get(str(i), [])):
        w, h = x2-x1, y2-y1; m = 0.3
        X1, Y1 = int(max((x1-m*w)*s, 0)), int(max((y1-m*h)*s, 0))
        X2, Y2 = int(min((x2+m*w)*s, W0)), int(min((y2+m*h)*s, H0))
        c = f[Y1:Y2, X1:X2]
        if c.size == 0: continue
        lado = max(c.shape[:2])
        if es_orig:  # referencia: el original ampliado con bicúbica al tamaño equivalente en 4K
            c = cv2.resize(c, (int(c.shape[1]*4.6965), int(c.shape[0]*4.6965)), interpolation=cv2.INTER_CUBIC); lado = max(c.shape[:2])
        if lado > 512:
            k = 512/lado; c = cv2.resize(c, (max(1,int(c.shape[1]*k)), max(1,int(c.shape[0]*k))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(f"{base}/caras/{i:05d}_{j}.jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 95]); cuenta += 1
    i += 1
print(nombre, ini, i, cuenta)
