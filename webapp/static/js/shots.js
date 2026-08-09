// Etiquetado manual de golpes: toma el frame/timestamp actual del <video>
// y lo envía a /api/videos/<id>/shots junto con jugador + tipo de golpe.

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

let playerNamesById = {};

async function loadPlayerOptions() {
  const res = await fetch(`/api/videos/${videoId}/players`);
  const data = await res.json();
  const select = document.getElementById('playerIdSelect');

  playerNamesById = {};
  (data.players || []).forEach((p) => { playerNamesById[p.player_id] = p.name; });

  select.innerHTML = '<option value="">(sin asignar)</option>' + (data.players || []).map(
    (p) => `<option value="${p.player_id}">${p.name}</option>`
  ).join('');
}

function playerLabel(playerId) {
  if (playerId == null) return '-';
  return playerNamesById[playerId] || `Jugador ${playerId}`;
}

async function loadShots() {
  const res = await fetch(`/api/videos/${videoId}/shots`);
  const shots = await res.json();
  const tbody = document.getElementById('shotsTableBody');
  tbody.innerHTML = '';

  shots.forEach((shot) => {
    const tr = document.createElement('tr');

    const shotTypeCell = shot.shot_type
      ? shot.shot_type
      : '<span class="muted">(sin etiquetar)</span>';

    tr.innerHTML = `
      <td><a href="#" class="seek-link" data-t="${shot.timestamp_s}">${shot.frame}</a></td>
      <td>${shot.timestamp_s.toFixed(2)}</td>
      <td>${playerLabel(shot.player_id)}</td>
      <td>${shotTypeCell}</td>
      <td>${shot.auto_detected ? 'auto' : 'manual'}</td>
      <td><button class="btn secondary delete-btn" data-id="${shot.id}">Borrar</button></td>
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
      await fetch(`/api/videos/${videoId}/shots/${btn.dataset.id}`, { method: 'DELETE' });
      loadShots();
    });
  });
}

document.getElementById('addShotBtn').addEventListener('click', async () => {
  const flash = document.getElementById('labelFlash');
  const playerIdRaw = document.getElementById('playerIdSelect').value;
  const shotType = document.getElementById('shotTypeSelect').value;

  const payload = {
    frame: currentFrame(),
    timestamp_s: player.currentTime,
    shot_type: shotType,
    player_id: playerIdRaw ? parseInt(playerIdRaw, 10) : null,
  };

  const res = await fetch(`/api/videos/${videoId}/shots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const data = await res.json();
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al guardar el golpe.'}</div>`;
    return;
  }

  flash.innerHTML = '<div class="flash info">Golpe registrado.</div>';
  loadShots();
});

loadPlayerOptions().then(loadShots);
