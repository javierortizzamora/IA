#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
remaster4k.py — Remasterización de vídeo de archivo de TV a 4K con IA (Apple Silicon)

Pensado para emisiones PAL antiguas (576i/480p): desentrelaza a 50p real,
escala con Real-ESRGAN, restaura caras con CodeFormer (opcional) y entrega
3840x2160 conservando la relación de aspecto original (4:3 con bandas o
recorte a 16:9). No escribe fotogramas temporales: todo va por tuberías.

Uso rápido:
    python remaster4k.py                       (te pide el vídeo)
    python remaster4k.py video.mp4 --prueba 10 (solo 10 s para ajustar)
    python remaster4k.py video.mp4 --modo caras --w 0.85
    python remaster4k.py video.mp4 --comparar  (los 4 métodos sobre el mismo tramo)

Modos:
    lanczos  línea base sin IA (solo FFmpeg)
    general  Real-ESRGAN realesr-general-x4v3 (recomendado para vídeo real)
    x4plus   Real-ESRGAN RealESRGAN_x4plus (más "pintado", más lento)
    caras    general + CodeFormer en rostros (necesita la carpeta CodeFormer)
"""

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
PESOS = AQUI / "pesos"
LOG_CSV = AQUI / "registro_tiempos.csv"

URLS = {
    "general": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
    "general_wdn": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth",
    "x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "codeformer": "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth",
}

UHD_W, UHD_H = 3840, 2160


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

def aviso(msg):
    print(f"  · {msg}", flush=True)


def error(msg):
    print(f"\n[ERROR] {msg}\n", file=sys.stderr, flush=True)
    sys.exit(1)


def limpiar_ruta(texto):
    """Ruta arrastrada a Terminal: quita comillas y escapes de espacios."""
    t = texto.strip()
    if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
        t = t[1:-1]
    t = re.sub(r"\\(.)", r"\1", t)  # "Mi\ video.mp4" -> "Mi video.mp4"
    return os.path.expanduser(t)


def descargar(nombre):
    PESOS.mkdir(exist_ok=True)
    url = URLS[nombre]
    destino = PESOS / url.rsplit("/", 1)[1]
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    aviso(f"Descargando pesos {destino.name} (solo la primera vez)…")
    import urllib.request
    tmp = destino.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(destino)
    return destino


def ffprobe_json(ruta):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(ruta)])
    return json.loads(out)


def info_video(ruta):
    d = ffprobe_json(ruta)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        error("El archivo no tiene pista de vídeo.")
    tiene_audio = any(s["codec_type"] == "audio" for s in d["streams"])
    fps = Fraction(v.get("avg_frame_rate") or v.get("r_frame_rate") or "25/1")
    if fps == 0:
        fps = Fraction(v.get("r_frame_rate", "25/1"))
    w, h = int(v["width"]), int(v["height"])
    sar = v.get("sample_aspect_ratio", "1:1")
    try:
        sn, sd = map(int, sar.split(":"))
        sar_f = Fraction(sn, sd) if sn and sd else Fraction(1)
    except Exception:
        sar_f = Fraction(1)
    dur = float(v.get("duration") or d["format"].get("duration") or 0)
    return {"w": w, "h": h, "fps": fps, "sar": sar_f, "dur": dur,
            "audio": tiene_audio, "field_order": v.get("field_order", "unknown"),
            "codec": v.get("codec_name", "?")}


def detectar_entrelazado(ruta, inicio, field_order="unknown"):
    """Usa el filtro idet de FFmpeg sobre ~600 fotogramas; si no concluye,
    se fía de la etiqueta del archivo."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if inicio:
        cmd += ["-ss", str(inicio)]
    cmd += ["-i", str(ruta), "-frames:v", "600", "-vf", "idet", "-an", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.findall(r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)", r.stderr)
    etiqueta = field_order in ("tt", "bb", "tb", "bt")
    if not m:
        return etiqueta, f"sin análisis, etiqueta={field_order}"
    tff, bff, prog = map(int, m[-1])
    detalle = f"TFF={tff} BFF={bff} progresivo={prog}"
    if tff + bff + prog < 20:  # imagen fija o muy corta: no concluyente
        return etiqueta, detalle + f" (no concluyente, etiqueta={field_order})"
    return (tff + bff) > prog, detalle


def detectar_recorte(ruta, inicio, dur):
    """Detecta bandas negras (p. ej. vídeo 4:3 subido a YouTube en 16:9)."""
    punto = (inicio or 0) + max(1.0, min(30.0, (dur or 60) / 3))
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{punto:.2f}", "-i", str(ruta),
           "-frames:v", "150", "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return None
    return tuple(map(int, m[-1]))


def elegir_dispositivo(forzar=None):
    import torch
    if forzar:
        return torch.device(forzar)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def elegir_encoder(prores):
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True).stdout
    if prores:
        if "prores_videotoolbox" in encoders:
            return ["-c:v", "prores_videotoolbox", "-profile:v", "hq", "-pix_fmt", "p210le"], ".mov"
        return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"], ".mov"
    if "hevc_videotoolbox" in encoders and platform.system() == "Darwin":
        return ["-c:v", "hevc_videotoolbox", "-b:v", "50M",
                "-tag:v", "hvc1", "-pix_fmt", "yuv420p"], ".mp4"
    return ["-c:v", "libx265", "-crf", "16", "-preset", "medium",
            "-tag:v", "hvc1", "-pix_fmt", "yuv420p"], ".mp4"


# ----------------------------------------------------------------------------
# Redes (arquitecturas de Real-ESRGAN, escritas aquí para no depender de basicsr)
# ----------------------------------------------------------------------------

def construir_redes():
    import torch
    from torch import nn
    from torch.nn import functional as F

    class SRVGGNetCompact(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4):
            super().__init__()
            self.upscale = upscale
            self.body = nn.ModuleList()
            self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
            for _ in range(num_conv):
                self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
                self.body.append(nn.PReLU(num_parameters=num_feat))
            self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
            self.upsampler = nn.PixelShuffle(upscale)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            out = self.upsampler(out)
            return out + F.interpolate(x, scale_factor=self.upscale, mode="nearest")

    class ResidualDenseBlock(nn.Module):
        def __init__(self, nf=64, gc=32):
            super().__init__()
            self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
            self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
            self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
            self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
            self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, nf, gc=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock(nf, gc)
            self.rdb2 = ResidualDenseBlock(nf, gc)
            self.rdb3 = ResidualDenseBlock(nf, gc)

        def forward(self, x):
            return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self, nf=64, nb=23, gc=32):
            super().__init__()
            self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
            self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, inplace=True)

        def forward(self, x):
            feat = self.conv_first(x)
            feat = feat + self.conv_body(self.body(feat))
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(feat)))

    return SRVGGNetCompact, RRDBNet


def cargar_estado(ruta):
    import torch
    ck = torch.load(ruta, map_location="cpu", weights_only=True)
    for k in ("params_ema", "params"):
        if k in ck:
            return ck[k]
    return ck


class Escalador:
    """Real-ESRGAN x4 sobre fotogramas BGR uint8, con troceado opcional."""

    def __init__(self, modelo, device, denoise=0.5, tile=0, fp16=False):
        import torch
        SRVGG, RRDBNet = construir_redes()
        self.torch = torch
        self.device = device
        self.tile = tile
        self.pad = 10
        self.dtype = torch.float16 if fp16 else torch.float32

        if modelo == "x4plus":
            net = RRDBNet()
            net.load_state_dict(cargar_estado(descargar("x4plus")), strict=True)
            if not tile:
                self.tile = 256 if device.type != "cuda" else 0
        else:
            net = SRVGG()
            a = cargar_estado(descargar("general"))
            if denoise > 0:
                b = cargar_estado(descargar("general_wdn"))
                # denoise=0 -> modelo general puro; denoise=1 -> variante con más limpieza
                a = {k: (1 - denoise) * a[k] + denoise * b[k] for k in a}
            net.load_state_dict(a, strict=True)
        self.net = net.eval().to(device=device, dtype=self.dtype)

    def _infer(self, t):
        return self.net(t)

    def __call__(self, bgr):
        torch = self.torch
        rgb = bgr[:, :, ::-1].copy()
        t = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
        t = t.to(self.device, dtype=self.dtype) / 255.0
        with torch.no_grad():
            if not self.tile:
                out = self._infer(t)
            else:
                out = self._troceado(t)
        out = out.clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)
        out = out.squeeze(0).permute(1, 2, 0).cpu().numpy()
        return np.ascontiguousarray(out[:, :, ::-1])

    def _troceado(self, t):
        torch = self.torch
        _, c, h, w = t.shape
        s, ts, p = 4, self.tile, self.pad
        out = torch.zeros((1, c, h * s, w * s), device=t.device, dtype=t.dtype)
        for y0 in range(0, h, ts):
            for x0 in range(0, w, ts):
                y1, x1 = min(y0 + ts, h), min(x0 + ts, w)
                py0, px0 = max(y0 - p, 0), max(x0 - p, 0)
                py1, px1 = min(y1 + p, h), min(x1 + p, w)
                o = self._infer(t[:, :, py0:py1, px0:px1])
                oy, ox = (y0 - py0) * s, (x0 - px0) * s
                out[:, :, y0 * s:y1 * s, x0 * s:x1 * s] = \
                    o[:, :, oy:oy + (y1 - y0) * s, ox:ox + (x1 - x0) * s]
        return out


class RestauradorCaras:
    """CodeFormer: detecta, restaura a 512 px y pega sobre el fondo escalado."""

    def __init__(self, device, w=0.85, escala=4, cara_min=40, cara_plena=90):
        cf = AQUI / "CodeFormer"
        if not cf.is_dir():
            error("Falta la carpeta CodeFormer junto al script. Ejecuta instalar.sh de nuevo.")
        sys.path.insert(0, str(cf))
        # Paquete basicsr "ligero": evita su __init__, que arrastra dependencias
        # de entrenamiento (lpips, etc.) que no hacen falta para inferencia.
        import types
        if "basicsr" not in sys.modules:
            pkg = types.ModuleType("basicsr")
            pkg.__path__ = [str(cf / "basicsr")]
            sys.modules["basicsr"] = pkg
        import torch
        from torchvision.transforms.functional import normalize
        from basicsr.utils import img2tensor, tensor2img
        from basicsr.utils.registry import ARCH_REGISTRY
        import basicsr.archs.codeformer_arch  # noqa: F401  (registra CodeFormer)
        from facelib.utils.face_restoration_helper import FaceRestoreHelper

        self.torch, self.normalize = torch, normalize
        self.img2tensor, self.tensor2img = img2tensor, tensor2img
        self.w = w
        # La detección de caras va en CPU si MPS da problemas con alguna operación
        self.device = device
        net = ARCH_REGISTRY.get("CodeFormer")(
            dim_embd=512, codebook_size=1024, n_head=8, n_layers=9,
            connect_list=["32", "64", "128", "256"])
        net.load_state_dict(cargar_estado(descargar("codeformer")))
        self.net = net.eval().to(device)
        self.helper = FaceRestoreHelper(
            escala, face_size=512, crop_ratio=(1, 1), det_model="retinaface_resnet50",
            save_ext="png", use_parse=True, device=device)
        self.n_caras = 0
        # Protección contra "caras de cera" en planos lejanos: según el ancho de la
        # cara en el original, CodeFormer no se aplica (< cara_min px), se mezcla
        # de forma gradual, o se aplica entero (>= cara_plena px).
        self.escala = escala
        self.cara_min, self.cara_plena = cara_min, max(cara_plena, cara_min + 1)
        self.stats = {"omitidas": 0, "parciales": 0, "plenas": 0}

    def _peso(self, ancho):
        a = (ancho - self.cara_min) / (self.cara_plena - self.cara_min)
        return float(min(max(a, 0.0), 1.0))

    def __call__(self, bgr, fondo_escalado):
        torch, h = self.torch, self.helper
        h.clean_all()
        h.read_image(bgr)
        n = h.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
        if n == 0:
            return fondo_escalado
        self.n_caras += n
        # facelib amplía internamente las imágenes de menos de 512 px de alto:
        # f es ese factor, para volver a las coordenadas del original.
        f = h.input_img.shape[0] / bgr.shape[0]
        pesos = [self._peso(float(b[2] - b[0]) / f) for b in h.det_faces]
        for p_ in pesos:
            self.stats["omitidas" if p_ <= 0 else "plenas" if p_ >= 1 else "parciales"] += 1
        if max(pesos) <= 0:
            return fondo_escalado
        h.align_warp_face()
        for cara, p_ in zip(h.cropped_faces, pesos):
            if p_ <= 0:
                h.add_restored_face(cara, cara)  # se descarta luego con peso 0
                continue
            t = self.img2tensor(cara / 255.0, bgr2rgb=True, float32=True)
            self.normalize(t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
            t = t.unsqueeze(0).to(self.device)
            with torch.no_grad():
                o = self.net(t, w=self.w, adain=True)[0]
            restaurada = self.tensor2img(o, rgb2bgr=True, min_max=(-1, 1)).astype("uint8")
            h.add_restored_face(restaurada, cara)
        h.get_inverse_affine(None)
        import cv2
        H, W = fondo_escalado.shape[:2]
        pegada = h.paste_faces_to_input_image(upsample_img=fondo_escalado.copy(), draw_box=False)
        if pegada.shape[:2] != (H, W):
            pegada = cv2.resize(pegada, (W, H), interpolation=cv2.INTER_AREA)
        pegada = pegada[:, :, :3].astype(np.uint8)
        # Mapa de mezcla: solo las zonas de cara salen de "pegada"; el resto del
        # plató queda exactamente como lo dejó Real-ESRGAN. Bordes suavizados.
        mapa = np.zeros((H, W), np.float32)
        s = self.escala / f
        for b, p_ in zip(h.det_faces, pesos):
            if p_ <= 0:
                continue
            x1, y1, x2, y2 = (float(v) * s for v in b[:4])
            mx, my = (x2 - x1) * 0.25, (y2 - y1) * 0.25
            xa, ya = int(max(x1 - mx, 0)), int(max(y1 - my, 0))
            xb, yb = int(min(x2 + mx, W)), int(min(y2 + my, H))
            mapa[ya:yb, xa:xb] = np.maximum(mapa[ya:yb, xa:xb], p_)
        k = int(max(H, W) * 0.01) | 1
        mapa = cv2.GaussianBlur(mapa, (k * 4 + 1, k * 4 + 1), 0)[..., None]
        out = fondo_escalado.astype(np.float32) * (1 - mapa) + pegada.astype(np.float32) * mapa
        return np.clip(out + 0.5, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------
# Proceso
# ----------------------------------------------------------------------------

def cadena_salida(dar, encuadre):
    """Filtros FFmpeg para llevar la imagen a 3840x2160 con el aspecto correcto."""
    if encuadre == "169":
        # Recorte central a 16:9 (se pierde parte de arriba y abajo)
        return (f"scale={UHD_W}:-2:flags=lanczos,setsar=1,"
                f"crop={UHD_W}:{UHD_H},setsar=1")
    w_img = int(round(UHD_H * dar / 2) * 2)
    w_img = min(w_img, UHD_W)
    return (f"scale={w_img}:{UHD_H}:flags=lanczos,setsar=1,"
            f"pad={UHD_W}:{UHD_H}:(ow-iw)/2:0:black,setsar=1")


def preparar(args, ruta):
    inf = info_video(ruta)
    aviso(f"Original: {inf['w']}x{inf['h']}, {float(inf['fps']):.3f} fps, "
          f"códec {inf['codec']}, {inf['dur']:.1f} s")

    # Desentrelazado
    if args.desentrelazar == "auto":
        ent, detalle = detectar_entrelazado(ruta, args.inicio, inf["field_order"])
        aviso(f"Análisis de entrelazado: {detalle} -> {'ENTRELAZADO' if ent else 'progresivo'}")
    else:
        ent = args.desentrelazar == "si"
    filtros = []
    fps_out = inf["fps"]
    if ent:
        filtros.append("bwdif=mode=send_field:parity=auto:deint=all")
        fps_out = inf["fps"] * 2
        aviso(f"Desentrelazado a doble tasa: {float(fps_out):.2f} fps progresivos reales")
    elif float(inf["fps"]) < 30:
        aviso("El vídeo ya es progresivo: no se pueden recuperar 50 fps reales "
              "(los campos se perdieron al convertirlo).")

    # Recorte de bandas negras
    w, h = inf["w"], inf["h"]
    crop = None
    if args.recorte == "auto":
        crop = detectar_recorte(ruta, args.inicio, inf["dur"])
        if crop and (crop[0] < w - 8 or crop[1] < h - 8):
            aviso(f"Bandas negras detectadas: recorto a {crop[0]}x{crop[1]}")
        else:
            crop = None
    if crop:
        filtros.append(f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}")
        w, h = crop[0], crop[1]

    # Aspecto de visualización (PAL 720x576 con SAR 16:15 -> 4:3)
    if args.aspecto:
        a, b = map(int, args.aspecto.split(":"))
        dar = Fraction(a, b)
    else:
        dar = Fraction(w, h) * inf["sar"]
    aviso(f"Aspecto de pantalla: {float(dar):.3f} ({'4:3' if abs(float(dar) - 4/3) < 0.03 else 'otro'})")

    return inf, filtros, fps_out, w, h, dar


def entradas_tramo(args):
    t = []
    if args.inicio:
        t += ["-ss", str(args.inicio)]
    if args.prueba:
        t += ["-t", str(args.prueba)]
    return t


def procesar(args, ruta, modo, salida):
    print(f"\n=== Modo: {modo} ===", flush=True)
    # Se escribe en un archivo ".parcial" y solo se renombra al terminar bien,
    # para que un corte (antivirus, reposo, Ctrl+C) nunca deje un archivo que
    # parezca completo.
    final = salida
    salida = final.with_name(final.stem + ".parcial" + final.suffix)
    inf, filtros, fps_out, w, h, dar = preparar(args, ruta)
    enc, _ = elegir_encoder(args.prores)
    vf_final = cadena_salida(dar, args.encuadre)
    tramo = entradas_tramo(args)

    audio_map = ["-map", "1:a:0?", "-c:a", "aac", "-b:a", "256k"] if inf["audio"] else []
    t0 = time.time()
    n_frames = 0
    disp = "ffmpeg"

    if modo == "lanczos":
        vf = ",".join(filtros + [vf_final])
        cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y"]
               + tramo + ["-i", str(ruta)] + tramo + ["-i", str(ruta),
               "-map", "0:v:0", "-vf", vf, "-r", str(fps_out)] + enc + audio_map
               + ["-movflags", "+faststart", str(salida)])
        subprocess.run(cmd, check=True)
        n_frames = int(round(float(fps_out) * (args.prueba or inf["dur"])))
    else:
        import torch
        device = elegir_dispositivo(args.dispositivo)
        disp = device.type
        aviso(f"Dispositivo de cálculo: {disp.upper()}"
              + (" (GPU Apple Silicon, Metal)" if disp == "mps" else ""))
        modelo = "x4plus" if modo == "x4plus" else "general"
        esc = Escalador(modelo, device, denoise=args.denoise, tile=args.tile, fp16=args.fp16)
        caras = RestauradorCaras(device, w=args.w, cara_min=args.cara_min,
                                 cara_plena=args.cara_plena) if modo == "caras" else None

        vf_in = ",".join(filtros + ["format=bgr24"])
        dec = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error"] + tramo
            + ["-i", str(ruta), "-map", "0:v:0", "-vf", vf_in, "-fps_mode", "passthrough",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=w * h * 3 * 4)
        W4, H4 = w * 4, h * 4
        enc_cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W4}x{H4}",
                    "-framerate", str(fps_out), "-i", "-"]
                   + tramo + ["-i", str(ruta), "-map", "0:v:0", "-vf", vf_final]
                   + enc + audio_map + ["-shortest", "-movflags", "+faststart", str(salida)])
        encp = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

        total = int(round(float(fps_out) * (args.prueba or max(inf["dur"] - (args.inicio or 0), 0))))
        try:
            from tqdm import tqdm
            barra = tqdm(total=total or None, unit="fot", desc="Escalando", dynamic_ncols=True)
        except ImportError:
            barra = None
        tam = w * h * 3
        interrumpido = False
        try:
            while True:
                buf = dec.stdout.read(tam)
                if not buf or len(buf) < tam:
                    break
                img = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                out = esc(img)
                if caras is not None:
                    out = caras(img, out)
                if out.shape[:2] != (H4, W4):
                    # Salvaguarda: un fotograma de otro tamaño corrompería todo el vídeo
                    import cv2
                    out = cv2.resize(out, (W4, H4), interpolation=cv2.INTER_AREA)
                encp.stdin.write(np.ascontiguousarray(out).tobytes())
                n_frames += 1
                if barra:
                    barra.update(1)
                elif n_frames % 25 == 0:
                    el = time.time() - t0
                    print(f"\r  {n_frames}/{total} fotogramas · {n_frames/el:.2f} fps", end="", flush=True)
        except KeyboardInterrupt:
            interrumpido = True
            print("\nInterrumpido: cierro el archivo con lo procesado hasta ahora.")
        finally:
            if barra:
                barra.close()
            err_dec = dec.stderr.read().decode("utf-8", "replace").strip()
            dec.stdout.close()
            dec.wait()
            encp.stdin.close()
            encp.wait()
        if interrumpido:
            error(f"Proceso interrumpido. Lo hecho queda en {salida.name}; "
                  "al relanzar se repetirá este paso.")
        if n_frames == 0:
            error("FFmpeg no entregó ningún fotograma a la IA.\n" + (err_dec or "(sin mensaje)"))
        if encp.returncode != 0:
            error("FFmpeg no pudo codificar la salida.")
        if caras is not None:
            st = caras.stats
            aviso(f"Caras detectadas: {caras.n_caras} · CodeFormer pleno: {st['plenas']} · "
                  f"mezclado: {st['parciales']} · omitido por pequeñas: {st['omitidas']}")

    seg = time.time() - t0
    vel = n_frames / seg if seg else 0
    dur_out = n_frames / float(fps_out) if fps_out else 0
    ratio = seg / dur_out if dur_out else 0
    os.replace(salida, final)
    salida = final
    print(f"\n  ✓ {salida.name}")
    print(f"    {n_frames} fotogramas en {seg/60:.1f} min · {vel:.2f} fot/s · "
          f"{ratio:.1f} min de cálculo por minuto de vídeo")

    nuevo = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        wcsv = csv.writer(f)
        if nuevo:
            wcsv.writerow(["fecha", "archivo", "modo", "salida", "fotogramas", "fps_salida",
                           "segundos_calculo", "fot_por_s", "min_calculo_por_min_video",
                           "dispositivo", "denoise", "w_codeformer", "encuadre", "maquina"])
        wcsv.writerow([dt.datetime.now().isoformat(timespec="seconds"), Path(ruta).name, modo,
                       salida.name, n_frames, f"{float(fps_out):.3f}", f"{seg:.1f}", f"{vel:.3f}",
                       f"{ratio:.2f}", disp, args.denoise if modo in ("general", "caras") else "",
                       args.w if modo == "caras" else "", args.encuadre,
                       f"{platform.machine()} {platform.processor()}".strip()])
    return salida


def main():
    p = argparse.ArgumentParser(description="Remasterización de archivo de TV a 4K con IA")
    p.add_argument("video", nargs="?", help="Vídeo de entrada (si no, se pide)")
    p.add_argument("--modo", choices=["lanczos", "general", "x4plus", "caras"], default="caras")
    p.add_argument("--comparar", action="store_true",
                   help="Ejecuta los cuatro modos sobre el mismo tramo")
    p.add_argument("--prueba", type=float, default=0, help="Segundos a procesar (0 = todo)")
    p.add_argument("--inicio", type=float, default=0, help="Segundo de inicio")
    p.add_argument("--w", type=float, default=0.85,
                   help="Fidelidad de CodeFormer (0 = inventa, 1 = fiel). Recomendado 0.8–0.9")
    p.add_argument("--cara-min", type=int, default=40,
                   help="Ancho de cara (px del original) por debajo del cual no se usa CodeFormer")
    p.add_argument("--cara-plena", type=int, default=90,
                   help="Ancho de cara a partir del cual CodeFormer se aplica entero")
    p.add_argument("--saltar-hechos", action="store_true",
                   help="No repetir las salidas que ya existen completas")
    p.add_argument("--denoise", type=float, default=0.5,
                   help="Limpieza de ruido del modelo general (0 = nada, 1 = máxima)")
    p.add_argument("--desentrelazar", choices=["auto", "si", "no"], default="auto")
    p.add_argument("--recorte", choices=["auto", "no"], default="auto",
                   help="Quitar bandas negras detectadas")
    p.add_argument("--aspecto", help="Forzar aspecto de pantalla, p. ej. 4:3")
    p.add_argument("--encuadre", choices=["43", "169"], default="43",
                   help="43 = imagen completa con bandas; 169 = recorte a pantalla completa")
    p.add_argument("--prores", action="store_true", help="Salida ProRes 422 HQ (.mov) para editar")
    p.add_argument("--tile", type=int, default=0, help="Tamaño de trozo (0 = automático)")
    p.add_argument("--fp16", action="store_true", help="Media precisión (más rápido, prueba antes)")
    p.add_argument("--dispositivo", choices=["mps", "cpu", "cuda"])
    args = p.parse_args()

    print("=" * 64)
    print("   REMASTER 4K · archivo de televisión · Real-ESRGAN + CodeFormer")
    print("=" * 64)

    if not shutil.which("ffmpeg"):
        error("No encuentro FFmpeg. Instálalo con:  brew install ffmpeg")

    ruta = args.video or input("\nArrastra aquí el vídeo y pulsa Enter: ")
    ruta = Path(limpiar_ruta(ruta))
    if not ruta.is_file():
        error(f"No existe el archivo: {ruta}")

    _, ext = elegir_encoder(args.prores)
    sufijo_tramo = f"_t{args.inicio:g}-{args.inicio + args.prueba:g}s" if args.prueba else ""
    modos = ["lanczos", "general", "x4plus", "caras"] if args.comparar else [args.modo]
    if args.comparar and not args.prueba:
        aviso("Consejo: con --comparar usa --prueba 10 para no tardar horas.")

    salidas = []
    for m in modos:
        extra = f"_w{args.w}_c{args.cara_min}-{args.cara_plena}" if m == "caras" else ""
        salida = ruta.with_name(f"{ruta.stem}_4K_{m}{extra}{sufijo_tramo}{ext}")
        if args.saltar_hechos and salida.exists() and salida.stat().st_size > 1_000_000:
            aviso(f"Ya existe, lo salto: {salida.name}")
            continue
        salidas.append(procesar(args, ruta, m, salida))

    print("\n" + "=" * 64)
    print("LISTO. Archivos en la misma carpeta que el original:")
    for s in salidas:
        print(f"  -> {s}")
    print(f"Tiempos registrados en: {LOG_CSV}")
    print("=" * 64)


if __name__ == "__main__":
    main()
