# -*- coding: utf-8 -*-
"""
Module d'authentification pour MCP Memory.

- TokenManager : Gestion des tokens clients (CRUD)
- Middleware : Vérification des tokens Bearer
"""

from .token_manager import TokenManager, get_token_manager
from .middleware import AuthMiddleware, LoggingMiddleware, StaticFilesMiddleware

__all__ = [
    "TokenManager", "get_token_manager",
    "AuthMiddleware", "LoggingMiddleware", "StaticFilesMiddleware",
]
