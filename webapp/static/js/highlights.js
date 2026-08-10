// Highlights: lista los puntos cerrados (ordenados por duración de rally,
// el más largo primero) y permite generar/ver/descargar el clip recortado
// de cada uno.

const videoId = window.PADEL_VIDEO_ID;

function formatDuration(s) {
  return s != null ? `${s.toFixed(2)}s` : '-';
}

async function loadHighlights() {
  const res = await fetch(`/api/videos/${videoId}/highlights`);
  const points = await res.json();
  renderGrid(points);
}

function renderGrid(points) {
  const grid = document.getElementById('highlightsGrid');
  if (points.length === 0) {
    grid.innerHTML = '<p class="muted">Todavía no hay puntos cerrados. Marcalos primero en la página de puntos.</p>';
    return;
  }

  grid.innerHTML = points.map((p, idx) => `
    <div class="card" style="margin-bottom:0;">
      <h3 style="margin-top:0;">Punto ${idx + 1} &middot; ${formatDuration(p.duration_s)} &middot; ganó ${p.winner_team || '-'}</h3>
      ${p.clip_exists
        ? `<video controls src="${p.clip_url}" style="width:100%;"></video>
           <a class="btn secondary" href="${p.clip_url}" download style="margin-top:8px; display:inline-block;">Descargar clip</a>`
        : `<button class="btn secondary generate-btn" data-id="${p.id}" ${window.PADEL_VIDEO_STATUS !== 'done' ? 'disabled' : ''}>Generar clip</button>`
      }
    </div>
  `).join('');

  grid.querySelectorAll('.generate-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = 'Generando...';
      const res = await fetch(`/api/videos/${videoId}/highlights/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ point_id: btn.dataset.id }),
      });
      if (!res.ok) {
        const data = await res.json();
        document.getElementById('highlightsFlash').innerHTML =
          `<div class="flash error">${data.error || 'Error al generar el clip.'}</div>`;
        btn.disabled = false;
        btn.textContent = 'Generar clip';
        return;
      }
      loadHighlights();
    });
  });
}

document.getElementById('generateTopBtn').addEventListener('click', async () => {
  const btn = document.getElementById('generateTopBtn');
  const flash = document.getElementById('highlightsFlash');
  btn.disabled = true;
  btn.textContent = 'Generando clips...';
  flash.innerHTML = '<div class="flash info">Generando los 5 mejores puntos, puede tardar unos segundos...</div>';

  const res = await fetch(`/api/videos/${videoId}/highlights/generate_top`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ top_n: 5 }),
  });

  btn.disabled = false;
  btn.textContent = 'Generar los 5 mejores puntos (rallies más largos)';

  if (!res.ok) {
    const data = await res.json();
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al generar los clips.'}</div>`;
    return;
  }

  flash.innerHTML = '<div class="flash info">Clips generados.</div>';
  loadHighlights();
});

loadHighlights();
