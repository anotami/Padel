"""
Informe HTML de una página: junta todo lo que el sistema calculó del
partido (marcador, golpes, movimiento, formación, momentum, heatmaps) en
un único archivo autocontenido para compartir — no depende de que la
webapp esté corriendo, sólo de que la carpeta de resultados del video
(con sus imágenes) se copie/comparta junto al `report.html`.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .points import PointLabelStore
from .shot_detection import ShotLabelStore
from .player_names import PlayerNameStore
from . import match_stats, performance_stats, momentum_stats, zone_stats
from .rendering import export_scatter_plot, SCATTER_STYLE_WIN_LOSS, export_momentum_chart


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def generate_html_report(
    video_id: str,
    video_name: str,
    output_dir: str | Path,
    fps: float,
    player_teams: dict[str, str],
) -> Path:
    """Calcula todas las métricas del partido y escribe `report.html` (+ un par de gráficos) en `output_dir`."""
    output_dir = Path(output_dir)

    shots = ShotLabelStore(output_dir / "shots.json").all()
    points = PointLabelStore(output_dir / "points.json").all()
    records = _load_json(output_dir / "timeseries.json", [])
    names = PlayerNameStore(output_dir / "player_names.json").get_names()

    outcomes = match_stats.compute_point_outcomes(points, shots, player_teams)
    shot_counts = match_stats.shots_per_player(shots)
    win_loss = match_stats.player_win_loss_counts(outcomes)
    movement = performance_stats.player_movement_stats(records, fps)
    geometry = config.CourtGeometry()

    player_ids = sorted(set(shot_counts) | set(win_loss) | set(movement))
    players_rows = [
        {
            "name": names.get(str(pid), f"Jugador {pid}"),
            "team": player_teams.get(str(pid), "-"),
            "shots": shot_counts.get(pid, 0),
            "wins": win_loss.get(pid, {}).get("WIN", 0),
            "losses": win_loss.get(pid, {}).get("LOSS", 0),
            "distance_m": movement.get(pid, {}).get("distance_m", 0),
            "avg_speed": movement.get(pid, {}).get("avg_speed_kmh", 0),
        }
        for pid in player_ids
    ]

    rally = match_stats.rally_stats(points, shots, fps)
    scoreboard = PointLabelStore(output_dir / "points.json").summary()

    # Gráficos como archivos estáticos en la misma carpeta, para que el
    # informe sea portable (basta compartir el directorio completo).
    shots_by_id = {s.id: s for s in shots}
    export_scatter_plot(
        zone_stats.winners_errors_positions(outcomes, shots_by_id),
        geometry, output_dir / "report_zone_winners_errors.png",
        title="Winners y errores por zona", styles=SCATTER_STYLE_WIN_LOSS,
    )
    export_momentum_chart(
        momentum_stats.momentum_timeline(points), output_dir / "report_momentum.png",
        title="Marcador acumulado punto a punto",
    )

    heatmap_files = sorted(p.name for p in output_dir.glob("heatmap_*.png"))

    html = _render_html(
        video_name=video_name,
        scoreboard=scoreboard,
        players_rows=players_rows,
        rally=rally,
        heatmap_files=heatmap_files,
    )
    report_path = output_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path


def _render_html(
    video_name: str,
    scoreboard: dict,
    players_rows: list[dict],
    rally: dict,
    heatmap_files: list[str],
) -> str:
    score_html = " &middot; ".join(
        f"<b>{team}</b>: {count}" for team, count in scoreboard.get("points_by_team", {}).items()
    ) or "Sin puntos confirmados"

    players_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['team']}</td><td>{r['shots']}</td>"
        f"<td>{r['wins']}</td><td>{r['losses']}</td>"
        f"<td>{r['distance_m']} m</td><td>{r['avg_speed']} km/h</td></tr>"
        for r in players_rows
    ) or '<tr><td colspan="7" class="muted">Sin datos.</td></tr>'

    rally_html = (
        f"Total de puntos: <b>{rally['count']}</b> &middot; "
        f"Duración promedio: <b>{rally['avg_duration_s']}s</b> "
        f"(mín {rally['min_duration_s']}s / máx {rally['max_duration_s']}s) &middot; "
        f"Golpes promedio por punto: <b>{rally['avg_shots_per_rally']}</b>"
        if rally.get("count") else "Sin puntos confirmados todavía."
    )

    heatmaps_html = "".join(
        f'<div class="hm"><img src="{name}" alt="{name}"><p>{name}</p></div>' for name in heatmap_files
    )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe — {video_name}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0f1720; color: #e7edf2; margin: 0; padding: 28px; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.05rem; color: #9db0bf; text-transform: uppercase; letter-spacing: .04em; margin-top: 34px; }}
  .card {{ background: #16212c; border: 1px solid #2a3b4a; border-radius: 10px; padding: 18px 22px; margin-bottom: 18px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #2a3b4a; font-size: .88rem; }}
  th {{ color: #9db0bf; text-transform: uppercase; font-size: .72rem; }}
  .muted {{ color: #9db0bf; }}
  .score {{ font-size: 1.3rem; margin: 6px 0 0 0; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
  .hm img {{ width: 100%; border-radius: 8px; border: 1px solid #2a3b4a; }}
  .hm p {{ text-align: center; color: #9db0bf; font-size: .8rem; }}
  img.chart {{ width: 100%; border-radius: 8px; border: 1px solid #2a3b4a; background: #fff; }}
</style>
</head>
<body>
  <h1>Informe del partido — {video_name}</h1>
  <p class="muted">Generado automáticamente por Padel Vision Analytics.</p>

  <div class="card">
    <h2>Marcador</h2>
    <p class="score">{score_html}</p>
    <p class="muted" style="margin-top:10px;">{rally_html}</p>
  </div>

  <div class="card">
    <h2>Jugadores</h2>
    <table>
      <thead><tr><th>Jugador</th><th>Pareja</th><th>Golpes</th><th>WIN</th><th>LOSS</th><th>Distancia</th><th>Vel. media</th></tr></thead>
      <tbody>{players_html}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>Momentum del partido</h2>
    <img class="chart" src="report_momentum.png" alt="Momentum">
  </div>

  <div class="card">
    <h2>Winners y errores por zona</h2>
    <img class="chart" src="report_zone_winners_errors.png" alt="Zonas">
  </div>

  {f'<div class="card"><h2>Mapas de calor</h2><div class="grid">{heatmaps_html}</div></div>' if heatmap_files else ''}
</body>
</html>
"""
