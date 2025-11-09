# TeaseMe Backend (FastAPI + Parlant)

## Quickstart

1. Start Postgres+pgvector in Docker:

   docker compose -f dev.compose.yml up -d

2. Create & migrate database (Alembic):

   poetry run alembic upgrade head

3. Run backend locally:

   poetry run uvicorn app.main:app --reload --port 8000

4. WebSocket chat:

   ws://localhost:8000/ws/chat/anna

## Project structure

- app/main.py # FastAPI entrypoint
- app/api/router.py # WebSocket chat endpoint
- app/db/models.py # SQLAlchemy+pgvector models
c
# TeaseMe Backend

TeaseMe is a multi-persona conversational AI platform with audio, memory, and customizable “brains” per agent.

## 🚀 How to run locally

```bash
git clone https://github.com/your-org/teaseme-backend.git
cd teaseme-backend
poetry install
cp .env.example .env  # edit your variables
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload
```
