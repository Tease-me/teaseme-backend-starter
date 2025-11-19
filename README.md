# TeaseMe Backend (FastAPI)

TeaseMe is a multi-persona conversational AI platform with audio, long-term memory, and customizable “brains” per agent.

## Quickstart

1. **Clone & prep env**

   ```bash
   git clone https://github.com/your-org/teaseme-backend.git
   cd teaseme-backend
   cp .env.example .env                         # edit secrets
   add certs to .cert/cert.pem and .cert/key.pem
   ```

2. **Start the full stack (backend + Postgres + Redis)**

   ```bash
   docker compose up --build -d
   ```

3. **Tail logs or stop services**

   ```bash
   docker compose logs -f backend
   docker compose down                          # add -v to prune volumes
   ```

4. **Talk to the API**

- app/main.py # FastAPI entrypoint
- app/api/router.py # WebSocket chat endpoint
- app/db/models.py # SQLAlchemy+pgvector models
c
# TeaseMe Backend
   - REST: `https://localhost:8000`
   - WebSocket chat: `wss://localhost:8000/ws/chat/<persona>`

Database migrations run automatically in the backend container, so no local tooling is required.

## Local development without Docker

Prefer running services directly? Install dependencies with Poetry and use Docker only for databases.

```bash
poetry install
cp .env.example .env
docker compose -f compose.yml up -d db redis
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload --port 8000
# or run everything (migrations + TLS-enabled dev server) in one go:
poetry run alembic upgrade head && \
poetry run uvicorn app.main:app \
  --host 0.0.0.0 --port 8080 --reload \
  --ssl-keyfile=./.cert/key.pem --ssl-certfile=./.cert/cert.pem
```

WebSocket endpoint: `ws://localhost:8000/ws/chat/<persona>`

## Project structure

- app/main.py — FastAPI entrypoint
- app/api/router.py — HTTP/WebSocket routes
- app/db/models.py — SQLAlchemy + pgvector models
