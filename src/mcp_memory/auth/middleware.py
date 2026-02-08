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
        public_paths = ["/health", "/healthz", "/ready", "/graph", "/api/"]
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


class StaticFilesMiddleware:
    """
    Middleware ASGI pour servir les fichiers statiques et l'API REST simple.
    
    Routes:
    - GET /graph -> Page de visualisation
    - GET /api/memories -> Liste des mémoires (JSON)
    - GET /api/graph/<memory_id> -> Graphe complet (JSON)
    """
    
    def __init__(self, app):
        self.app = app
        self._static_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "static"
        )
        self._graph_service = None
    
    @property
    def graph_service(self):
        """Lazy-load GraphService."""
        if self._graph_service is None:
            from ..core.graph import get_graph_service
            self._graph_service = get_graph_service()
        return self._graph_service
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        
        # Page de visualisation
        if path == "/graph" or path == "/graph/":
            await self._serve_file(send, "graph.html", "text/html")
            return
        
        # Health check
        if path in ("/health", "/healthz", "/ready"):
            await self._api_health(send)
            return
        
        # API REST - Liste des mémoires
        if path == "/api/memories" and method == "GET":
            await self._api_memories(send)
            return
        
        # API REST - Graphe d'une mémoire
        if path.startswith("/api/graph/") and method == "GET":
            memory_id = path[len("/api/graph/"):]
            if memory_id:
                await self._api_graph(send, memory_id)
                return
        
        # Passer au handler suivant
        await self.app(scope, receive, send)
    
    async def _api_health(self, send):
        """Retourne l'état de santé du serveur."""
        import json
        from datetime import datetime
        try:
            # Test rapide Neo4j via une requête simple
            neo4j_ok = False
            neo4j_msg = "Non testé"
            try:
                test = await self.graph_service.test_connection()
                neo4j_ok = test.get("status") == "ok"
                neo4j_msg = test.get("message", "OK")
            except Exception as e:
                neo4j_msg = str(e)
            
            data = {
                "status": "healthy" if neo4j_ok else "degraded",
                "version": "0.5.0",
                "timestamp": datetime.utcnow().isoformat(),
                "services": {
                    "neo4j": {"status": "ok" if neo4j_ok else "error", "message": neo4j_msg}
                }
            }
            await self._send_json(send, data)
        except Exception as e:
            await self._send_json(send, {
                "status": "error",
                "version": "0.5.0",
                "message": str(e)
            }, 500)
    
    async def _api_memories(self, send):
        """Retourne la liste des mémoires en JSON."""
        import json
        try:
            memories = await self.graph_service.list_memories()
            data = {
                "status": "ok",
                "count": len(memories),
                "memories": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "description": m.description,
                        "ontology": m.ontology,
                        "ontology_uri": m.ontology_uri,
                        "created_at": m.created_at.isoformat() if m.created_at else None
                    }
                    for m in memories
                ]
            }
            await self._send_json(send, data)
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)
    
    async def _api_graph(self, send, memory_id: str):
        """Retourne le graphe complet d'une mémoire en JSON."""
        import json
        try:
            graph_data = await self.graph_service.get_full_graph(memory_id)
            data = {
                "status": "ok",
                "memory_id": memory_id,
                "node_count": len(graph_data["nodes"]),
                "edge_count": len(graph_data["edges"]),
                "document_count": len(graph_data["documents"]),
                "nodes": graph_data["nodes"],
                "edges": graph_data["edges"],
                "documents": graph_data["documents"]
            }
            await self._send_json(send, data)
        except Exception as e:
            await self._send_json(send, {"status": "error", "message": str(e)}, 500)
    
    async def _send_json(self, send, data: dict, status: int = 200):
        """Envoie une réponse JSON."""
        import json
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
    
    async def _serve_file(self, send, filename: str, content_type: str):
        """Sert un fichier statique."""
        filepath = os.path.join(self._static_dir, filename)
        
        if not os.path.exists(filepath):
            await self._send_404(send, f"File not found: {filename}")
            return
        
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", content_type.encode()),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-cache"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
        except Exception as e:
            await self._send_500(send, str(e))
    
    async def _send_404(self, send, message: str):
        """Envoie une erreur 404."""
        body = f"<h1>404 Not Found</h1><p>{message}</p>".encode()
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [
                (b"content-type", b"text/html"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
    
    async def _send_500(self, send, message: str):
        """Envoie une erreur 500."""
        body = f"<h1>500 Internal Server Error</h1><p>{message}</p>".encode()
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"text/html"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
