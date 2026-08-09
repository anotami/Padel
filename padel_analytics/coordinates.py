"""
FASE 3 — Traducción de Coordenadas y Mapas de Calor.

`CoordinateTransformer` usa la homografía calculada en la Fase 1 para
convertir, frame a frame, la posición de los pies de cada jugador (y de
la pelota) del plano de cámara al plano cenital 2D en metros reales.

`AnalyticsEngine` acumula esas posiciones a lo largo de todo el partido
para:
  * armar la serie temporal completa (para el CSV/JSON de exportación),
  * calcular la matriz de ocupación (heatmap) por jugador y por pareja,
  * asignar automáticamente cada jugador a un lado de la pista (pareja
    "cercana"/"lejana" a la red) en base a su posición promedio.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .calibration import CourtCalibrator
from .tracking import FrameTrackingResult
from . import config


@dataclass
class TimeSeriesRow:
    """Una fila de la serie temporal exportable (Frame, Player_ID, Pos_X_2D, Pos_Y_2D, Ball_X, Ball_Y)."""

    frame: int
    timestamp_s: float
    player_id: int | None
    pos_x_2d_m: float | None
    pos_y_2d_m: float | None
    ball_x_m: float | None
    ball_y_m: float | None

    def to_dict(self) -> dict:
        return {
            "frame": self.frame,
            "timestamp_s": round(self.timestamp_s, 3),
            "player_id": self.player_id,
            "pos_x_2d_m": None if self.pos_x_2d_m is None else round(self.pos_x_2d_m, 3),
            "pos_y_2d_m": None if self.pos_y_2d_m is None else round(self.pos_y_2d_m, 3),
            "ball_x_m": None if self.ball_x_m is None else round(self.ball_x_m, 3),
            "ball_y_m": None if self.ball_y_m is None else round(self.ball_y_m, 3),
        }


class CoordinateTransformer:
    """Aplica la homografía a las detecciones de un frame para obtener posiciones en metros."""

    def __init__(self, calibrator: CourtCalibrator):
        self.calibrator = calibrator

    def player_to_meters(self, foot_point_xy: tuple[float, float]) -> tuple[float, float]:
        return self.calibrator.project_point_to_meters(foot_point_xy)

    def ball_to_meters(self, point_xy: tuple[float, float]) -> tuple[float, float]:
        return self.calibrator.project_point_to_meters(point_xy)


class AnalyticsEngine:
    """
    Acumula la posición 2D de cada jugador y de la pelota frame a frame,
    y deriva analítica táctica: heatmaps de ocupación y series temporales.
    """

    def __init__(self, calibrator: CourtCalibrator, fps: float = 30.0, heatmap_bins: tuple[int, int] = (40, 20)):
        self.transformer = CoordinateTransformer(calibrator)
        self.geometry = calibrator.geometry
        self.fps = fps

        # bins del histograma 2D usado para el heatmap: (bins_x, bins_y).
        # 40x20 sobre una pista de 20x10m -> celdas de 0.5m x 0.5m.
        self.heatmap_bins = heatmap_bins

        self.rows: list[TimeSeriesRow] = []
        # posiciones (en metros) acumuladas por tracker_id, para poder
        # calcular heatmaps individuales y por pareja al final.
        self._positions_by_player: dict[int, list[tuple[float, float]]] = defaultdict(list)

    def ingest_frame(self, tracking_result: FrameTrackingResult) -> None:
        """Procesa el resultado de tracking de un frame y lo agrega a la serie temporal."""
        frame = tracking_result.frame_index
        timestamp_s = frame / self.fps if self.fps > 0 else 0.0

        ball_x_m = ball_y_m = None
        if tracking_result.ball is not None and tracking_result.ball.point_xy is not None:
            ball_x_m, ball_y_m = self.transformer.ball_to_meters(tracking_result.ball.point_xy)

        if not tracking_result.players:
            # igual dejamos una fila con la posición de la pelota, para no perder ese dato
            self.rows.append(
                TimeSeriesRow(frame, timestamp_s, None, None, None, ball_x_m, ball_y_m)
            )
            return

        for player in tracking_result.players:
            x_m, y_m = self.transformer.player_to_meters(player.foot_point)
            self.rows.append(
                TimeSeriesRow(frame, timestamp_s, player.tracker_id, x_m, y_m, ball_x_m, ball_y_m)
            )
            self._positions_by_player[player.tracker_id].append((x_m, y_m))

    # ------------------------------------------------------------------
    # Asignación de jugadores a "pareja cercana" / "pareja lejana" a la red.
    # ------------------------------------------------------------------
    def infer_teams(self) -> dict[int, str]:
        """
        Divide a los jugadores en dos parejas según su posición promedio
        respecto al eje largo de la pista (donde está la red, a mitad de
        los 20m). Esto es una heurística geométrica simple: en pádel cada
        pareja juega de un lado fijo de la red durante el punto.
        """
        net_x_m = self.geometry.length_m / 2.0
        teams: dict[int, str] = {}
        for player_id, positions in self._positions_by_player.items():
            avg_x = float(np.mean([p[0] for p in positions]))
            teams[player_id] = "pareja_A" if avg_x < net_x_m else "pareja_B"
        return teams

    # ------------------------------------------------------------------
    # Mapas de calor (matriz de ocupación)
    # ------------------------------------------------------------------
    def occupancy_grid(self, player_ids: list[int] | None = None) -> np.ndarray:
        """
        Genera la matriz de ocupación 2D (histograma) de las posiciones
        (en metros) de uno o varios jugadores sobre la pista. Sirve tanto
        para el heatmap individual (un solo player_id) como para el
        heatmap de pareja (pasando los 2 IDs de esa pareja).

        Se usa np.histogram2d: cada celda cuenta cuántas muestras de
        posición cayeron dentro de ella a lo largo del partido -> más
        muestras = más tiempo ocupando esa zona de la pista.
        """
        if player_ids is None:
            positions = [p for plist in self._positions_by_player.values() for p in plist]
        else:
            positions = [p for pid in player_ids for p in self._positions_by_player.get(pid, [])]

        if not positions:
            bins_x, bins_y = self.heatmap_bins
            return np.zeros((bins_y, bins_x), dtype=np.float64)

        xs = np.array([p[0] for p in positions])
        ys = np.array([p[1] for p in positions])

        bins_x, bins_y = self.heatmap_bins
        hist, _, _ = np.histogram2d(
            xs, ys,
            bins=[bins_x, bins_y],
            range=[[0, self.geometry.length_m], [0, self.geometry.width_m]],
        )
        # transponemos para que quede en orden (fila=Y, columna=X), convención
        # estándar para visualizar con imshow/matplotlib.
        return hist.T

    def heatmaps_by_team(self) -> dict[str, np.ndarray]:
        """Heatmap agregado por pareja (par de jugadores que comparten lado de la red)."""
        teams = self.infer_teams()
        grouped: dict[str, list[int]] = defaultdict(list)
        for player_id, team in teams.items():
            grouped[team].append(player_id)

        return {team: self.occupancy_grid(ids) for team, ids in grouped.items()}

    def heatmaps_by_player(self) -> dict[int, np.ndarray]:
        return {pid: self.occupancy_grid([pid]) for pid in self._positions_by_player.keys()}

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    def to_records(self) -> list[dict]:
        return [row.to_dict() for row in self.rows]
