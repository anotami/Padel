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
    """

    def __init__(self):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32
        )
        self.kf.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32
        )
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 1e-2
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-1
        self._initialized = False
        self.misses = 0
        self.max_misses_before_reset = 15  # ~0.5s a 30fps sin detecciones -> se descarta la predicción

    def update(self, measurement_xy: tuple[float, float] | None) -> tuple[float, float] | None:
        if measurement_xy is None:
            if not self._initialized:
                return None
            self.misses += 1
            if self.misses > self.max_misses_before_reset:
                self._initialized = False
                return None
            predicted = self.kf.predict()
            return float(predicted[0, 0]), float(predicted[1, 0])

        x, y = measurement_xy
        if not self._initialized:
            self.kf.statePre = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self.kf.statePost = np.array([[x], [y], [0], [0]], dtype=np.float32)
            self._initialized = True
            self.misses = 0
            return x, y

        self.misses = 0
        self.kf.predict()
        corrected = self.kf.correct(np.array([[x], [y]], dtype=np.float32))
        return float(corrected[0, 0]), float(corrected[1, 0])


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
            verbose=False,
            device=self.device,
        )[0]

        detections = sv.Detections.from_ultralytics(results)

        players = self._track_players(detections, frame_index)
        ball = self._track_ball(detections)

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

    def _track_ball(self, detections) -> BallDetection:
        ball_mask = (detections.class_id == config.COCO_BALL_CLASS_ID) & (
            detections.confidence >= self.ball_conf_threshold
        )
        ball_detections = detections[ball_mask]

        measurement = None
        confidence = 0.0
        if len(ball_detections) > 0:
            # Puede haber falsos positivos (ej. cabeza pequeña, gorra). Nos
            # quedamos con la detección de mayor confianza como medición.
            best_idx = int(np.argmax(ball_detections.confidence))
            x1, y1, x2, y2 = ball_detections.xyxy[best_idx]
            measurement = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            confidence = float(ball_detections.confidence[best_idx])

        smoothed = self.ball_tracker.update(measurement)
        if smoothed is None:
            return BallDetection(point_xy=None, confidence=0.0, is_predicted=False)

        return BallDetection(
            point_xy=smoothed,
            confidence=confidence,
            is_predicted=measurement is None,
        )
