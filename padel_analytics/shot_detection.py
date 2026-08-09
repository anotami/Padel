"""
Seguimiento y etiquetado de golpes.

Dos piezas:
  * `ShotDetector`: heurística automática que propone "candidatos a golpe"
    analizando la trayectoria 2D de la pelota (cambios bruscos de
    dirección/velocidad = posible impacto de paleta) y los asocia al
    jugador más cercano en ese instante. No reemplaza un clasificador
    entrenado, pero da un punto de partida razonable y barato de calcular.
  * `ShotLabelStore`: persistencia simple (JSON) de los golpes, ya sea
    los propuestos automáticamente o los que el usuario etiqueta a mano
    desde la webapp (fase de "permitir etiquetar golpes").
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from .coordinates import TimeSeriesRow


# Tipos de golpe sugeridos en la UI de etiquetado (el usuario puede
# escribir uno distinto igual, esto es sólo una lista de referencia).
SHOT_TYPES = [
    "derecha",
    "reves",
    "volea_derecha",
    "volea_reves",
    "bandeja",
    "vibora",
    "smash",
    "saque",
    "globo",
    "bajada_de_pared",
]


@dataclass
class ShotEvent:
    id: str
    frame: int
    timestamp_s: float
    player_id: int | None
    ball_x_m: float | None
    ball_y_m: float | None
    shot_type: str | None = None       # None mientras no fue etiquetado por el usuario
    auto_detected: bool = True
    confidence: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ShotEvent":
        return cls(**data)


class ShotDetector:
    """
    Heurística de detección de golpes basada en la trayectoria de la
    pelota en el plano 2D (metros):

      1. Se calcula la velocidad instantánea de la pelota entre frames
         consecutivos (vector diferencia / delta_t).
      2. Un "golpe" se aproxima como un punto donde el ángulo de la
         velocidad cambia bruscamente (rebote de paleta) y la pelota está
         cerca de algún jugador -- una pared o el piso también generan
         cambios de dirección, por eso se prioriza la cercanía a un jugador
         para decidir el `player_id` asociado, y se guarda todo con
         auto_detected=True para que el usuario lo confirme/corrija.
    """

    def __init__(
        self,
        min_angle_change_deg: float = 35.0,
        min_speed_mps: float = 2.0,
        max_player_distance_m: float = 2.5,
        min_frames_between_shots: int = 8,
    ):
        self.min_angle_change_deg = min_angle_change_deg
        self.min_speed_mps = min_speed_mps
        self.max_player_distance_m = max_player_distance_m
        self.min_frames_between_shots = min_frames_between_shots

    def detect(self, rows: list[TimeSeriesRow], fps: float) -> list[ShotEvent]:
        # Reconstruimos, frame por frame, la trayectoria de la pelota y las
        # posiciones de todos los jugadores presentes en ese frame.
        ball_by_frame: dict[int, tuple[float, float]] = {}
        players_by_frame: dict[int, list[tuple[int, float, float]]] = {}

        for row in rows:
            if row.ball_x_m is not None and row.frame not in ball_by_frame:
                ball_by_frame[row.frame] = (row.ball_x_m, row.ball_y_m)
            if row.player_id is not None and row.pos_x_2d_m is not None:
                players_by_frame.setdefault(row.frame, []).append(
                    (row.player_id, row.pos_x_2d_m, row.pos_y_2d_m)
                )

        frames = sorted(ball_by_frame.keys())
        if len(frames) < 3:
            return []

        events: list[ShotEvent] = []
        last_shot_frame = -10_000

        for i in range(1, len(frames) - 1):
            f_prev, f_curr, f_next = frames[i - 1], frames[i], frames[i + 1]
            if f_curr - last_shot_frame < self.min_frames_between_shots:
                continue

            p_prev = np.array(ball_by_frame[f_prev])
            p_curr = np.array(ball_by_frame[f_curr])
            p_next = np.array(ball_by_frame[f_next])

            dt_in = max((f_curr - f_prev) / fps, 1e-6)
            dt_out = max((f_next - f_curr) / fps, 1e-6)

            v_in = (p_curr - p_prev) / dt_in
            v_out = (p_next - p_curr) / dt_out

            speed_in = float(np.linalg.norm(v_in))
            speed_out = float(np.linalg.norm(v_out))

            if max(speed_in, speed_out) < self.min_speed_mps:
                continue

            angle_change = self._angle_between(v_in, v_out)
            if angle_change < self.min_angle_change_deg:
                continue

            # Buscamos el jugador más cercano a la pelota en el frame del posible golpe.
            nearest_player_id, nearest_dist = self._nearest_player(
                p_curr, players_by_frame.get(f_curr, [])
            )
            if nearest_player_id is None or nearest_dist > self.max_player_distance_m:
                continue  # probablemente rebote en pared/piso, no un golpe de jugador

            confidence = float(np.clip(angle_change / 180.0, 0.0, 1.0))
            events.append(
                ShotEvent(
                    id=str(uuid.uuid4()),
                    frame=int(f_curr),
                    timestamp_s=f_curr / fps,
                    player_id=nearest_player_id,
                    ball_x_m=float(p_curr[0]),
                    ball_y_m=float(p_curr[1]),
                    shot_type=None,
                    auto_detected=True,
                    confidence=round(confidence, 3),
                )
            )
            last_shot_frame = f_curr

        return events

    @staticmethod
    def _angle_between(v1: np.ndarray, v2: np.ndarray) -> float:
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cos_angle = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
        return float(np.degrees(np.arccos(cos_angle)))

    @staticmethod
    def _nearest_player(
        ball_pos: np.ndarray, players: list[tuple[int, float, float]]
    ) -> tuple[int | None, float]:
        if not players:
            return None, float("inf")
        dists = [
            (pid, float(np.linalg.norm(ball_pos - np.array([x, y]))))
            for pid, x, y in players
        ]
        dists.sort(key=lambda t: t[1])
        return dists[0]


class ShotLabelStore:
    """Persistencia JSON de los golpes (auto-detectados + etiquetados a mano) de un video."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._events: list[ShotEvent] = []
        if self.path.exists():
            self.load()

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._events = [ShotEvent.from_dict(e) for e in data]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([e.to_dict() for e in self._events], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def set_auto_detected(self, events: list[ShotEvent]) -> None:
        """Reemplaza los eventos auto-detectados, preservando los que ya fueron etiquetados a mano."""
        manual = [e for e in self._events if not e.auto_detected]
        self._events = manual + events
        self._events.sort(key=lambda e: e.frame)
        self.save()

    def add_manual_shot(
        self,
        frame: int,
        timestamp_s: float,
        player_id: int | None,
        shot_type: str,
        ball_x_m: float | None = None,
        ball_y_m: float | None = None,
        note: str = "",
    ) -> ShotEvent:
        event = ShotEvent(
            id=str(uuid.uuid4()),
            frame=frame,
            timestamp_s=timestamp_s,
            player_id=player_id,
            ball_x_m=ball_x_m,
            ball_y_m=ball_y_m,
            shot_type=shot_type,
            auto_detected=False,
            confidence=1.0,
            note=note,
        )
        self._events.append(event)
        self._events.sort(key=lambda e: e.frame)
        self.save()
        return event

    def update_shot(self, shot_id: str, **fields) -> ShotEvent | None:
        for event in self._events:
            if event.id == shot_id:
                for key, value in fields.items():
                    if hasattr(event, key):
                        setattr(event, key, value)
                self.save()
                return event
        return None

    def delete_shot(self, shot_id: str) -> bool:
        before = len(self._events)
        self._events = [e for e in self._events if e.id != shot_id]
        if len(self._events) != before:
            self.save()
            return True
        return False

    def all(self) -> list[ShotEvent]:
        return list(self._events)

    def to_records(self) -> list[dict]:
        return [e.to_dict() for e in self._events]
