"""Environment variables, logging setup and business-rule loading."""
import logging
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Reasonable bounding box for Nicaragua (with a small margin).
NI_LAT_MIN, NI_LAT_MAX = 10.7, 15.1
NI_LON_MIN, NI_LON_MAX = -87.8, -82.5


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    api_host: str
    api_port: int
    log_level: str
    request_timeout_seconds: float
    output_retention_days: int
    google_api_key: str
    service_api_key: str
    template_path: Path
    output_dir: Path
    rules_path: Path
    log_file: Path
    ngrok_domain: str = ""
    libreoffice_path: str = ""   # empty: autodetect soffice (recalc.find_soffice)
    red_fibra_db: Path = BASE_DIR / "red_fibra" / "red_fibra.db"   # Visio SQLite (fallback)
    # Visio network in PostgreSQL (schema red_fibra). Empty VISIO_DB_NAME disables it.
    visio_db_host: str = "localhost"
    visio_db_port: int = 5432
    visio_db_name: str = ""
    visio_db_user: str = ""
    visio_db_password: str = ""
    radio_busqueda_m: float = 2000.0
    max_candidatos: int = 5


def _require(name: str) -> str:
    """Return a mandatory env var or fail fast with a clear message."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _path(name: str, default: str) -> Path:
    """Read a path env var; relative paths are resolved from the project folder."""
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else BASE_DIR / p


def _int_setting(name: str, default: str, *, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"Environment variable {name} must be >= {minimum}")
    return value


def _float_setting(name: str, default: str, *, minimum: float = 0) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be a number") from exc
    if not math.isfinite(value) or value <= minimum:
        raise RuntimeError(f"Environment variable {name} must be > {minimum}")
    return value


@lru_cache
def get_settings() -> Settings:
    """Load settings once from the environment (.env is loaded above)."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if not isinstance(getattr(logging, log_level, None), int):
        raise RuntimeError("Environment variable LOG_LEVEL must be a valid logging level")
    api_port = _int_setting("API_PORT", "8000", minimum=1)
    if api_port > 65535:
        raise RuntimeError("Environment variable API_PORT must be <= 65535")
    db_port = _int_setting("DB_PORT", _require("DB_PORT"), minimum=1)
    if db_port > 65535:
        raise RuntimeError("Environment variable DB_PORT must be <= 65535")
    api_host = os.getenv("API_HOST", "127.0.0.1").strip()
    if not api_host:
        raise RuntimeError("Environment variable API_HOST must not be empty")
    return Settings(
        db_host=_require("DB_HOST"),
        db_port=db_port,
        db_name=_require("DB_NAME"),
        db_user=_require("DB_USER"),
        db_password=_require("DB_PASSWORD"),
        google_api_key=_require("GOOGLE_API_KEY"),
        service_api_key=_require("SERVICE_API_KEY"),
        template_path=_path("TEMPLATE_PATH", "templates/PlantilaEjemploPresupuesto.xlsx"),
        output_dir=_path("OUTPUT_DIR", "output"),
        rules_path=_path("RULES_PATH", "business_rules.yaml"),
        log_file=_path("LOG_FILE", "logs/service.log"),
        api_host=api_host,
        api_port=api_port,
        log_level=log_level,
        request_timeout_seconds=_float_setting("REQUEST_TIMEOUT_SECONDS", "60"),
        output_retention_days=_int_setting("OUTPUT_RETENTION_DAYS", "30"),
        ngrok_domain=os.getenv("NGROK_DOMAIN", "").strip(),
        libreoffice_path=os.getenv("LIBREOFFICE_PATH", "").strip(),
        red_fibra_db=_path("RED_FIBRA_DB", "red_fibra/red_fibra.db"),
        visio_db_host=os.getenv("VISIO_DB_HOST", "localhost").strip() or "localhost",
        visio_db_port=_int_setting("VISIO_DB_PORT", "5432", minimum=1),
        visio_db_name=os.getenv("VISIO_DB_NAME", "").strip(),
        visio_db_user=os.getenv("VISIO_DB_USER", "").strip(),
        visio_db_password=os.getenv("VISIO_DB_PASSWORD", ""),
        radio_busqueda_m=_float_setting("RADIO_BUSQUEDA_M", "2000"),
        max_candidatos=_int_setting("MAX_CANDIDATOS", "5", minimum=1),
    )


def load_rules(path: Path) -> dict[str, Any]:
    """Read the business rules YAML file. Called per request so edits apply
    without touching code (restart not even required)."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_logging_ready = False


def setup_logging(log_file: Path, log_level: str = "INFO") -> None:
    """Log to console and to a rotating file (5 MB x 3 backups). Idempotent."""
    global _logging_ready
    if _logging_ready:
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_h = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    console_h = logging.StreamHandler()
    for h in (file_h, console_h):
        h.setFormatter(fmt)
    root = logging.getLogger()
    level = getattr(logging, log_level, None)
    if not isinstance(level, int):
        raise RuntimeError("Environment variable LOG_LEVEL must be a valid logging level")
    root.setLevel(level)
    root.addHandler(file_h)
    root.addHandler(console_h)
    _logging_ready = True
