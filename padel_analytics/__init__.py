"""
padel_analytics
================

Sistema modular de análisis de video de pádel:

  Fase 1 - calibration.py   : CourtCalibrator (homografía cámara -> vista cenital)
  Fase 2 - tracking.py      : PadelTracker (YOLOv8 + ByteTrack + tracking de pelota)
  Fase 3 - coordinates.py   : CoordinateTransformer + AnalyticsEngine (heatmaps)
  Fase 4 - rendering.py     : VideoRenderer + exportación CSV/JSON/heatmaps
            shot_detection.py: detección heurística y etiquetado manual de golpes
            pipeline.py       : orquestador end-to-end de las 4 fases
"""

__version__ = "0.1.0"
