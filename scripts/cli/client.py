# -*- coding: utf-8 -*-
"""
MCPClient - Communication avec le serveur MCP Memory.

Deux modes de communication :
  - REST : pour les endpoints simples (health, list, graph)
  - SSE/MCP : pour appeler les outils MCP (ingest, delete, search...)

Gestion des erreurs de connexion :
  - Si le serveur est injoignable, lève ServerNotRunningError
  - Le message indique comment démarrer le serveur (docker compose up -d)
"""

import json
from typing import Dict, Any


class ServerNotRunningError(Exception):
    """Levée quand le serveur MCP n'est pas accessible."""

    def __init__(self, url: str, original_error: Exception = None):
        self.url = url
        self.original_error = original_error
        super().__init__(
            f"🔴 Serveur MCP non accessible ({url})\n"
            f"\n"
            f"  Démarrez-le avec :  docker compose up -d\n"
            f"  Vérifiez les logs : docker compose logs -f mcp-memory\n"
        )


class MCPClient:
    """Client pour communiquer avec le serveur MCP Memory."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    # =========================================================================
    # Transport bas niveau
    # =========================================================================

    async def _fetch(self, endpoint: str) -> dict:
        """
        Requête GET sur l'API REST.

        Lève ServerNotRunningError si le serveur est injoignable.
        """
        import aiohttp

        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        return await response.json()
                    text = await response.text()
                    raise Exception(f"HTTP {response.status}: {text}")
        except aiohttp.ClientConnectorError:
            raise ServerNotRunningError(self.base_url)
        except aiohttp.ClientConnectionError:
            raise ServerNotRunningError(self.base_url)
        except ConnectionRefusedError:
            raise ServerNotRunningError(self.base_url)
        except OSError as e:
            # Couvre les erreurs réseau bas niveau (ex: "Connection refused")
            if "Connect call failed" in str(e) or "refused" in str(e).lower():
                raise ServerNotRunningError(self.base_url)
            raise

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """
        Appeler un outil MCP via le protocole SSE.

        Lève ServerNotRunningError si le serveur est injoignable.
        Les erreurs de connexion SSE sont souvent wrappées dans un
        ExceptionGroup/TaskGroup, d'où le parsing récursif.
        """
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            async with sse_client(f"{self.base_url}/sse", headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, args)
                    return json.loads(result.content[0].text)
        except ConnectionRefusedError:
            raise ServerNotRunningError(self.base_url)
        except OSError as e:
            if "refused" in str(e).lower() or "Connect call failed" in str(e):
                raise ServerNotRunningError(self.base_url)
            raise
        except BaseException as e:
            # ExceptionGroup / TaskGroup wrappent souvent les erreurs de connexion
            if self._is_connection_error(e):
                raise ServerNotRunningError(self.base_url)
            raise

    @staticmethod
    def _is_connection_error(exc: BaseException) -> bool:
        """
        Vérifie récursivement si une exception (ou un ExceptionGroup)
        contient une erreur de connexion.

        Couvre :
        - ConnectionRefusedError (stdlib)
        - OSError avec "refused" ou "connect call failed"
        - httpx.ConnectError ("All connection attempts failed")
        - Toute exception avec "connection" dans le nom de type
        """
        # Types stdlib
        if isinstance(exc, (ConnectionRefusedError,)):
            return True
        if isinstance(exc, OSError):
            msg = str(exc).lower()
            if "refused" in msg or "connect call failed" in msg:
                return True
        # httpx/anyio ConnectError et variantes
        type_name = type(exc).__name__
        if "ConnectError" in type_name or "ConnectionError" in type_name:
            return True
        # Message générique de connexion
        msg = str(exc).lower()
        if "connection attempts failed" in msg or "connection refused" in msg:
            return True
        # Parcourir les sous-exceptions d'un ExceptionGroup
        if hasattr(exc, 'exceptions'):
            for sub in exc.exceptions:
                if MCPClient._is_connection_error(sub):
                    return True
        return False

    # =========================================================================
    # Raccourcis API REST
    # =========================================================================

    async def list_memories(self) -> dict:
        """Liste les mémoires via REST."""
        return await self._fetch("/api/memories")

    async def get_graph(self, memory_id: str) -> dict:
        """Récupère le graphe complet d'une mémoire via REST."""
        return await self._fetch(f"/api/graph/{memory_id}")
