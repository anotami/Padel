// Página de resultados: lightbox para ver los heatmaps en grande, y
// reemplazo de los captions crudos ("heatmap_player_1.png") por el
// nombre del jugador (color de camiseta detectado, o el que se le puso).

const videoId = window.PADEL_VIDEO_ID;

const overlay = document.getElementById('heatmapLightbox');
const lightboxImage = document.getElementById('lightboxImage');
const lightboxCaption = document.getElementById('lightboxCaption');

function openLightbox(src, caption) {
  lightboxImage.src = src;
  lightboxCaption.textContent = caption;
  overlay.style.display = 'flex';
}

function closeLightbox() {
  overlay.style.display = 'none';
  lightboxImage.src = '';
}

document.querySelectorAll('.heatmap-thumb').forEach((img) => {
  img.addEventListener('click', () => openLightbox(img.src, img.dataset.caption));
});

document.getElementById('lightboxBackBtn').addEventListener('click', closeLightbox);
overlay.addEventListener('click', (e) => {
  if (e.target === overlay) closeLightbox();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLightbox();
});

// Reemplaza "heatmap_player_N.png" / "heatmap_pareja_X.png" por un nombre
// legible ("ID 2 · Rosa"), con el mismo número de ID que se ve pegado al
// jugador en el video anotado (la cajita "ID 2" sobre cada jugador), para
// poder cruzar fácilmente uno con el otro.
function friendlyHeatmapLabel(filename, playersByFileKey) {
  const playerMatch = filename.match(/^heatmap_player_(\d+)\.png$/);
  if (playerMatch) {
    const id = playerMatch[1];
    const name = playersByFileKey[id];
    return `ID ${id} · ${name || `Jugador ${id}`}`;
  }
  const teamMatch = filename.match(/^heatmap_(pareja_[AB])\.png$/);
  if (teamMatch) {
    return `Pareja: ${teamMatch[1].replace('pareja_', '')}`;
  }
  return filename;
}

async function applyFriendlyHeatmapLabels() {
  try {
    const res = await fetch(`/api/videos/${videoId}/players`);
    if (!res.ok) return;
    const data = await res.json();
    const byId = {};
    (data.players || []).forEach((p) => { byId[String(p.player_id)] = p.name; });

    document.querySelectorAll('.heatmap-thumb').forEach((img) => {
      const label = friendlyHeatmapLabel(img.dataset.caption, byId);
      img.dataset.caption = label;
    });
    document.querySelectorAll('.heatmap-caption').forEach((el) => {
      el.textContent = friendlyHeatmapLabel(el.dataset.filename, byId);
    });
  } catch (err) {
    // si falla (por ejemplo, video no procesado todavia), dejamos los nombres de archivo crudos
  }
}

applyFriendlyHeatmapLabels();

// Resumen automático: todo lo que el sistema detectó solo (golpes, puntos,
// marcador) apenas terminó de procesar, con links para corregir cada cosa.
async function loadAutoSummary() {
  const box = document.getElementById('autoSummaryBody');
  try {
    const [stats, pointsSummary, playersData] = await Promise.all([
      fetch(`/api/videos/${videoId}/stats`).then((r) => r.json()),
      fetch(`/api/videos/${videoId}/points/summary`).then((r) => r.json()),
      fetch(`/api/videos/${videoId}/players`).then((r) => r.json()),
    ]);

    const namesById = {};
    (playersData.players || []).forEach((p) => { namesById[p.player_id] = p.name; });

    const scoreEntries = Object.entries(pointsSummary.points_by_team || {});
    const scoreHtml = scoreEntries.length
      ? scoreEntries.map(([team, count]) => `<b>${team}</b>: ${count}`).join(' &middot; ')
      : 'todavía sin puntos confirmados';

    const pendingHtml = pointsSummary.pending_confirmation > 0
      ? `<p style="color: var(--warn);">${pointsSummary.pending_confirmation} punto(s) detectados automáticamente esperan que confirmes el ganador.</p>`
      : '';

    const totalShots = (stats.players || []).reduce((sum, p) => sum + p.total_shots, 0);
    const playersHtml = (stats.players || [])
      .map((p) => `${namesById[p.player_id] || `Jugador ${p.player_id}`} (${p.total_shots} golpes, ${p.distance_m}m)`)
      .join(' &middot; ');

    box.innerHTML = `
      <p>Marcador: ${scoreHtml}</p>
      ${pendingHtml}
      <p>Puntos detectados: <b>${pointsSummary.total_points}</b> &middot; Golpes detectados: <b>${totalShots}</b></p>
      ${playersHtml ? `<p class="muted">${playersHtml}</p>` : ''}
      <div class="shot-form" style="margin-top:10px;">
        <a class="btn secondary" href="/video/${videoId}/points">Confirmar/corregir puntos</a>
        <a class="btn secondary" href="/video/${videoId}/label">Corregir golpes</a>
        <a class="btn secondary" href="/video/${videoId}/players">Corregir jugadores</a>
      </div>
    `;
  } catch (err) {
    box.innerHTML = '<p class="muted">No se pudo cargar el resumen todavía.</p>';
  }
}

loadAutoSummary();

const generateScoreboardBtn = document.getElementById('generateScoreboardBtn');
if (generateScoreboardBtn) {
  generateScoreboardBtn.addEventListener('click', async () => {
    const flash = document.getElementById('scoreboardFlash');
    generateScoreboardBtn.disabled = true;
    const originalText = generateScoreboardBtn.textContent;
    generateScoreboardBtn.textContent = 'Generando...';
    flash.innerHTML = '<div class="flash info">Generando video con marcador, puede tardar unos segundos...</div>';

    const res = await fetch(`/api/videos/${videoId}/scoreboard/generate`, { method: 'POST' });
    const data = await res.json();

    generateScoreboardBtn.disabled = false;
    generateScoreboardBtn.textContent = originalText;

    if (!res.ok) {
      flash.innerHTML = `<div class="flash error">${data.error || 'Error al generar el video.'}</div>`;
      return;
    }

    flash.innerHTML = '<div class="flash info">Listo.</div>';
    const video = document.getElementById('scoreboardVideo');
    video.src = `${data.url}?_=${Date.now()}`;
    video.style.display = 'block';
    generateScoreboardBtn.textContent = 'Regenerar video con marcador';
  });
}

const generateReportBtn = document.getElementById('generateReportBtn');
if (generateReportBtn) {
  generateReportBtn.addEventListener('click', async () => {
    const flash = document.getElementById('reportFlash');
    generateReportBtn.disabled = true;
    flash.innerHTML = '<div class="flash info">Generando informe...</div>';

    const res = await fetch(`/api/videos/${videoId}/report/generate`, { method: 'POST' });
    const data = await res.json();
    generateReportBtn.disabled = false;

    if (!res.ok) {
      flash.innerHTML = `<div class="flash error">${data.error || 'Error al generar el informe.'}</div>`;
      return;
    }

    flash.innerHTML = '<div class="flash info">Listo.</div>';
    generateReportBtn.textContent = 'Regenerar informe';
    const link = document.getElementById('reportLink');
    link.href = `${data.url}?_=${Date.now()}`;
    link.style.display = 'inline-block';
  });
}
