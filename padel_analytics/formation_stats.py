"""
Formación y juego de red.

La investigación en pádel de rendimiento (comparación de niveles nacional
vs. principiante, estudios de juego de red) marca la formación de pareja
y el dominio de la red como uno de los indicadores más fuertes de nivel:
en pádel, ganar un punto desde el fondo es mucho más difícil que desde la
red, y las parejas de nivel alto juegan en la red mucho más tiempo y de
forma más sincronizada que las principiantes.

Todo se deriva de la serie temporal de posiciones 2D ya calculada
(`timeseries.json`) — no hace falta ningún dato ni modelo adicional.
Convención de ejes (ver `CourtGeometry`): Y = largo de la pista (fondo a
fondo), la red está a mitad de ese eje.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .config import CourtGeometry
from .match_stats import PointOutcome


def _zone(pos_y_m: float, net_y_m: float, net_zone_m: float) -> str:
    return "red" if abs(pos_y_m - net_y_m) <= net_zone_m else "fondo"


def player_zone_time(
    records: list[dict], geometry: CourtGeometry, net_zone_m: float = 3.0
) -> dict[int, dict]:
    """% del tiempo que cada jugador pasó en la zona de red vs. en el fondo."""
    net_y_m = geometry.length_m / 2.0
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"red": 0, "fondo": 0})

    for r in records:
        pid = r.get("player_id")
        y = r.get("pos_y_2d_m")
        if pid is None or y is None:
            continue
        counts[pid][_zone(y, net_y_m, net_zone_m)] += 1

    result = {}
    for pid, c in counts.items():
        total = c["red"] + c["fondo"]
        result[pid] = {
            "net_pct": round(c["red"] / total * 100, 1) if total else 0.0,
            "baseline_pct": round(c["fondo"] / total * 100, 1) if total else 0.0,
            "samples": total,
        }
    return result


def _positions_by_frame_and_player(records: list[dict]) -> dict[int, dict[int, tuple[float, float]]]:
    """frame -> {player_id: (x_m, y_m)} para poder mirar "el mismo instante" entre compañeros."""
    by_frame: dict[int, dict[int, tuple[float, float]]] = defaultdict(dict)
    for r in records:
        pid = r.get("player_id")
        x, y = r.get("pos_x_2d_m"), r.get("pos_y_2d_m")
        if pid is not None and x is not None and y is not None:
            by_frame[r["frame"]][pid] = (x, y)
    return by_frame


def team_formation_time(
    records: list[dict],
    player_teams: dict[str, str],
    geometry: CourtGeometry,
    net_zone_m: float = 3.0,
) -> dict[str, dict]:
    """
    Para cada pareja, en qué formación estuvieron parados la mayor parte
    del tiempo: ambos en la red, ambos en el fondo, o mixta (uno arriba,
    uno atrás) — la formación "australiana" al saque cae en esta última
    categoría si el que no saca se para en la red.
    """
    net_y_m = geometry.length_m / 2.0
    team_of: dict[int, str] = {int(pid): team for pid, team in player_teams.items()}

    by_frame = _positions_by_frame_and_player(records)
    by_team_players: dict[str, list[int]] = defaultdict(list)
    for pid, team in team_of.items():
        by_team_players[team].append(pid)

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"ambos_red": 0, "ambos_fondo": 0, "mixta": 0})

    for players_here in by_frame.values():
        for team, member_ids in by_team_players.items():
            positions = [players_here[pid] for pid in member_ids if pid in players_here]
            if len(positions) < 2:
                continue  # necesitamos a los 2 miembros de la pareja en el mismo frame
            zones = [_zone(y, net_y_m, net_zone_m) for _, y in positions]
            if all(z == "red" for z in zones):
                counts[team]["ambos_red"] += 1
            elif all(z == "fondo" for z in zones):
                counts[team]["ambos_fondo"] += 1
            else:
                counts[team]["mixta"] += 1

    result = {}
    for team, c in counts.items():
        total = c["ambos_red"] + c["ambos_fondo"] + c["mixta"]
        result[team] = {
            "ambos_red_pct": round(c["ambos_red"] / total * 100, 1) if total else 0.0,
            "ambos_fondo_pct": round(c["ambos_fondo"] / total * 100, 1) if total else 0.0,
            "mixta_pct": round(c["mixta"] / total * 100, 1) if total else 0.0,
            "samples": total,
        }
    return result


def partner_distance_stats(records: list[dict], player_teams: dict[str, str]) -> dict[str, dict]:
    """Distancia entre los dos integrantes de cada pareja (sincronía/cobertura conjunta)."""
    team_of: dict[int, str] = {int(pid): team for pid, team in player_teams.items()}
    by_frame = _positions_by_frame_and_player(records)
    by_team_players: dict[str, list[int]] = defaultdict(list)
    for pid, team in team_of.items():
        by_team_players[team].append(pid)

    distances: dict[str, list[float]] = defaultdict(list)
    for players_here in by_frame.values():
        for team, member_ids in by_team_players.items():
            positions = [players_here[pid] for pid in member_ids if pid in players_here]
            if len(positions) < 2:
                continue
            (x1, y1), (x2, y2) = positions[0], positions[1]
            distances[team].append(math.hypot(x2 - x1, y2 - y1))

    result = {}
    for team, dists in distances.items():
        result[team] = {
            "avg_distance_m": round(sum(dists) / len(dists), 2),
            "min_distance_m": round(min(dists), 2),
            "max_distance_m": round(max(dists), 2),
            "samples": len(dists),
        }
    return result


def net_conversion_rate(
    outcomes: list[PointOutcome],
    records: list[dict],
    geometry: CourtGeometry,
    net_zone_m: float = 3.0,
) -> dict[str, dict]:
    """
    De los puntos donde se pudo determinar quién tocó la pelota por última
    vez, compara la tasa de puntos ganados según si esa persona estaba en
    la zona de red o en el fondo en ese momento — la métrica que la
    investigación marca como el indicador más fuerte de nivel de juego.
    """
    net_y_m = geometry.length_m / 2.0
    pos_by_player_frame: dict[tuple[int, int], float] = {}
    for r in records:
        pid = r.get("player_id")
        y = r.get("pos_y_2d_m")
        if pid is not None and y is not None:
            pos_by_player_frame.setdefault((pid, r["frame"]), y)

    counts: dict[str, dict[str, int]] = {
        "red": {"WIN": 0, "LOSS": 0},
        "fondo": {"WIN": 0, "LOSS": 0},
    }
    for outcome in outcomes:
        if outcome.outcome_for_last_touch is None or outcome.last_touch_player_id is None:
            continue
        y = pos_by_player_frame.get((outcome.last_touch_player_id, outcome.last_touch_frame))
        if y is None:
            continue
        zone = _zone(y, net_y_m, net_zone_m)
        counts[zone][outcome.outcome_for_last_touch] += 1

    result = {}
    for zone, c in counts.items():
        total = c["WIN"] + c["LOSS"]
        result[zone] = {
            "wins": c["WIN"],
            "losses": c["LOSS"],
            "total": total,
            "win_pct": round(c["WIN"] / total * 100, 1) if total else None,
        }
    return result
