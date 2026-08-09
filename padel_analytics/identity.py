"""
Resolución de identidad estable de jugadores.

ByteTrack (Fase 2) asigna un `tracker_id` nuevo cada vez que pierde y
recupera el track de una persona: oclusión detrás de otro jugador o de la
red, un frame con motion blur, alguien que sale un instante del polígono
de la pista, etc. En un partido de pádel real esto pasa seguido, y el
resultado sin corregir es que aparecen muchos más de 4 "jugadores"
distintos (ID 1, 2, 3... 9, 10) aunque físicamente sólo haya 4 personas en
cancha — lo cual además arruina los heatmaps (cada ID fantasma sólo tiene
un puñado de muestras, concentradas en un punto).

`PlayerIdentityResolver` corrige esto con re-identificación espacial
simple: mantiene como máximo `max_players` "slots" (1..N) con su última
posición conocida en metros reales (plano cenital). Cuando aparece un
`tracker_id` que nunca vimos, lo asocia al slot activo más cercano si está
a una distancia razonable (misma persona que "reapareció" cerca de donde
estaba), o le asigna un slot libre si todavía hay lugar, o lo descarta si
ya hay 4 slots ocupados y ninguno está ni cerca ni "frío" (probablemente
sea ruido: un espectador que se coló por el filtro espacial).
"""

from __future__ import annotations

import math


class PlayerIdentityResolver:
    def __init__(
        self,
        max_players: int = 4,
        max_match_distance_m: float = 3.0,
        max_frames_gap: int = 90,
    ):
        self.max_players = max_players
        self.max_match_distance_m = max_match_distance_m
        self.max_frames_gap = max_frames_gap

        # slot_id (1..max_players) -> {"pos": (x, y), "last_frame": int}
        self._slots: dict[int, dict] = {}
        # tracker_id "crudo" de ByteTrack -> slot_id estable ya asignado
        self._raw_to_slot: dict[int, int] = {}

    def resolve(self, raw_tracker_id: int, pos_m: tuple[float, float], frame_index: int) -> int | None:
        """Devuelve el slot_id estable (1..max_players) para esta detección, o None si se descarta como ruido."""

        # Caso más común: ya conocemos este tracker_id de ByteTrack.
        if raw_tracker_id in self._raw_to_slot:
            slot_id = self._raw_to_slot[raw_tracker_id]
            self._slots[slot_id] = {"pos": pos_m, "last_frame": frame_index}
            return slot_id

        # tracker_id nuevo: buscamos el slot activo más cercano en metros.
        best_slot, best_dist = None, float("inf")
        for slot_id, slot in self._slots.items():
            dist = math.dist(pos_m, slot["pos"])
            if dist < best_dist:
                best_dist, best_slot = dist, slot_id

        if best_slot is not None and best_dist <= self.max_match_distance_m:
            self._raw_to_slot[raw_tracker_id] = best_slot
            self._slots[best_slot] = {"pos": pos_m, "last_frame": frame_index}
            return best_slot

        # No hay match cercano: si queda lugar, es un jugador nuevo -> slot libre.
        if len(self._slots) < self.max_players:
            slot_id = len(self._slots) + 1
            self._slots[slot_id] = {"pos": pos_m, "last_frame": frame_index}
            self._raw_to_slot[raw_tracker_id] = slot_id
            return slot_id

        # Ya hay max_players slots ocupados y ninguno está cerca: si el slot
        # más "frío" (hace más tiempo que no se actualiza) lleva bastante sin
        # verse, asumimos que ese jugador se perdió del todo y este nuevo
        # track lo reemplaza (por ejemplo volvió a entrar en cuadro lejos de
        # donde salió). Si no, esta detección se descarta como ruido.
        stalest_slot = max(self._slots, key=lambda s: frame_index - self._slots[s]["last_frame"])
        if frame_index - self._slots[stalest_slot]["last_frame"] > self.max_frames_gap:
            self._raw_to_slot[raw_tracker_id] = stalest_slot
            self._slots[stalest_slot] = {"pos": pos_m, "last_frame": frame_index}
            return stalest_slot

        return None
