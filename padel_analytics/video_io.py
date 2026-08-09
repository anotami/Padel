"""Utilidades de lectura de video compartidas por la webapp (metadata, extracción de frames)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class VideoMetadata:
    width: int
    height: int
    fps: float
    total_frames: int
    duration_s: float


def read_metadata(video_path: str | Path) -> VideoMetadata:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_s = total_frames / fps if fps > 0 else 0.0
        return VideoMetadata(width, height, fps, total_frames, duration_s)
    finally:
        cap.release()


def extract_frame_at(video_path: str | Path, timestamp_s: float | None = None) -> np.ndarray:
    """
    Extrae un frame del video en el instante `timestamp_s`. Si no se
    especifica, toma el frame del medio del video (suele mostrar la pista
    despejada, buen default para calibrar).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if timestamp_s is None:
            target_frame = total_frames // 2
        else:
            target_frame = int(timestamp_s * fps)
            target_frame = max(0, min(target_frame, max(total_frames - 1, 0)))

        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("No se pudo leer el frame solicitado del video.")
        return frame
    finally:
        cap.release()


def frame_to_jpeg_bytes(frame: np.ndarray, quality: int = 90) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("No se pudo codificar el frame como JPEG.")
    return buffer.tobytes()
