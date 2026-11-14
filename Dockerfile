FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the retrieval embedding model into the image. Without this the tutor's passage index can silently stay
# empty (embed.ready() is False when the weights can't be fetched at runtime) and every tutor prompt falls back
# to whole files (~50k tokens). Same default as embed.py (EMBED_MODEL / FASTEMBED_CACHE_PATH).
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN mkdir -p /opt/fastembed \
 && python -c "from fastembed import TextEmbedding; list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed').embed(['warm']))" \
 && chmod -R a+rX /opt/fastembed \
 && HF_HUB_OFFLINE=1 python -c "from fastembed import TextEmbedding; import sys; v=list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed').embed(['offline check']))[0]; sys.exit(0 if len(v)==384 else 1)"

COPY run.py llm.py auth.py storage.py migrate.py embed.py retrieval.py schedule.py oral.py essay.py casetrainer.py tts.py course_brief.py blueprint.py readiness.py card_tagging.py concepts.py citecheck.py countdown.py weaktopics.py pack.py mockexam.py docketgen.py relevance.py gateway.py ./
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
