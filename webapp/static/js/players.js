// Nombres de jugadores: por defecto viene el color de camiseta detectado
// por el pipeline (player_names.json). Los 4 campos se editan juntos acá
// y se guardan todos de una con el botón "Guardar todos los nombres".

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
      <td>
        <input type="text" class="player-name-input" data-id="${p.player_id}"
          value="${p.is_placeholder ? '' : p.name}"
          placeholder="${p.is_placeholder ? 'ej. Rojo, Juan...' : p.name}">
      </td>
    </tr>
  `).join('');
}

document.getElementById('saveAllBtn').addEventListener('click', async () => {
  const flash = document.getElementById('playersFlash');
  const inputs = Array.from(document.querySelectorAll('.player-name-input'));
  const toSave = inputs
    .map((input) => ({ player_id: parseInt(input.dataset.id, 10), name: input.value.trim() }))
    .filter((entry) => entry.name);

  if (toSave.length === 0) {
    flash.innerHTML = '<div class="flash error">Escribí al menos un nombre antes de guardar.</div>';
    return;
  }

  const results = await Promise.all(toSave.map((entry) => fetch(`/api/videos/${videoId}/players`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  })));

  if (results.some((r) => !r.ok)) {
    flash.innerHTML = '<div class="flash error">Hubo un error al guardar alguno de los nombres.</div>';
  } else {
    flash.innerHTML = '<div class="flash info">Nombres guardados.</div>';
  }
  loadPlayers();
});

loadPlayers();
