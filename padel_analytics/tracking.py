"""
FASE 2 — Detección y Seguimiento (Players & Ball Tracking).

Este módulo integra:
  * Ultralytics YOLOv8 para detectar personas y la pelota en cada frame.
  * Supervision (`ByteTrack`) para asignar un ID único y persistente a
    cada jugador a lo largo del video (re-identificación frame a frame
    aunque haya oclusiones breves).
  * Filtrado espacial por polígono de pista para descartar espectadores,
    árbitros fuera de cancha, etc.
  * Un tracker simple para la pelota (single-object, basado en el
    detector + un filtro de Kalman de velocidad constante) porque
    ByteTrack está pensado para múltiples objetos "tipo persona" y la
    pelota es un caso aparte: un solo objeto, muy rápido, con
    detecciones intermitentes (se pierde en los golpes fuertes).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config


@dataclass
class PlayerDetection:
    """Detección/track de un jugador en un frame."""

    tracker_id: int
    bbox_xyxy: tuple[float, float, float, float]  # (x1, y1, x2, y2) en píxeles de cámara
    confidence: float
    foot_point: tuple[float, float]  # punto usado para proyectar a 2D: centro-inferior del bbox

    @staticmethod
    def foot_point_from_bbox(bbox_xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
        """
        El centro inferior del bounding box aproxima la posición de los pies
        del jugador sobre el piso. Es el punto correcto para proyectar con
        la homografía: la cabeza/torso están "levantados" del plano de la
        pista por la altura de la persona, y esa altura introduce error de
        paralaje si se usa el centro del bbox.
        """
        x1, y1, x2, y2 = bbox_xyxy
        return ((x1 + x2) / 2.0, y2)


@dataclass
class BallDetection:
    """Detección de la pelota en un frame (puede no haber ninguna)."""

    point_xy: tuple[float, float] | None
    confidence: float = 0.0
    is_predicted: bool = False  # True si viene del filtro de Kalman (no hubo detección directa)


@dataclass
class FrameTrackingResult:
    frame_index: int
    players: list[PlayerDetection] = field(default_factory=list)
    ball: BallDetection | None = None


class CourtAreaFilter:
    """
    Filtrado espacial: determina si un punto (típicamente el "foot point"
    de una persona) cae dentro del polígono de la pista, con un margen de
    tolerancia en metros para no descartar jugadores que pisan la línea.
    """

    def __init__(self, court_polygon_image: np.ndarray, margin_px: float = 0.0):
        self.polygon = court_polygon_image.astype(np.float32)
        self.margin_px = margin_px

    def contains(self, point_xy: tuple[float, float]) -> bool:
        # cv2.pointPolygonTest devuelve la distancia con signo al polígono:
        # > 0 adentro, < 0 afuera, 0 sobre el borde. Usamos el margen para
        # tolerar jugadores que están apenas fuera de línea (rebote en pared,
        # jugador restando pegado al fondo, etc.).
        distance = cv2.pointPolygonTest(self.polygon, point_xy, measureDist=True)
        return distance >= -self.margin_px


class BallKalmanTracker:
    """
    Filtro de Kalman de velocidad constante (estado = [x, y, vx, vy]) para
    suavizar y predecir la posición de la pelota cuando el detector falla
    (motion blur en los golpes fuertes es habitual en pádel).

    Dos mejoras sobre un Kalman básico, pensadas para poder bajar el
    umbral de confianza del detector (más recall) sin que eso arruine el
    tracking con falsos positivos:

    1. Gating de outliers: si llega una detección muy lejos de donde el
       filtro predice que debería estar la pelota, se descarta como
       probable falso positivo (una línea blanca de la cancha, una gorra,
       el reflejo de una luz) en vez de "teletransportar" el tracker ahí.
    2. Tolerancia a gaps más alta (`max_misses_before_reset`): la pelota
       puede perderse varios frames seguidos por motion blur en un golpe
       fuerte; con más margen se sigue prediciendo su posición en vez de
       darla por perdida antes de tiempo.
    """

    def __init__(self, max_misses_before_reset: int = 30, max_jump_px: float = 350.0):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32
        )
        self.kf.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32
        )
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 5e-2
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-1
        self._initialized = False
        self.misses = 0
        self.max_misses_before_reset = max_misses_before_reset
        self.max_jump_px = max_jump_px

    def update(self, measurement_xy: tuple[float, float] | None) -> tuple[float, float] | None:
        if not self._initialized:
            if measurement_xy is None:
                return None
            x, y = measurement_xy
            self.kf.statePre = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self.kf.statePost = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self._initialized = True
            self.misses = 0
            return x, y

        predicted = self.kf.predict()
        predicted_xy = (float(predicted[0, 0]), float(predicted[1, 0]))

        if measurement_xy is not None:
            jump = math.dist(measurement_xy, predicted_xy)
            if jump > self.max_jump_px:
                measurement_xy = None  # probable falso positivo: se ignora, no se corrige con esto

        if measurement_xy is None:
            self.misses += 1
            if self.misses > self.max_misses_before_reset:
                self._initialized = False
                return None
            return predicted_xy

        self.misses = 0
        corrected = self.kf.correct(np.array([[measurement_xy[0]], [measurement_xy[1]]], dtype=np.float32))
        return float(corrected[0, 0]), float(corrected[1, 0])

    def peek_predicted_position_and_speed(self) -> tuple[tuple[float, float] | None, float]:
        """
        Adelanta la posición un paso (x+vx, y+vy) a partir del último estado
        corregido, SIN llamar a `kf.predict()` (que sí muta el estado
        interno del filtro) — se usa sólo para centrar la ventana de
        búsqueda de la pelota antes de procesar el frame, no para el
        tracking en sí. Devuelve también la velocidad (px/frame) para
        poder agrandar la ventana cuando la pelota viene rápido.
        """
        if not self._initialized:
            return None, 0.0
        state = self.kf.statePost
        x, y, vx, vy = (float(state[i, 0]) for i in range(4))
        return (x + vx, y + vy), math.hypot(vx, vy)


def compute_search_window(
    frame_width: int,
    frame_height: int,
    center_xy: tuple[float, float],
    radius_px: float,
) -> tuple[int, int, int, int]:
    """
    Ventana cuadrada de radio `radius_px` centrada en `center_xy`, recortada
    a los límites del frame. Devuelve (x1, y1, x2, y2) en píxeles enteros.
    Función pura (sin YOLO) para poder testear la geometría del recorte.
    """
    cx, cy = center_xy
    x1 = int(max(0, cx - radius_px))
    y1 = int(max(0, cy - radius_px))
    x2 = int(min(frame_width, cx + radius_px))
    y2 = int(min(frame_height, cy + radius_px))
    return x1, y1, x2, y2


def translate_point_to_frame(point_xy_in_crop: tuple[float, float], offset_x: int, offset_y: int) -> tuple[float, float]:
    """Convierte un punto en coordenadas del recorte a coordenadas del frame completo."""
    return point_xy_in_crop[0] + offset_x, point_xy_in_crop[1] + offset_y


def adaptive_search_radius(
    speed_px_per_frame: float,
    base_radius_px: float = config.BALL_SEARCH_BASE_RADIUS_PX,
    max_radius_px: float = config.BALL_SEARCH_MAX_RADIUS_PX,
    speed_multiplier: float = config.BALL_SEARCH_SPEED_MULTIPLIER,
) -> float:
    """
    Radio de la ventana de búsqueda, agrandado según qué tan rápido venía
    la pelota (para no perderla en un smash) pero acotado a un máximo (para
    no perder el beneficio del "zoom" ni tardar de más en cada frame).
    """
    return min(max_radius_px, base_radius_px + speed_multiplier * speed_px_per_frame)


class PadelTracker:
    """
    Orquesta YOLOv8 + ByteTrack + filtrado espacial + tracking de pelota
    para un frame de video a la vez.
    """

    def __init__(
        self,
        weights_path: str = config.DEFAULT_YOLO_WEIGHTS,
        court_filter: CourtAreaFilter | None = None,
        person_conf_threshold: float = config.DEFAULT_PERSON_CONF_THRESHOLD,
        ball_conf_threshold: float = config.DEFAULT_BALL_CONF_THRESHOLD,
        max_players: int = config.MAX_PLAYERS_ON_COURT,
        imgsz: int = config.DEFAULT_YOLO_IMGSZ,
        device: str | None = None,
    ):
        # Imports pesados (torch/ultralytics/supervision) se hacen acá adentro
        # para que el resto del paquete se pueda importar/testear sin tener
        # esas dependencias instaladas (por ejemplo, para testear calibración
        # o coordenadas con datos sintéticos).
        from ultralytics import YOLO
        import supervision as sv

        self.model = YOLO(weights_path)
        self.device = device
        self.imgsz = imgsz
        self._sv = sv
        self.tracker = sv.ByteTrack()

        self.court_filter = court_filter
        self.person_conf_threshold = person_conf_threshold
        self.ball_conf_threshold = ball_conf_threshold
        self.max_players = max_players
        self.ball_tracker = BallKalmanTracker()

    def set_court_filter(self, court_filter: CourtAreaFilter) -> None:
        self.court_filter = court_filter

    def process_frame(self, frame: np.ndarray, frame_index: int) -> FrameTrackingResult:
        sv = self._sv

        results = self.model(
            frame,
            classes=[config.COCO_PERSON_CLASS_ID, config.COCO_BALL_CLASS_ID],
            conf=min(self.person_conf_threshold, self.ball_conf_threshold),
            imgsz=self.imgsz,
            verbose=False,
            device=self.device,
        )[0]

        detections = sv.Detections.from_ultralytics(results)

        players = self._track_players(detections, frame_index)
        ball = self._track_ball(detections, frame)

        return FrameTrackingResult(frame_index=frame_index, players=players, ball=ball)

    # ------------------------------------------------------------------
    def _track_players(self, detections, frame_index: int) -> list[PlayerDetection]:
        person_mask = (detections.class_id == config.COCO_PERSON_CLASS_ID) & (
            detections.confidence >= self.person_conf_threshold
        )
        person_detections = detections[person_mask]

        # ByteTrack asigna/mantiene un tracker_id estable por objeto a lo
        # largo de los frames, asociando detecciones consecutivas por
        # solapamiento de cajas (IoU) + score de confianza, incluso si el
        # detector falla en algún frame puntual (oclusión breve).
        tracked = self.tracker.update_with_detections(person_detections)

        players: list[PlayerDetection] = []
        for bbox, tracker_id, conf in zip(tracked.xyxy, tracked.tracker_id, tracked.confidence):
            bbox_t = tuple(float(v) for v in bbox)
            foot_point = PlayerDetection.foot_point_from_bbox(bbox_t)

            # Filtrado espacial: descarta espectadores/gente fuera de la pista.
            if self.court_filter is not None and not self.court_filter.contains(foot_point):
                continue

            players.append(
                PlayerDetection(
                    tracker_id=int(tracker_id),
                    bbox_xyxy=bbox_t,
                    confidence=float(conf),
                    foot_point=foot_point,
                )
            )

        # Si por ruido quedan más de 4 "jugadores" (ej. alguien pegado a la
        # línea justo cuando entra/sale), nos quedamos con los 4 de mayor
        # confianza para respetar la regla de negocio "4 jugadores en cancha".
        if len(players) > self.max_players:
            players.sort(key=lambda p: p.confidence, reverse=True)
            players = players[: self.max_players]

        return players

    def _track_ball(self, detections, frame: np.ndarray) -> BallDetection:
        measurement, confidence = self._best_ball_detection(detections)

        # Segundo pase "con zoom": si ya tenemos una posición previa de la
        # pelota (o el filtro predice dónde debería estar este frame),
        # recortamos una ventana chica alrededor y volvemos a correr YOLO
        # ahí. La pelota es tan pequeña que en el frame completo casi no
        # tiene píxeles; en el recorte ocupa una fracción mucho mayor del
        # cuadro que ve el modelo, así que se detecta con más precisión.
        # Se prioriza este resultado sobre el del frame completo cuando
        # aparece, precisamente por eso.
        predicted_xy, speed_px = self.ball_tracker.peek_predicted_position_and_speed()
        if predicted_xy is not None:
            radius = adaptive_search_radius(speed_px)
            roi_measurement, roi_confidence = self._detect_ball_in_roi(frame, predicted_xy, radius)
            if roi_measurement is not None:
                measurement, confidence = roi_measurement, roi_confidence

        smoothed = self.ball_tracker.update(measurement)
        if smoothed is None:
            return BallDetection(point_xy=None, confidence=0.0, is_predicted=False)

        return BallDetection(
            point_xy=smoothed,
            confidence=confidence,
            is_predicted=measurement is None,
        )

    def _best_ball_detection(self, detections) -> tuple[tuple[float, float] | None, float]:
        """Mejor detección de pelota del pase de YOLO sobre el frame completo (puede no haber ninguna)."""
        ball_mask = (detections.class_id == config.COCO_BALL_CLASS_ID) & (
            detections.confidence >= self.ball_conf_threshold
        )
        ball_detections = detections[ball_mask]
        if len(ball_detections) == 0:
            return None, 0.0

        # Puede haber falsos positivos (ej. cabeza pequeña, gorra). Nos
        # quedamos con la detección de mayor confianza como medición.
        best_idx = int(np.argmax(ball_detections.confidence))
        x1, y1, x2, y2 = ball_detections.xyxy[best_idx]
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0), float(ball_detections.confidence[best_idx])

    def _detect_ball_in_roi(
        self, frame: np.ndarray, center_xy: tuple[float, float], radius_px: float
    ) -> tuple[tuple[float, float] | None, float]:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = compute_search_window(w, h, center_xy, radius_px)
        if x2 - x1 < 20 or y2 - y1 < 20:
            return None, 0.0

        crop = frame[y1:y2, x1:x2]
        results = self.model(
            crop,
            classes=[config.COCO_BALL_CLASS_ID],
            conf=self.ball_conf_threshold,
            imgsz=config.BALL_SEARCH_ROI_IMGSZ,
            verbose=False,
            device=self.device,
        )[0]
        detections = self._sv.Detections.from_ultralytics(results)
        if len(detections) == 0:
            return None, 0.0

        best_idx = int(np.argmax(detections.confidence))
        bx1, by1, bx2, by2 = detections.xyxy[best_idx]
        point_in_crop = ((bx1 + bx2) / 2.0, (by1 + by2) / 2.0)
        return translate_point_to_frame(point_in_crop, x1, y1), float(detections.confidence[best_idx])
