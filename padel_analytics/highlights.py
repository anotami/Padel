"""
Highlights automáticos: recorta el video anotado en clips por punto, la
misma idea que ofrecen PlaySight, Padmi o GameCam como su feature
principal ("automated highlights"). Reutiliza el binario de FFmpeg que ya
trae empaquetado `imageio-ffmpeg` (el mismo que usa video_transcode.py
para re-codificar a H.264), así que no hace falta ninguna dependencia
adicional.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .points import PointEvent


def cut_clip(
    source_video_path: str | Path,
    start_s: float,
    end_s: float,
    output_path: str | Path,
    padding_s: float = 1.0,
) -> bool:
    """
    Recorta [start_s - padding_s, end_s + padding_s] de `source_video_path`
    y lo guarda como un nuevo mp4 en `output_path`. Se re-codifica con
    libx264 (no un simple stream-copy) para que el corte sea preciso al
    frame y el clip resultante quede reproducible en cualquier navegador,
    igual que el video principal.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        return False

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    start = max(0.0, start_s - padding_s)
    duration = (end_s + padding_s) - start
    if duration <= 0:
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_exe, "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(source_video_path),
        "-t", f"{duration:.3f}",
        "-an",  # el video anotado no tiene audio (cv2.VideoWriter no lo genera)
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        output_path.unlink(missing_ok=True)
        return False

    if not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return False

    return True


def select_top_rallies(points: list[PointEvent], top_n: int = 5) -> list[PointEvent]:
    """Los `top_n` puntos cerrados más largos (rallies más largos = candidatos a "mejor punto")."""
    closed = [p for p in points if p.is_closed and p.duration_s is not None]
    closed.sort(key=lambda p: p.duration_s, reverse=True)
    return closed[:top_n]


def clip_filename(point_id: str) -> str:
    return f"point_{point_id}.mp4"
