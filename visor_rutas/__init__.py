"""Visor de rutas de escritorio (HTML + Leaflet en pywebview; Tkinter de respaldo).

Modo local (esta PC): reutiliza las funciones del servicio de presupuestos (main.py, db.py,
routing.py, presupuesto.py, red_fibra_pg.py, origen.py) sin modificarlas.
Modo remoto (otras computadoras, VisorRutas.exe): pide todo a la API por ngrok (/visor/*).

Arranque local: "Visor de rutas.bat", o  .venv\\Scripts\\pythonw.exe -m visor_rutas
Arranque remoto: VisorRutas.exe (herramientas\\build_visor.bat), o  .venv\\Scripts\\python.exe -m visor_rutas.remoto_main
"""
