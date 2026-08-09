// Estadísticas derivadas: consume /api/videos/<id>/stats (golpes por
// jugador + WIN/LOSS por último toque, ya calculados en el backend
// cruzando points.json y shots.json) y las renderiza en tablas.

const videoId = window.PADEL_VIDEO_ID;

function badge(outcome) {
  if (outcome === 'WIN') return '<span class="badge done">WIN</span>';
  if (outcome === 'LOSS') return '<span class="badge error">LOSS</span>';
  return '<span class="muted">-</span>';
}

async function loadStats() {
  const res = await fetch(`/api/videos/${videoId}/stats`);
  const data = await res.json();

  document.getElementById('teamsWarning').style.display = data.teams_available ? 'none' : 'block';

  const playersBody = document.getElementById('playersTableBody');
  if (data.players.length === 0) {
    playersBody.innerHTML = '<tr><td colspan="5" class="muted">Todavía no hay golpes registrados.</td></tr>';
  } else {
    playersBody.innerHTML = data.players.map((p) => `
      <tr>
        <td>ID ${p.player_id}</td>
        <td>${p.team || '<span class="muted">-</span>'}</td>
        <td>${p.total_shots}</td>
        <td>${p.wins}</td>
        <td>${p.losses}</td>
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
        <td>${o.last_touch_player_id != null ? `ID ${o.last_touch_player_id} (${o.last_touch_team || '?'})` : '<span class="muted">sin golpes registrados</span>'}</td>
        <td>${o.last_touch_shot_type || '<span class="muted">sin etiquetar</span>'}</td>
        <td>${badge(o.outcome_for_last_touch)}</td>
      </tr>
    `).join('');
  }
}

loadStats();
