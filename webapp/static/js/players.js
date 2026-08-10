// Nombres y pareja de cada jugador: por defecto vienen del color de
// camiseta detectado y de la posición promedio respecto a la red (ambos
// calculados por el pipeline). Los 4 se editan juntos acá y se guardan
// todos de una con "Guardar todo". Las correcciones sobreviven a un
// reproceso del video (no se pisan con los valores automáticos de nuevo).

const videoId = window.PADEL_VIDEO_ID;
const teamNames = window.PADEL_TEAM_NAMES || ['pareja_A', 'pareja_B'];

async function loadPlayers() {
  const res = await fetch(`/api/videos/${videoId}/players`);
  const data = await res.json();
  renderTable(data.players);
}

function teamSelectHtml(player) {
  const blank = `<option value="" ${!player.team ? 'selected' : ''}>(sin definir)</option>`;
  const options = teamNames.map(
    (t) => `<option value="${t}" ${t === player.team ? 'selected' : ''}>${t}</option>`
  ).join('');
  return `<select class="player-team-select" data-id="${player.player_id}">${blank}${options}</select>`;
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
      <td>${teamSelectHtml(p)}</td>
    </tr>
  `).join('');
}

document.getElementById('saveAllBtn').addEventListener('click', async () => {
  const flash = document.getElementById('playersFlash');
  const rows = Array.from(document.querySelectorAll('#playersTableBody tr'));

  const toSave = rows.map((row) => {
    const nameInput = row.querySelector('.player-name-input');
    const teamSelect = row.querySelector('.player-team-select');
    return {
      player_id: parseInt(nameInput.dataset.id, 10),
      name: nameInput.value.trim(),
      team: teamSelect.value,
    };
  }).filter((entry) => entry.name || entry.team);

  if (toSave.length === 0) {
    flash.innerHTML = '<div class="flash error">Completá al menos un nombre o pareja antes de guardar.</div>';
    return;
  }

  const results = await Promise.all(toSave.map((entry) => fetch(`/api/videos/${videoId}/players`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  })));

  if (results.some((r) => !r.ok)) {
    flash.innerHTML = '<div class="flash error">Hubo un error al guardar alguno de los cambios.</div>';
  } else {
    flash.innerHTML = '<div class="flash info">Cambios guardados.</div>';
  }
  loadPlayers();
});

loadPlayers();
