"""
FASE 4 — Rendering y Exportación.

`VideoRenderer` compone, para cada frame procesado, un video de salida
de doble panel:
  (a) el frame original anotado con las cajas delimitadoras, el ID de
      cada jugador y su rastro de trayectoria reciente;
  (b) un minimapa 2D (vista cenital) incrustado en la esquina inferior
      con la posición exacta de los 4 jugadores y la pelota sobre el
      dibujo de la pista real.

`export_timeseries_csv` / `export_timeseries_json` vuelcan la serie
temporal acumulada por `AnalyticsEngine` a disco.
`export_heatmap_image` genera el mapa de calor de ocupación como PNG
usando matplotlib.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from pathlib import Path

import cv2
import numpy as np

from .config import CourtGeometry
from .tracking import FrameTrackingResult


# Paleta de colores estable por índice de jugador (BGR, para overlay con OpenCV).
PLAYER_COLORS_BGR = [
    (60, 180, 75),    # verde
    (0, 130, 255),    # naranja
    (255, 90, 60),    # azul
    (0, 215, 255),    # amarillo
]


def color_for_player(tracker_id: int) -> tuple[int, int, int]:
    return PLAYER_COLORS_BGR[tracker_id % len(PLAYER_COLORS_BGR)]


class CourtMinimapRenderer:
    """Dibuja la pista de pádel (vista cenital) y las posiciones proyectadas sobre ella."""

    def __init__(self, geometry: CourtGeometry, background_color=(30, 110, 60)):
        self.geometry = geometry
        self.background_color = background_color
        self._base_court = self._draw_base_court()

    def _draw_base_court(self) -> np.ndarray:
        """
        Dibuja las líneas reglamentarias de una pista de pádel (perímetro,
        red al medio del eje largo, y líneas de servicio a 3m de cada red)
        sobre el lienzo del minimapa. Sirve de fondo estático que se
        reutiliza (copy()) en cada frame para no redibujar todo cada vez.
        """
        w, h = self.geometry.width_px, self.geometry.height_px
        scale = self.geometry.scale_px_per_m
        canvas = np.full((h, w, 3), self.background_color, dtype=np.uint8)

        line_color = (255, 255, 255)
        thickness = 2

        # Perímetro
        cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), line_color, thickness)

        # Red (mitad del eje largo, 20m -> línea vertical en x=10m)
        net_x = int(self.geometry.length_m / 2 * scale)
        cv2.line(canvas, (net_x, 0), (net_x, h), line_color, thickness)

        # Líneas de servicio, reglamentariamente a 3m de la red hacia cada lado
        service_offset_px = int(3.0 * scale)
        for direction in (-1, 1):
            x = net_x + direction * service_offset_px
            if 0 <= x < w:
                cv2.line(canvas, (x, 0), (x, h), line_color, 1)

        return canvas

    def render(
        self,
        players_2d: dict[int, tuple[float, float]],
        ball_2d: tuple[float, float] | None,
    ) -> np.ndarray:
        """players_2d/ball_2d ya vienen en METROS reales; acá se escalan a píxeles del minimapa."""
        canvas = self._base_court.copy()
        scale = self.geometry.scale_px_per_m

        for tracker_id, (x_m, y_m) in players_2d.items():
            px, py = int(x_m * scale), int(y_m * scale)
            color = color_for_player(tracker_id)
            cv2.circle(canvas, (px, py), 8, color, -1)
            cv2.circle(canvas, (px, py), 8, (255, 255, 255), 1)
            cv2.putText(
                canvas, str(tracker_id), (px + 10, py - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA,
            )

        if ball_2d is not None:
            bx, by = int(ball_2d[0] * scale), int(ball_2d[1] * scale)
            cv2.circle(canvas, (bx, by), 5, (0, 255, 255), -1)
            cv2.circle(canvas, (bx, by), 5, (0, 0, 0), 1)

        return canvas


# Candidatos de códec a probar, en orden de preferencia. 'avc1'/'H264' son
# H.264, el único códec que TODOS los navegadores reproducen de forma nativa
# en un <video>; 'mp4v' (MPEG-4 Part 2) es el que trae OpenCV como garantía
# de funcionar en cualquier instalación, pero Chrome/Edge/Firefox se niegan
# a reproducirlo embebido en un .mp4 (el video queda "mudo": se sube bien,
# pero el <video> se ve en negro/0:00 como si no tuviera contenido). Por eso
# se intenta primero H.264 y sólo se cae a mp4v si el sistema no lo soporta.
VIDEO_CODEC_CANDIDATES = ["avc1", "H264", "mp4v"]


class VideoRenderer:
    """
    Compone el video final de doble panel: video original anotado (arriba)
    + minimapa incrustado en la esquina inferior derecha.
    """

    def __init__(
        self,
        output_path: str | Path,
        frame_size: tuple[int, int],  # (width, height) del video original
        fps: float,
        geometry: CourtGeometry,
        trail_length: int = 20,
        minimap_scale: float = 0.42,
        fourcc: str | None = None,
    ):
        self.output_path = Path(output_path)
        self.frame_width, self.frame_height = frame_size
        self.fps = fps
        self.minimap = CourtMinimapRenderer(geometry)
        self.minimap_width = int(self.minimap.geometry.width_px * minimap_scale)
        self.minimap_height = int(self.minimap.geometry.height_px * minimap_scale)

        self._trails: dict[int, deque] = defaultdict(lambda: deque(maxlen=trail_length))

        candidates = [fourcc] if fourcc else VIDEO_CODEC_CANDIDATES
        self.writer, self.codec_used = self._open_writer(candidates)

    def _open_writer(self, codec_candidates: list[str]) -> tuple[cv2.VideoWriter, str]:
        last_writer = None
        for codec in codec_candidates:
            writer = cv2.VideoWriter(
                str(self.output_path),
                cv2.VideoWriter_fourcc(*codec),
                self.fps,
                (self.frame_width, self.frame_height),
            )
            if writer.isOpened():
                return writer, codec
            writer.release()
            last_writer = writer

        # Ningún códec preferido abrió: nos quedamos con mp4v, que en la
        # práctica de OpenCV siempre está disponible (aunque el navegador
        # no lo reproduzca embebido, el archivo se genera y es válido para
        # abrir con VLC/mpv o descargar).
        fallback = cv2.VideoWriter(
            str(self.output_path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps,
            (self.frame_width, self.frame_height),
        )
        return fallback, "mp4v"

    def _annotate_main_panel(self, frame: np.ndarray, tracking_result: FrameTrackingResult) -> np.ndarray:
        annotated = frame.copy()

        for player in tracking_result.players:
            x1, y1, x2, y2 = (int(v) for v in player.bbox_xyxy)
            color = color_for_player(player.tracker_id)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f"ID {player.tracker_id}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(annotated, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)
            cv2.putText(
                annotated, label, (x1 + 3, y1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
            )

            # Rastro de trayectoria: dibuja las últimas N posiciones del "foot point".
            self._trails[player.tracker_id].append(tuple(int(v) for v in player.foot_point))
            trail_points = list(self._trails[player.tracker_id])
            for i in range(1, len(trail_points)):
                cv2.line(annotated, trail_points[i - 1], trail_points[i], color, 2)

        if tracking_result.ball is not None and tracking_result.ball.point_xy is not None:
            bx, by = (int(v) for v in tracking_result.ball.point_xy)
            cv2.circle(annotated, (bx, by), 6, (0, 255, 255), -1)
            cv2.circle(annotated, (bx, by), 6, (0, 0, 0), 2)

        return annotated

    def _compose_dual_panel(
        self, annotated_frame: np.ndarray, minimap_frame: np.ndarray
    ) -> np.ndarray:
        composed = annotated_frame.copy()
        resized_minimap = cv2.resize(minimap_frame, (self.minimap_width, self.minimap_height))

        margin = 16
        x0 = self.frame_width - self.minimap_width - margin
        y0 = self.frame_height - self.minimap_height - margin
        x1, y1 = x0 + self.minimap_width, y0 + self.minimap_height

        # Borde blanco + leve oscurecido de fondo para que el minimapa resalte
        # sobre el video, y alpha-blend por si el video es muy claro ahí.
        overlay = composed.copy()
        cv2.rectangle(overlay, (x0 - 4, y0 - 4), (x1 + 4, y1 + 4), (255, 255, 255), -1)
        composed = cv2.addWeighted(overlay, 0.9, composed, 0.1, 0)
        composed[y0:y1, x0:x1] = resized_minimap

        return composed

    def write_frame(
        self,
        frame: np.ndarray,
        tracking_result: FrameTrackingResult,
        players_2d_m: dict[int, tuple[float, float]],
        ball_2d_m: tuple[float, float] | None,
    ) -> None:
        annotated = self._annotate_main_panel(frame, tracking_result)
        minimap = self.minimap.render(players_2d_m, ball_2d_m)
        composed = self._compose_dual_panel(annotated, minimap)
        self.writer.write(composed)

    def release(self) -> None:
        self.writer.release()


# ---------------------------------------------------------------------------
# Exportación de la serie temporal
# ---------------------------------------------------------------------------

def export_timeseries_csv(records: list[dict], path: str | Path) -> None:
    path = Path(path)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def export_timeseries_json(records: list[dict], path: str | Path) -> None:
    Path(path).write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def export_heatmap_image(grid: np.ndarray, geometry: CourtGeometry, path: str | Path, title: str = "") -> None:
    """
    Renderiza la matriz de ocupación como imagen PNG con matplotlib,
    superpuesta al contorno de la pista para dar contexto espacial.
    Import de matplotlib es local para no forzar la dependencia si sólo
    se usa la parte de tracking/CSV.
    """
    import matplotlib
    matplotlib.use("Agg")  # backend sin GUI, apto para server/headless
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    extent = [0, geometry.length_m, geometry.width_m, 0]  # y invertido para que 0 quede "arriba" visualmente
    im = ax.imshow(grid, extent=extent, cmap="inferno", aspect="auto", interpolation="bilinear")

    net_x = geometry.length_m / 2
    ax.axvline(net_x, color="white", linewidth=1.5, linestyle="--")
    ax.set_xlim(0, geometry.length_m)
    ax.set_ylim(geometry.width_m, 0)
    ax.set_xlabel("Longitud de pista (m)")
    ax.set_ylabel("Ancho de pista (m)")
    if title:
        ax.set_title(title)
    fig.colorbar(im, ax=ax, label="Densidad de ocupación")
    fig.tight_layout()
    fig.savefig(str(path), dpi=140)
    plt.close(fig)
