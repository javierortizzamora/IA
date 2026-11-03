#!/bin/bash
# EXPERIMENTO PARA EL ARTÍCULO (informativo de 1992 completo, 25 fps, sin interpolar).
# Genera las variantes que faltan para comparar con el método final ya hecho (caras 40-90).
# Tarda unas 5-6 horas. Si algo lo corta, vuelve a hacer doble clic: salta lo terminado.
cd "$(dirname "$0")"
source venv/bin/activate
V="Antena 3 Noticias 28-09-1992.mp4"
LOG="registro_experimento.txt"
caffeinate -dims -w $$ &
paso() {
  echo; echo "########## $(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$LOG"
  python remaster4k.py "$V" --saltar-hechos "$@" 2>&1 | tee -a "$LOG"
}
# 1) Referencia sin IA (Lanczos) y super-resolución general sin caras (B)
paso --modo lanczos
paso --modo general
# 2) CodeFormer UNIFORME: en todas las caras, sin control por tamaño (la variante clave)
paso --modo caras --cara-min 0 --cara-plena 1
# 3) Umbrales alternativos del control por tamaño (sensibilidad)
paso --modo caras --cara-min 20 --cara-plena 60
paso --modo caras --cara-min 60 --cara-plena 120
echo; echo "== Terminado $(date '+%H:%M:%S'). Avísale a Claude." | tee -a "$LOG"
read -p "Pulsa Enter para cerrar…"
