"""
Momentum y ritmo del partido: cómo evolucionó el marcador punto a punto,
distribución de cuánto duran los rallies, y comparación de la primera
mitad del partido contra la segunda (¿bajó el ritmo por cansancio, o subió
la efectividad al entrar en calor?). Todo se deriva de `points.json` +
`shots.json` + `timeseries.json` ya calculados.
"""

from __future__ import annotations

from collections import defaultdict

from .points import PointEvent
from .shot_detection import ShotEvent
from . import match_stats, performance_stats


def momentum_timeline(points: list[PointEvent]) -> list[dict]:
    """
    Marcador acumulado punto a punto, en el orden en que ocurrieron (por
    frame de inicio). Sólo se cuentan los puntos cerrados con ganador
    confirmado — un punto "pendiente de confirmar" todavía no suma.
    """
    closed = sorted(
        (p for p in points if p.is_closed and p.winner_team), key=lambda p: p.start_frame
    )
    scores: dict[str, int] = {}
    timeline = []
    for i, p in enumerate(closed):
        scores[p.winner_team] = scores.get(p.winner_team, 0) + 1
        timeline.append({
            "point_index": i + 1,
            "frame": p.start_frame,
            "timestamp_s": p.start_timestamp_s,
            "winner_team": p.winner_team,
            "scores": dict(scores),
        })
    return timeline


def rally_duration_histogram(points: list[PointEvent], bucket_size_s: float = 5.0) -> list[dict]:
    """Distribución de cuánto duraron los rallies, agrupados en baldes de `bucket_size_s` segundos."""
    closed = [p for p in points if p.is_closed and p.duration_s is not None]
    if not closed:
        return []

    buckets: dict[int, int] = defaultdict(int)
    for p in closed:
        buckets[int(p.duration_s // bucket_size_s)] += 1

    max_bucket = max(buckets)
    return [
        {
            "bucket_label": f"{i * bucket_size_s:.0f}-{(i + 1) * bucket_size_s:.0f}s",
            "count": buckets.get(i, 0),
        }
        for i in range(max_bucket + 1)
    ]


def compare_halves(
    points: list[PointEvent],
    shots: list[ShotEvent],
    records: list[dict],
    fps: float,
) -> dict:
    """
    Compara la primera mitad del partido (por cantidad de puntos jugados)
    contra la segunda: duración de rally y velocidad media de los
    jugadores en cada tramo — una caída notable en la segunda mitad es un
    indicio de cansancio; una suba, de que el partido "se picó" o costó
    entrar en calor.
    """
    closed = sorted((p for p in points if p.is_closed), key=lambda p: p.start_frame)
    if len(closed) < 2:
        return {"first_half": None, "second_half": None}

    midpoint = len(closed) // 2
    first_points, second_points = closed[:midpoint], closed[midpoint:]
    cutoff_frame = second_points[0].start_frame

    first_records = [r for r in records if r["frame"] < cutoff_frame]
    second_records = [r for r in records if r["frame"] >= cutoff_frame]

    def _half_summary(pts: list[PointEvent], recs: list[dict]) -> dict:
        movement = performance_stats.player_movement_stats(recs, fps)
        avg_speed = (
            round(sum(m["avg_speed_kmh"] for m in movement.values()) / len(movement), 1)
            if movement else 0.0
        )
        return {
            "rally_stats": match_stats.rally_stats(pts, shots, fps),
            "avg_player_speed_kmh": avg_speed,
        }

    return {
        "first_half": _half_summary(first_points, first_records),
        "second_half": _half_summary(second_points, second_records),
    }
