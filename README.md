# Padel Vision Analytics

Sistema modular en Python para analizar videos de partidos de pádel grabados
con cámara fija: calibración de pista, detección y seguimiento de jugadores
y pelota, proyección a vista cenital 2D, mapas de calor tácticos y
etiquetado de golpes. Se gestiona desde una **webapp local** (Flask) que
corre 100% en tu PC — no se sube nada a internet ni depende de GitHub Pages
(GitHub Pages sólo sirve archivos estáticos y no puede ejecutar Python/YOLO).

## Arquitectura del sistema de visión artificial

```
padel_analytics/
  config.py           Constantes: dimensiones de pista (20x10m), umbrales, rutas
  calibration.py       FASE 1 — CourtCalibrator: homografía cámara -> vista cenital
  tracking.py          FASE 2 — PadelTracker: YOLOv8 + ByteTrack + filtrado espacial + pelota
  coordinates.py        FASE 3 — CoordinateTransformer + AnalyticsEngine: proyección 2D + heatmaps
  shot_detection.py     Detección heurística de golpes + almacenamiento de etiquetas
  points.py              Marcado de inicio/fin de cada punto + ganador por pareja
  match_stats.py          Cruza puntos + golpes: WIN/LOSS por último toque, golpes por jugador
  identity.py              Limita el tracking a 4 jugadores estables (reidentificación espacial)
  shirt_color.py            Detecta el color de camiseta de cada jugador (nombre por defecto)
  player_names.py            Nombres de jugadores: color detectado, editables por el usuario
  rendering.py           FASE 4 — VideoRenderer: video doble panel + export CSV/JSON/heatmaps
  video_transcode.py       Re-codifica el video de salida a H.264 (compatible con el navegador)
  pipeline.py             Orquestador end-to-end de las 4 fases
  storage.py               Registro de videos/jobs (JSON, sin DB externa)
  video_io.py               Utilidades de lectura de video (metadata, extracción de frames)

webapp/
  server.py             App Flask: páginas + API REST
  jobs.py                Procesamiento en background (threading)
  templates/               Páginas HTML (subir, calibrar, resultados, etiquetar golpes)
  static/                    CSS + JS (canvas de calibración, reproductor, etiquetado)

run.py                  Punto de entrada: levanta el servidor y abre el navegador
```

## 1. Instalación

Requiere **Python 3.10+**.

```bash
git clone <este-repo>
cd Padel
python3 -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Dependencias instaladas (ver `requirements.txt`):

```
pip install ultralytics supervision opencv-python numpy pandas matplotlib Flask Werkzeug
```

> **GPU (opcional, recomendado):** si tenés GPU NVIDIA, instalá PyTorch con
> CUDA *antes* de correr `pip install -r requirements.txt`, siguiendo
> https://pytorch.org/get-started/locally/. Sin GPU, YOLOv8 corre en CPU
> (más lento, pero funciona igual).

La primera vez que se procese un video, `ultralytics` descarga automáticamente
los pesos `yolov8n.pt` (modelo pre-entrenado en COCO, detecta clases
`person` y `sports ball` sin necesidad de entrenar nada extra).

## 2. Levantar la webapp local

```bash
python run.py
```

Esto abre automáticamente `http://127.0.0.1:5000` en tu navegador. Si no
querés que se abra solo: `python run.py --no-browser`.

Todo el procesamiento (YOLOv8, tracking, homografía, rendering) corre en tu
propia PC; los videos y resultados se guardan en `data/`.

## 3. Flujo de uso paso a paso

1. **Subir video** (`/`): elegí un `.mp4` o `.mov` grabado con cámara fija
   que muestre la pista completa. Desde el listado también podés
   **Reprocesar** un video ya calibrado (por ejemplo, después de
   actualizar el código con `git pull`, para que los resultados se
   regeneren con la versión nueva) o **Eliminar** uno (borra el archivo
   subido y toda su carpeta de resultados — calibración, video anotado,
   golpes, puntos, nombres, heatmaps — sin vuelta atrás).
2. **Calibrar la pista** (`/video/<id>/calibrate` — FASE 1): se muestra un
   frame del video; hacé click en las 4 esquinas de la pista en el orden
   indicado (fondo-izq, fondo-der, frente-der, frente-izq). Esto calcula la
   homografía `cv2.getPerspectiveTransform` que se usa para toda la
   proyección 2D posterior.
3. **Procesar** (mismo página, una vez calibrado): dispara el pipeline de
   las FASES 2-4 en segundo plano — detección de jugadores/pelota con
   YOLOv8, tracking con ByteTrack, filtrado espacial por el polígono de la
   pista, proyección a metros reales y generación del video anotado. Una
   barra de progreso muestra el avance frame a frame.
4. **Resultados** (`/video/<id>/results` — FASE 4): video de doble panel
   (cámara anotada + minimapa 2D), heatmaps de ocupación por pareja y por
   jugador (click en cualquiera para verlo grande en un modal, con botón
   de volver), y descarga de la serie temporal en CSV/JSON.
5. **Jugadores** (`/video/<id>/players`): a cada jugador se le pone
   automáticamente de nombre por defecto el color de su camiseta
   ("Rojo", "Azul", etc.), detectado muestreando el color del torso
   durante el procesamiento (Fases 2-4). Desde esta página podés
   cambiarle el nombre a cualquiera de los 4 en cualquier momento — se
   usa en el selector de jugador al etiquetar golpes, en las
   estadísticas y en las leyendas de los heatmaps. Si reprocesás el
   video, los nombres que ya pusiste a mano no se pisan.
6. **Etiquetar golpes** (`/video/<id>/label`): lista los golpes detectados
   automáticamente por la heurística de trayectoria de la pelota (cambios
   bruscos de dirección cerca de un jugador) y permite corregirlos o
   agregar golpes manuales marcando el frame exacto sobre el reproductor
   de video, eligiendo jugador y tipo de golpe (derecha, revés, bandeja,
   víbora, smash, saque, etc.).
6. **Marcar puntos** (`/video/<id>/points`): mientras mirás el video, un
   botón "Marcar inicio de punto" registra el frame donde arranca el rally;
   cuando termina, "Marcar fin de punto" te pide elegir qué pareja lo ganó
   (y opcionalmente una nota). Sólo puede haber un punto abierto a la vez.
   La página muestra el marcador acumulado (puntos ganados por cada pareja),
   la duración promedio del rally, y la lista completa de puntos — cada uno
   clickeable para saltar el video a ese instante. Esto sirve para poder
   filtrar después cualquier otra analítica (posiciones, golpes, heatmaps)
   al rango de frames de un punto específico, sin tener que cortar el video
   en clips separados. Se puede usar en cualquier momento, no hace falta
   esperar a que termine el procesamiento de YOLOv8.
7. **Estadísticas** (`/video/<id>/stats`): cruza automáticamente los puntos
   marcados con los golpes registrados. Por cada punto cerrado, toma el
   golpe con el frame más alto dentro de su rango como "el último que tocó
   la pelota" y lo marca **WIN** si esa persona pertenecía a la pareja que
   ganó el punto (golpe ganador) o **LOSS** si pertenecía a la pareja que
   lo perdió (error propio, forzado o no forzado) — la misma convención que
   se usa en estadísticas de pádel/tenis. También muestra el conteo total
   de golpes por jugador (no hace falta haber marcado puntos para ver esto
   último). Para que se calculen los equipos y por lo tanto el WIN/LOSS,
   el video tiene que haber sido procesado al menos una vez (Fases 2-4);
   los golpes por jugador se calculan igual sin procesar, si los cargaste
   a mano.

## 4. Uso también como librería (sin la webapp)

Todo el sistema de visión artificial es utilizable directamente en un
script Python, por ejemplo en Jupyter/Colab:

```python
from padel_analytics.calibration import CourtCalibrator
from padel_analytics.pipeline import PadelAnalysisPipeline

# 1) Calibración manual (o cargar una guardada con CourtCalibrator.load(...))
calibrator = CourtCalibrator()
calibrator.set_image_points(
    points=[[120, 80], [980, 80], [1100, 620], [10, 620]],  # 4 esquinas en píxeles
    frame_width=1280, frame_height=720,
)
calibrator.save("data/outputs/mi_video/calibration.json", video_id="mi_video")

# 2) Pipeline completo (Fases 2-4)
pipeline = PadelAnalysisPipeline(
    video_path="mi_partido.mp4",
    calibrator=calibrator,
    video_id="mi_video",
)
result = pipeline.run(progress_cb=lambda cur, total, msg: print(f"{cur}/{total} - {msg}"))

print(result.output_video_path)     # video anotado con doble panel
print(result.timeseries_csv_path)   # Frame, Player_ID, Pos_X_2D, Pos_Y_2D, Ball_X, Ball_Y
print(result.heatmap_paths)         # heatmaps PNG por pareja/jugador
```

## 5. Notas de ingeniería

- **Homografía**: `cv2.getPerspectiveTransform` resuelve los 8 grados de
  libertad de la transformación proyectiva a partir de 4 correspondencias
  de puntos (cámara → cenital). Se asume que la pista es plana, lo cual es
  válido en pádel real.
- **Punto de proyección del jugador**: se usa el centro-inferior del
  bounding box ("foot point"), no el centro, para minimizar el error de
  paralaje causado por la altura de la persona.
- **Filtrado espacial**: `cv2.pointPolygonTest` descarta cualquier persona
  detectada fuera del polígono de la pista (espectadores, utileros), con
  un margen configurable en metros para no descartar jugadores pegados a
  la línea.
- **Tracking de jugadores**: `supervision.ByteTrack` asocia detecciones
  entre frames por IoU + confianza, manteniendo IDs estables incluso con
  oclusiones breves (jugador tapado por otro, por la red, etc.). Aun así,
  con oclusiones más largas ByteTrack puede "perder" a un jugador y darle
  un `tracker_id` nuevo al reaparecer — sin corregir esto, un partido
  entero puede terminar con 8-10 IDs distintos para sólo 4 personas.
  `padel_analytics/identity.py` (`PlayerIdentityResolver`) corrige esto
  después del tracking: mantiene como máximo 4 "slots" estables con su
  última posición 2D conocida, y reasigna cualquier `tracker_id` nuevo al
  slot más cercano en metros (o lo descarta como ruido si no hay lugar ni
  cercanía — típicamente un espectador que se coló por el filtro
  espacial). Es la capa que garantiza que siempre haya como máximo 4
  jugadores en el video anotado, el CSV y los heatmaps.
- **Códec del video de salida**: `cv2.VideoWriter` intenta primero un
  fourcc H.264 (`avc1`/`H264`); en muchas instalaciones de OpenCV (sobre
  todo `opencv-python` por pip) ese encoder no está disponible y cae en
  silencio a `mp4v` (MPEG-4 Part 2) — un archivo válido, pero que ningún
  navegador reproduce embebido en un `<video>` (se ve en negro / 0:00).
  Para no depender de eso, si el fourcc H.264 de OpenCV falla, el pipeline
  re-codifica el archivo con el binario de FFmpeg que trae empaquetado
  `imageio-ffmpeg` (`libx264`, sin que el usuario tenga que instalar nada
  aparte). Si ni siquiera eso está disponible, la webapp lo detecta
  (`metadata.json` guarda qué códec quedó) y muestra un aviso + botón de
  descarga directa en vez de un reproductor roto.
- **Tracking de pelota**: no se usa ByteTrack (pensado para múltiples
  objetos tipo persona) sino un filtro de Kalman de velocidad constante,
  porque la pelota es un único objeto muy rápido y con detecciones
  intermitentes (motion blur en los golpes fuertes).
- **Heatmaps**: matriz de ocupación 2D (`np.histogram2d`) sobre las
  posiciones proyectadas en metros, agregada por pareja (según el lado de
  la red donde jugó cada ID en promedio) y por jugador individual.
- **Detección de golpes**: heurística basada en cambios bruscos de
  dirección/velocidad de la pelota en el plano 2D, filtrando por cercanía
  a un jugador para descartar rebotes en pared/piso. Es un punto de
  partida razonable sin entrenar un clasificador; el usuario confirma o
  corrige cada golpe desde la webapp.

## 6. Sobre GitHub Pages

GitHub Pages sólo puede servir archivos estáticos (HTML/CSS/JS) — no puede
ejecutar Python, YOLOv8 ni procesar video subido por el usuario. Por eso
este proyecto se gestiona como una app local (`python run.py`) que corre en
tu propia máquina. Si en el futuro querés una versión pública, la opción
realista es desplegar `webapp/` en un servicio con backend (Render,
Railway, un VPS propio, etc.) en vez de GitHub Pages.
