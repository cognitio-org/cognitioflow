.PHONY: dev test migrate db-reset db-branch

PORT ?= 8000

dev:
	uvicorn run:app --reload --env-file .env.local --port $(PORT)

test:
	pytest tests/ -v --tb=short

migrate:
	python -m migrate

db-reset:
	@python3 -c "\
import os; \
from dotenv import load_dotenv; \
load_dotenv('.env.local', override=True); load_dotenv(); \
import psycopg; \
conn = psycopg.connect(os.environ['DATABASE_URL']); \
conn.execute('DROP TABLE IF EXISTS schema_migrations, reviews, recordings, note_versions, sessions, cards, notes, messages, files, courses, users CASCADE'); \
conn.commit(); conn.close(); \
print('DB reset complete.')"
	$(MAKE) migrate

db-branch:
	@test -n "$(NAME)" || (echo "Usage: make db-branch NAME=<branch-name>" && exit 1)
	neonctl branches create --name $(NAME)
	@echo "Get the connection string with: neonctl connection-string --branch $(NAME)"
