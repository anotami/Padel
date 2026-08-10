"""
Marcador incrustado: segunda pasada sobre el video ya anotado que dibuja
el score corriendo (puntos por pareja) en una esquina, actualizado en el
frame exacto donde terminó cada punto.

Se ejecuta a pedido (no durante el procesamiento inicial de las Fases
2-4) porque necesita que el usuario ya haya confirmado el ganador de los
puntos — si se hiciera en el primer pase, el marcador todavía no
existiría (ver `points.py` / detección automática de puntos).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .points import PointEvent
from .video_transcode import try_transcode_to_h264


def burn_in_scoreboard(
    source_video_path: str | Path,
    points: list[PointEvent],
    output_path: str | Path,
) -> bool:
    """
    Recorre `source_video_path` (ya con las cajas/minimapa dibujados por
    VideoRenderer) y vuelve a escribirlo con el marcador acumulado en la
    esquina superior izquierda, actualizándose en cada frame donde
    terminó un punto. Devuelve False si no hay ningún punto con ganador
    confirmado (nada que dibujar).
    """
    closed = sorted(
        (p for p in points if p.is_closed and p.winner_team), key=lambda p: p.end_frame
    )
    if not closed:
        return False

    cap = cv2.VideoCapture(str(source_video_path))
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    teams = sorted({p.winner_team for p in closed})
    scores = {team: 0 for team in teams}
    next_point_idx = 0
    frame_idx = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            # Sumamos cualquier punto que ya haya terminado a esta altura del
            # video (puede ser más de uno si el frame stride del procesamiento
            # dejó puntos muy pegados entre sí).
            while next_point_idx < len(closed) and closed[next_point_idx].end_frame <= frame_idx:
                scores[closed[next_point_idx].winner_team] += 1
                next_point_idx += 1

            _draw_scoreboard(frame, scores, teams)
            writer.write(frame)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()

    # mismo tratamiento de códec que el video principal, para que se
    # reproduzca embebido en el navegador.
    try_transcode_to_h264(output_path)
    return True


def _draw_scoreboard(frame: np.ndarray, scores: dict[str, int], teams: list[str]) -> None:
    text = "   ".join(f"{team}: {scores[team]}" for team in teams)

    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    margin = 16
    x0, y0 = margin, margin

    cv2.rectangle(frame, (x0 - 8, y0 - 8), (x0 + text_w + 8, y0 + text_h + 16), (0, 0, 0), -1)
    cv2.putText(
        frame, text, (x0, y0 + text_h + 4),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA,
    )
