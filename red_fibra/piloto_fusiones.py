#!/usr/bin/env python3
"""
PILOTO de extracción automática de fusiones (red_fibra/fusiones.py), medido a mano.

1) Correr la extracción sobre las mufas elegidas y generar los reportes:
       .venv\\Scripts\\python.exe red_fibra\\piloto_fusiones.py --mufas lista.txt

   lista.txt: una mufa por línea (nombre exacto de la mufa, md5 del diagrama o parte de la ruta del
   archivo); las líneas que empiezan con # se ignoran.
   Resultado en red_fibra/piloto/: index.html y un reporte HTML por mufa con la imagen del diagrama,
   las fusiones detectadas dibujadas encima (verde >= 0.7, naranja 0.4-0.7, rojo < 0.4) y una
   tabla con "Correcto / Incorrecto" por fusión. Las fusiones también quedan en la tabla
   fusiones_piloto de red_fibra.db.

2) Marcar en cada reporte (se abre con doble clic en Edge/Chrome; las marcas se recuerdan en ese
   navegador) y anotar cuántas fusiones reales tiene el diagrama. "Descargar marcas (CSV)" guarda
   marcas_<archivo_id>.csv: muévalo a red_fibra/piloto/marcas/.

3) Calcular precisión y cobertura:
       .venv\\Scripts\\python.exe red_fibra\\piloto_fusiones.py --metricas red_fibra\\piloto\\marcas

   precisión = correctas / marcadas;  cobertura = correctas / reales (y detectadas / reales),
   en total, por mufa y por umbral de confianza.
"""
import argparse
import csv
import glob
import html
import json
import os
import re
import shutil
import sqlite3
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
PROYECTO = os.path.dirname(AQUI)
for ruta in (AQUI, PROYECTO):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
import fusiones  # noqa: E402

RE_MD5 = re.compile(r'^[0-9a-fA-F]{32}$')
PX_POR_CM = 96 / 2.54


# --------------------------------------------------------------------------- lista de mufas -> diagramas

def leer_lista(ruta):
    with open(ruta, encoding='utf-8-sig') as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]


def buscar_diagrama(con, entrada):
    """(archivo_id, md5, ruta_relativa, nombre de la mufa) del diagrama de una línea de la lista, o None."""
    base = "SELECT f.id, f.md5, f.ruta_relativa FROM archivos f WHERE f.estado = 'ok' AND f.formato != 'xlsx' "
    if RE_MD5.match(entrada):
        fila = con.execute(base + 'AND lower(f.md5) = lower(?)', (entrada,)).fetchone()
        return (fila + (os.path.basename(fila[2]),)) if fila else None
    filas = con.execute(
        "SELECT f.id, f.md5, f.ruta_relativa, n.nombre, a.rol, f.tipo_diagrama FROM nodos n "
        "JOIN nodo_apariciones a ON a.nodo_id = n.id JOIN archivos f ON f.id = a.archivo_id "
        "WHERE upper(n.nombre) = upper(?) AND f.estado = 'ok' AND f.formato != 'xlsx'", (entrada,)).fetchall()
    if filas:
        orden = {'principal': 0, 'vecino': 1, 'red': 2}
        filas.sort(key=lambda r: (orden.get(r[4], 9), r[5] != 'mufa'))
        return filas[0][:4]
    fila = con.execute(base + 'AND upper(f.ruta_relativa) LIKE upper(?) ORDER BY f.ruta_relativa',
                       ('%' + entrada + '%',)).fetchone()
    return (fila + (entrada,)) if fila else None


# --------------------------------------------------------------------------- reporte HTML

PLANTILLA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Piloto fusiones – __TITULO__</title>
<style>
 body{margin:0;font:14px "Segoe UI",system-ui,sans-serif;color:#1d2128;background:#f4f5f7}
 header{padding:12px 16px;background:#fff;border-bottom:1px solid #d5d8de}
 h1{margin:0 0 4px;font-size:18px} .sub{color:#5b6270;font-size:12px}
 .controles{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-top:8px}
 .marco{position:relative;height:62vh;overflow:hidden;background:#e9eaed;cursor:grab;border-bottom:1px solid #d5d8de}
 .marco.arrastrando{cursor:grabbing} #lienzo{position:absolute;left:0;top:0}
 #lienzo img{display:block;width:100%;height:100%;background:#fff} #lienzo svg{position:absolute;left:0;top:0;width:100%;height:100%}
 polyline{fill:none;stroke-width:var(--grosor);stroke-linejoin:round;opacity:.6;cursor:pointer}
 polyline:hover{opacity:1}
 polyline.alta{stroke:#0a9b3a} polyline.media{stroke:#ff8c00} polyline.baja{stroke:#e01b1b}
 polyline.sel{stroke:#00a3ff!important;opacity:1;stroke-width:calc(var(--grosor)*2)}
 circle{fill:none;stroke:#00a3ff;stroke-width:calc(var(--grosor)*.6)}
 table{border-collapse:collapse;width:100%;background:#fff;font-size:12px}
 th,td{border-bottom:1px solid #e3e5e9;padding:5px 8px;text-align:left;vertical-align:top}
 th{position:sticky;top:0;background:#f8f9fa} tr.sel td{background:#e7f4ff} tr:hover td{background:#f4f9ff}
 .conf{font-weight:700} .alta{color:#0a7d3b} .media{color:#a06000} .baja{color:#b00020}
 .muestra{display:inline-block;width:14px;height:14px;border:1px solid #333;vertical-align:-3px;margin-right:4px}
 .tabla{max-height:38vh;overflow:auto} button{font:inherit;padding:4px 12px;cursor:pointer}
 .resumen{font-weight:600}
</style></head><body>
<header>
 <h1>__TITULO__</h1>
 <div class="sub">__RUTA__ · archivo_id __ARCHIVO_ID__ · __N__ fusiones detectadas</div>
 <div class="controles">
  <label>Mostrar confianza ≥ <input id="umbral" type="range" min="0" max="1" step="0.05" value="0"> <b id="umbral-v">0.00</b></label>
  <label>Fusiones reales en el diagrama: <input id="reales" type="number" min="0" style="width:70px"></label>
  <span class="resumen" id="resumen"></span>
  <button id="descargar">Descargar marcas (CSV)</button>
  <span class="sub">Rueda: zoom · arrastrar: mover · clic en una línea o fila: resaltar</span>
 </div>
</header>
<div class="marco" id="marco"><div id="lienzo">
 <img id="img" src="__IMG__" width="__PX_W__" height="__PX_H__" alt="diagrama" draggable="false">
 <svg viewBox="0 0 __CM_W__ __CM_H__" preserveAspectRatio="none" id="svg"></svg>
</div></div>
<div class="tabla"><table><thead><tr><th>#</th><th>Confianza</th><th>Color</th><th>Entrada</th><th>Salida</th><th>Motivo</th><th>Marca</th></tr></thead>
<tbody id="filas"></tbody></table></div>
<script>
const DATOS = __DATOS__;
const CLAVE = "piloto_fusiones_" + DATOS.archivo_id;
const nivel = (c) => c >= 0.7 ? "alta" : (c >= 0.4 ? "media" : "baja");
// Marks are kept by the fusion's end points, not by its id: re-running the pilot renumbers the ids.
DATOS.fusiones.forEach((f) => f.clave = [f.x1_cm, f.y1_cm, f.x2_cm, f.y2_cm].map((v) => Number(v).toFixed(2)).join("|"));
let marcas = {}; try { marcas = JSON.parse(localStorage.getItem(CLAVE) || "{}"); } catch (e) {}
const guardar = () => { try { localStorage.setItem(CLAVE, JSON.stringify(marcas)); } catch (e) {} resumen(); };
const svg = document.getElementById("svg"), filas = document.getElementById("filas");
svg.style.setProperty("--grosor", (DATOS.cm_w / 2600).toFixed(4));   // thin: the real hilo colour stays visible
const NS = "http://www.w3.org/2000/svg";
DATOS.fusiones.forEach((f) => {
  const pl = document.createElementNS(NS, "polyline");
  pl.setAttribute("points", JSON.parse(f.puntos).map((p) => p.join(",")).join(" "));
  pl.setAttribute("class", nivel(f.confianza)); pl.dataset.id = f.id;
  const t = document.createElementNS(NS, "title"); t.textContent = `#${f.id} ${f.confianza} · ${f.entrada} → ${f.salida}`;
  pl.appendChild(t); svg.appendChild(pl);
  [[f.x1_cm, f.y1_cm], [f.x2_cm, f.y2_cm]].forEach(([x, y]) => {
    const c = document.createElementNS(NS, "circle"); c.setAttribute("cx", x); c.setAttribute("cy", y);
    c.setAttribute("r", DATOS.cm_w / 1500); c.dataset.id = f.id; svg.appendChild(c); });
  const tr = document.createElement("tr"); tr.dataset.id = f.id;
  const celda = (txt, cls) => { const td = document.createElement("td"); td.textContent = txt; if (cls) td.className = cls; tr.appendChild(td); return td; };
  celda(f.id); celda(f.confianza.toFixed(2), "conf " + nivel(f.confianza));
  const tdColor = celda(f.color_tia); const m = document.createElement("span"); m.className = "muestra"; m.style.background = f.color; tdColor.prepend(m);
  celda(f.entrada); celda(f.salida); celda(f.motivo);
  const td = document.createElement("td");
  ["correcto", "incorrecto"].forEach((v) => { const l = document.createElement("label"); const r = document.createElement("input");
    r.type = "radio"; r.name = "m" + f.id; r.value = v; r.checked = marcas[f.clave] === v;
    r.addEventListener("change", () => { marcas[f.clave] = v; guardar(); });
    l.append(r, " " + (v === "correcto" ? "Correcto" : "Incorrecto")); td.append(l, document.createElement("br")); });
  tr.appendChild(td); filas.appendChild(tr);
});
const reales = document.getElementById("reales");
reales.value = marcas._reales ?? ""; reales.addEventListener("input", () => { marcas._reales = reales.value; guardar(); });
function resumen() {
  const ids = DATOS.fusiones.map((f) => f.clave);
  const c = ids.filter((i) => marcas[i] === "correcto").length, x = ids.filter((i) => marcas[i] === "incorrecto").length;
  document.getElementById("resumen").textContent = `Marcadas ${c + x}/${ids.length} · correctas ${c}` +
    (c + x ? ` · precisión ${(100 * c / (c + x)).toFixed(0)}%` : "") + (marcas._reales ? ` · cobertura ${(100 * c / marcas._reales).toFixed(0)}%` : "");
}
resumen();
function seleccionar(id, desplazar) {
  document.querySelectorAll(".sel").forEach((e) => e.classList.remove("sel"));
  document.querySelectorAll(`[data-id="${id}"]`).forEach((e) => e.classList.add("sel"));
  const tr = filas.querySelector(`tr[data-id="${id}"]`); if (tr && desplazar) tr.scrollIntoView({ block: "nearest" });
}
svg.addEventListener("click", (e) => { const id = e.target.dataset && e.target.dataset.id; if (id) seleccionar(id, true); });
filas.addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr && e.target.tagName !== "INPUT") seleccionar(tr.dataset.id, false); });
const umbral = document.getElementById("umbral");
umbral.addEventListener("input", () => { const u = Number(umbral.value); document.getElementById("umbral-v").textContent = u.toFixed(2);
  DATOS.fusiones.forEach((f) => document.querySelectorAll(`[data-id="${f.id}"]`).forEach((e) => e.style.display = f.confianza >= u ? "" : "none")); });
document.getElementById("descargar").addEventListener("click", () => {
  const q = (v) => '"' + String(v ?? "").replace(/"/g, '""') + '"';
  const filasCsv = [["archivo_id", "md5", "mufa", "fusion_id", "confianza", "entrada", "salida", "color_tia", "marca", "reales_en_diagrama"]];
  DATOS.fusiones.forEach((f) => filasCsv.push([DATOS.archivo_id, DATOS.md5, DATOS.titulo, f.id, f.confianza, f.entrada, f.salida, f.color_tia, marcas[f.clave] || "", marcas._reales || ""]));
  if (!DATOS.fusiones.length) filasCsv.push([DATOS.archivo_id, DATOS.md5, DATOS.titulo, "", "", "", "", "", "", marcas._reales || ""]);
  const blob = new Blob(["﻿" + filasCsv.map((r) => r.map(q).join(",")).join("\r\n")], { type: "text/csv" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `marcas_${DATOS.archivo_id}.csv`; a.click();
});
// zoom y arrastre
const marco = document.getElementById("marco"), lienzo = document.getElementById("lienzo"), img = document.getElementById("img");
// Zoom resizes the drawing (not a CSS scale) so the SVG diagram is redrawn sharp at every zoom.
const W = __PX_W__, H = __PX_H__;
let z = { s: 1, x: 0, y: 0 }, arr = null;
const aplicar = () => Object.assign(lienzo.style, { left: z.x + "px", top: z.y + "px", width: W * z.s + "px", height: H * z.s + "px" });
function ajustar() { z.s = Math.min(marco.clientWidth / W, marco.clientHeight / H); z.x = (marco.clientWidth - W * z.s) / 2; z.y = 0; aplicar(); }
marco.addEventListener("wheel", (e) => { e.preventDefault(); const r = marco.getBoundingClientRect(), cx = e.clientX - r.left, cy = e.clientY - r.top;
  const n = Math.min(Math.max(z.s * (e.deltaY < 0 ? 1.2 : 1 / 1.2), 0.01), 60000 / W); z.x = cx - (cx - z.x) * n / z.s; z.y = cy - (cy - z.y) * n / z.s; z.s = n; aplicar(); }, { passive: false });
marco.addEventListener("pointerdown", (e) => { if (e.target.tagName === "polyline") return; arr = { x: e.clientX - z.x, y: e.clientY - z.y }; marco.setPointerCapture(e.pointerId); marco.classList.add("arrastrando"); });
marco.addEventListener("pointermove", (e) => { if (!arr) return; z.x = e.clientX - arr.x; z.y = e.clientY - arr.y; aplicar(); });
marco.addEventListener("pointerup", () => { arr = null; marco.classList.remove("arrastrando"); });
ajustar();
</script></body></html>
"""


def _slug(texto):
    return re.sub(r'[^A-Za-z0-9]+', '_', texto).strip('_')[:50] or 'mufa'


def reporte_html(destino, titulo, archivo, filas, png_rel, px, cm):
    datos = {'archivo_id': archivo[0], 'md5': archivo[1], 'titulo': titulo, 'cm_w': cm[0],
             'fusiones': [dict(f) for f in filas]}
    texto = (PLANTILLA.replace('__TITULO__', html.escape(titulo)).replace('__RUTA__', html.escape(archivo[2]))
             .replace('__ARCHIVO_ID__', str(archivo[0])).replace('__N__', str(len(filas)))
             .replace('__IMG__', html.escape(png_rel)).replace('__PX_W__', str(px[0])).replace('__PX_H__', str(px[1]))
             .replace('__CM_W__', '%.3f' % cm[0]).replace('__CM_H__', '%.3f' % cm[1])
             .replace('__DATOS__', json.dumps(datos, ensure_ascii=False).replace('</', '<\\/')))
    with open(destino, 'w', encoding='utf-8') as f:
        f.write(texto)


def generar(args):
    from visor_rutas.fusion import diagrama_mejor    # same LibreOffice conversion and cache as the viewer

    salida = os.path.abspath(args.salida)
    os.makedirs(os.path.join(salida, 'img'), exist_ok=True)
    os.makedirs(os.path.join(salida, 'marcas'), exist_ok=True)
    con = sqlite3.connect(args.db)
    indice, faltantes = [], []
    for n, entrada in enumerate(leer_lista(args.mufas), 1):
        archivo = buscar_diagrama(con, entrada)
        if archivo is None:
            faltantes.append(entrada)
            print('  %2d. %-50s NO ENCONTRADA' % (n, entrada[:50]))
            continue
        archivo_id, md5, ruta, nombre = archivo
        odg = os.path.join(AQUI, 'cache_odg', md5 + '.odg')
        if not os.path.exists(odg):
            faltantes.append(entrada)
            print('  %2d. %-50s sin .odg en cache_odg' % (n, entrada[:50]))
            continue
        detectadas = fusiones.extraer_fusiones(odg)
        fusiones.guardar(con, archivo_id, detectadas)
        con.row_factory = sqlite3.Row
        filas = con.execute('SELECT * FROM fusiones_piloto WHERE archivo_id = ? ORDER BY confianza DESC, id',
                            (archivo_id,)).fetchall()
        con.row_factory = None
        imagen, formato = diagrama_mejor(md5)          # SVG: sharp at any zoom; PNG only as fallback
        if imagen is None:
            sys.exit('Falta LibreOffice para generar la imagen del diagrama (LIBREOFFICE_PATH en .env).')
        png_rel = 'img/%s.%s' % (md5, formato)
        shutil.copyfile(imagen, os.path.join(salida, png_rel))
        anterior = os.path.join(salida, 'img', '%s.%s' % (md5, 'png' if formato == 'svg' else 'svg'))
        if os.path.exists(anterior):                    # image of a previous run in the other format
            os.remove(anterior)
        cm = fusiones.tamano_pagina_cm(odg)
        px = (round(cm[0] * PX_POR_CM), round(cm[1] * PX_POR_CM))     # page size at 96 dpi
        nombre_html = '%02d_%s.html' % (n, _slug(nombre))
        reporte_html(os.path.join(salida, nombre_html), nombre, archivo, filas, png_rel, px, cm)
        niveles = [sum(f['confianza'] >= 0.7 for f in filas), sum(0.4 <= f['confianza'] < 0.7 for f in filas),
                   sum(f['confianza'] < 0.4 for f in filas)]
        indice.append((nombre_html, nombre, ruta, len(filas), niveles))
        print('  %2d. %-50s %3d fusiones (alta %d, media %d, baja %d)' % ((n, nombre[:50], len(filas)) + tuple(niveles)))
    con.close()
    filas_html = ''.join(
        '<tr><td><a href="%s">%s</a></td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td class="sub">%s</td></tr>'
        % (html.escape(h), html.escape(nm), total, a, m, b, html.escape(r)) for h, nm, r, total, (a, m, b) in indice)
    with open(os.path.join(salida, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Piloto de fusiones</title>'
                '<style>body{font:14px "Segoe UI",sans-serif;margin:24px}table{border-collapse:collapse}'
                'td,th{border-bottom:1px solid #ddd;padding:6px 10px;text-align:left}.sub{color:#666;font-size:12px}</style>'
                '</head><body><h1>Piloto de extracción de fusiones</h1><p>Abra cada mufa, marque Correcto / Incorrecto, '
                'anote las fusiones reales y descargue las marcas a <code>red_fibra/piloto/marcas/</code>.</p>'
                '<table><tr><th>Mufa</th><th>Detectadas</th><th>Alta ≥0.7</th><th>Media</th><th>Baja &lt;0.4</th><th>Diagrama</th></tr>'
                + filas_html + '</table>' + (('<p>No encontradas: %s</p>' % html.escape(', '.join(faltantes))) if faltantes else '')
                + '</body></html>')
    print('\nReportes en %s (abrir index.html)' % salida)
    if faltantes:
        print('No encontradas: %s' % ', '.join(faltantes))


# --------------------------------------------------------------------------- métricas

def leer_marcas(rutas):
    archivos = []
    for r in rutas:
        archivos += sorted(glob.glob(os.path.join(r, '*.csv'))) if os.path.isdir(r) else [r]
    filas = []
    for a in archivos:
        with open(a, encoding='utf-8-sig', newline='') as f:
            filas += list(csv.DictReader(f))
    return filas


def _pct(a, b):
    return ('%5.1f%%' % (100.0 * a / b)) if b else '   - '


def metricas(filas, umbrales=(0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)):
    """Precisión y cobertura por mufa y por umbral de confianza. Devuelve el resumen (dict)."""
    por_archivo = {}
    for f in filas:
        d = por_archivo.setdefault(f['archivo_id'], {'mufa': f.get('mufa', ''), 'reales': 0, 'fusiones': []})
        if str(f.get('reales_en_diagrama', '')).strip():
            d['reales'] = max(d['reales'], int(float(f['reales_en_diagrama'])))
        if str(f.get('fusion_id', '')).strip():
            d['fusiones'].append((float(f['confianza'] or 0), (f.get('marca') or '').strip().lower()))
    print('%-40s %10s %8s %9s %10s %10s %11s' % ('Mufa', 'Detectadas', 'Marcadas', 'Correctas', 'Precisión', 'Cobertura', 'Detec/real'))
    tot = {'det': 0, 'marc': 0, 'corr': 0, 'reales': 0}
    for d in por_archivo.values():
        det = len(d['fusiones'])
        marc = sum(m in ('correcto', 'incorrecto') for _, m in d['fusiones'])
        corr = sum(m == 'correcto' for _, m in d['fusiones'])
        print('%-40s %10d %8d %9d %10s %10s %11s' % (d['mufa'][:40], det, marc, corr, _pct(corr, marc),
                                                  _pct(corr, d['reales']), _pct(det, d['reales'])))
        for k, v in (('det', det), ('marc', marc), ('corr', corr), ('reales', d['reales'])):
            tot[k] += v
    print('%-40s %10d %8d %9d %10s %10s %11s' % ('TOTAL', tot['det'], tot['marc'], tot['corr'], _pct(tot['corr'], tot['marc']),
                                              _pct(tot['corr'], tot['reales']), _pct(tot['det'], tot['reales'])))
    print('\nPor umbral de confianza (solo fusiones con confianza >= umbral):')
    print('%8s %10s %9s %10s %10s' % ('Umbral', 'Detectadas', 'Correctas', 'Precisión', 'Cobertura'))
    por_umbral = []
    todas = [x for d in por_archivo.values() for x in d['fusiones']]
    for u in umbrales:
        sel = [m for c, m in todas if c >= u]
        marc = sum(m in ('correcto', 'incorrecto') for m in sel)
        corr = sum(m == 'correcto' for m in sel)
        por_umbral.append({'umbral': u, 'detectadas': len(sel), 'correctas': corr,
                           'precision': corr / marc if marc else None,
                           'cobertura': corr / tot['reales'] if tot['reales'] else None})
        print('%8.2f %10d %9d %10s %10s' % (u, len(sel), corr, _pct(corr, marc), _pct(corr, tot['reales'])))
    sin_marcar = tot['det'] - tot['marc']
    if sin_marcar:
        print('\nAviso: %d fusiones detectadas todavía sin marcar (no cuentan en la precisión).' % sin_marcar)
    return {'total': tot, 'por_umbral': por_umbral}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Piloto de extracción de fusiones (reportes y métricas)')
    ap.add_argument('--mufas', help='Archivo de texto con las mufas (una por línea)')
    ap.add_argument('--metricas', nargs='+', help='Carpeta(s) o CSV con las marcas descargadas de los reportes')
    ap.add_argument('--db', default=os.path.join(AQUI, 'red_fibra.db'))
    ap.add_argument('--salida', default=os.path.join(AQUI, 'piloto'))
    a = ap.parse_args()
    if a.metricas:
        metricas(leer_marcas(a.metricas))
    elif a.mufas:
        generar(a)
    else:
        ap.error('Indique --mufas lista.txt o --metricas carpeta_de_marcas')
