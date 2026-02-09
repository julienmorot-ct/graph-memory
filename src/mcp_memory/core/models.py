# -*- coding: utf-8 -*-
"""
Modèles Pydantic pour MCP Memory.

Définit les structures de données utilisées dans tout le service.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class EntityType(str, Enum):
    """Types d'entités reconnus."""
    PERSON = "Person"
    ORGANIZATION = "Organization"
    CONCEPT = "Concept"
    LOCATION = "Location"
    DATE = "Date"
    PRODUCT = "Product"
    SERVICE = "Service"
    CLAUSE = "Clause"
    CERTIFICATION = "Certification"  # ISO 27001, HDS, SecNumCloud
    METRIC = "Metric"                # SLA 99.95%, GTI 15 min
    DURATION = "Duration"            # 36 mois, préavis 6 mois
    AMOUNT = "Amount"                # 50 000 EUR/mois
    OTHER = "Other"


class RelationType(str, Enum):
    """Types de relations reconnus."""
    MENTIONS = "MENTIONS"
    DEFINES = "DEFINES"
    RELATED_TO = "RELATED_TO"
    CONTAINS = "CONTAINS"
    BELONGS_TO = "BELONGS_TO"
    SIGNED_BY = "SIGNED_BY"
    CREATED_BY = "CREATED_BY"
    REFERENCES = "REFERENCES"


class SearchMode(str, Enum):
    """Modes de recherche disponibles."""
    GRAPH = "graph"      # Recherche graphe uniquement
    VECTOR = "vector"    # Recherche vectorielle uniquement
    AUTO = "auto"        # Graph-first, fallback vector si nécessaire


# =============================================================================
# Entités & Relations (pour extraction LLM)
# =============================================================================

class ExtractedEntity(BaseModel):
    """Entité extraite par le LLM."""
    name: str = Field(..., description="Nom de l'entité")
    type: EntityType = Field(default=EntityType.OTHER, description="Type d'entité")
    description: Optional[str] = Field(None, description="Description contextuelle")
    aliases: List[str] = Field(default_factory=list, description="Noms alternatifs")
    
    class Config:
        use_enum_values = True


class ExtractedRelation(BaseModel):
    """Relation extraite par le LLM."""
    from_entity: str = Field(..., description="Nom de l'entité source")
    to_entity: str = Field(..., description="Nom de l'entité cible")
    type: str = Field(default="RELATED_TO", description="Type de relation (string libre, supporte les types d'ontologie)")
    description: Optional[str] = Field(None, description="Description de la relation")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Force de la relation")
    
    class Config:
        use_enum_values = True


class ExtractionResult(BaseModel):
    """Résultat complet d'une extraction LLM."""
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relations: List[ExtractedRelation] = Field(default_factory=list)
    summary: Optional[str] = Field(None, description="Résumé du document")
    key_topics: List[str] = Field(default_factory=list, description="Sujets principaux")


# =============================================================================
# Documents
# =============================================================================

class DocumentMetadata(BaseModel):
    """Métadonnées d'un document."""
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    source: Optional[str] = None  # Ex: "upload", "s3_sync"
    custom: Dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    """Représentation d'un document dans le système."""
    id: str = Field(..., description="Identifiant unique (UUID)")
    memory_id: str = Field(..., description="ID de la mémoire propriétaire")
    uri: str = Field(..., description="URI S3 du document")
    filename: str
    hash: str = Field(..., description="SHA256 du contenu")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: DocumentMetadata
    entity_count: int = Field(default=0)
    relation_count: int = Field(default=0)


# =============================================================================
# Mémoires
# =============================================================================

class Memory(BaseModel):
    """Représentation d'une mémoire (namespace)."""
    id: str = Field(..., description="Identifiant unique de la mémoire")
    name: str = Field(..., description="Nom lisible")
    description: Optional[str] = None
    ontology: str = Field(default="default", description="Nom de l'ontologie utilisée pour l'extraction")
    ontology_uri: Optional[str] = Field(None, description="URI S3 de l'ontologie copiée")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    owner_token: Optional[str] = Field(None, description="Token propriétaire")


class MemoryStats(BaseModel):
    """Statistiques d'une mémoire."""
    memory_id: str
    document_count: int = 0
    entity_count: int = 0
    relation_count: int = 0
    total_size_bytes: int = 0
    last_ingestion: Optional[datetime] = None
    top_entities: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Recherche
# =============================================================================

class SearchResult(BaseModel):
    """Résultat d'une recherche."""
    query: str
    mode: SearchMode
    confidence: float = Field(ge=0.0, le=1.0)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    relations: List[Dict[str, Any]] = Field(default_factory=list)
    context: Optional[str] = Field(None, description="Contexte synthétisé")
    used_fallback: bool = Field(default=False, description="RAG vectoriel utilisé")


class GraphContext(BaseModel):
    """Contexte d'une entité dans le graphe."""
    entity_name: str
    entity_type: Optional[str] = None
    depth: int = 1
    documents: List[Dict[str, Any]] = Field(default_factory=list)
    related_entities: List[Dict[str, Any]] = Field(default_factory=list)
    relations: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Tokens / Auth
# =============================================================================

class TokenInfo(BaseModel):
    """Information sur un token client."""
    token_hash: str = Field(..., description="Hash du token (pas le token lui-même)")
    client_name: str
    email: Optional[str] = Field(None, description="Adresse email du propriétaire du token")
    created_at: datetime
    expires_at: Optional[datetime] = None
    permissions: List[str] = Field(default_factory=list)
    is_active: bool = True
    memory_ids: List[str] = Field(default_factory=list, description="Mémoires autorisées (vide = toutes)")


class TokenCreateRequest(BaseModel):
    """Requête de création de token."""
    client_name: str
    email: Optional[str] = Field(None, description="Adresse email du propriétaire")
    permissions: List[str] = Field(default_factory=lambda: ["read", "write"])
    memory_ids: List[str] = Field(default_factory=list)
    expires_in_days: Optional[int] = None
