#!/usr/bin/env python3
"""
Acabado final del remaster: 25 -> 50 fps con RIFE 4.9, tonos y audio normalizado.

  python acabado50.py ENTRADA_4K_25fps.mp4 ORIGINAL.mp4 SALIDA.mp4 [--fp16] [--max-fotogramas N]

- RIFE genera un fotograma intermedio entre cada par de fotogramas consecutivos.
  En un corte de plano (diferencia muy grande) repite el anterior en vez de
  inventar una mezcla de los dos planos.
- Solo se interpola la zona con imagen (las bandas negras laterales se dejan fuera).
- Acabado: +4 % contraste, +8 % saturación, piel algo más cálida.
- Audio del original normalizado a -14 LUFS (referencia de YouTube).
- Salida HEVC 4K 50 fps etiquetada en BT.709.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from rife_arch import IFNet  # noqa: E402

W, H = 3840, 2160


def dispositivo():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def encoder():
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "hevc_videotoolbox" in enc:
        return ["-c:v", "hevc_videotoolbox", "-b:v", "80M", "-tag:v", "hvc1"]
    return ["-c:v", "libx265", "-crf", "16", "-preset", "medium", "-tag:v", "hvc1"]


def zona_activa(f):
    """Columnas con imagen (fuera quedan las bandas negras laterales)."""
    col = f.max(axis=(0, 2))
    idx = np.where(col > 12)[0]
    if len(idx) == 0:
        return 0, W
    x0, x1 = int(idx[0]), int(idx[-1]) + 1
    x0 -= x0 % 2
    x1 += x1 % 2
    return x0, min(x1, W)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("original", help="Vídeo original (para el audio)")
    ap.add_argument("salida")
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--escala", type=float, default=0.5, help="Escala del flujo óptico (0.5 recomendado en 4K)")
    ap.add_argument("--umbral-corte", type=float, default=0.12)
    ap.add_argument("--max-fotogramas", type=int, default=0)
    a = ap.parse_args()

    dev = dispositivo()
    dt = torch.float16 if a.fp16 else torch.float32
    print(f"· Dispositivo: {dev.type.upper()}  ·  precisión: {'fp16' if a.fp16 else 'fp32'}", flush=True)
    net = IFNet(arch_ver="4.7")
    net.load_state_dict(torch.load(AQUI / "rife49.pth", map_location="cpu", weights_only=False))
    net = net.eval().to(dev, dtype=dt)
    escalas = [8 / a.escala, 4 / a.escala, 2 / a.escala, 1 / a.escala]

    total = int(subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", a.entrada],
        capture_output=True, text=True).stdout.strip() or 0)
    if a.max_fotogramas:
        total = min(total, a.max_fotogramas)

    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.entrada, "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=W * H * 3 * 2)
    filtros = ("eq=contrast=1.04:saturation=1.08,"
               "colorbalance=rm=0.03:bm=-0.03,"
               "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
    enc_cmd = (["ffmpeg", "-v", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", "50", "-i", "-",
                "-i", a.original, "-map", "0:v", "-map", "1:a:0?",
                "-vf", filtros] + encoder() +
               ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-af", "loudnorm=I=-14:TP=-1:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                "-shortest", "-movflags", "+faststart", a.salida])
    encp = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    tam = W * H * 3

    def leer():
        b = dec.stdout.read(tam)
        return None if len(b) < tam else np.frombuffer(b, np.uint8).reshape(H, W, 3)

    def tensor(f, x0, x1):
        t = torch.from_numpy(np.ascontiguousarray(f[:, x0:x1])).permute(2, 0, 1)[None]
        return t.to(dev, dtype=dt) / 255.0

    prev = leer()
    if prev is None:
        sys.exit("No se pudo leer la entrada")
    x0, x1 = zona_activa(prev)
    print(f"· Zona con imagen: columnas {x0}-{x1} ({x1 - x0} px de ancho)", flush=True)
    t_prev = tensor(prev, x0, x1)
    n, cortes, t0 = 1, 0, time.time()
    with torch.inference_mode():
        while True:
            if a.max_fotogramas and n >= a.max_fotogramas:
                break
            cur = leer()
            if cur is None:
                break
            t_cur = tensor(cur, x0, x1)
            dif = (t_cur - t_prev).abs().mean().item()
            if dif > a.umbral_corte:
                medio = prev
                cortes += 1
            else:
                m = net(t_prev, t_cur, 0.5, escalas, False, True, False)
                m = m[:, :, :H, :x1 - x0].clamp(0, 1).mul(255).round().to(torch.uint8)
                medio = prev.copy()
                medio[:, x0:x1] = m[0].permute(1, 2, 0).cpu().numpy()
            encp.stdin.write(prev.tobytes())
            encp.stdin.write(np.ascontiguousarray(medio).tobytes())
            prev, t_prev = cur, t_cur
            n += 1
            if n % 25 == 0:
                v = n / (time.time() - t0)
                resto = (total - n) / v / 60 if total else 0
                print(f"\r  {n}/{total} fotogramas · {v:.2f} fot/s · quedan ~{resto:.0f} min · cortes: {cortes}",
                      end="", flush=True)
    # último fotograma, duplicado para mantener la duración
    encp.stdin.write(prev.tobytes())
    encp.stdin.write(prev.tobytes())
    dec.stdout.close()
    dec.wait()
    encp.stdin.close()
    encp.wait()
    seg = time.time() - t0
    print(f"\n✓ {a.salida}\n  {n} fotogramas de entrada -> {2 * n} a 50 fps en {seg / 60:.1f} min · "
          f"cortes de plano detectados: {cortes}")
    if encp.returncode != 0:
        sys.exit("FFmpeg no pudo codificar la salida")


if __name__ == "__main__":
    main()
