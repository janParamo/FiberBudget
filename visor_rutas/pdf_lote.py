"""PDF de presupuestos que ya existen: uno o varios Excel sueltos de output/visor, o carpetas enteras de coordenadas masivas.

- `carpetas(base)`: las carpetas de lotes masivos (masivo_*) con sus grupos (aprobados / desaprobados, o la carpeta plana de los lotes anteriores),
  cuántos Excel y cuántos PDF tiene cada uno. Lo que ya solo está en la base de archivos también se lista.
- `planificar(base, archivos, carpetas)`: qué Excel se convierte y en qué carpeta queda su PDF. Un Excel suelto: el PDF junto a él. Un grupo de un
  lote: `aprobados/` -> `aprobados_pdf/`, `desaprobados/` -> `desaprobados_pdf/`, una carpeta plana -> `pdf/` (dentro del lote).
- `GestorPdf`: la conversión en segundo plano (un trabajo a la vez), con avance y un .zip de los PDF hechos.

Las rutas son claves relativas a output/visor con «/» (`Uno_12.1_-86.2_2026.xlsx`, `masivo_X/aprobados`): nunca una ruta absoluta del equipo.
"""
import io
import logging
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

from visor_rutas import almacen_archivos

log = logging.getLogger(__name__)
PREFIJO_LOTE = "masivo_"
GRUPOS = ("aprobados", "desaprobados")
CARPETA_PLANA = "pdf"
MAX_ARCHIVOS = 600
_RE_LOTE = re.compile(r"^masivo_(\d{8})-(\d{6})_(.*)$")


def _clave(texto: str) -> str:
    partes = [p for p in str(texto or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if not partes or any(p == ".." or ":" in p for p in partes):
        raise ValueError("Ruta no válida")
    return "/".join(partes)


def _xlsx_de(base: Path, carpeta: str) -> dict[str, int]:
    """{clave de cada Excel de esa carpeta (sin entrar a otras): tamaño}, de la base de archivos y del disco."""
    salida: dict[str, int] = {}
    for f in almacen_archivos.listar("visor", carpeta + "/"):
        resto = f["clave"][len(carpeta) + 1:]
        if "/" not in resto and resto.lower().endswith(".xlsx") and not resto.startswith("~$") and resto != "Resumen.xlsx":
            salida[f["clave"]] = f["tamano"]
    directorio = base / carpeta
    if directorio.is_dir():
        for p in directorio.glob("*.xlsx"):
            if p.is_file() and not p.name.startswith("~$") and p.name != "Resumen.xlsx":
                salida[f"{carpeta}/{p.name}"] = p.stat().st_size
    return salida


def _pdf_de(base: Path, carpeta: str) -> int:
    claves = {f["clave"] for f in almacen_archivos.listar("visor", carpeta + "/") if "/" not in f["clave"][len(carpeta) + 1:] and f["clave"].lower().endswith(".pdf")}
    directorio = base / carpeta
    if directorio.is_dir():
        claves |= {f"{carpeta}/{p.name}" for p in directorio.glob("*.pdf") if p.is_file()}
    return len(claves)


def carpetas(base: Path) -> list[dict[str, Any]]:
    """Batch folders of output/visor (newest first) with their groups: [{id, nombre, fecha, grupos: [{id, nombre, xlsx, pdf, destino}], xlsx}]."""
    nombres = {p.name for p in base.glob(PREFIJO_LOTE + "*") if p.is_dir()} if base.is_dir() else set()
    nombres |= {f["clave"].split("/", 1)[0] for f in almacen_archivos.listar("visor", PREFIJO_LOTE) if "/" in f["clave"]}
    salida = []
    for nombre in sorted(nombres, reverse=True):
        grupos = []
        for g in GRUPOS:
            n = len(_xlsx_de(base, f"{nombre}/{g}"))
            if n:
                grupos.append({"id": f"{nombre}/{g}", "nombre": g, "xlsx": n, "pdf": _pdf_de(base, f"{nombre}/{g}_pdf"), "destino": f"{g}_pdf"})
        planos = len(_xlsx_de(base, nombre))                                    # batches from before the two folders: everything in one
        if planos:
            grupos.append({"id": nombre, "nombre": "(todos, carpeta sin separar)", "xlsx": planos, "pdf": _pdf_de(base, f"{nombre}/{CARPETA_PLANA}") or _pdf_de(base, nombre),
                           "destino": CARPETA_PLANA})
        if not grupos:
            continue
        m = _RE_LOTE.match(nombre)
        fecha = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2][:2]}:{m[2][2:4]}" if m else ""
        salida.append({"id": nombre, "nombre": (m[3] if m else nombre).replace("_", " ").strip(), "fecha": fecha, "grupos": grupos,
                       "xlsx": sum(g["xlsx"] for g in grupos)})
    return salida


def planificar(base: Path, archivos: list[str], carpetas_pedidas: list[str]) -> list[tuple[str, Path, Path]]:
    """[(clave del Excel, ruta local del Excel, carpeta donde queda su PDF)], en orden y sin repetir. ValueError si lo pedido no existe o es demasiado."""
    trabajos: dict[str, tuple[str, Path, Path]] = {}
    base = base.resolve()
    for pedido in archivos:
        clave = _clave(pedido)
        if not clave.lower().endswith(".xlsx") or clave.split("/")[-1].startswith("~$"):
            raise ValueError(f"No es un presupuesto de Excel: {clave}")
        trabajos[clave] = (clave, base / clave, (base / clave).parent)
    for pedido in carpetas_pedidas:
        clave = _clave(pedido)
        partes = clave.split("/")
        if not partes[0].startswith(PREFIJO_LOTE) or len(partes) > 2 or (len(partes) == 2 and partes[1] not in GRUPOS):
            raise ValueError(f"No es una carpeta de coordenadas masivas: {clave}")
        # a whole batch = its groups, each to its own *_pdf folder, plus whatever is loose in it (a batch from before the two folders) to pdf/
        if len(partes) == 2:
            origenes = [(clave, f"{partes[1]}_pdf")]
        else:
            origenes = [(f"{clave}/{g}", f"{g}_pdf") for g in GRUPOS] + [(clave, CARPETA_PLANA)]
        for origen, destino in origenes:
            for k in sorted(_xlsx_de(base, origen)):
                trabajos.setdefault(k, (k, base / k, base / partes[0] / destino))
    if not trabajos:
        raise ValueError("No hay presupuestos de Excel en lo que eligió")
    if len(trabajos) > MAX_ARCHIVOS:
        raise ValueError(f"Hasta {MAX_ARCHIVOS} presupuestos por vez (eligió {len(trabajos)})")
    for clave, ruta, _ in trabajos.values():
        if base not in ruta.resolve().parents:
            raise ValueError("Ruta no válida")
    return list(trabajos.values())


def planificar_externo(archivos: list[str], carpetas_elegidas: list[str]) -> list[tuple[str | None, Path, Path]]:
    """The same plan for files and folders chosen in the file explorer (anywhere in this computer; the key is None).
    A file: its PDF next to it. A folder: its Excel files go to `pdf/` inside it, those of its `aprobados` / `desaprobados` subfolders to
    `aprobados_pdf` / `desaprobados_pdf` next to them, and those of any other subfolder to a `pdf/` inside that subfolder."""
    trabajos: dict[Path, tuple[str | None, Path, Path]] = {}

    def libros(directorio: Path) -> list[Path]:
        return sorted(p for p in directorio.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$") and p.name != "Resumen.xlsx")
    for pedido in archivos:
        ruta = Path(str(pedido))
        if ruta.suffix.lower() != ".xlsx" or ruta.name.startswith("~$") or not ruta.is_file():
            raise ValueError(f"No es un presupuesto de Excel que exista: {ruta.name or pedido}")
        trabajos.setdefault(ruta.resolve(), (None, ruta.resolve(), ruta.resolve().parent))
    for pedido in carpetas_elegidas:
        carpeta = Path(str(pedido))
        if not carpeta.is_dir():
            raise ValueError(f"No es una carpeta que exista: {pedido}")
        carpeta = carpeta.resolve()
        subcarpetas = [d for d in sorted(carpeta.iterdir()) if d.is_dir() and not d.name.lower().endswith("pdf")]
        for directorio in [carpeta] + subcarpetas:
            if directorio == carpeta:
                destino = carpeta / CARPETA_PLANA
            elif directorio.name in GRUPOS:
                destino = carpeta / f"{directorio.name}_pdf"
            else:
                destino = directorio / CARPETA_PLANA
            for libro in libros(directorio):
                trabajos.setdefault(libro.resolve(), (None, libro.resolve(), destino))
    if not trabajos:
        raise ValueError("No hay presupuestos de Excel en lo que eligió")
    if len(trabajos) > MAX_ARCHIVOS:
        raise ValueError(f"Hasta {MAX_ARCHIVOS} presupuestos por vez (eligió {len(trabajos)})")
    return list(trabajos.values())


class Trabajo:
    def __init__(self, id_: str, total: int):
        self.id = id_
        self.estado = "convirtiendo"                    # convirtiendo | listo | error
        self.hechos = 0
        self.total = total
        self.actual = ""
        self.fallos: list[str] = []
        self.salidas: list[Path] = []
        self.inicio = time.time()

    def carpetas_de_salida(self) -> list[str]:
        return sorted({p.parent.name for p in self.salidas})

    def publico(self) -> dict[str, Any]:
        return {"carpetas_salida": self.carpetas_de_salida(), "id": self.id, "estado": self.estado, "hechos": self.hechos, "total": self.total, "actual": self.actual, "fallos": list(self.fallos),
                "pdf": len(self.salidas), "segundos": round(time.time() - self.inicio)}


class GestorPdf:
    """One PDF job at a time in this process (LibreOffice converts one workbook at a time anyway)."""

    def __init__(self) -> None:
        self._trabajos: dict[str, Trabajo] = {}
        self._lock = threading.Lock()
        self._base: Path | None = None

    def iniciar(self, base: Path, plan: list[tuple[str | None, Path, Path]], convertir: Callable[[Path, Path], Path]) -> Trabajo:
        """`convertir(xlsx, carpeta_pdf) -> ruta del pdf`. Excel files that are only in the database are written back to the disk first."""
        with self._lock:
            if any(t.estado == "convirtiendo" for t in self._trabajos.values()):
                raise ValueError("Ya hay una conversión a PDF en curso: espere a que termine")
            trabajo = Trabajo(time.strftime("%Y%m%d-%H%M%S"), len(plan))
            self._trabajos[trabajo.id] = trabajo
            for viejo in sorted(self._trabajos)[:-5]:
                del self._trabajos[viejo]
            self._base = base

        def correr() -> None:
            try:
                for clave, ruta, destino in plan:
                    trabajo.actual = ruta.name
                    try:
                        if not ruta.is_file() and clave:
                            almacen_archivos.restaurar("visor", clave, ruta)
                        trabajo.salidas.append(convertir(ruta, destino))
                    except Exception as exc:                       # one workbook failing never stops the rest
                        log.warning("PDF of existing budgets: %s failed (%s: %s)", ruta.name, type(exc).__name__, exc)
                        trabajo.fallos.append(ruta.name)
                    trabajo.hechos += 1
                trabajo.estado = "listo" if trabajo.salidas else "error"
                try:
                    almacen_archivos.subir_carpeta("visor", base, patron="**/*.pdf", excluir=("mapas",))
                except Exception:
                    log.exception("PDF of existing budgets: could not store the PDFs in the database")
            except Exception:
                log.exception("PDF of existing budgets: the job failed")
                trabajo.estado = "error"
            finally:
                trabajo.actual = ""

        threading.Thread(target=correr, name=f"pdf-{trabajo.id}", daemon=True).start()
        return trabajo

    def obtener(self, id_: str) -> Trabajo:
        with self._lock:
            t = self._trabajos.get(str(id_))
        if t is None:
            raise KeyError("La conversión ya no existe (el visor o el servicio se reinició)")
        return t

    def comprimir(self, id_: str) -> tuple[str, bytes]:
        t = self.obtener(id_)
        if t.estado == "convirtiendo":
            raise ValueError("Todavía se está convirtiendo")
        salida = io.BytesIO()
        base = (self._base or Path(".")).resolve()
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
            for pdf in t.salidas:
                try:
                    try:
                        nombre = pdf.resolve().relative_to(base).as_posix()
                    except ValueError:                                   # a PDF outside output/visor (chosen in the explorer)
                        nombre = f"{pdf.parent.name}/{pdf.name}"
                    z.write(pdf, nombre)
                except OSError:
                    pass
        return f"PDF_{t.id}.zip", salida.getvalue()
