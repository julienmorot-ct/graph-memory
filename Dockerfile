# =============================================================================
# MCP Memory Service - Dockerfile
# =============================================================================
# Build   : docker build -t mcp-memory .
# Run     : docker run -p 8002:8002 --env-file .env mcp-memory
# =============================================================================

FROM python:3.11-slim

# Métadonnées
LABEL maintainer="Cloud Temple"
LABEL description="MCP Memory Service - Knowledge Graph Memory for AI Agents"
LABEL version="1.0.0"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Installer uv depuis l'image officielle
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Répertoire de travail
WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python (cache optimisé)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# Copie des ontologies
COPY ONTOLOGIES/ ./ONTOLOGIES/

# Copie de la version et du code source
COPY VERSION .
COPY src/ ./src/

# Installation du projet avec les sources (dépendances déjà en cache)
RUN uv sync --frozen --no-dev --no-editable

# Créer un utilisateur non-root pour la sécurité
RUN groupadd -r mcp && useradd -r -g mcp -d /app -s /sbin/nologin mcp

# Donner les droits à l'utilisateur mcp
RUN chown -R mcp:mcp /app

# Port exposé
EXPOSE 8002

# Passer en utilisateur non-root
USER mcp

# Healthcheck via /health endpoint (léger, pas de fork Python)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8002/health -o /dev/null 2>/dev/null

# Point d'entrée
ENTRYPOINT ["uv", "run", "mcp-memory"]
CMD ["--port", "8002"]
