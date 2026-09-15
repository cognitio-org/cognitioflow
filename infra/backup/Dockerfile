# The weekly backup job (scripts/backup.py). Built and deployed by .github/workflows/deploy.yml as the Cloud Run job
# cognitioflow-backup; infra/backup.sh creates its service account and schedule.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# pg_dump must be at least the server's major version (Neon runs Postgres 18); Debian ships older, so use PGDG.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install "psycopg[binary]" google-cloud-storage
COPY scripts/backup.py scripts/pgtools.py scripts/

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
USER app

CMD ["python", "scripts/backup.py"]
