"""
Mapas de eficacia por zona: dónde en la pista terminan los puntos
(winners vs. errores) y dónde caen los saques. Se arman cruzando los
golpes (posición de la pelota en cada golpe, ya guardada en `ShotEvent`)
con los puntos y sus resultados (`match_stats.PointOutcome`) — no hace
falta recalcular ninguna posición desde cero.
"""

from __future__ import annotations

from .points import PointEvent
from .shot_detection import ShotEvent
from .match_stats import PointOutcome


def winners_errors_positions(
    outcomes: list[PointOutcome], shots_by_id: dict[str, ShotEvent]
) -> dict[str, list[tuple[float, float]]]:
    """Posición (x_m, y_m) de la pelota en el golpe que definió cada punto, separadas por WIN/LOSS."""
    positions: dict[str, list[tuple[float, float]]] = {"WIN": [], "LOSS": []}
    for outcome in outcomes:
        if outcome.outcome_for_last_touch is None:
            continue
        shot = shots_by_id.get(outcome.last_touch_shot_id)
        if shot is None or shot.ball_x_m is None:
            continue
        positions[outcome.outcome_for_last_touch].append((shot.ball_x_m, shot.ball_y_m))
    return positions


def serve_placement_positions(points: list[PointEvent], shots: list[ShotEvent]) -> list[dict]:
    """
    Para cada punto cerrado, la posición de la pelota en el primer golpe
    dentro de su rango de frames — el saque. Se ordenan los golpes del
    punto por frame y se toma el primero con posición de pelota conocida.
    """
    serves = []
    for point in points:
        if not point.is_closed:
            continue
        in_range = sorted(
            (s for s in shots if point.start_frame <= s.frame <= point.end_frame and s.ball_x_m is not None),
            key=lambda s: s.frame,
        )
        if in_range:
            first = in_range[0]
            serves.append({
                "point_id": point.id,
                "x_m": first.ball_x_m,
                "y_m": first.ball_y_m,
                "player_id": first.player_id,
                "winner_team": point.winner_team,
            })
    return serves
