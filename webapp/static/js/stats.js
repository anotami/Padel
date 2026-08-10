// Estadísticas derivadas: consume /api/videos/<id>/stats (golpes por
// jugador + WIN/LOSS por último toque, ya calculados en el backend
// cruzando points.json y shots.json) y las renderiza en tablas.

const videoId = window.PADEL_VIDEO_ID;

function badge(outcome) {
  if (outcome === 'WIN') return '<span class="badge done">WIN</span>';
  if (outcome === 'LOSS') return '<span class="badge error">LOSS</span>';
  return '<span class="muted">-</span>';
}

async function fetchPlayerNames() {
  const res = await fetch(`/api/videos/${videoId}/players`);
  const data = await res.json();
  const byId = {};
  (data.players || []).forEach((p) => { byId[p.player_id] = p.name; });
  return byId;
}

function playerLabel(playerId, namesById) {
  if (playerId == null) return null;
  return namesById[playerId] || `Jugador ${playerId}`;
}

async function loadStats() {
  const [statsRes, namesById] = await Promise.all([
    fetch(`/api/videos/${videoId}/stats`).then((r) => r.json()),
    fetchPlayerNames(),
  ]);
  const data = statsRes;

  document.getElementById('teamsWarning').style.display = data.teams_available ? 'none' : 'block';

  const playersBody = document.getElementById('playersTableBody');
  if (data.players.length === 0) {
    playersBody.innerHTML = '<tr><td colspan="10" class="muted">Todavía no hay golpes ni posiciones registradas.</td></tr>';
  } else {
    playersBody.innerHTML = data.players.map((p) => `
      <tr>
        <td>${playerLabel(p.player_id, namesById)}</td>
        <td>${p.team || '<span class="muted">-</span>'}</td>
        <td>${p.total_shots}</td>
        <td>${p.wins}</td>
        <td>${p.losses}</td>
        <td>${p.distance_m}</td>
        <td>${p.avg_speed_kmh} km/h</td>
        <td>${p.max_speed_kmh} km/h</td>
        <td>${p.sprints}</td>
        <td>${p.court_coverage_pct}%</td>
      </tr>
    `).join('');
  }

  const pointsBody = document.getElementById('pointsTableBody');
  if (data.point_outcomes.length === 0) {
    pointsBody.innerHTML = '<tr><td colspan="6" class="muted">Todavía no hay puntos cerrados.</td></tr>';
  } else {
    pointsBody.innerHTML = data.point_outcomes.map((o, idx) => `
      <tr>
        <td>${idx + 1}</td>
        <td>${o.start_frame} - ${o.end_frame}</td>
        <td>${o.winner_team || '-'}</td>
        <td>${o.last_touch_player_id != null ? `${playerLabel(o.last_touch_player_id, namesById)} (${o.last_touch_team || '?'})` : '<span class="muted">sin golpes registrados</span>'}</td>
        <td>${o.last_touch_shot_type || '<span class="muted">sin etiquetar</span>'}</td>
        <td>${badge(o.outcome_for_last_touch)}</td>
      </tr>
    `).join('');
  }

  const rallyBody = document.getElementById('rallyStatsBody');
  const rs = data.rally_stats;
  if (!rs || rs.count === 0) {
    rallyBody.innerHTML = '<p class="muted">Todavía no hay puntos cerrados.</p>';
  } else {
    rallyBody.innerHTML = `
      <p>Total de puntos: <b>${rs.count}</b></p>
      <p>Duración promedio: <b>${rs.avg_duration_s}s</b> (mín ${rs.min_duration_s}s / máx ${rs.max_duration_s}s)</p>
      <p>Golpes promedio por punto: <b>${rs.avg_shots_per_rally}</b></p>
    `;
  }

  const ballSpeedsBody = document.getElementById('ballSpeedsBody');
  if (!data.top_ball_speeds || data.top_ball_speeds.length === 0) {
    ballSpeedsBody.innerHTML = '<tr><td colspan="3" class="muted">Sin datos suficientes de trayectoria de pelota.</td></tr>';
  } else {
    ballSpeedsBody.innerHTML = data.top_ball_speeds.map((s) => `
      <tr>
        <td>${playerLabel(s.player_id, namesById) || '<span class="muted">-</span>'}</td>
        <td>${s.shot_type || '<span class="muted">sin etiquetar</span>'}</td>
        <td>${s.speed_kmh} km/h</td>
      </tr>
    `).join('');
  }

  const shotTypeBody = document.getElementById('shotTypeOutcomesBody');
  const shotTypeEntries = Object.entries(data.winners_errors_by_shot_type || {});
  if (shotTypeEntries.length === 0) {
    shotTypeBody.innerHTML = '<tr><td colspan="3" class="muted">Sin puntos con golpe final etiquetado todavía.</td></tr>';
  } else {
    shotTypeBody.innerHTML = shotTypeEntries.map(([shotType, counts]) => `
      <tr>
        <td>${shotType}</td>
        <td>${counts.WIN || 0}</td>
        <td>${counts.LOSS || 0}</td>
      </tr>
    `).join('');
  }
}

loadStats();
