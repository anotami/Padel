"""
Pipeline orquestador: une las 4 fases (calibración -> tracking ->
coordenadas/heatmaps -> rendering/export) en un flujo end-to-end.

Se usa tanto desde un script de línea de comandos como desde la webapp
local (webapp/server.py ejecuta esto mismo en un hilo de background).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2

from . import config
from .calibration import CourtCalibrator
from .tracking import PadelTracker, CourtAreaFilter
from .coordinates import AnalyticsEngine
from .identity import PlayerIdentityResolver
from .video_transcode import try_transcode_to_h264
from .shot_detection import ShotDetector, ShotLabelStore
from .points import PointDetector, PointLabelStore
from .shirt_color import ShirtColorAccumulator
from .player_names import PlayerNameStore
from .rendering import (
    VideoRenderer,
    export_timeseries_csv,
    export_timeseries_json,
    export_heatmap_image,
)


ProgressCallback = Callable[[int, int, str], None]  # (frame_actual, frame_total, mensaje)


@dataclass
class PipelineResult:
    video_id: str
    output_video_path: Path
    timeseries_csv_path: Path
    timeseries_json_path: Path
    shots_json_path: Path
    points_json_path: Path
    heatmap_paths: dict[str, Path]
    total_frames: int
    fps: float
    video_codec_used: str = "mp4v"


class PadelAnalysisPipeline:
    """
    Ejecuta el análisis completo de un video ya calibrado:
      1. Recorre el video frame a frame con PadelTracker (Fase 2).
      2. Proyecta cada posición a metros reales con AnalyticsEngine (Fase 3).
      3. Renderiza el video de doble panel (Fase 4).
      4. Al terminar, exporta CSV/JSON de la serie temporal, heatmaps PNG
         y corre la detección heurística de golpes.
    """

    def __init__(
        self,
        video_path: str | Path,
        calibrator: CourtCalibrator,
        video_id: str,
        output_dir: str | Path = config.OUTPUTS_DIR,
        yolo_weights: str = config.DEFAULT_YOLO_WEIGHTS,
        frame_stride: int = 1,
        device: str | None = None,
    ):
        self.video_path = Path(video_path)
        self.calibrator = calibrator
        self.video_id = video_id
        self.output_dir = Path(output_dir) / video_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.yolo_weights = yolo_weights
        self.frame_stride = max(1, frame_stride)
        self.device = device

    def run(self, progress_cb: ProgressCallback | None = None) -> PipelineResult:
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el video: {self.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # --- Fase 2 setup: filtro espacial por el polígono calibrado en Fase 1 ---
        court_polygon = self.calibrator.court_polygon_image()
        court_filter = CourtAreaFilter(court_polygon, margin_px=25.0)
        tracker = PadelTracker(
            weights_path=self.yolo_weights,
            court_filter=court_filter,
            device=self.device,
        )

        # --- Fase 3 setup ---
        analytics = AnalyticsEngine(self.calibrator, fps=fps / self.frame_stride)

        # --- Fase 4 setup ---
        output_video_path = self.output_dir / "output_annotated.mp4"
        renderer = VideoRenderer(
            output_path=output_video_path,
            frame_size=(width, height),
            fps=fps / self.frame_stride,
            geometry=self.calibrator.geometry,
        )

        # --- Resolución de identidad: limita a MAX_PLAYERS_ON_COURT IDs estables,
        # re-identificando por posición 2D en vez de confiar en el tracker_id
        # crudo de ByteTrack (que se multiplica con cada oclusión/reentrada). ---
        identity_resolver = PlayerIdentityResolver(max_players=config.MAX_PLAYERS_ON_COURT)

        # --- Color de camiseta: se usa como nombre por defecto de cada jugador. ---
        color_accumulator = ShirtColorAccumulator()

        frame_index = 0
        processed_index = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                if frame_index % self.frame_stride != 0:
                    frame_index += 1
                    continue

                tracking_result = tracker.process_frame(frame, processed_index)

                players_2d_m: dict[int, tuple[float, float]] = {}
                resolved_players = []
                for p in tracking_result.players:
                    pos_m = analytics.transformer.player_to_meters(p.foot_point)
                    slot_id = identity_resolver.resolve(p.tracker_id, pos_m, processed_index)
                    if slot_id is None:
                        continue  # detección descartada como ruido (ver PlayerIdentityResolver)
                    p.tracker_id = slot_id
                    players_2d_m[slot_id] = pos_m
                    resolved_players.append(p)
                    color_accumulator.add_sample(slot_id, frame, p.bbox_xyxy)
                tracking_result.players = resolved_players

                analytics.ingest_frame(tracking_result)

                ball_2d_m = None
                if tracking_result.ball is not None and tracking_result.ball.point_xy is not None:
                    ball_2d_m = analytics.transformer.ball_to_meters(tracking_result.ball.point_xy)

                renderer.write_frame(frame, tracking_result, players_2d_m, ball_2d_m)

                if progress_cb is not None:
                    progress_cb(frame_index + 1, total_frames, "Procesando frames")

                frame_index += 1
                processed_index += 1
        finally:
            cap.release()
            renderer.release()

        # Si cv2.VideoWriter no pudo usar un códec H.264 real, intentamos
        # re-codificar con ffmpeg (vía imageio-ffmpeg) para que el video
        # final se pueda reproducir embebido en el navegador. Si no está
        # disponible, el mp4 queda igual de válido pero sólo reproducible
        # descargándolo (se avisa en la webapp).
        video_codec_used = renderer.codec_used
        if video_codec_used not in ("avc1", "H264"):
            if progress_cb is not None:
                progress_cb(total_frames, total_frames, "Convirtiendo video a H.264 para el navegador...")
            if try_transcode_to_h264(output_video_path):
                video_codec_used = "h264_ffmpeg"

        if progress_cb is not None:
            progress_cb(total_frames, total_frames, "Generando analítica y exportaciones")

        default_player_names = color_accumulator.finalize()
        result = self._export_all(
            analytics, output_video_path, total_frames, fps, video_codec_used, default_player_names
        )

        if progress_cb is not None:
            progress_cb(total_frames, total_frames, "Completado")

        return result

    def _export_all(
        self,
        analytics: AnalyticsEngine,
        output_video_path: Path,
        total_frames: int,
        fps: float,
        video_codec_used: str = "mp4v",
        default_player_names: dict[int, str] | None = None,
    ) -> PipelineResult:
        records = analytics.to_records()

        # Nombre por defecto = color de camiseta detectado; no pisa nombres
        # que el usuario ya haya puesto a mano en una corrida anterior.
        name_store = PlayerNameStore(self.output_dir / "player_names.json")
        name_store.set_default_names(default_player_names or {})

        csv_path = self.output_dir / "timeseries.csv"
        json_path = self.output_dir / "timeseries.json"
        export_timeseries_csv(records, csv_path)
        export_timeseries_json(records, json_path)

        # Heatmaps por pareja + individuales
        heatmap_paths: dict[str, Path] = {}
        for team, grid in analytics.heatmaps_by_team().items():
            path = self.output_dir / f"heatmap_{team}.png"
            export_heatmap_image(grid, self.calibrator.geometry, path, title=f"Heatmap - {team}")
            heatmap_paths[team] = path

        for player_id, grid in analytics.heatmaps_by_player().items():
            path = self.output_dir / f"heatmap_player_{player_id}.png"
            export_heatmap_image(
                grid, self.calibrator.geometry, path, title=f"Heatmap - Jugador {player_id}"
            )
            heatmap_paths[f"jugador_{player_id}"] = path

        # Detección heurística de golpes (Fase de eventos de juego)
        shots_path = self.output_dir / "shots.json"
        shot_detector = ShotDetector()
        auto_shots = shot_detector.detect(analytics.rows, fps=fps)
        shot_store = ShotLabelStore(shots_path)
        shot_store.set_auto_detected(auto_shots)

        # Segmentación automática de puntos (rallies), agrupando los golpes
        # recién detectados: así la analítica por punto (marcador, WIN/LOSS,
        # duración de rally) queda disponible de entrada sin que el usuario
        # tenga que marcar cada punto a mano; sólo confirma el ganador.
        points_path = self.output_dir / "points.json"
        point_detector = PointDetector()
        auto_points = point_detector.detect(shot_store.all(), fps=fps, total_frames=total_frames)
        point_store = PointLabelStore(points_path)
        point_store.set_auto_detected(auto_points)

        # metadata del job, útil para que la webapp sepa qué mostrar
        metadata = {
            "video_id": self.video_id,
            "total_frames": total_frames,
            "fps": fps,
            "teams": analytics.infer_teams(),
            "video_codec_used": video_codec_used,
        }
        (self.output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return PipelineResult(
            video_id=self.video_id,
            output_video_path=output_video_path,
            timeseries_csv_path=csv_path,
            timeseries_json_path=json_path,
            shots_json_path=shots_path,
            points_json_path=points_path,
            heatmap_paths=heatmap_paths,
            total_frames=total_frames,
            fps=fps,
            video_codec_used=video_codec_used,
        )
