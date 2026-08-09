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
// legible ("Heatmap - Rojo") usando los nombres de jugador guardados.
function friendlyHeatmapLabel(filename, playersByFileKey) {
  const playerMatch = filename.match(/^heatmap_player_(\d+)\.png$/);
  if (playerMatch) {
    const name = playersByFileKey[playerMatch[1]];
    return name ? `Jugador: ${name}` : filename;
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
