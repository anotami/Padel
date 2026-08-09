"""
Estadísticas derivadas del partido: cruza los golpes (`shot_detection`) con
los puntos (`points`) para calcular, automáticamente:

  1. Quién tocó la pelota por última vez en cada punto, y si ese punto fue
     WIN (golpe ganador: su pareja terminó ganando el punto) o LOSS (error,
     forzado o no forzado: su pareja terminó perdiendo el punto) para esa
     persona. Es la convención estándar de pádel/tenis: todo punto termina
     con un "winner" o con un error del último que tocó la bola.
  2. El conteo total de golpes por jugador (útil para ver quién más
     participó del punto en juego, no sólo quién lo definió).

No requiere entrenar nada: es puro cruce de los datos ya calculados por
`AnalyticsEngine` (equipos), `ShotDetector`/`ShotLabelStore` (golpes) y
`PointLabelStore` (puntos).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .points import PointEvent
from .shot_detection import ShotEvent


@dataclass
class PointOutcome:
    """Resultado derivado de un punto: quién lo definió y cómo."""

    point_id: str
    start_frame: int
    end_frame: int
    winner_team: str | None
    last_touch_player_id: int | None
    last_touch_shot_id: str | None
    last_touch_frame: int | None
    last_touch_shot_type: str | None
    last_touch_team: str | None
    # "WIN"  -> el último en tocar la pelota terminó ganando el punto (golpe ganador)
    # "LOSS" -> el último en tocar la pelota terminó perdiendo el punto (error propio)
    # None   -> no se pudo determinar (sin golpes registrados en el rango del punto,
    #           o el video todavía no fue procesado y no hay equipos inferidos)
    outcome_for_last_touch: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _last_shot_in_range(shots: list[ShotEvent], start_frame: int, end_frame: int) -> ShotEvent | None:
    """
    El golpe con mayor número de frame dentro de [start_frame, end_frame].
    Es el candidato a "última pelota tocada" antes de que el punto termine
    (por definición del punto: winner o error en ese último contacto).
    """
    candidates = [
        s for s in shots
        if s.player_id is not None and start_frame <= s.frame <= end_frame
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.frame)


def compute_point_outcomes(
    points: list[PointEvent],
    shots: list[ShotEvent],
    player_teams: dict[str, str],
) -> list[PointOutcome]:
    """
    player_teams: mapea player_id (como string, tal cual se guarda en
    metadata.json) -> nombre de pareja ("pareja_A"/"pareja_B"). Viene de
    `AnalyticsEngine.infer_teams()` guardado por el pipeline.
    """
    outcomes: list[PointOutcome] = []

    for point in points:
        if not point.is_closed:
            continue  # un punto abierto todavía no tiene ganador ni rango final

        last_shot = _last_shot_in_range(shots, point.start_frame, point.end_frame)

        last_touch_team = None
        outcome = None
        if last_shot is not None:
            last_touch_team = player_teams.get(str(last_shot.player_id))
            if last_touch_team is not None and point.winner_team is not None:
                outcome = "WIN" if last_touch_team == point.winner_team else "LOSS"

        outcomes.append(
            PointOutcome(
                point_id=point.id,
                start_frame=point.start_frame,
                end_frame=point.end_frame,
                winner_team=point.winner_team,
                last_touch_player_id=last_shot.player_id if last_shot else None,
                last_touch_shot_id=last_shot.id if last_shot else None,
                last_touch_frame=last_shot.frame if last_shot else None,
                last_touch_shot_type=last_shot.shot_type if last_shot else None,
                last_touch_team=last_touch_team,
                outcome_for_last_touch=outcome,
            )
        )

    return outcomes


def shots_per_player(shots: list[ShotEvent]) -> dict[int, int]:
    """Conteo total de golpes (auto-detectados + manuales) por player_id."""
    counts: dict[int, int] = {}
    for shot in shots:
        if shot.player_id is not None:
            counts[shot.player_id] = counts.get(shot.player_id, 0) + 1
    return counts


def player_win_loss_counts(outcomes: list[PointOutcome]) -> dict[int, dict[str, int]]:
    """
    Por jugador: cuántos puntos definió con golpe ganador (WIN) vs. cuántos
    perdió por error propio (LOSS), contando sólo los puntos donde fue la
    última persona en tocar la pelota.
    """
    result: dict[int, dict[str, int]] = {}
    for outcome in outcomes:
        if outcome.last_touch_player_id is None or outcome.outcome_for_last_touch is None:
            continue
        entry = result.setdefault(outcome.last_touch_player_id, {"WIN": 0, "LOSS": 0})
        entry[outcome.outcome_for_last_touch] += 1
    return result
