#!/bin/bash
# Vídeo comparativo antes/después de «Sábado Cine» (web, ligero).
# Arriba: original 720p. Abajo: versión final 4K reducida a 720p. Con el audio final.
cd "$(dirname "$0")"
ORIG="S_BADO_CINE_CABECERA_1989_16_9.mp4"
NEW="S_BADO_CINE_1989_4K60_FINAL_DEFINITIVO.mp4"
OUT="_temporales_web/sabado_cine_v2/antes-despues.mp4"
if [ ! -s "$ORIG" ] || [ ! -s "$NEW" ]; then echo "Faltan $ORIG o $NEW en esta carpeta."; read -p "Enter…"; exit 1; fi
mkdir -p "_temporales_web/sabado_cine_v2"
echo "== Generando comparativo antes/después (puede tardar varios minutos)…"
ffmpeg -y -i "$ORIG" -i "$NEW" -filter_complex \
"[0:v]scale=1280:720,drawtext=text='Original':fontcolor=white:fontsize=36:x=20:y=20:box=1:boxcolor=black@0.6:boxborderw=10[top];\
[1:v]scale=1280:720,drawtext=text='4K IA (version final)':fontcolor=white:fontsize=36:x=20:y=20:box=1:boxcolor=black@0.6:boxborderw=10[bot];\
[top][bot]vstack=inputs=2[v]" \
-map "[v]" -map 1:a:0 -c:v libx264 -preset medium -crf 25 -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart "$OUT"
if [ $? -eq 0 ]; then
  echo "== Listo: $OUT"
  ls -la "$OUT"
else
  echo "== Error al generar el vídeo."
fi
read -p "Pulsa Enter para cerrar…"
