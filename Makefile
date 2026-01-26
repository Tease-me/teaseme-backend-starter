.PHONY: seed-influencers seed-pricing seed-users seed-all seed-prompts seed-subscription-plans

COMPOSE ?= docker compose
SERVICE ?= backend

seed-influencers:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_influencers

seed-pricing:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_pricing

seed-users:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_users

seed-prompts:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_prompts

seed-subscription-plans:
	$(COMPOSE) exec $(SERVICE) poetry run python -m app.scripts.seed_subscription_plans

seed-all: seed-influencers seed-pricing seed-users seed-prompts seed-subscription-plans

.PHONY: db-wipe-conversations
db-wipe-conversations:
	$(COMPOSE) exec db psql -U postgres -d teaseme -c "TRUNCATE messages, memories, chats, calls CASCADE;"

.PHONY: alembic-revision alembic-upgrade alembic-downgrade alembic-current alembic-history alembic-stamp-production
alembic-revision:
	$(COMPOSE) exec $(SERVICE) poetry run alembic revision --autogenerate -m "$(MESSAGE)"

alembic-upgrade:
	$(COMPOSE) exec $(SERVICE) poetry run alembic upgrade head

alembic-downgrade:
	$(COMPOSE) exec $(SERVICE) poetry run alembic downgrade -1

alembic-current:
	$(COMPOSE) exec $(SERVICE) poetry run alembic current

alembic-history:
	$(COMPOSE) exec $(SERVICE) poetry run alembic history

# IMPORTANTE: Use este comando em produção após o primeiro deploy
alembic-stamp-production:
	@echo "⚠️  ATENÇÃO: Este comando marca o banco de produção sem executar migrações"
	@echo "📋 Use apenas na primeira vez após limpar as migrações antigas"
	@read -p "Você tem certeza? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		$(COMPOSE) exec $(SERVICE) poetry run alembic stamp head; \
		echo "✅ Banco marcado como versão inicial"; \
	else \
		echo "❌ Operação cancelada"; \
	fi

# Desenvolvimento local (fora do Docker)
.PHONY: alembic-local-revision alembic-local-upgrade alembic-local-current
alembic-local-revision:
	DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/teaseme" \
	poetry run alembic revision --autogenerate -m "$(MESSAGE)"

alembic-local-upgrade:
	DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/teaseme" \
	poetry run alembic upgrade head

alembic-local-current:
	DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/teaseme" \
	poetry run alembic current
