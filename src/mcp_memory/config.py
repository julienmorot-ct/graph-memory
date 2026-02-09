# -*- coding: utf-8 -*-
"""
Configuration centralisée du service MCP Memory.

Utilise pydantic-settings pour charger et valider la configuration
depuis les variables d'environnement ou un fichier .env.
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration du service MCP Memory.
    
    Toutes les variables peuvent être définies via:
    - Variables d'environnement
    - Fichier .env à la racine du projet
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # =========================================================================
    # S3 Cloud Temple
    # =========================================================================
    s3_endpoint_url: str = "https://takinc5acc.s3.fr1.cloud-temple.com"
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_bucket_name: str = "quoteflow-memory"
    s3_region_name: str = "fr1"
    
    # =========================================================================
    # LLMaaS Cloud Temple
    # =========================================================================
    llmaas_api_url: str = "https://api.ai.cloud-temple.com"
    llmaas_api_key: str
    llmaas_model: str = "gpt-oss:120b"
    llmaas_max_tokens: int = 60000  # gpt-oss:120b fait du chain-of-thought qui consomme beaucoup de tokens
    llmaas_temperature: float = 1.0  # gpt-oss:120b fonctionne mieux à température 1.0
    extraction_max_text_length: int = 950000  # Max chars du texte envoyé au LLM (défaut ~950K)
    
    # =========================================================================
    # Embedding (LLMaaS)
    # =========================================================================
    llmaas_embedding_model: str = "bge-m3:567m"
    llmaas_embedding_dimensions: int = 1024  # Dimension des vecteurs BGE-M3
    
    # =========================================================================
    # Qdrant (base vectorielle)
    # =========================================================================
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection_prefix: str = "memory_"  # Préfixe pour les collections Qdrant
    
    # =========================================================================
    # Chunking sémantique
    # =========================================================================
    chunk_size: int = 500  # Taille cible en tokens par chunk
    chunk_overlap: int = 50  # Tokens de chevauchement entre chunks adjacents
    
    # =========================================================================
    # RAG — Recherche vectorielle
    # =========================================================================
    rag_score_threshold: float = 0.65  # Score cosinus minimum pour un chunk (en dessous = ignoré)
    rag_chunk_limit: int = 8  # Nombre max de chunks retournés par Qdrant
    
    # =========================================================================
    # Neo4j
    # =========================================================================
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"  # Base par défaut
    
    # =========================================================================
    # MCP Server
    # =========================================================================
    mcp_server_port: int = 8002
    mcp_server_host: str = "0.0.0.0"
    mcp_server_debug: bool = False
    mcp_server_name: str = "mcp-memory"
    
    # =========================================================================
    # Admin / Auth
    # =========================================================================
    admin_bootstrap_key: Optional[str] = None  # Pour créer le premier token
    
    # =========================================================================
    # Limites et timeouts
    # =========================================================================
    max_document_size_mb: int = 50
    extraction_timeout_seconds: int = 120
    s3_upload_timeout_seconds: int = 60
    neo4j_query_timeout_seconds: int = 30
    
    @property
    def llmaas_base_url(self) -> str:
        """URL complète pour le client OpenAI (compatible OpenAI)."""
        # L'URL doit pointer vers le endpoint compatible OpenAI
        # Cloud Temple: https://api.ai.cloud-temple.com (déjà avec /v1 intégré)
        return self.llmaas_api_url
    
    @property
    def max_document_size_bytes(self) -> int:
        """Taille max en bytes."""
        return self.max_document_size_mb * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    """
    Retourne l'instance de configuration (singleton).
    
    Utilise lru_cache pour ne charger la config qu'une seule fois.
    
    Usage:
        from src.mcp_memory.config import get_settings
        settings = get_settings()
        print(settings.neo4j_uri)
    """
    return Settings()


# Pour usage direct: from config import settings
settings = get_settings()
