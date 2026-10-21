"""Estudio 3a: lee los 428 .odg una vez y guarda texto / líneas en un pickle para los demás estudios; cuenta el color de los splitters."""
import sys, pickle, re, collections, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import odgtools as T

SAL = Path(__file__).parent / "odg_cache.pkl"
datos = {}
t0 = time.time()
for f in sorted(T.CACHE.glob("*.odg")):
    try:
        o = T.leer_odg(f.stem)
    except Exception as e:                                           # noqa: BLE001
        print("falla", f.name, type(e).__name__)
        continue
    datos[f.stem] = {"textos": o["textos"],
                     "lineas": [{"pts": l["pts"], "color": l["estilo"].get("stroke-color"), "dash": l["estilo"].get("stroke"), "ancho": l["estilo"].get("stroke-width"),
                                 "flecha_fin": l["estilo"].get("marker-end"), "flecha_ini": l["estilo"].get("marker-start"), "tipo": l["tipo"]} for l in o["lineas"]]}
pickle.dump(datos, open(SAL, "wb"))
print(len(datos), "diagramas en", round(time.time() - t0), "s;", sum(len(d["textos"]) for d in datos.values()), "textos;", sum(len(d["lineas"]) for d in datos.values()), "lineas")

# color of the splitter labels
cont = collections.defaultdict(collections.Counter)
for md5, d in datos.items():
    for t in d["textos"]:
        s = t["texto"]
        if re.search(r"\bSPL\b|\bSPL\d|SPLITTER", s, re.I) and len(s) < 160:
            clase = "SECUNDARIO" if re.search(r"SECUNDARI", s, re.I) else "PRINCIPAL" if re.search(r"PRINCIPAL|PRIMARI", s, re.I) else "sin palabra"
            cont[clase][(t["color"] or "?").lower()] += 1
for k, v in cont.items():
    print(k, v.most_common(8))
