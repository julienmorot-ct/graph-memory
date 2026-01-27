# -*- coding: utf-8 -*-
"""
AuthMiddleware - Middleware ASGI pour l'authentification Bearer Token.

Vérifie le header Authorization et valide le token via TokenManager.
"""

import os
import sys
from typing import Optional

from ..config import get_settings


class AuthMiddleware:
    """
    Middleware ASGI pour l'authentification.
    
    Vérifie le header `Authorization: Bearer <token>` et valide le token.
    Pour le bootstrap initial, accepte aussi ADMIN_BOOTSTRAP_KEY.
    """
    
    def __init__(self, app, debug: bool = False):
        """
        Initialise le middleware.
        
        Args:
            app: Application ASGI à wrapper
            debug: Mode debug (logs détaillés)
        """
        self.app = app
        self.debug = debug
        self._settings = get_settings()
        self._token_manager = None
    
    @property
    def token_manager(self):
        """Lazy-load du TokenManager."""
        if self._token_manager is None:
            from .token_manager import get_token_manager
            self._token_manager = get_token_manager()
        return self._token_manager
    
    async def __call__(self, scope, receive, send):
        """Point d'entrée ASGI."""
        if scope["type"] != "http":
            # Passer directement pour WebSocket, lifespan, etc.
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        
        # Endpoints publics (pas d'auth requise)
        public_paths = ["/health", "/healthz", "/ready"]
        if any(path.startswith(p) for p in public_paths):
            await self.app(scope, receive, send)
            return
        
        # Récupérer le header Authorization
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")
        
        if not auth_header:
            if self.debug:
                print(f"❌ [Auth] Header Authorization manquant pour {path}", file=sys.stderr)
            await self._send_error(send, 401, "Authorization header required")
            return
        
        # Parser le Bearer token
        if not auth_header.startswith("Bearer "):
            if self.debug:
                print(f"❌ [Auth] Format invalide (attendu: Bearer <token>)", file=sys.stderr)
            await self._send_error(send, 401, "Invalid authorization format. Use: Bearer <token>")
            return
        
        token = auth_header[7:]  # Retire "Bearer "
        
        # Vérifier si c'est la clé bootstrap admin
        bootstrap_key = self._settings.admin_bootstrap_key
        if bootstrap_key and token == bootstrap_key:
            if self.debug:
                print(f"✅ [Auth] Authentification avec clé bootstrap admin", file=sys.stderr)
            # Ajouter info d'auth au scope
            scope["auth"] = {
                "type": "bootstrap",
                "client_name": "admin",
                "permissions": ["admin", "read", "write"],
                "memory_ids": []  # Accès à toutes
            }
            await self.app(scope, receive, send)
            return
        
        # Valider le token client
        try:
            token_info = await self.token_manager.validate_token(token)
            
            if not token_info:
                if self.debug:
                    print(f"❌ [Auth] Token invalide ou expiré", file=sys.stderr)
                await self._send_error(send, 401, "Invalid or expired token")
                return
            
            if self.debug:
                print(f"✅ [Auth] Client '{token_info.client_name}' authentifié", file=sys.stderr)
            
            # Ajouter info d'auth au scope
            scope["auth"] = {
                "type": "token",
                "client_name": token_info.client_name,
                "permissions": token_info.permissions,
                "memory_ids": token_info.memory_ids,
                "token_hash": token_info.token_hash
            }
            
            await self.app(scope, receive, send)
            
        except Exception as e:
            if self.debug:
                print(f"❌ [Auth] Erreur validation: {e}", file=sys.stderr)
            await self._send_error(send, 500, "Authentication error")
    
    async def _send_error(self, send, status: int, message: str):
        """Envoie une réponse d'erreur HTTP."""
        import json
        
        body = json.dumps({"error": message}).encode()
        
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })


class LoggingMiddleware:
    """
    Middleware ASGI pour le logging des requêtes (mode debug).
    """
    
    def __init__(self, app, debug: bool = False):
        self.app = app
        self.debug = debug
    
    async def __call__(self, scope, receive, send):
        if not self.debug or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        method = scope.get("method", "?")
        query = scope.get("query_string", b"").decode()
        
        full_path = f"{path}?{query}" if query else path
        print(f"📥 [HTTP] {method} {full_path}", file=sys.stderr)
        
        # Wrapper pour logger la réponse
        status_code = [None]
        
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code[0] = message.get("status")
            await send(message)
        
        await self.app(scope, receive, send_wrapper)
        
        if status_code[0]:
            emoji = "✅" if status_code[0] < 400 else "❌"
            print(f"{emoji} [HTTP] {method} {path} -> {status_code[0]}", file=sys.stderr)
