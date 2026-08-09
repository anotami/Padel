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
# 50 px/m -> minimapa de 1000x500 px, buen compromiso nitidez/tamaño.
TOPDOWN_SCALE_PX_PER_M = 50

TOPDOWN_WIDTH_PX = int(COURT_LENGTH_M * TOPDOWN_SCALE_PX_PER_M)
TOPDOWN_HEIGHT_PX = int(COURT_WIDTH_M * TOPDOWN_SCALE_PX_PER_M)

# ---------------------------------------------------------------------------
# Clases COCO relevantes para el modelo YOLOv8 "de fábrica" (yolov8n.pt).
# No hace falta reentrenar para tener un baseline funcional:
#   0  -> person
#   32 -> sports ball
# ---------------------------------------------------------------------------
COCO_PERSON_CLASS_ID = 0
COCO_BALL_CLASS_ID = 32

# ---------------------------------------------------------------------------
# Parámetros por defecto de detección / tracking.
# ---------------------------------------------------------------------------
DEFAULT_PERSON_CONF_THRESHOLD = 0.35
DEFAULT_BALL_CONF_THRESHOLD = 0.15  # la pelota es pequeña y rápida -> umbral más laxo
MAX_PLAYERS_ON_COURT = 4

# Margen (en metros, en el plano cenital) que se tolera fuera del polígono
# de la pista antes de descartar una detección como "espectador".
COURT_MARGIN_M = 0.8

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

DEFAULT_YOLO_WEIGHTS = "yolov8n.pt"  # se descarga solo la primera vez (ultralytics)


@dataclass
class CourtGeometry:
    """Encapsula la geometría real de la pista y su versión en píxeles (top-down)."""

    length_m: float = COURT_LENGTH_M
    width_m: float = COURT_WIDTH_M
    scale_px_per_m: float = TOPDOWN_SCALE_PX_PER_M

    @property
    def width_px(self) -> int:
        return int(self.length_m * self.scale_px_per_m)

    @property
    def height_px(self) -> int:
        return int(self.width_m * self.scale_px_per_m)

    def destination_corners_px(self) -> list[tuple[float, float]]:
        """
        Las 4 esquinas de la pista en el plano cenital (destino de la homografía),
        en orden: [sup-izq, sup-der, inf-der, inf-izq] -> igual convención que
        se le pedirá al usuario al hacer clic sobre el video.
        """
        w, h = self.width_px, self.height_px
        return [(0, 0), (w, 0), (w, h), (0, h)]

    def net_x_px(self) -> float:
        """Posición X del medio de la red en píxeles del plano cenital."""
        return self.width_px / 2.0
