# Remasterización 4K de Antena 3 Noticias con IA abierta

Código y documentación del remaster del informativo de Antena 3 (28-09-1992), con Real-ESRGAN, CodeFormer y RIFE, ejecutado en local sobre Apple Silicon.

- `remaster4k.py`: proceso principal (modos lanczos, general, x4plus y caras).
- `rife/acabado50.py` y `rife/rife_arch.py`: interpolación 25 → 50 fps, acabado de color y audio.
- `filtro_original.py`: reproduce el mismo recorte y aspecto sobre el original para la comparativa.
- `registro_tiempos.csv`: tiempos medidos de cada ejecución.
- `experimento_articulo.command`: genera las variantes evaluadas en el artículo (ver `evaluacion/`).
- `Informe_tecnico_remaster_Antena3_1992.pdf`: informe técnico con alternativas, pipeline y referencias.

Los pesos de los modelos no se incluyen; se descargan de sus repositorios oficiales (ver `URLS` en `remaster4k.py`).

Licencias: CodeFormer (S-Lab) solo para uso no comercial; Real-ESRGAN (BSD-3-Clause); RIFE (MIT).
