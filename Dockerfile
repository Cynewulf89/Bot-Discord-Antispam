# Utiliser l'image uv officielle pour copier le binaire
FROM ghcr.io/astral-sh/uv:latest AS uv_bin

# Image Python de base
FROM python:3.13-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier le binaire uv
COPY --from=uv_bin /uv /uvx /bin/

# Configuration environnement uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Installer les dépendances d'abord pour le cache Docker
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copier le code source
COPY . .
RUN uv sync --frozen --no-dev

# Lancer l'application
CMD ["uv", "run", "python", "src/bot_discord_antispam/silence.py"]
