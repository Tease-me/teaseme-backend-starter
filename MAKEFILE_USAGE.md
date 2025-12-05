# Makefile Quickstart

Use these targets to run common tasks inside the backend container. Targets assume the project runs under Docker Compose; override variables as needed.

## Variables
- `COMPOSE` (default: `docker compose`) — set to `docker-compose` on servers that require the hyphenated CLI.
- `SERVICE` (default: `backend`) — container name where commands run.

Example for servers with `docker-compose`:
```sh
COMPOSE="docker-compose" make seed-all
```

## Seeding data
- `make seed-influencers` — updates influencer prompt templates/voice config.
- `make seed-pricing` — seeds or updates pricing rows.
- `make seed-users` — seeds default users (e.g., admin).
- `make seed-prompts` — seeds system prompts (BASE_SYSTEM, BASE_AUDIO_SYSTEM, etc.).
- `make seed-all` — runs all of the above in sequence.

## Database cleanup
- `make db-wipe-conversations` — truncates messages, memories, chats, and calls tables. **Destructive**.

## Alembic migrations
- `make alembic-revision MESSAGE="add new table"` — create an autogen migration.
- `make alembic-upgrade` — apply migrations to `head`.
- `make alembic-downgrade` — roll back one revision.

## Running with a different service/container
If your API container is named differently:
```sh
SERVICE=app COMPOSE="docker-compose" make seed-users
```

## Troubleshooting
- Ensure the target container is running before invoking `make` (e.g., `docker compose up backend`).
- If `make` cannot find the container, double-check `SERVICE` matches the Compose service name.
- If commands fail with “command not found,” verify `poetry` is installed inside the container.***
