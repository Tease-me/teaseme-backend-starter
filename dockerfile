FROM python:3.11-slim

# Install build deps and Poetry
RUN apt-get update \
    && apt-get install -y curl build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && apt-get purge -y curl build-essential \
    && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/

# Copy only pyproject.toml and poetry.lock to install deps first
COPY pyproject.toml poetry.lock ./
# Copy the rest of your app
COPY ./alembic ./alembic
COPY ./app ./app
COPY ./alembic.ini ./
COPY ./poetry.lock ./
COPY ./pyproject.toml ./
COPY .env ./
COPY ./.cert ./.cert

RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-interaction --no-ansi --no-root