# Servicio de presupuestos (FastAPI) + visor remoto + app de campo, en un solo contenedor.
# Despliegue paso a paso: docker/LEEME.md.  Construir:  docker build -t presupuestos:local .
#
# Trae: Python 3.13, LibreOffice (recalcula el Excel y exporta el PDF) con sus fuentes, y el cliente de PostgreSQL 18 (pg_dump de los respaldos).
# NO trae: el .env, las bases de datos, el KMZ, los Visio, ni el visor de escritorio (VisorRutas.exe se genera aparte en Windows).
FROM python:3.13-slim-bookworm

ARG PG_CLIENT_VERSION=18
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Managua \
    HOME=/home/app

# LibreOffice (solo Calc; sin interfaz grafica) + fuentes compatibles con Arial / Calibri / Cambria (el Excel de la empresa y los PDF se ven igual)
# + cliente de PostgreSQL de la MISMA version que el servidor (pg_dump no acepta un servidor mas nuevo que el)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl tini tzdata \
        libreoffice-core libreoffice-calc \
        fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends "postgresql-client-${PG_CLIENT_VERSION}" \
 && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios (uid 1000). Las carpetas de datos se montan como volumenes (ver docker-compose.yml).
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/output /app/logs /app/datos /respaldos \
 && chown -R app:app /app /respaldos /home/app

WORKDIR /app

COPY requirements-servicio.txt .
RUN pip install -r requirements-servicio.txt

# El codigo (el .dockerignore deja pasar solo lo necesario)
COPY --chown=app:app . .

USER app

# Prueba de humo al construir: el servicio y el visor remoto se importan en Linux (con variables de relleno) y LibreOffice arranca.
# Si esto falla, la imagen no sirve: no se publica una imagen rota.
RUN DB_HOST=x DB_PORT=5432 DB_NAME=x DB_USER=x DB_PASSWORD=x GOOGLE_API_KEY=x SERVICE_API_KEY=x python -c "import main, visor_api; print('imports ok')" \
 && soffice --headless --version

# Dentro del contenedor escucha en todas las interfaces; quien lo publica (docker-compose.yml) lo deja solo en la VM o detras del proxy HTTPS.
ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    REDES_RESPALDOS_DIR=/respaldos

EXPOSE 8000
VOLUME ["/app/output", "/app/datos", "/app/logs", "/respaldos"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Un solo proceso (--workers 1): el indice de tickets y los avisos en tiempo real no admiten varios.
# --forwarded-allow-ips "*": el contenedor solo es alcanzable por el proxy (Caddy) o por el tunel de ngrok que abre el propio servicio.
ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
