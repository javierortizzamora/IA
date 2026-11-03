#!/bin/bash
# Uso: temporal_siguiente.sh "<archivo variante>" <nombre>. Ejecuta el siguiente trozo pendiente.
cd "$(dirname "$0")/.."
F="$1"; N="$2"; HECHO="articulo_datos/temporal2_$N.hecho"; touch "$HECHO"
for j in 0 1 2 3 4; do
  grep -qx "$j" "$HECHO" && continue
  timeout 172 python3 articulo_datos/temporal.py "$F" $((j*1099)) 1101 "articulo_datos/temporal2_$N.csv.$j" && mv "articulo_datos/temporal2_$N.csv.$j" "articulo_datos/temporal2_$N.part$j" && echo "$j" >> "$HECHO"
  echo "trozo $j de $N"; exit 0
done
cat articulo_datos/temporal2_$N.part* > "articulo_datos/temporal2_$N.csv"; echo "COMPLETO $N"
