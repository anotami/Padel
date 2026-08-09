#!/usr/bin/env python3
"""
Punto de entrada para levantar la webapp de análisis de pádel en tu PC.

Uso:
    python run.py [--port 5000] [--no-browser]

Todo corre localmente: el servidor Flask, el procesamiento con YOLOv8 y
el almacenamiento de videos/resultados en ./data/.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from webapp.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Padel Vision Analytics - servidor local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador automáticamente")
    parser.add_argument("--debug", action="store_true", help="Modo debug de Flask (auto-reload)")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\nPadel Vision Analytics corriendo en {url}")
    print("Presioná Ctrl+C para detener.\n")

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
