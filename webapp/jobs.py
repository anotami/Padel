"""
Ejecución del pipeline de análisis en un hilo de background, para que la
webapp Flask no se bloquee mientras YOLOv8 procesa el video (puede tardar
varios minutos según duración/resolución/hardware).

Al ser una app 100% local de un solo usuario, un `threading.Thread` por
job alcanza: no hay necesidad de una cola de tareas tipo Celery/Redis.
"""

from __future__ import annotations

import threading
import traceback

from padel_analytics import storage
from padel_analytics.calibration import CourtCalibrator
from padel_analytics.pipeline import PadelAnalysisPipeline


_active_threads: dict[str, threading.Thread] = {}


def is_processing(video_id: str) -> bool:
    thread = _active_threads.get(video_id)
    return thread is not None and thread.is_alive()


def start_processing_job(video_id: str, frame_stride: int = 1) -> None:
    if is_processing(video_id):
        return

    thread = threading.Thread(
        target=_run_job, args=(video_id, frame_stride), daemon=True
    )
    _active_threads[video_id] = thread
    thread.start()


def _run_job(video_id: str, frame_stride: int) -> None:
    record = storage.get_video(video_id)
    if record is None or record.calibration_path is None:
        storage.update_video(video_id, status="error", error_message="Video no calibrado.")
        return

    storage.update_video(
        video_id, status="processing", progress_current=0, progress_total=0,
        progress_message="Inicializando modelo YOLOv8...", error_message=None,
    )

    def on_progress(current: int, total: int, message: str) -> None:
        storage.update_video(
            video_id, progress_current=current, progress_total=total, progress_message=message
        )

    try:
        calibrator = CourtCalibrator.load(record.calibration_path)
        pipeline = PadelAnalysisPipeline(
            video_path=record.upload_path,
            calibrator=calibrator,
            video_id=video_id,
            frame_stride=frame_stride,
        )
        result = pipeline.run(progress_cb=on_progress)
        storage.update_video(
            video_id,
            status="done",
            output_dir=str(result.output_video_path.parent),
            progress_message="Completado",
        )
    except Exception as exc:  # noqa: BLE001 - queremos capturar y exponer cualquier falla del pipeline
        traceback.print_exc()
        storage.update_video(video_id, status="error", error_message=str(exc))
