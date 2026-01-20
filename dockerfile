FROM python:3.11-slim

# Install build deps, Pillow dependencies, and Poetry
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
        libpng-dev \
        ffmpeg \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry

WORKDIR /usr/src/

# Copy only pyproject.toml and poetry.lock to install deps first
COPY pyproject.toml poetry.lock ./

# Install Python dependencies (before purging build tools)
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Clean up build dependencies to reduce image size
RUN apt-get purge -y curl build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the rest of your app
COPY ./alembic ./alembic
COPY ./app ./app
COPY ./alembic.ini ./
COPY ./poetry.lock ./
COPY ./pyproject.toml ./
COPY .env ./
COPY ./.cert ./.cert