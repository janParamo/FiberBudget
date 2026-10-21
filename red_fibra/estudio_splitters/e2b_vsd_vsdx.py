import sys, math, collections, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import odgtools as T
exec(open(Path(__file__).parent / "e2_lineas.py", encoding="utf-8").read().split("filas = []")[0])
import sqlite3, os
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import main  # noqa
from config import get_settings
c = sqlite3.connect(get_settings().red_fibra_db)
base = collections.defaultdict(dict)
for r, f, m in c.execute("select ruta_relativa, formato, md5 from archivos where estado='ok' and formato in ('vsd','vsdx')"):
    base[os.path.splitext(r)[0].lower()][f] = m
for k, v in base.items():
    if len(v) != 2:
        continue
    a, b = T.leer_odg(v["vsd"]), T.leer_odg(v["vsdx"])
    ea = [p for l in a["lineas"] for p in (l["pts"][0], l["pts"][-1])]
    idx = Indice([p for l in b["lineas"] for p in (l["pts"][0], l["pts"][-1])])
    ds = [(idx.cercano(*p) or (99,))[0] for p in ea]
    ta = {t["texto"].upper(): (t["x"], t["y"]) for t in a["textos"]}
    tb = {t["texto"].upper(): (t["x"], t["y"]) for t in b["textos"]}
    comunes = [t for t in ta if t in tb]
    dt = [math.hypot(ta[t][0] - tb[t][0], ta[t][1] - tb[t][1]) for t in comunes]
    print(k[-45:], "| lineas vsd/vsdx:", len(a["lineas"]), len(b["lineas"]), "| extremos a <=0.05 cm:", round(sum(1 for d in ds if d <= 0.05) / max(1, len(ds)) * 100), "% (de", len(ds), ")",
          "| textos comunes:", len(comunes), "mediana", round(statistics.median(dt), 3) if dt else None, "cm")
