#!/usr/bin/env python3
"""Duplica los fotogramas con RIFE 4.9 (movimiento suavizado), sin cambiar el color,
con filtro antibloques (deband), un filtro de enfoque ajustable y el audio del
original sin tocar.

  python rife/acabado2x.py ENTRADA_4K.mp4 ORIGINAL.mp4 SALIDA.mp4 [--fp16] [--escala 0.5] [--umbral-corte 0.12] [--enfoque 1.2]

La tasa de salida es el doble exacto de la de entrada (29,97 -> 59,94).
--enfoque controla la cantidad de nitidez (unsharp de luminancia): 0 = sin enfoque,
0.6-0.8 = enfoque suave, 1.0-1.5 = enfoque notable, por encima de 1.8 puede generar halos."""
import argparse, subprocess, sys, time
from pathlib import Path
import numpy as np
import torch

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from rife_arch import IFNet  # noqa: E402

W, H = 3840, 2160

def dispositivo():
    if torch.backends.mps.is_available(): return torch.device("mps")
    if torch.cuda.is_available(): return torch.device("cuda")
    return torch.device("cpu")

def encoder():
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "hevc_videotoolbox" in enc:
        return ["-c:v", "hevc_videotoolbox", "-b:v", "80M", "-tag:v", "hvc1"]
    return ["-c:v", "libx265", "-crf", "16", "-preset", "medium", "-tag:v", "hvc1"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada"); ap.add_argument("original"); ap.add_argument("salida")
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--escala", type=float, default=0.5)
    ap.add_argument("--umbral-corte", type=float, default=0.12)
    ap.add_argument("--enfoque", type=float, default=1.2,
                     help="Cantidad de nitidez (unsharp de luminancia). 0 = desactivado. Por defecto 1.2.")
    a = ap.parse_args()

    fr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", a.entrada],
                        capture_output=True, text=True).stdout.strip()
    num, den = map(int, fr.split("/"))
    tasa_salida = f"{2*num}/{den}"
    print(f"· Tasa de entrada: {fr}  ->  salida: {tasa_salida}", flush=True)
    print(f"· Enfoque (unsharp): {a.enfoque}", flush=True)

    dev = dispositivo(); dt = torch.float16 if a.fp16 else torch.float32
    print(f"· Dispositivo: {dev.type.upper()}", flush=True)
    net = IFNet(arch_ver="4.7")
    net.load_state_dict(torch.load(AQUI / "rife49.pth", map_location="cpu", weights_only=False))
    net = net.eval().to(dev, dtype=dt)
    escalas = [8/a.escala, 4/a.escala, 2/a.escala, 1/a.escala]

    total = int(subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                                "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", a.entrada],
                               capture_output=True, text=True).stdout.strip() or 0)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.entrada, "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=W*H*3*2)
    # Orden: primero quitamos bandas (deband), luego enfoque (unsharp solo en luminancia,
    # radio 5x5, sin tocar croma: últimos tres parámetros a 0) para no realzar ruido de color.
    if a.enfoque > 0:
        filtros = f"deband,unsharp=5:5:{a.enfoque}:5:5:0.0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    else:
        filtros = "deband,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    enc_cmd = (["ffmpeg", "-v", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", tasa_salida, "-i", "-",
                "-i", a.original, "-map", "0:v", "-map", "1:a:0?", "-vf", filtros] + encoder() +
               ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-c:a", "copy", "-shortest", "-movflags", "+faststart", a.salida])
    encp = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)
    tam = W*H*3

    def leer():
        b = dec.stdout.read(tam)
        return None if len(b) < tam else np.frombuffer(b, np.uint8).reshape(H, W, 3)

    def tensor(f):
        t = torch.from_numpy(np.ascontiguousarray(f)).permute(2, 0, 1)[None]
        return t.to(dev, dtype=dt) / 255.0

    prev = leer()
    if prev is None: sys.exit("No se pudo leer la entrada")
    t_prev = tensor(prev)
    n, cortes, t0 = 1, 0, time.time()
    with torch.inference_mode():
        while True:
            cur = leer()
            if cur is None: break
            t_cur = tensor(cur)
            dif = (t_cur - t_prev).abs().mean().item()
            if dif > a.umbral_corte:
                medio = prev; cortes += 1
            else:
                m = net(t_prev, t_cur, 0.5, escalas, False, True, False)
                m = m[:, :, :H, :W].clamp(0, 1).mul(255).round().to(torch.uint8)
                medio = m[0].permute(1, 2, 0).cpu().numpy()
            encp.stdin.write(prev.tobytes())
            encp.stdin.write(np.ascontiguousarray(medio).tobytes())
            prev, t_prev = cur, t_cur
            n += 1
            if n % 25 == 0:
                v = n / (time.time() - t0)
                resto = (total - n) / v / 60 if total else 0
                print(f"\r  {n}/{total} · {v:.2f} fot/s · quedan ~{resto:.0f} min · cortes: {cortes}", end="", flush=True)
    encp.stdin.write(prev.tobytes()); encp.stdin.write(prev.tobytes())
    dec.stdout.close(); dec.wait(); encp.stdin.close(); encp.wait()
    print(f"\n✓ {a.salida} · {n} -> {2*n} fotogramas en {(time.time()-t0)/60:.1f} min · cortes: {cortes}")
    if encp.returncode != 0: sys.exit("FFmpeg no pudo codificar la salida")

if __name__ == "__main__":
    main()
