#!/bin/sh
# Container entrypoint: refuse bad config, apply migrations, then serve on $PORT (Cloud Run sets it).
set -eu
python -c "from scripts.check_env import enforce; enforce()"
python -m migrate
exec uvicorn run:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips='*'
