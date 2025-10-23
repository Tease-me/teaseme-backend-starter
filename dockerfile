FROM python:3.11-slim

# Install build deps and Poetry
RUN apt-get update \
    && apt-get install -y curl build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && apt-get purge -y curl build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/

# Copy only pyproject.toml and poetry.lock to install deps first
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-interaction --no-ansi --no-root

# Copy the rest of your app
COPY ./alembic ./alembic
COPY ./app ./app
COPY ./alembic.ini ./
COPY ./poetry.lock ./
COPY ./pyproject.toml ./
COPY ./redis_dump_all.py ./
COPY .env ./
COPY ./.cert ./
# Expose the port FastAPI will run on
EXPOSE 8000

# Default command (run migrations then start the app)
CMD ["sh", "-c", "poetry run alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --ssl-keyfile=./.cert/key.pem --ssl-certfile=./.cert/cert.pem"]
