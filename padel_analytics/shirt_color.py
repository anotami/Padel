"""
Detección del color de camiseta de cada jugador, para poder ponerle un
nombre por defecto razonable ("Rojo", "Azul", ...) sin que el usuario
tenga que hacerlo a mano desde el primer frame.

Estrategia (barata, sin entrenar nada):
  1. Por cada jugador detectado en un frame, se recorta la región del
     torso dentro de su bounding box (evitando la cabeza y las piernas,
     que suelen tener otro color y meten ruido).
  2. Se toma el color mediano (BGR) de esa región — la mediana es más
     robusta que el promedio ante bordes/fondo que se cuelan en el recorte.
  3. Se acumulan muestras a lo largo del video (acotadas, no hace falta
     usar el partido entero) y al final se clasifica el color mediano de
     todas las muestras a un nombre de color usando rangos de matiz (H)
     en el espacio HSV, que es más estable que comparar RGB directo ante
     cambios de iluminación.
"""

from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np


# Rangos de matiz (H de OpenCV: 0-179) -> nombre de color en español.
# Se evalúan en orden; el primero que matchea gana.
_HUE_RANGES: list[tuple[int, int, str]] = [
    (0, 10, "Rojo"),
    (10, 20, "Naranja"),
    (20, 35, "Amarillo"),
    (35, 85, "Verde"),
    (85, 100, "Celeste"),
    (100, 130, "Azul"),
    (130, 150, "Violeta"),
    (150, 170, "Rosa"),
    (170, 180, "Rojo"),
]


def sample_torso_color(frame: np.ndarray, bbox_xyxy: tuple[float, float, float, float]) -> np.ndarray | None:
    """Recorta el torso dentro del bbox y devuelve su color BGR mediano, o None si el recorte quedó vacío."""
    x1, y1, x2, y2 = bbox_xyxy
    h, w = frame.shape[:2]
    box_h, box_w = y2 - y1, x2 - x1
    if box_h <= 0 or box_w <= 0:
        return None

    # torso: debajo de la cabeza (25%-55% de la altura del bbox), centrado
    # horizontalmente (25%-75% del ancho) para evitar brazos/fondo en los bordes.
    ty1 = int(y1 + 0.25 * box_h)
    ty2 = int(y1 + 0.55 * box_h)
    tx1 = int(x1 + 0.25 * box_w)
    tx2 = int(x1 + 0.75 * box_w)

    ty1, ty2 = max(0, ty1), min(h, ty2)
    tx1, tx2 = max(0, tx1), min(w, tx2)
    if ty2 <= ty1 or tx2 <= tx1:
        return None

    crop = frame[ty1:ty2, tx1:tx2]
    if crop.size == 0:
        return None

    return np.median(crop.reshape(-1, 3), axis=0)


def classify_color_name(bgr: np.ndarray) -> str:
    """Clasifica un color BGR a un nombre en español usando rangos de matiz en HSV."""
    pixel = np.uint8([[bgr]])
    h, s, v = (int(c) for c in cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0])

    if v < 50:
        return "Negro"
    if s < 40 and v > 190:
        return "Blanco"
    if s < 40:
        return "Gris"

    for lo, hi, name in _HUE_RANGES:
        if lo <= h < hi:
            return name
    return "Gris"  # no debería llegar acá, pero por las dudas


class ShirtColorAccumulator:
    """
    Acumula muestras de color de torso por jugador a lo largo del video
    (acotadas a `max_samples_per_player` para no gastar cómputo de más en
    partidos largos) y al finalizar resuelve un nombre de color por
    jugador, desambiguando si dos jugadores terminan con el mismo nombre
    (camisetas parecidas bajo la misma luz).
    """

    def __init__(self, max_samples_per_player: int = 60):
        self.max_samples_per_player = max_samples_per_player
        self._samples: dict[int, list[np.ndarray]] = defaultdict(list)

    def add_sample(self, player_id: int, frame: np.ndarray, bbox_xyxy: tuple[float, float, float, float]) -> None:
        if len(self._samples[player_id]) >= self.max_samples_per_player:
            return
        color = sample_torso_color(frame, bbox_xyxy)
        if color is not None:
            self._samples[player_id].append(color)

    def finalize(self) -> dict[int, str]:
        raw_names: dict[int, str] = {}
        for player_id, samples in self._samples.items():
            if not samples:
                continue
            median_color = np.median(np.array(samples), axis=0)
            raw_names[player_id] = classify_color_name(median_color)

        # Desambiguar nombres repetidos (ej. dos jugadores clasificados "Negro").
        counts: dict[str, int] = defaultdict(int)
        for name in raw_names.values():
            counts[name] += 1

        seen: dict[str, int] = defaultdict(int)
        final_names: dict[int, str] = {}
        for player_id, name in raw_names.items():
            if counts[name] > 1:
                seen[name] += 1
                final_names[player_id] = f"{name} {seen[name]}"
            else:
                final_names[player_id] = name

        return final_names
