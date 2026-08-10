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
  points.py              Marcado de inicio/fin de cada punto + PointDetector (detección
                            automática de rallies agrupando golpes) + ganador por pareja
  match_stats.py          Cruza puntos + golpes: WIN/LOSS por último toque, golpes por jugador,
                            estadísticas de rally, winners/errores por tipo de golpe
  performance_stats.py     Distancia recorrida, velocidad, sprints, cobertura de cancha,
                            velocidad de la pelota en cada golpe
  highlights.py             Recorte automático de clips de video por punto (ffmpeg)
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
4. **Resultados** (`/video/<id>/results` — FASE 4): lo primero que ves es
   un **resumen automático** (marcador, puntos y golpes detectados, un
   par de datos por jugador) con links directos para corregir cualquier
   cosa — no hace falta ir página por página para enterarte de qué
   detectó el sistema solo. Debajo, el video de doble panel (cámara
   anotada + minimapa 2D), heatmaps de ocupación por pareja y por jugador
   (click en cualquiera para verlo grande en un modal, con botón de
   volver), y descarga de la serie temporal en CSV/JSON.
5. **Jugadores** (`/video/<id>/players`): a cada jugador se le pone
   automáticamente de nombre por defecto el color de su camiseta
   ("Rojo", "Azul", etc.) y se le asigna una pareja según de qué lado de
   la red jugó en promedio — ambos calculados durante el procesamiento
   (Fases 2-4). Desde esta página podés corregir el nombre y/o la pareja
   de cualquiera de los 4 en cualquier momento — se usan en el selector
   de jugador al etiquetar golpes, en el marcador de puntos, en las
   estadísticas y en las leyendas de los heatmaps. Si reprocesás el
   video, ninguna corrección que hayas hecho a mano se pisa.
6. **Etiquetar golpes** (`/video/<id>/label`): lista los golpes detectados
   automáticamente por la heurística de trayectoria de la pelota (cambios
   bruscos de dirección cerca de un jugador) y permite corregirlos o
   agregar golpes manuales marcando el frame exacto sobre el reproductor
   de video, eligiendo jugador y tipo de golpe (derecha, revés, bandeja,
   víbora, smash, saque, etc.).
7. **Marcar puntos** (`/video/<id>/points`): apenas termina de procesar,
   esta página ya viene con los puntos (rallies) **detectados
   automáticamente** — `PointDetector` agrupa los golpes que están
   pegados en el tiempo (menos de ~4s entre uno y el siguiente) en un
   mismo punto, y separa dos puntos cuando hay un hueco más largo (el
   tiempo muerto real entre rallies: ir a buscar la pelota, prepararse
   para sacar). Lo único que no se puede inferir solo de la trayectoria
   de la pelota es **quién ganó** cada punto, así que esos quedan
   marcados como "pendiente de confirmar" (con un aviso destacado) hasta
   que elegís la pareja ganadora en un desplegable — sin tener que
   scrubear el video ni marcar el inicio/fin a mano. También podés seguir
   marcando puntos manualmente (útil si el auto-detector se equivocó en
   algún tramo, o para un video que todavía no procesaste) con "Marcar
   inicio/fin de punto", y corregir el ganador de cualquier punto ya
   cerrado en cualquier momento desde el mismo listado. La página muestra
   el marcador acumulado, la duración promedio del rally, y la lista
   completa de puntos — cada uno clickeable para saltar el video a ese
   instante. Esto sirve para poder filtrar después cualquier otra
   analítica (posiciones, golpes, heatmaps) al rango de frames de un
   punto específico, sin tener que cortar el video en clips separados.
7. **Estadísticas** (`/video/<id>/stats`): cruza automáticamente los puntos
   marcados con los golpes registrados. Por cada punto cerrado, toma el
   golpe con el frame más alto dentro de su rango como "el último que tocó
   la pelota" y lo marca **WIN** si esa persona pertenecía a la pareja que
   ganó el punto (golpe ganador) o **LOSS** si pertenecía a la pareja que
   lo perdió (error propio, forzado o no forzado) — la misma convención que
   se usa en estadísticas de pádel/tenis. También calcula, inspirado en lo
   que ofrecen plataformas comerciales de análisis de pádel (Padelytics,
   Padmi, GameCam, PlaySight):
   - **Distancia recorrida y velocidad** (media/máxima, km/h) por jugador,
     y conteo de **sprints**, a partir de la posición 2D frame a frame.
   - **Cobertura de cancha** (% de la pista donde estuvo cada jugador).
   - **Velocidad de la pelota** en cada golpe (ranking de los más rápidos).
   - **Duración de los rallies** (promedio/mín/máx) y golpes promedio por punto.
   - **Winners vs. errores por tipo de golpe** (ej. cuántos puntos definió
     un smash ganador vs. cuántos se perdieron por error de víbora).

   El conteo de golpes por jugador se calcula igual sin procesar el video
   (si cargaste golpes a mano); todo lo demás necesita que el video haya
   sido procesado al menos una vez (Fases 2-4).
8. **Highlights** (`/video/<id>/highlights`): recorta automáticamente el
   video anotado en un clip por punto (con ~1s de margen antes/después),
   la misma idea que ofrecen PlaySight/Padmi/GameCam como su feature
   estrella. Un botón genera de una los clips de los 5 rallies más largos;
   cada punto también se puede recortar individualmente. Los clips quedan
   reproducibles en el navegador y con enlace de descarga directa.

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
- **Ejes del plano cenital**: por convención, X = ancho de la pista (0 a
  10m, lateral a lateral) e Y = largo (0 a 20m, fondo a fondo) — la red
  queda como línea horizontal a mitad del eje Y. Todo el sistema
  (`CoordinateTransformer`, heatmaps, minimapa embebido, `infer_teams`)
  usa esta misma convención, así que el minimapa y los heatmaps salen
  siempre "verticales" (más alto que ancho), como un diagrama de cancha
  visto de pie.
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
  intermitentes (motion blur en los golpes fuertes). Dos afinamientos:
  tolera hasta 30 frames seguidos sin detección antes de dar la pelota
  por perdida (bridging de gaps largos por motion blur), y descarta como
  outlier cualquier detección que aparezca muy lejos de donde el filtro
  predice que debería estar (gating), para poder bajar el umbral de
  confianza del detector — y así perder menos detecciones reales — sin
  que eso meta falsos positivos (líneas de la cancha, gorras) en la
  trayectoria.
- **Recall de jugadores lejanos y de la pelota**: YOLOv8 corre con
  `imgsz=960` (en vez del default de 640) para que objetos chicos en la
  imagen —el jugador más lejos de cámara, la pelota— ocupen más píxeles
  y el detector los vea mejor, y con el modelo `yolov8s` en vez de
  `yolov8n` (más preciso; como el análisis es offline, no en vivo, vale
  la pena pagar el costo extra de cómputo). Los umbrales de confianza
  también se bajaron a propósito (recall por sobre precisión bruta), ya
  que el filtrado espacial, el tope de 4 jugadores y el gating de la
  pelota ya se encargan de limpiar falsos positivos.
- **Heatmaps**: matriz de ocupación 2D (`np.histogram2d`) sobre las
  posiciones proyectadas en metros, agregada por pareja (según el lado de
  la red donde jugó cada ID en promedio) y por jugador individual.
- **Detección de golpes**: heurística basada en cambios bruscos de
  dirección/velocidad de la pelota en el plano 2D, filtrando por cercanía
  a un jugador para descartar rebotes en pared/piso. Es un punto de
  partida razonable sin entrenar un clasificador; el usuario confirma o
  corrige cada golpe desde la webapp.
- **Distancia/velocidad/sprints**: se derivan de la distancia euclidiana
  entre posiciones 2D consecutivas del mismo jugador, dividida por el
  tiempo entre esos frames. Se descartan pasos con distancia o velocidad
  físicamente imposibles (saltos de identidad, no movimiento real) para
  que no infle la distancia total ni la velocidad máxima.
- **Highlights**: recorte con el binario de FFmpeg de `imageio-ffmpeg`
  (mismo que usa `video_transcode.py`), re-codificando en vez de copiar
  el stream, para que el corte sea preciso al segundo pedido.
- **Detección automática de puntos**: `PointDetector` agrupa los golpes ya
  detectados por gaps de tiempo (huecos cortos = mismo rally, hueco largo
  = tiempo muerto entre puntos), no analiza la trayectoria de la pelota
  de forma independiente. El ganador queda deliberadamente sin definir
  (no se puede inferir con confianza si la pelota terminó afuera o en la
  red sólo con su trayectoria 2D) — el usuario lo confirma desde
  `/video/<id>/points`, donde los puntos pendientes de confirmación se
  destacan.
- **Correcciones que sobreviven a un reproceso**: `ShotLabelStore` y
  `PointLabelStore` marcan cada golpe/punto con `auto_detected` (True
  mientras nadie lo tocó). Editar cualquier campo desde la webapp lo
  "promueve" a `auto_detected=False`; en el siguiente reproceso,
  `set_auto_detected()` reemplaza sólo las propuestas automáticas viejas
  y deja intacto todo lo que el usuario ya confirmó o corrigió. Lo mismo
  aplica a nombres y parejas de jugador (`player_names.json` /
  `player_teams.json`): los valores por defecto sólo completan huecos,
  nunca pisan una corrección existente.

### Qué quedó afuera (y por qué)

Investigué varias plataformas comerciales de análisis de pádel
(Padelytics, Padmi, PlaySight, SPASH Match Analyzer, GameCam, Padelplay)
antes de agregar las funciones de arriba. Dejé afuera, a propósito:

- **Sensor de pala** (Padelplay): requiere hardware dedicado que este
  proyecto no asume que tengas.
- **Clasificación automática del tipo de golpe por visión** (bandeja,
  víbora, smash como categorías detectadas por un modelo, no elegidas a
  mano): necesitaría entrenar un clasificador con un dataset de golpes de
  pádel etiquetado, que no existe en este repo. Mientras tanto, la
  heurística de `shot_detection.py` + el etiquetado manual cubren buena
  parte de ese caso de uso.
- **Comparación de rendimiento entre partidos / perfil de jugador en el
  tiempo**: cada video es independiente y los nombres de jugador son por
  video, así que no hay todavía una forma confiable de saber que el
  "Rojo" del partido de hoy es la misma persona que el "Rojo" del de la
  semana pasada. Se podría agregar definiendo cómo vincular identidades
  entre videos.
- **Calorías quemadas**: es más un gancho de marketing que una métrica
  analítica rigurosa (depende de peso, edad, condición física reales del
  jugador, que no tenemos), así que no se implementó.

## 6. Sobre GitHub Pages

GitHub Pages sólo puede servir archivos estáticos (HTML/CSS/JS) — no puede
ejecutar Python, YOLOv8 ni procesar video subido por el usuario. Por eso
este proyecto se gestiona como una app local (`python run.py`) que corre en
tu propia máquina. Si en el futuro querés una versión pública, la opción
realista es desplegar `webapp/` en un servicio con backend (Render,
Railway, un VPS propio, etc.) en vez de GitHub Pages.
