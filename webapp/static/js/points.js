// Marcado de puntos (rallies): inicio, fin y pareja ganadora. Sólo puede
// haber un punto abierto a la vez (impuesto también en el backend).

const videoId = window.PADEL_VIDEO_ID;
const fps = window.PADEL_VIDEO_FPS || 30;
const player = document.getElementById('playerVideo');
const currentTimeText = document.getElementById('currentTimeText');

function currentFrame() {
  return Math.round(player.currentTime * fps);
}

player.addEventListener('timeupdate', () => {
  currentTimeText.textContent = `Frame actual: ${currentFrame()} (t=${player.currentTime.toFixed(2)}s)`;
});

function formatTime(t) {
  return `${t.toFixed(2)}s`;
}

const teamNames = window.PADEL_TEAM_NAMES || ['pareja_A', 'pareja_B'];

function winnerSelectHtml(point) {
  const options = teamNames.map((t) => `<option value="${t}" ${t === point.winner_team ? 'selected' : ''}>${t}</option>`).join('');
  return `<select class="winner-edit-select" data-id="${point.id}">${options}</select>`;
}

async function refreshAll() {
  const [pointsRes, summaryRes] = await Promise.all([
    fetch(`/api/videos/${videoId}/points`),
    fetch(`/api/videos/${videoId}/points/summary`),
  ]);
  const points = await pointsRes.json();
  const summary = await summaryRes.json();

  renderPointsTable(points);
  renderScoreboard(summary);
  renderOpenPointState(points);
}

function renderScoreboard(summary) {
  const board = document.getElementById('scoreboard');
  const entries = Object.entries(summary.points_by_team || {});
  if (entries.length === 0) {
    board.innerHTML = '<p class="muted">Todavía no hay puntos cerrados.</p>';
  } else {
    board.innerHTML = entries.map(([team, count]) => `
      <div class="card" style="margin-bottom:0; padding:14px 16px;">
        <h3 style="margin:0;">${team}</h3>
        <p style="font-size:1.8rem; margin:6px 0 0 0;">${count}</p>
      </div>
    `).join('');
  }
  const avgText = document.getElementById('avgDurationText');
  avgText.textContent = summary.avg_rally_duration_s != null
    ? `Total de puntos: ${summary.total_points} · Duración promedio del punto: ${summary.avg_rally_duration_s}s`
    : `Total de puntos: ${summary.total_points}`;
}

function renderPointsTable(points) {
  const tbody = document.getElementById('pointsTableBody');
  tbody.innerHTML = '';

  points.forEach((p, idx) => {
    const tr = document.createElement('tr');
    const endCell = p.is_closed
      ? `<a href="#" class="seek-link" data-t="${p.end_timestamp_s}">${p.end_frame} (${formatTime(p.end_timestamp_s)})</a>`
      : '<span class="badge processing">en curso</span>';
    const durationCell = p.duration_s != null ? `${p.duration_s}s` : '-';
    // El ganador se puede editar en cualquier momento desde acá (no sólo al
    // cerrar el punto), por si te equivocaste o querés corregirlo después.
    const winnerCell = p.is_closed
      ? winnerSelectHtml(p)
      : '<span class="muted">(en curso)</span>';

    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td><a href="#" class="seek-link" data-t="${p.start_timestamp_s}">${p.start_frame} (${formatTime(p.start_timestamp_s)})</a></td>
      <td>${endCell}</td>
      <td>${durationCell}</td>
      <td>${winnerCell}</td>
      <td><button class="btn secondary delete-btn" data-id="${p.id}">Borrar</button></td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('.seek-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      player.currentTime = parseFloat(link.dataset.t);
    });
  });

  tbody.querySelectorAll('.delete-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await fetch(`/api/videos/${videoId}/points/${btn.dataset.id}`, { method: 'DELETE' });
      refreshAll();
    });
  });

  tbody.querySelectorAll('.winner-edit-select').forEach((select) => {
    select.addEventListener('change', async () => {
      await fetch(`/api/videos/${videoId}/points/${select.dataset.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ winner_team: select.value }),
      });
      refreshAll();  // el marcador (puntos por pareja) depende del ganador, hay que recalcularlo
    });
  });
}

let openPointId = null;

function renderOpenPointState(points) {
  const open = points.find((p) => !p.is_closed);
  const banner = document.getElementById('openPointBanner');
  const startBtn = document.getElementById('startPointBtn');
  const closeForm = document.getElementById('closePointForm');

  if (open) {
    openPointId = open.id;
    banner.style.display = 'block';
    banner.textContent = `Punto en curso — inicio en frame ${open.start_frame} (${formatTime(open.start_timestamp_s)}). Marcá el fin cuando termine el punto.`;
    startBtn.style.display = 'none';
    closeForm.style.display = 'flex';
  } else {
    openPointId = null;
    banner.style.display = 'none';
    startBtn.style.display = 'inline-flex';
    closeForm.style.display = 'none';
  }
}

document.getElementById('startPointBtn').addEventListener('click', async () => {
  const flash = document.getElementById('pointsFlash');
  const res = await fetch(`/api/videos/${videoId}/points/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frame: currentFrame(), timestamp_s: player.currentTime }),
  });
  const data = await res.json();
  if (!res.ok) {
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al marcar el inicio del punto.'}</div>`;
    return;
  }
  flash.innerHTML = '';
  refreshAll();
});

document.getElementById('closePointBtn').addEventListener('click', async () => {
  const flash = document.getElementById('pointsFlash');
  if (!openPointId) return;

  const winnerTeam = document.getElementById('winnerSelect').value;
  const note = document.getElementById('pointNoteInput').value;

  const res = await fetch(`/api/videos/${videoId}/points/${openPointId}/close`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      frame: currentFrame(),
      timestamp_s: player.currentTime,
      winner_team: winnerTeam,
      note,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al cerrar el punto.'}</div>`;
    return;
  }
  document.getElementById('pointNoteInput').value = '';
  flash.innerHTML = '<div class="flash info">Punto registrado.</div>';
  refreshAll();
});

refreshAll();
