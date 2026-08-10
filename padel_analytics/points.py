"""
Segmentación de puntos (rallies) del partido.

`PointEvent` marca el inicio y el fin de un punto (frame + timestamp de
cada borde) y quién lo ganó. Con esto se puede filtrar cualquier otra
analítica ya calculada (serie temporal de posiciones, golpes detectados)
al rango de frames de un punto puntual, sin necesidad de recortar
físicamente el video en clips separados.

`PointDetector` propone puntos automáticamente agrupando los golpes ya
detectados (mismo espíritu que `ShotDetector`): no hace falta marcar cada
punto a mano para tener analítica de entrada, sólo confirmar/corregir el
ganador de cada uno (eso sí requiere criterio humano — no se puede inferir
sólo de la trayectoria de la pelota).

`PointLabelStore` persiste los puntos en JSON (mismo patrón que
`ShotLabelStore`) y expone un resumen de marcador: puntos ganados por
cada pareja.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from .shot_detection import ShotEvent


@dataclass
class PointEvent:
    id: str
    start_frame: int
    start_timestamp_s: float
    end_frame: int | None = None
    end_timestamp_s: float | None = None
    winner_team: str | None = None   # ej. "pareja_A" / "pareja_B"; None mientras el punto sigue abierto o sin confirmar
    note: str = ""
    auto_detected: bool = False      # True si lo propuso PointDetector y el usuario todavía no lo confirmó/corrigió

    @property
    def is_closed(self) -> bool:
        return self.end_frame is not None

    @property
    def duration_s(self) -> float | None:
        if self.end_timestamp_s is None:
            return None
        return round(self.end_timestamp_s - self.start_timestamp_s, 2)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["is_closed"] = self.is_closed
        data["duration_s"] = self.duration_s
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PointEvent":
        # is_closed/duration_s son derivados, no campos propios del dataclass
        data = {k: v for k, v in data.items() if k not in ("is_closed", "duration_s")}
        return cls(**data)


class PointLabelStore:
    """
    Persistencia JSON de los puntos marcados de un video, con la regla de
    negocio de que sólo puede haber un punto abierto (sin `end_frame`) a
    la vez: no tiene sentido marcar el inicio de un punto nuevo mientras
    el anterior no fue cerrado con un ganador.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._points: list[PointEvent] = []
        if self.path.exists():
            self.load()

    def load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._points = [PointEvent.from_dict(p) for p in data]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([p.to_dict() for p in self._points], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def open_point(self) -> PointEvent | None:
        return next((p for p in self._points if not p.is_closed), None)

    def start_point(self, frame: int, timestamp_s: float) -> PointEvent:
        if self.open_point() is not None:
            raise ValueError("Ya hay un punto abierto sin cerrar. Cerralo antes de marcar uno nuevo.")

        event = PointEvent(
            id=str(uuid.uuid4()), start_frame=frame, start_timestamp_s=timestamp_s
        )
        self._points.append(event)
        self._points.sort(key=lambda p: p.start_frame)
        self.save()
        return event

    def close_point(
        self, point_id: str, frame: int, timestamp_s: float, winner_team: str, note: str = ""
    ) -> PointEvent:
        point = self._get(point_id)
        if point is None:
            raise KeyError(f"Punto no encontrado: {point_id}")
        if frame < point.start_frame:
            raise ValueError("El frame de fin no puede ser anterior al frame de inicio del punto.")

        point.end_frame = frame
        point.end_timestamp_s = timestamp_s
        point.winner_team = winner_team
        point.note = note
        self.save()
        return point

    def update_point(self, point_id: str, **fields) -> PointEvent | None:
        point = self._get(point_id)
        if point is None:
            return None
        for key, value in fields.items():
            if hasattr(point, key):
                setattr(point, key, value)
        # una vez que el usuario edita un punto (confirma el ganador, corrige
        # el rango, etc.) se lo trata como definitivo: si se reprocesa el
        # video, PointDetector no debe pisarlo con una nueva propuesta.
        point.auto_detected = False
        self.save()
        return point

    def set_auto_detected(self, points: list[PointEvent]) -> None:
        """Reemplaza los puntos propuestos automáticamente, preservando los creados o editados a mano."""
        manual = [p for p in self._points if not p.auto_detected]
        self._points = manual + points
        self._points.sort(key=lambda p: p.start_frame)
        self.save()

    def delete_point(self, point_id: str) -> bool:
        before = len(self._points)
        self._points = [p for p in self._points if p.id != point_id]
        if len(self._points) != before:
            self.save()
            return True
        return False

    def _get(self, point_id: str) -> PointEvent | None:
        return next((p for p in self._points if p.id == point_id), None)

    def all(self) -> list[PointEvent]:
        return list(self._points)

    def to_records(self) -> list[dict]:
        return [p.to_dict() for p in self._points]

    def points_in_range(self, start_frame: int, end_frame: int) -> list[PointEvent]:
        """Puntos cuyo rango se solapa con [start_frame, end_frame] (para filtrar otra analítica)."""
        return [
            p for p in self._points
            if p.is_closed and p.start_frame <= end_frame and p.end_frame >= start_frame
        ]

    def summary(self) -> dict:
        """
        Marcador agregado: cantidad de puntos ganados por cada pareja +
        duración promedio del punto (rally), sólo sobre los puntos cerrados.
        """
        closed = [p for p in self._points if p.is_closed]
        wins: dict[str, int] = {}
        for p in closed:
            if p.winner_team:
                wins[p.winner_team] = wins.get(p.winner_team, 0) + 1

        durations = [p.duration_s for p in closed if p.duration_s is not None]
        avg_duration = round(sum(durations) / len(durations), 2) if durations else None

        return {
            "total_points": len(closed),
            "points_by_team": wins,
            "avg_rally_duration_s": avg_duration,
            "has_open_point": self.open_point() is not None,
            "pending_confirmation": sum(1 for p in closed if p.winner_team is None),
        }


class PointDetector:
    """
    Propone puntos (rallies) automáticamente agrupando los golpes ya
    detectados (`ShotDetector`/etiquetados a mano): un hueco largo sin
    ningún golpe se interpreta como el tiempo muerto entre un punto y el
    siguiente (se va a buscar la pelota, se prepara el saque); un hueco
    corto significa que el punto sigue en curso.

    El ganador queda sin definir (`winner_team=None`, "pendiente de
    confirmar"): no se puede inferir de forma confiable con sólo la
    trayectoria 2D si la pelota terminó afuera, en la red, etc. — eso lo
    confirma o corrige el usuario desde la webapp (así todo lo automático
    sigue siendo 100% corregible).
    """

    def __init__(
        self,
        max_gap_s: float = 4.0,
        pre_roll_s: float = 0.5,
        post_roll_s: float = 1.2,
        min_shots_per_point: int = 1,
    ):
        self.max_gap_s = max_gap_s
        self.pre_roll_s = pre_roll_s
        self.post_roll_s = post_roll_s
        self.min_shots_per_point = min_shots_per_point

    def detect(
        self, shots: list[ShotEvent], fps: float, total_frames: int | None = None
    ) -> list[PointEvent]:
        if not shots or fps <= 0:
            return []

        ordered = sorted((s for s in shots if s.frame is not None), key=lambda s: s.frame)
        if not ordered:
            return []

        max_gap_frames = self.max_gap_s * fps
        pre_roll_frames = int(self.pre_roll_s * fps)
        post_roll_frames = int(self.post_roll_s * fps)

        clusters: list[list[ShotEvent]] = [[ordered[0]]]
        for shot in ordered[1:]:
            if shot.frame - clusters[-1][-1].frame > max_gap_frames:
                clusters.append([shot])
            else:
                clusters[-1].append(shot)

        points: list[PointEvent] = []
        for cluster in clusters:
            if len(cluster) < self.min_shots_per_point:
                continue

            start_frame = max(0, cluster[0].frame - pre_roll_frames)
            end_frame = cluster[-1].frame + post_roll_frames
            if total_frames is not None:
                end_frame = min(end_frame, max(total_frames - 1, start_frame))

            points.append(
                PointEvent(
                    id=str(uuid.uuid4()),
                    start_frame=start_frame,
                    start_timestamp_s=round(start_frame / fps, 3),
                    end_frame=end_frame,
                    end_timestamp_s=round(end_frame / fps, 3),
                    winner_team=None,
                    auto_detected=True,
                )
            )

        return points
