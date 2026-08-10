"""
Configuración global del sistema de análisis de pádel.

Centraliza constantes físicas de la pista, parámetros de los modelos
y rutas por defecto, para que el resto de los módulos no tengan
"números mágicos" repartidos por el código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dimensiones reales de una pista de pádel (norma WPT / FIP).
# Se usan como destino de la homografía (vista cenital 2D).
# ---------------------------------------------------------------------------
COURT_LENGTH_M = 20.0   # eje "largo" de la pista (línea de fondo a línea de fondo)
COURT_WIDTH_M = 10.0    # eje "ancho" de la pista (pared lateral a pared lateral)

# Escala de renderizado del minimapa / heatmap: píxeles por metro.
# 50 px/m -> minimapa de 500x1000 px (vertical: 10m de ancho x 20m de largo),
# buen compromiso nitidez/tamaño.
TOPDOWN_SCALE_PX_PER_M = 50

# Ancho (10m, lateral a lateral) en el eje horizontal, largo (20m, fondo a
# fondo) en el eje vertical -> plano cenital "de pie", como se ve una pista
# de pádel dibujada en un diagrama (la red queda como línea horizontal).
TOPDOWN_WIDTH_PX = int(COURT_WIDTH_M * TOPDOWN_SCALE_PX_PER_M)
TOPDOWN_HEIGHT_PX = int(COURT_LENGTH_M * TOPDOWN_SCALE_PX_PER_M)

# ---------------------------------------------------------------------------
# Clases COCO relevantes para el modelo YOLOv8 "de fábrica".
# No hace falta reentrenar para tener un baseline funcional:
#   0  -> person
#   32 -> sports ball
# ---------------------------------------------------------------------------
COCO_PERSON_CLASS_ID = 0
COCO_BALL_CLASS_ID = 32

# ---------------------------------------------------------------------------
# Parámetros por defecto de detección / tracking.
# ---------------------------------------------------------------------------
# Umbrales relativamente laxos a propósito: el filtrado espacial (polígono
# de pista), el tope de 4 jugadores (identity.py) y el gating de outliers
# de la pelota (tracking.py) ya se encargan de descartar falsos positivos,
# así que conviene priorizar recall (no perderse al jugador del fondo ni
# la pelota en movimiento) antes que precisión bruta del detector.
DEFAULT_PERSON_CONF_THRESHOLD = 0.25
DEFAULT_BALL_CONF_THRESHOLD = 0.10  # la pelota es pequeña y rápida -> umbral más laxo todavía
MAX_PLAYERS_ON_COURT = 4

# Tamaño de imagen de entrada a YOLO. El default de Ultralytics (640px en
# el lado más largo) hace que jugadores lejanos y la pelota ocupen muy
# pocos píxeles y se pierdan; subirlo a 960 mejora notablemente el recall
# de objetos chicos a costa de más tiempo de cómputo por frame.
DEFAULT_YOLO_IMGSZ = 960

# Margen (en metros, en el plano cenital) que se tolera fuera del polígono
# de la pista antes de descartar una detección como "espectador".
COURT_MARGIN_M = 0.8

# ---------------------------------------------------------------------------
# Ventana de búsqueda de la pelota (segundo pase de YOLO, "zoom" alrededor
# de la posición predicha por el Kalman). La pelota real de pádel mide unos
# pocos centímetros y en un frame completo a 960px de lado puede ocupar
# menos de 10px — casi imposible de detectar de forma confiable. Recortando
# una ventana chica alrededor de donde el filtro predice que debería estar
# y corriendo YOLO sólo ahí (con el mismo imgsz), la pelota queda mucho más
# grande en relación al cuadro de entrada del modelo -> se detecta mejor.
# ---------------------------------------------------------------------------
BALL_SEARCH_BASE_RADIUS_PX = 130      # radio mínimo de la ventana (pelota quieta/lenta)
BALL_SEARCH_MAX_RADIUS_PX = 380       # tope, para no perder el efecto "zoom" ni tardar de más
BALL_SEARCH_SPEED_MULTIPLIER = 2.2    # cuánto crece el radio por cada px/frame de velocidad reciente
BALL_SEARCH_ROI_IMGSZ = 640           # imgsz del pase de YOLO sobre el recorte

# ---------------------------------------------------------------------------
# Rutas del proyecto.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
MODELS_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "db.json"

for _dir in (UPLOADS_DIR, OUTPUTS_DIR, MODELS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# yolov8s.pt (small) en vez de yolov8n (nano): en este sistema el video se
# procesa offline (no en vivo), así que conviene priorizar precisión sobre
# velocidad — sube notablemente la detección de jugadores lejanos/pequeños
# y de la pelota frente al modelo nano, a costa de tardar más por frame.
# Se descarga solo la primera vez que se usa (ultralytics).
DEFAULT_YOLO_WEIGHTS = "yolov8s.pt"


@dataclass
class CourtGeometry:
    """
    Encapsula la geometría real de la pista y su versión en píxeles
    (top-down). Convención de ejes del plano cenital: X = ancho de la
    pista (0 a width_m, lateral a lateral), Y = largo de la pista (0 a
    length_m, fondo a fondo) — la red queda como línea horizontal a mitad
    del eje Y. Es la misma convención que usan CoordinateTransformer,
    AnalyticsEngine y CourtMinimapRenderer para leer/dibujar posiciones.
    """

    length_m: float = COURT_LENGTH_M
    width_m: float = COURT_WIDTH_M
    scale_px_per_m: float = TOPDOWN_SCALE_PX_PER_M

    @property
    def width_px(self) -> int:
        return int(self.width_m * self.scale_px_per_m)

    @property
    def height_px(self) -> int:
        return int(self.length_m * self.scale_px_per_m)

    def destination_corners_px(self) -> list[tuple[float, float]]:
        """
        Las 4 esquinas de la pista en el plano cenital (destino de la
        homografía), en el mismo orden en que se le piden al usuario
        (fondo-izq, fondo-der, frente-der, frente-izq): las dos esquinas
        del "fondo" quedan en Y=0 y las del "frente" en Y=height_px, de
        modo que avanzar de fondo a frente (la dimensión real de 20m)
        recorre el eje vertical del plano cenital, e izquierda-derecha
        (los 10m de ancho real) recorre el eje horizontal.
        """
        w, h = self.width_px, self.height_px
        return [(0, 0), (w, 0), (w, h), (0, h)]

    def net_y_px(self) -> float:
        """Posición Y del medio de la red en píxeles del plano cenital (línea horizontal)."""
        return self.height_px / 2.0
