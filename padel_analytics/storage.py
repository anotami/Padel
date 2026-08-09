"""
Registro simple de videos/jobs en un archivo JSON (`data/db.json`).

No se usa una base de datos real a propósito: esto corre 100% local en
la PC del usuario, para un solo usuario a la vez, así que un archivo
JSON con locking básico alcanza y sobra, y evita pedirle al usuario que
instale/levante un motor de base de datos aparte.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from . import config


_LOCK = threading.Lock()


@dataclass
class VideoRecord:
    id: str
    original_filename: str
    upload_path: str
    created_at: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    total_frames: int = 0
    duration_s: float = 0.0

    status: str = "uploaded"  # uploaded -> calibrated -> processing -> done -> error
    calibration_path: str | None = None
    output_dir: str | None = None

    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoRecord":
        return cls(**data)


def _load_raw() -> dict[str, dict]:
    if not config.DB_PATH.exists():
        return {}
    try:
        return json.loads(config.DB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_raw(data: dict[str, dict]) -> None:
    config.DB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def create_video(original_filename: str, upload_path: str, created_at: str) -> VideoRecord:
    with _LOCK:
        data = _load_raw()
        video_id = uuid.uuid4().hex[:12]
        record = VideoRecord(
            id=video_id,
            original_filename=original_filename,
            upload_path=upload_path,
            created_at=created_at,
        )
        data[video_id] = record.to_dict()
        _save_raw(data)
        return record


def get_video(video_id: str) -> VideoRecord | None:
    with _LOCK:
        data = _load_raw()
    raw = data.get(video_id)
    return VideoRecord.from_dict(raw) if raw else None


def list_videos() -> list[VideoRecord]:
    with _LOCK:
        data = _load_raw()
    records = [VideoRecord.from_dict(v) for v in data.values()]
    records.sort(key=lambda r: r.created_at, reverse=True)
    return records


def update_video(video_id: str, **fields: Any) -> VideoRecord | None:
    with _LOCK:
        data = _load_raw()
        if video_id not in data:
            return None
        data[video_id].update(fields)
        _save_raw(data)
        return VideoRecord.from_dict(data[video_id])


def delete_video(video_id: str) -> bool:
    with _LOCK:
        data = _load_raw()
        if video_id not in data:
            return False
        del data[video_id]
        _save_raw(data)
        return True
