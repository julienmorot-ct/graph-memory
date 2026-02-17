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
ENV PYTHONPATH=/app

# Répertoire de travail
WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Créer un utilisateur non-root pour la sécurité
RUN groupadd -r mcp && useradd -r -g mcp -d /app -s /sbin/nologin mcp

# Copie des ontologies
COPY ONTOLOGIES/ ./ONTOLOGIES/

# Copie du code source
COPY src/ ./src/

# Donner les droits à l'utilisateur mcp
RUN chown -R mcp:mcp /app

# Port exposé
EXPOSE 8002

# Passer en utilisateur non-root
USER mcp

# Healthcheck (curl = léger, pas de fork Python qui consomme 50MB+)
# /sse est un endpoint SSE (streaming infini) : curl reçoit le HTTP 200 puis
# timeout car le flux ne se ferme jamais → exit code 28.
# On accepte exit 0 (succès) OU exit 28 (timeout après connexion réussie) = healthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8002/sse --max-time 2 -o /dev/null 2>/dev/null; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 28 ]

# Point d'entrée
ENTRYPOINT ["python", "-m", "src.mcp_memory.server"]
CMD ["--port", "8002"]
