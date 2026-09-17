FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY run.py auth.py storage.py migrate.py embed.py retrieval.py schedule.py oral.py tts.py course_brief.py ./
COPY transcribe/ transcribe/
COPY scripts/check_env.py scripts/start.sh scripts/
COPY static/ static/
# The Arena's 3D player and its games (served at /play/player and via /api/courses/{cid}/docket, both behind sign-in)
COPY play/ play/
COPY prompts/ prompts/
COPY migrations/ migrations/

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
USER app

EXPOSE 8080
CMD ["scripts/start.sh"]
