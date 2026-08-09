"""
Nombres de jugadores: por defecto el color de camiseta detectado
(`shirt_color.ShirtColorAccumulator`), editables por el usuario desde la
webapp. Mismo patrón de persistencia JSON que `ShotLabelStore`/`PointLabelStore`.
"""

from __future__ import annotations

import json
from pathlib import Path


class PlayerNameStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._names: dict[str, str] = {}
        if self.path.exists():
            self.load()

    def load(self) -> None:
        self._names = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._names, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def set_default_names(self, defaults: dict[int, str]) -> None:
        """
        Completa nombres detectados automáticamente (color de camiseta),
        pero sólo para jugadores que todavía no tienen un nombre puesto a
        mano por el usuario — para que reprocesar el video no le pise el
        nombre que alguien ya eligió.
        """
        changed = False
        for player_id, name in defaults.items():
            key = str(player_id)
            if key not in self._names:
                self._names[key] = name
                changed = True
        if changed:
            self.save()

    def set_name(self, player_id: int, name: str) -> None:
        self._names[str(player_id)] = name
        self.save()

    def get_names(self) -> dict[str, str]:
        return dict(self._names)
