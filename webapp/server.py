"""
Servidor web local (Flask) que expone el sistema de análisis de pádel
como una aplicación gestionable desde el navegador, corriendo 100% en
la PC del usuario (no requiere ningún servicio en la nube).

Flujo de páginas:
  /                      -> subir video, ver listado y estado de cada uno
  /video/<id>/calibrate  -> Fase 1: click en las 4 esquinas de la pista
  /video/<id>/results    -> Fase 4: video anotado, heatmaps, descargas
  /video/<id>/label      -> etiquetado manual de golpes (+ los auto-detectados)
  /video/<id>/points     -> marcado de inicio/fin de cada punto y ganador por pareja
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, abort
from werkzeug.utils import secure_filename

from padel_analytics import config, storage, video_io
from padel_analytics.calibration import CourtCalibrator
from padel_analytics.shot_detection import ShotLabelStore, SHOT_TYPES
from padel_analytics.points import PointLabelStore

DEFAULT_TEAM_NAMES = ["pareja_A", "pareja_B"]

from . import jobs


ALLOWED_EXTENSIONS = {".mp4", ".mov"}
SAFE_FILENAME_RE = re.compile(r"^[\w.\-]+$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB, video de partido completo


def _video_or_404(video_id: str) -> storage.VideoRecord:
    record = storage.get_video(video_id)
    if record is None:
        abort(404, description="Video no encontrado")
    return record


def _team_names(record: storage.VideoRecord) -> list[str]:
    """
    Nombres de las 2 parejas a ofrecer en el selector de "ganador del punto".
    Si el video ya fue procesado, usa los que infirió AnalyticsEngine
    (metadata.json); si no, cae al default genérico pareja_A/pareja_B.
    """
    if record.output_dir:
        metadata_path = Path(record.output_dir) / "metadata.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                teams = sorted(set(metadata.get("teams", {}).values()))
                if teams:
                    return teams
            except (json.JSONDecodeError, OSError):
                pass
    return DEFAULT_TEAM_NAMES


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    videos = storage.list_videos()
    return render_template("index.html", videos=videos)


@app.route("/video/<video_id>/calibrate")
def calibrate_page(video_id: str):
    record = _video_or_404(video_id)
    return render_template("calibrate.html", video=record)


@app.route("/video/<video_id>/results")
def results_page(video_id: str):
    record = _video_or_404(video_id)
    heatmaps = []
    has_points_export = False
    if record.output_dir:
        heatmaps = sorted(p.name for p in Path(record.output_dir).glob("heatmap_*.png"))
        has_points_export = (Path(record.output_dir) / "points.json").exists()
    return render_template(
        "results.html", video=record, heatmaps=heatmaps, has_points_export=has_points_export
    )


@app.route("/video/<video_id>/label")
def label_page(video_id: str):
    record = _video_or_404(video_id)
    return render_template("label_shots.html", video=record, shot_types=SHOT_TYPES)


@app.route("/video/<video_id>/points")
def points_page(video_id: str):
    record = _video_or_404(video_id)
    return render_template("points.html", video=record, team_names=_team_names(record))


# ---------------------------------------------------------------------------
# API: subida y metadata
# ---------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "video" not in request.files:
        return jsonify({"error": "No se envió ningún archivo (campo 'video')."}), 400

    file = request.files["video"]
    if not file.filename:
        return jsonify({"error": "Nombre de archivo vacío."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Formato no soportado ({ext}). Usá .mp4 o .mov."}), 400

    created_at = datetime.datetime.utcnow().isoformat()
    safe_name = secure_filename(file.filename) or "video.mp4"

    # Creamos el registro primero para obtener un video_id único, y con
    # ese id armamos un nombre de archivo sin colisiones.
    record = storage.create_video(original_filename=file.filename, upload_path="", created_at=created_at)
    dest_path = config.UPLOADS_DIR / f"{record.id}_{safe_name}"
    file.save(dest_path)

    try:
        meta = video_io.read_metadata(dest_path)
    except Exception as exc:
        storage.delete_video(record.id)
        dest_path.unlink(missing_ok=True)
        return jsonify({"error": f"No se pudo leer el video: {exc}"}), 400

    record = storage.update_video(
        record.id,
        upload_path=str(dest_path),
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        total_frames=meta.total_frames,
        duration_s=meta.duration_s,
    )
    return jsonify({"video_id": record.id, "video": record.to_dict()})


@app.route("/api/videos")
def api_list_videos():
    return jsonify([v.to_dict() for v in storage.list_videos()])


@app.route("/api/videos/<video_id>")
def api_get_video(video_id: str):
    record = _video_or_404(video_id)
    return jsonify(record.to_dict())


@app.route("/api/videos/<video_id>/frame")
def api_get_frame(video_id: str):
    record = _video_or_404(video_id)
    timestamp_s = request.args.get("t", type=float)
    try:
        frame = video_io.extract_frame_at(record.upload_path, timestamp_s)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    jpeg_bytes = video_io.frame_to_jpeg_bytes(frame)
    return app.response_class(jpeg_bytes, mimetype="image/jpeg")


# ---------------------------------------------------------------------------
# API: Fase 1 - calibración
# ---------------------------------------------------------------------------

@app.route("/api/videos/<video_id>/calibration", methods=["POST"])
def api_set_calibration(video_id: str):
    record = _video_or_404(video_id)
    payload = request.get_json(force=True)

    points = payload.get("points")
    frame_width = payload.get("frame_width")
    frame_height = payload.get("frame_height")

    if not points or len(points) != 4 or not frame_width or not frame_height:
        return jsonify({"error": "Se requieren 4 puntos [x,y] y frame_width/frame_height."}), 400

    calibrator = CourtCalibrator()
    calibrator.set_image_points(points, int(frame_width), int(frame_height))

    calib_dir = config.OUTPUTS_DIR / video_id
    calib_dir.mkdir(parents=True, exist_ok=True)
    calib_path = calib_dir / "calibration.json"
    calibrator.save(calib_path, video_id)

    storage.update_video(video_id, status="calibrated", calibration_path=str(calib_path))
    return jsonify({"ok": True, "calibration_path": str(calib_path)})


@app.route("/api/videos/<video_id>/calibration", methods=["GET"])
def api_get_calibration(video_id: str):
    record = _video_or_404(video_id)
    if not record.calibration_path or not Path(record.calibration_path).exists():
        return jsonify({"calibrated": False})
    calibrator = CourtCalibrator.load(record.calibration_path)
    return jsonify({
        "calibrated": True,
        "points": calibrator.court_polygon_image().tolist(),
    })


# ---------------------------------------------------------------------------
# API: procesamiento (Fases 2-4) y progreso
# ---------------------------------------------------------------------------

@app.route("/api/videos/<video_id>/process", methods=["POST"])
def api_start_processing(video_id: str):
    record = _video_or_404(video_id)
    if not record.calibration_path:
        return jsonify({"error": "Primero tenés que calibrar la pista."}), 400
    if jobs.is_processing(video_id):
        return jsonify({"ok": True, "already_running": True})

    payload = request.get_json(silent=True) or {}
    frame_stride = int(payload.get("frame_stride", 1))

    jobs.start_processing_job(video_id, frame_stride=frame_stride)
    return jsonify({"ok": True})


@app.route("/api/videos/<video_id>/status")
def api_status(video_id: str):
    record = _video_or_404(video_id)
    return jsonify({
        "status": record.status,
        "progress_current": record.progress_current,
        "progress_total": record.progress_total,
        "progress_message": record.progress_message,
        "error_message": record.error_message,
    })


# ---------------------------------------------------------------------------
# API: golpes (auto-detectados + etiquetado manual)
# ---------------------------------------------------------------------------

def _shots_path(video_id: str) -> Path:
    return config.OUTPUTS_DIR / video_id / "shots.json"


@app.route("/api/videos/<video_id>/shots", methods=["GET"])
def api_list_shots(video_id: str):
    _video_or_404(video_id)
    store = ShotLabelStore(_shots_path(video_id))
    return jsonify(store.to_records())


@app.route("/api/videos/<video_id>/shots", methods=["POST"])
def api_add_shot(video_id: str):
    _video_or_404(video_id)
    payload = request.get_json(force=True)

    frame = payload.get("frame")
    timestamp_s = payload.get("timestamp_s")
    shot_type = payload.get("shot_type")
    if frame is None or timestamp_s is None or not shot_type:
        return jsonify({"error": "Faltan campos: frame, timestamp_s, shot_type."}), 400

    store = ShotLabelStore(_shots_path(video_id))
    event = store.add_manual_shot(
        frame=int(frame),
        timestamp_s=float(timestamp_s),
        player_id=payload.get("player_id"),
        shot_type=shot_type,
        ball_x_m=payload.get("ball_x_m"),
        ball_y_m=payload.get("ball_y_m"),
        note=payload.get("note", ""),
    )
    return jsonify(event.to_dict())


@app.route("/api/videos/<video_id>/shots/<shot_id>", methods=["PUT", "PATCH"])
def api_update_shot(video_id: str, shot_id: str):
    _video_or_404(video_id)
    payload = request.get_json(force=True)
    store = ShotLabelStore(_shots_path(video_id))
    allowed_fields = {"shot_type", "player_id", "note"}
    updates = {k: v for k, v in payload.items() if k in allowed_fields}
    event = store.update_shot(shot_id, **updates)
    if event is None:
        return jsonify({"error": "Golpe no encontrado."}), 404
    return jsonify(event.to_dict())


@app.route("/api/videos/<video_id>/shots/<shot_id>", methods=["DELETE"])
def api_delete_shot(video_id: str, shot_id: str):
    _video_or_404(video_id)
    store = ShotLabelStore(_shots_path(video_id))
    ok = store.delete_shot(shot_id)
    if not ok:
        return jsonify({"error": "Golpe no encontrado."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: puntos (inicio/fin de cada punto + ganador por pareja)
# ---------------------------------------------------------------------------

def _points_path(video_id: str) -> Path:
    return config.OUTPUTS_DIR / video_id / "points.json"


@app.route("/api/videos/<video_id>/teams")
def api_get_teams(video_id: str):
    record = _video_or_404(video_id)
    return jsonify({"teams": _team_names(record)})


@app.route("/api/videos/<video_id>/points", methods=["GET"])
def api_list_points(video_id: str):
    _video_or_404(video_id)
    store = PointLabelStore(_points_path(video_id))
    return jsonify(store.to_records())


@app.route("/api/videos/<video_id>/points/summary")
def api_points_summary(video_id: str):
    _video_or_404(video_id)
    store = PointLabelStore(_points_path(video_id))
    return jsonify(store.summary())


@app.route("/api/videos/<video_id>/points/start", methods=["POST"])
def api_start_point(video_id: str):
    _video_or_404(video_id)
    payload = request.get_json(force=True)
    frame = payload.get("frame")
    timestamp_s = payload.get("timestamp_s")
    if frame is None or timestamp_s is None:
        return jsonify({"error": "Faltan campos: frame, timestamp_s."}), 400

    store = PointLabelStore(_points_path(video_id))
    try:
        event = store.start_point(frame=int(frame), timestamp_s=float(timestamp_s))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(event.to_dict())


@app.route("/api/videos/<video_id>/points/<point_id>/close", methods=["POST"])
def api_close_point(video_id: str, point_id: str):
    _video_or_404(video_id)
    payload = request.get_json(force=True)
    frame = payload.get("frame")
    timestamp_s = payload.get("timestamp_s")
    winner_team = payload.get("winner_team")
    if frame is None or timestamp_s is None or not winner_team:
        return jsonify({"error": "Faltan campos: frame, timestamp_s, winner_team."}), 400

    store = PointLabelStore(_points_path(video_id))
    try:
        event = store.close_point(
            point_id=point_id,
            frame=int(frame),
            timestamp_s=float(timestamp_s),
            winner_team=winner_team,
            note=payload.get("note", ""),
        )
    except KeyError:
        return jsonify({"error": "Punto no encontrado."}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(event.to_dict())


@app.route("/api/videos/<video_id>/points/<point_id>", methods=["PUT", "PATCH"])
def api_update_point(video_id: str, point_id: str):
    _video_or_404(video_id)
    payload = request.get_json(force=True)
    store = PointLabelStore(_points_path(video_id))
    allowed_fields = {"winner_team", "note"}
    updates = {k: v for k, v in payload.items() if k in allowed_fields}
    event = store.update_point(point_id, **updates)
    if event is None:
        return jsonify({"error": "Punto no encontrado."}), 404
    return jsonify(event.to_dict())


@app.route("/api/videos/<video_id>/points/<point_id>", methods=["DELETE"])
def api_delete_point(video_id: str, point_id: str):
    _video_or_404(video_id)
    store = PointLabelStore(_points_path(video_id))
    ok = store.delete_point(point_id)
    if not ok:
        return jsonify({"error": "Punto no encontrado."}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Servido de archivos multimedia (video original / video anotado / descargas)
# ---------------------------------------------------------------------------

@app.route("/media/uploads/<video_id>")
def media_upload(video_id: str):
    record = _video_or_404(video_id)
    path = Path(record.upload_path)
    return send_from_directory(path.parent, path.name)


@app.route("/media/outputs/<video_id>/<path:filename>")
def media_output(video_id: str, filename: str):
    record = _video_or_404(video_id)
    if not record.output_dir:
        abort(404)
    # Sólo se permiten nombres de archivo "planos" (sin subcarpetas) generados
    # por el propio pipeline, para evitar path traversal.
    if not SAFE_FILENAME_RE.match(Path(filename).name) or filename != Path(filename).name:
        abort(400)
    return send_from_directory(record.output_dir, filename)


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
