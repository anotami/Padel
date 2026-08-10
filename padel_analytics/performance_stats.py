"""
Métricas de rendimiento físico, inspiradas en lo que ofrecen las plataformas
comerciales de análisis de pádel (Padelytics, Padmi, GameCam, PlaySight):
distancia recorrida, velocidad, sprints, cobertura de cancha y velocidad de
la pelota en cada golpe. Todo se deriva de datos que el sistema ya calcula
(serie temporal de posiciones 2D + golpes) — no hace falta ningún sensor ni
modelo adicional.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .config import CourtGeometry
from .shot_detection import ShotEvent


def player_movement_stats(
    records: list[dict],
    fps: float,
    max_step_distance_m: float = 3.0,
    max_speed_kmh: float = 40.0,
    sprint_threshold_kmh: float = 15.0,
    min_sprint_frames: int = 5,
) -> dict[int, dict]:
    """
    Distancia recorrida y velocidad por jugador, a partir de la serie
    temporal de posiciones 2D (records = timeseries.json/csv ya exportado).

    Cada paso entre dos frames consecutivos con posición conocida del
    mismo jugador se convierte en una velocidad instantánea (m/s -> km/h).
    Se descartan pasos con distancia o velocidad absurdas
    (`max_step_distance_m` / `max_speed_kmh`): son saltos de identidad
    (el jugador "cambió" de posición de golpe, ej. una reidentificación
    imperfecta) y no movimiento real, así que no deben sumar a la
    distancia total ni inflar la velocidad máxima.

    Un "sprint" se cuenta cuando la velocidad se mantiene por encima de
    `sprint_threshold_kmh` durante al menos `min_sprint_frames` pasos
    consecutivos (evita contar como sprint un único frame ruidoso).
    """
    by_player: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for r in records:
        if r.get("player_id") is not None and r.get("pos_x_2d_m") is not None:
            by_player[r["player_id"]].append((r["frame"], r["pos_x_2d_m"], r["pos_y_2d_m"]))

    results: dict[int, dict] = {}
    for player_id, points in by_player.items():
        points.sort(key=lambda t: t[0])

        total_distance_m = 0.0
        speeds_kmh: list[float] = []
        sprint_count = 0
        consecutive_fast = 0

        for (f0, x0, y0), (f1, x1, y1) in zip(points, points[1:]):
            dt_s = (f1 - f0) / fps if fps > 0 else 0
            if dt_s <= 0:
                continue

            dist_m = math.hypot(x1 - x0, y1 - y0)
            speed_kmh = (dist_m / dt_s) * 3.6

            if dist_m > max_step_distance_m or speed_kmh > max_speed_kmh:
                # salto no físico (probable reidentificación imperfecta): se ignora
                consecutive_fast = 0
                continue

            total_distance_m += dist_m
            speeds_kmh.append(speed_kmh)

            if speed_kmh >= sprint_threshold_kmh:
                consecutive_fast += 1
                if consecutive_fast == min_sprint_frames:
                    sprint_count += 1
            else:
                consecutive_fast = 0

        results[player_id] = {
            "distance_m": round(total_distance_m, 1),
            "avg_speed_kmh": round(float(np.mean(speeds_kmh)), 1) if speeds_kmh else 0.0,
            "max_speed_kmh": round(float(np.max(speeds_kmh)), 1) if speeds_kmh else 0.0,
            "sprints": sprint_count,
        }

    return results


def court_coverage_pct(
    records: list[dict],
    geometry: CourtGeometry,
    player_ids: list[int] | None = None,
    bins: tuple[int, int] = (20, 40),
) -> float:
    """
    Porcentaje de la pista "cubierto" por uno o varios jugadores: cuántas
    celdas de una grilla de ocupación (misma convención de ejes que
    AnalyticsEngine.occupancy_grid) tuvieron al menos una posición
    registrada, sobre el total de celdas.
    """
    xs, ys = [], []
    for r in records:
        pid = r.get("player_id")
        if pid is None or r.get("pos_x_2d_m") is None:
            continue
        if player_ids is not None and pid not in player_ids:
            continue
        xs.append(r["pos_x_2d_m"])
        ys.append(r["pos_y_2d_m"])

    if not xs:
        return 0.0

    hist, _, _ = np.histogram2d(
        xs, ys, bins=bins, range=[[0, geometry.width_m], [0, geometry.length_m]]
    )
    covered_cells = int(np.count_nonzero(hist))
    total_cells = hist.size
    return round(covered_cells / total_cells * 100, 1) if total_cells else 0.0


def compute_ball_speeds_for_shots(
    records: list[dict], shots: list[ShotEvent], fps: float, window_frames: int = 3
) -> dict[str, float]:
    """
    Velocidad de "salida" de la pelota en cada golpe: mide cuánto se
    desplazó la pelota entre el frame del golpe y hasta `window_frames`
    después, y la convierte a km/h. Sirve como proxy de la potencia del
    golpe (un smash desplaza la pelota mucho más rápido que un globo).
    """
    ball_by_frame: dict[int, tuple[float, float]] = {}
    for r in records:
        if r.get("ball_x_m") is not None and r["frame"] not in ball_by_frame:
            ball_by_frame[r["frame"]] = (r["ball_x_m"], r["ball_y_m"])

    sorted_frames = sorted(ball_by_frame.keys())
    if not sorted_frames:
        return {}

    speeds: dict[str, float] = {}
    for shot in shots:
        candidates = [f for f in sorted_frames if shot.frame <= f <= shot.frame + window_frames]
        if len(candidates) < 2:
            continue

        f0, f1 = candidates[0], candidates[-1]
        p0, p1 = ball_by_frame[f0], ball_by_frame[f1]
        dt_s = (f1 - f0) / fps if fps > 0 else 0
        if dt_s <= 0:
            continue

        dist_m = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        speeds[shot.id] = round((dist_m / dt_s) * 3.6, 1)

    return speeds
