# =============================================================================
# WAF Dockerfile — Caddy + Coraza WAF + OWASP CRS
# =============================================================================
# Build multi-stage :
# 1. Compile Caddy avec le plugin coraza-caddy via xcaddy
# 2. Image finale caddy:2-alpine avec le binaire custom
# =============================================================================

# Stage 1 : Build Caddy avec Coraza
FROM caddy:2-builder AS builder

RUN xcaddy build \
    --with github.com/corazawaf/coraza-caddy/v2 \
    --with github.com/mholt/caddy-ratelimit

# Stage 2 : Image finale
FROM caddy:2-alpine

# Copier le binaire Caddy custom (avec Coraza)
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# Le Caddyfile sera monté en volume depuis docker-compose
