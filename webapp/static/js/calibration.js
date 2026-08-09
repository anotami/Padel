// Fase 1 (frontend): captura de los 4 clicks del usuario sobre el frame
// del video y envío a /api/videos/<id>/calibration para calcular la
// homografía en el backend (Python/OpenCV).

const videoId = window.PADEL_VIDEO_ID;
const canvas = document.getElementById('calibCanvas');
const ctx = canvas.getContext('2d');

let currentImage = null;
let points = []; // hasta 4 puntos, en coordenadas del frame original (no del canvas escalado)

function drawScene() {
  if (!currentImage) return;
  canvas.width = currentImage.width;
  canvas.height = currentImage.height;
  ctx.drawImage(currentImage, 0, 0);

  const labels = ['1', '2', '3', '4'];
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#3ddc97';

  points.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p[0], p[1], 7, 0, Math.PI * 2);
    ctx.fillStyle = '#3ddc97';
    ctx.fill();
    ctx.strokeStyle = '#06251a';
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 16px sans-serif';
    ctx.fillText(labels[i], p[0] + 10, p[1] - 10);
  });

  if (points.length > 1) {
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
    if (points.length === 4) ctx.closePath();
    ctx.strokeStyle = '#3ddc97';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  updateCornerChips();
  document.getElementById('saveCalibrationBtn').disabled = points.length !== 4;
}

function updateCornerChips() {
  document.querySelectorAll('.corner-chip').forEach((chip, idx) => {
    chip.classList.toggle('filled', idx < points.length);
  });
}

async function loadFrame() {
  const t = document.getElementById('timestampInput').value || 0;
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    currentImage = img;
    drawScene();
  };
  img.src = `/api/videos/${videoId}/frame?t=${encodeURIComponent(t)}&_=${Date.now()}`;
}

canvas.addEventListener('click', (e) => {
  if (points.length >= 4) return;
  const rect = canvas.getBoundingClientRect();
  // Escalamos del tamaño mostrado en pantalla (CSS) al tamaño real del frame,
  // porque el canvas puede estar reducido por max-width:100% en CSS.
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const x = (e.clientX - rect.left) * scaleX;
  const y = (e.clientY - rect.top) * scaleY;
  points.push([x, y]);
  drawScene();
});

document.getElementById('loadFrameBtn').addEventListener('click', loadFrame);

document.getElementById('resetPointsBtn').addEventListener('click', () => {
  points = [];
  drawScene();
});

document.getElementById('saveCalibrationBtn').addEventListener('click', async () => {
  const flash = document.getElementById('calibFlash');
  flash.innerHTML = '<div class="flash info">Guardando calibración...</div>';

  const res = await fetch(`/api/videos/${videoId}/calibration`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      points,
      frame_width: canvas.width,
      frame_height: canvas.height,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    flash.innerHTML = `<div class="flash error">${data.error || 'Error al guardar calibración.'}</div>`;
    return;
  }
  flash.innerHTML = '<div class="flash info">Calibración guardada. Ya podés procesar el video.</div>';
  document.getElementById('processCard').style.display = 'block';
});

document.getElementById('startProcessBtn').addEventListener('click', async () => {
  const stride = parseInt(document.getElementById('strideInput').value || '1', 10);
  const statusText = document.getElementById('processStatusText');
  document.getElementById('startProcessBtn').disabled = true;

  await fetch(`/api/videos/${videoId}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frame_stride: stride }),
  });

  pollStatus();
});

function pollStatus() {
  const fill = document.getElementById('processProgressFill');
  const statusText = document.getElementById('processStatusText');

  const interval = setInterval(async () => {
    const res = await fetch(`/api/videos/${videoId}/status`);
    const data = await res.json();

    const pct = data.progress_total > 0
      ? Math.round((data.progress_current / data.progress_total) * 100)
      : 0;
    fill.style.width = `${pct}%`;
    statusText.textContent = `${data.status} — ${data.progress_message} (${pct}%)`;

    if (data.status === 'done') {
      clearInterval(interval);
      statusText.textContent = 'Procesamiento completo. Redirigiendo a resultados...';
      setTimeout(() => { window.location.href = `/video/${videoId}/results`; }, 1200);
    } else if (data.status === 'error') {
      clearInterval(interval);
      statusText.textContent = `Error: ${data.error_message}`;
    }
  }, 1500);
}

// Si ya venía en processing (ej. recargó la página), retomamos el polling.
if (window.PADEL_VIDEO_STATUS === 'processing') {
  document.getElementById('processCard').style.display = 'block';
  pollStatus();
}

loadFrame();
