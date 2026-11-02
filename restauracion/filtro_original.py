"""Imprime el filtro FFmpeg que coloca el ORIGINAL exactamente igual que el remaster
(mismo recorte de bordes y mismo encuadre 4K), para la comparativa de pantalla partida."""
import sys
from fractions import Fraction
sys.argv = sys.argv[:2]
import remaster4k as r
ruta = sys.argv[1]
inf = r.info_video(ruta)
w, h = inf["w"], inf["h"]
crop = r.detectar_recorte(ruta, 0, inf["dur"])
f = []
if crop and (crop[0] < w - 8 or crop[1] < h - 8):
    f.append(f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}")
    w, h = crop[0], crop[1]
dar = Fraction(w, h) * inf["sar"]
wi = min(int(round(r.UHD_H * dar / 2) * 2), r.UHD_W)
f.append(f"scale={wi}:{r.UHD_H}:flags=bicubic,setsar=1,pad={r.UHD_W}:{r.UHD_H}:{(r.UHD_W - wi) // 2}:0")
print(",".join(f))
