"""
FASE 1 — Calibración y Homografía (pista 2D).

`CourtCalibrator` resuelve el problema de perspectiva: la cámara está fija
pero angulada, así que las distancias en píxeles de la imagen NO son
proporcionales a las distancias reales en la pista. Para poder medir
posiciones y generar mapas de calor en metros reales necesitamos una
transformación de perspectiva (homografía) que "aplane" la vista de cámara
a una vista cenital (top-down).

Flujo:
  1. El usuario marca las 4 esquinas de la pista sobre un frame del video
     (en la webapp esto se hace con clicks sobre un <canvas>; en modo CLI
     se puede usar `CourtCalibrator.calibrate_interactive` con OpenCV).
  2. Con esos 4 puntos (origen) y las 4 esquinas conocidas de la pista real
     en el plano cenital (destino, en píxeles-por-metro) se calcula la
     matriz de homografía 3x3 con `cv2.getPerspectiveTransform`.
  3. Esa matriz se reutiliza para proyectar cualquier punto (jugador, pelota)
     de la imagen de cámara al plano 2D real.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from .config import CourtGeometry


# Orden esperado de los 4 clicks del usuario. Es importante ser consistentes
# porque cv2.getPerspectiveTransform empareja punto-a-punto por índice.
CORNER_ORDER = [
    "esquina_sup_izquierda",   # fondo izquierdo (más lejos de cámara, o el que se elija como referencia)
    "esquina_sup_derecha",     # fondo derecho
    "esquina_inf_derecha",     # frente derecho (más cerca de cámara)
    "esquina_inf_izquierda",   # frente izquierdo
]


@dataclass
class CourtCalibration:
    """Resultado serializable de una calibración de pista."""

    video_id: str
    image_points: list[list[float]]      # 4 puntos [x, y] clickeados sobre el frame (píxeles de cámara)
    frame_width: int
    frame_height: int
    court_length_m: float
    court_width_m: float
    scale_px_per_m: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CourtCalibration":
        return cls(**data)


class CourtCalibrator:
    """
    Calcula y persiste la homografía cámara -> vista cenital.

    Uso típico:
        calibrator = CourtCalibrator()
        calibrator.set_image_points(points, frame_width, frame_height)
        H = calibrator.homography_matrix()
        punto_2d = calibrator.project_point((x_img, y_img))
    """

    def __init__(self, geometry: CourtGeometry | None = None):
        self.geometry = geometry or CourtGeometry()
        self._image_points: np.ndarray | None = None
        self._homography: np.ndarray | None = None
        self._frame_size: tuple[int, int] | None = None  # (w, h)

    # ------------------------------------------------------------------
    # Construcción de la calibración
    # ------------------------------------------------------------------
    def set_image_points(
        self,
        points: list[tuple[float, float]] | list[list[float]],
        frame_width: int,
        frame_height: int,
    ) -> np.ndarray:
        """
        Recibe los 4 puntos de cámara (en el orden CORNER_ORDER) y calcula
        la matriz de homografía 3x3.

        Matemática: cv2.getPerspectiveTransform resuelve el sistema lineal
        que mapea 4 puntos origen -> 4 puntos destino asumiendo una
        transformación proyectiva general (8 grados de libertad):

            [x']   [h11 h12 h13] [x]
            [y'] ~ [h21 h22 h23] [y]      (igualdad hasta escala,
            [w']   [h31 h32   1] [1]       por eso se normaliza por w')

        Con 4 correspondencias de puntos (8 ecuaciones) se resuelven
        exactamente los 8 coeficientes desconocidos de H.
        """
        if len(points) != 4:
            raise ValueError(f"Se requieren exactamente 4 puntos, se recibieron {len(points)}")

        src = np.array(points, dtype=np.float32)
        dst = np.array(self.geometry.destination_corners_px(), dtype=np.float32)

        self._image_points = src
        self._frame_size = (frame_width, frame_height)
        self._homography = cv2.getPerspectiveTransform(src, dst)
        return self._homography

    def homography_matrix(self) -> np.ndarray:
        if self._homography is None:
            raise RuntimeError("La calibración todavía no fue calculada. Llamá a set_image_points() primero.")
        return self._homography

    # ------------------------------------------------------------------
    # Proyección de puntos cámara -> plano cenital
    # ------------------------------------------------------------------
    def project_point(self, point_xy: tuple[float, float]) -> tuple[float, float]:
        """Proyecta un único punto (x, y) de la imagen de cámara al plano cenital (píxeles top-down)."""
        px, py = self.project_points(np.array([point_xy], dtype=np.float32))[0]
        # cv2 devuelve numpy.float32; lo convertimos a float nativo de Python
        # para que el resto del sistema (json.dumps, dataclasses, etc.) no falle.
        return float(px), float(py)

    def project_points(self, points_xy: np.ndarray) -> np.ndarray:
        """
        Proyecta un array Nx2 de puntos de cámara al plano cenital usando
        cv2.perspectiveTransform, que aplica la homografía y normaliza
        automáticamente por la coordenada homogénea w'.
        """
        H = self.homography_matrix()
        pts = np.asarray(points_xy, dtype=np.float32).reshape(-1, 1, 2)
        projected = cv2.perspectiveTransform(pts, H)
        return projected.reshape(-1, 2)

    def project_point_to_meters(self, point_xy: tuple[float, float]) -> tuple[float, float]:
        """Igual que project_point pero devuelve metros reales en vez de píxeles del minimapa."""
        px, py = self.project_point(point_xy)
        scale = self.geometry.scale_px_per_m
        return px / scale, py / scale

    # ------------------------------------------------------------------
    # Polígono de la pista (para el filtrado espacial de la Fase 2)
    # ------------------------------------------------------------------
    def court_polygon_image(self) -> np.ndarray:
        """Devuelve los 4 puntos originales (en coordenadas de cámara) como polígono cerrado."""
        if self._image_points is None:
            raise RuntimeError("La calibración todavía no fue calculada.")
        return self._image_points.copy()

    # ------------------------------------------------------------------
    # Persistencia (para no tener que recalibrar cada vez que se procesa el mismo video)
    # ------------------------------------------------------------------
    def to_calibration(self, video_id: str) -> CourtCalibration:
        if self._image_points is None or self._frame_size is None:
            raise RuntimeError("No hay calibración calculada para exportar.")
        w, h = self._frame_size
        return CourtCalibration(
            video_id=video_id,
            image_points=self._image_points.tolist(),
            frame_width=w,
            frame_height=h,
            court_length_m=self.geometry.length_m,
            court_width_m=self.geometry.width_m,
            scale_px_per_m=self.geometry.scale_px_per_m,
        )

    def save(self, path: str | Path, video_id: str) -> None:
        calibration = self.to_calibration(video_id)
        Path(path).write_text(json.dumps(calibration.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CourtCalibrator":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        calibration = CourtCalibration.from_dict(data)
        geometry = CourtGeometry(
            length_m=calibration.court_length_m,
            width_m=calibration.court_width_m,
            scale_px_per_m=calibration.scale_px_per_m,
        )
        calibrator = cls(geometry)
        calibrator.set_image_points(
            calibration.image_points, calibration.frame_width, calibration.frame_height
        )
        return calibrator

    # ------------------------------------------------------------------
    # Modo interactivo por consola (fallback sin la webapp): click con el mouse
    # sobre una ventana de OpenCV para marcar las 4 esquinas.
    # ------------------------------------------------------------------
    @staticmethod
    def pick_points_interactive(frame: np.ndarray) -> list[tuple[float, float]]:
        """
        Abre una ventana de OpenCV sobre `frame` y permite clickear las 4
        esquinas de la pista en el orden CORNER_ORDER. Devuelve los puntos.
        Pensado para uso local (script/CLI); la webapp usa un <canvas> HTML
        equivalente y envía los puntos por la API en vez de esto.
        """
        points: list[tuple[float, float]] = []
        display = frame.copy()
        window_name = "Calibracion de pista - click en las 4 esquinas (ESC para cancelar)"

        def on_mouse(event, x, y, flags, _param):
            if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
                points.append((float(x), float(y)))
                cv2.circle(display, (x, y), 6, (0, 255, 0), -1)
                label = CORNER_ORDER[len(points) - 1]
                cv2.putText(display, label, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                cv2.imshow(window_name, display)

        cv2.imshow(window_name, display)
        cv2.setMouseCallback(window_name, on_mouse)

        while len(points) < 4:
            key = cv2.waitKey(20) & 0xFF
            if key == 27:  # ESC
                break

        cv2.destroyWindow(window_name)
        return points
