

set -e

ENV=${1:-development}

if [ "$ENV" = "production" ]; then
    echo "🚀 Deploying to PRODUCTION"
    echo "⚠️  Checking if this is the initial migration..."
    
    HAS_VERSION=$(docker exec tm-service-backend alembic current 2>/dev/null | grep -c "2139b2e332d3" || echo "0")
    
    if [ "$HAS_VERSION" = "0" ]; then
        echo "📌 Stamping database as initial version (no tables will be created)"
        docker exec tm-service-backend alembic stamp head
    else
        echo "✅ Running normal migrations"
        docker exec tm-service-backend alembic upgrade head
    fi
else
    echo "🔧 Deploying to DEVELOPMENT"
    DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/tm_service" \
    poetry run alembic upgrade head
fi

echo "✨ Migration deployment complete!"
alembic current
