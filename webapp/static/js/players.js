// Nombres de jugadores: por defecto viene el color de camiseta detectado
// por el pipeline (player_names.json), editable a mano acá.

const videoId = window.PADEL_VIDEO_ID;

async function loadPlayers() {
  const res = await fetch(`/api/videos/${videoId}/players`);
  const data = await res.json();
  renderTable(data.players);
}

function renderTable(players) {
  const tbody = document.getElementById('playersTableBody');
  tbody.innerHTML = players.map((p) => `
    <tr>
      <td>Jugador ${p.player_id}</td>
      <td>${p.name}${p.is_placeholder ? ' <span class="muted">(sin detectar todavía)</span>' : ''}</td>
      <td><input type="text" class="player-name-input" data-id="${p.player_id}" placeholder="ej. Rojo, Juan..."></td>
      <td><button class="btn secondary save-btn" data-id="${p.player_id}">Guardar</button></td>
    </tr>
  `).join('');

  tbody.querySelectorAll('.save-btn').forEach((btn) => {
    btn.addEventListener('click', () => saveName(btn.dataset.id));
  });
}

async function saveName(playerId) {
  const flash = document.getElementById('playersFlash');
  const input = document.querySelector(`.player-name-input[data-id="${playerId}"]`);
  const name = input.value.trim();
  if (!name) {
    flash.innerHTML = '<div class="flash error">Escribí un nombre antes de guardar.</div>';
    return;
  }

  const res = await fetch(`/api/videos/${videoId}/players`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_id: parseInt(playerId, 10), name }),
  });
  const data = await res.json();
  if (!res.ok) {
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al guardar el nombre.'}</div>`;
    return;
  }
  flash.innerHTML = '<div class="flash info">Nombre guardado.</div>';
  renderTable(data.players);
}

loadPlayers();
