"""
Re-codificación a H.264 para que el video de salida se reproduzca embebido
en cualquier navegador.

`VideoRenderer` (rendering.py) escribe el video frame a frame con
`cv2.VideoWriter`. Intenta primero un fourcc H.264 ('avc1'/'H264'), pero en
la práctica muchas instalaciones de OpenCV (sobre todo `opencv-python` vía
pip en Windows/Linux) no traen un encoder H.264 utilizable y OpenCV cae
silenciosamente a 'mp4v' (MPEG-4 Part 2) — un archivo .mp4 perfectamente
válido, pero que Chrome/Edge/Firefox se niegan a reproducir dentro de un
<video>, porque no es el códec que ese contenedor "promete".

Para no depender de que el usuario tenga `ffmpeg` instalado aparte, se usa
el paquete `imageio-ffmpeg`, que trae un binario de FFmpeg self-contained
(con soporte libx264) instalable con un simple `pip install`. Si ese
paquete no está disponible, simplemente no se hace el transcode y el video
mp4v original queda disponible para descargar y abrir con VLC/mpv.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def try_transcode_to_h264(video_path: str | Path) -> bool:
    """
    Re-codifica `video_path` a H.264 in-place (mismo archivo al terminar).
    Devuelve True si el transcode se completó con éxito, False si no se
    pudo (falta `imageio-ffmpeg` o el proceso de ffmpeg falló) — en ese
    caso el archivo original queda intacto, sin tocar.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        return False

    video_path = Path(video_path)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    tmp_path = video_path.with_name(video_path.stem + ".h264tmp.mp4")

    cmd = [
        ffmpeg_exe, "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",       # formato de píxel que todos los navegadores decodifican
        "-movflags", "+faststart",    # permite reproducir mientras descarga, no sólo al final
        str(tmp_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        tmp_path.unlink(missing_ok=True)
        return False

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
        return False

    tmp_path.replace(video_path)
    return True
