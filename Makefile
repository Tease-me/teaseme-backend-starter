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
