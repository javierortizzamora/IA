# Evaluación: restauración facial por tamaño (Antena 3 Noticias, 28-09-1992)

Datos y scripts del artículo *Size-aware face restoration for 4K remastering of archival television: a reproducible case study on a 1992 Spanish newscast* (Javier Ortiz Zamora, Universidad de Alicante).

No se incluye material audiovisual: los derechos de la emisión pertenecen a Atresmedia.

## Variantes evaluadas (programa completo, 3 min 31 s, 25 fps)

| Nombre | Configuración |
|---|---|
| `A-lanczos` | Escalado Lanczos, sin IA |
| `B-general` | Real-ESRGAN `realesr-general-x4v3`, denoise 0,5 |
| `D-unif` | B + CodeFormer (w = 0,85) en todas las caras |
| `D20-60`, `D40-90`, `D60-120` | B + CodeFormer con mezcla por tamaño de cara (umbrales en px del original) |

Las variantes se generan con `../experimento_articulo.command` (usa `../remaster4k.py`). Los tiempos de cálculo están en `../registro_tiempos.csv`.

## Scripts (`scripts/`)

- `caras.py`: detecta caras con RetinaFace en uno de cada cinco fotogramas del original y guarda sus cajas → `datos/caras_original.json`.
- `difs.py`: reproduce el detector de cortes de RIFE (diferencia media entre fotogramas en 4K) → `datos/dif4k.csv`.
- `extraer.py`: extrae de cada variante fotogramas (1 cada 2 s, 1470×1080) y recortes de caras.
- `metricas.py`: NIQE, MUSIQ y CLIP-IQA por fotograma; TOPIQ-face, similitud ArcFace con el original y energía de textura por cara.
- `temporal.py`, `temporal_siguiente.sh`: error de deformación temporal con flujo óptico DIS calculado sobre el original, global y dentro de las caras.
- `tramos.py`, `tramos_met.py`: comparación con x4plus en el tramo 1:40–1:50 y en la cortinilla.
- `analisis.py`: tablas de resultados con intervalos de confianza bootstrap → `datos/resultados.json`.

## Datos (`datos/`)

- `transiciones.csv`: anotación manual de las 13 transiciones del programa.
- `caras_original.json`: cajas de cara por fotograma (coordenadas del recorte 626×460).
- `res_frames_*.csv`, `res_caras_*.csv`, `temporal2_*.csv`, `res_tramos.csv`: medidas por variante.
- `resultados.json`: resumen usado en las tablas del artículo.

Correspondencia de índices: el fotograma `k` de las salidas 4K corresponde al fotograma `k + 1` del original.
