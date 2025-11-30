.PHONY: seed-influencers seed-pricing seed-users seed-all

# Adjust COMPOSE or SERVICE if your setup differs.
COMPOSE ?= docker compose
SERVICE ?= backend

seed-influencers:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_influencers

seed-pricing:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_pricing

seed-users:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_users

seed-all: seed-influencers seed-pricing seed-users

.PHONY: db-wipe-conversations
db-wipe-conversations:
	$(COMPOSE) exec db psql -U postgres -d teaseme -c "TRUNCATE messages, memories, chats, calls CASCADE;"

.PHONY: alembic-revision alembic-upgrade alembic-downgrade
alembic-revision:
	$(COMPOSE) exec $(SERVICE) poetry run alembic revision --autogenerate -m "$(MESSAGE)"

alembic-upgrade:
	$(COMPOSE) exec $(SERVICE) poetry run alembic upgrade head

alembic-downgrade:
	$(COMPOSE) exec $(SERVICE) poetry run alembic downgrade -1
