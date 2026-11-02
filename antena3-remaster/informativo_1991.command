#!/bin/bash
# Antena 3 Noticias 12-9-1991 (0:00-4:00): IA general + caras, 50 fps con RIFE y comparativa antes/después.
# Si algo lo corta (antivirus, reposo), vuelve a hacer doble clic: retoma lo pendiente.
cd "$(dirname "$0")"
source venv/bin/activate
LOG="registro_ejecucion.txt"
ORIG="Antena3_Noticias_1991_tramo_0-4min_640x480.mp4"
ESC="Antena3_Noticias_1991_tramo_0-4min_640x480_4K_caras_w0.85_c40-90.mp4"
DEF="Antena3_Noticias_1991_remaster_4K50_DEFINITIVO.mp4"
CMP="Antena3_Noticias_1991_ANTES_DESPUES_4K50.mp4"
caffeinate -dims -w $$ &

# Da por bueno un .parcial completo (la duración coincide con el original) y le pone su nombre
cerrar() {
  local fin="$1" par="$1.parcial.mp4"
  [ -s "$fin" ] && return 0
  [ -s "$par" ] || return 1
  local d0 d1
  d0=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$ORIG")
  d1=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$par" 2>/dev/null)
  if python -c "import sys; sys.exit(0 if abs(float('$d1' or 0)-float('$d0'))<0.5 else 1)"; then
    mv -f "$par" "$fin"; echo "✓ $fin"; return 0
  fi
  return 1
}

echo; echo "########## $(date '+%H:%M:%S')  1991 · 1/3 escalado con IA y caras" | tee -a "$LOG"
python remaster4k.py "$ORIG" --saltar-hechos --modo caras 2>&1 | tee -a "$LOG"
[ -s "$ESC" ] || { echo "Falta $ESC: vuelve a lanzar."; read -p "Enter…"; exit 1; }

echo; echo "########## $(date '+%H:%M:%S')  1991 · 2/3 50 fps con RIFE y acabado" | tee -a "$LOG"
if ! cerrar "$DEF"; then
  python rife/acabado50.py "$ESC" "$ORIG" "$DEF.parcial.mp4" 2>&1 | tee -a "$LOG"
  cerrar "$DEF" || { echo "El paso 2 no terminó: vuelve a lanzar."; read -p "Enter…"; exit 1; }
fi

echo; echo "########## $(date '+%H:%M:%S')  1991 · 3/3 comparativa antes/después" | tee -a "$LOG"
if ! cerrar "$CMP"; then
  FO=$(python filtro_original.py "$ORIG")
  echo "Encuadre del original: $FO"
  ffmpeg -hide_banner -loglevel error -stats -y -i "$ORIG" -i "$DEF" -filter_complex \
  "[0:v]$FO,fps=50,crop=1920:2160:0:0[a];[1:v]setsar=1,crop=1920:2160:1920:0[b];[a][b]hstack,drawbox=x=1918:y=0:w=4:h=2160:color=white@0.9:t=fill,format=yuv420p[v]" \
  -map "[v]" -map 1:a -c:v hevc_videotoolbox -b:v 60M -tag:v hvc1 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a copy -shortest -movflags +faststart "$CMP.parcial.mp4"
  cerrar "$CMP" || echo "La comparativa no terminó: vuelve a lanzar."
fi
echo; echo "== Terminado $(date '+%H:%M:%S'). Avísale a Claude." | tee -a "$LOG"
read -p "Pulsa Enter para cerrar…"
