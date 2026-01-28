# -*- coding: utf-8 -*-
"""
MCP Memory Server - Serveur principal.

Expose tous les outils MCP via HTTP/SSE avec FastMCP.
"""

import os
import sys
import json
import uuid
import base64
import argparse
from typing import Optional, List, Dict, Any

import uvicorn
from dotenv import load_dotenv

# Charger .env avant les imports qui en dépendent
load_dotenv()

from mcp.server.fastmcp import FastMCP

from .config import get_settings
from .auth.middleware import AuthMiddleware, LoggingMiddleware


# =============================================================================
# Initialisation
# =============================================================================

settings = get_settings()

# Créer l'instance FastMCP
mcp = FastMCP(
    name=settings.mcp_server_name
)


# =============================================================================
# Helpers - Services (lazy-loaded)
# =============================================================================

_graph_service = None
_storage_service = None
_extractor_service = None
_token_manager = None


def get_graph():
    """Lazy-load GraphService."""
    global _graph_service
    if _graph_service is None:
        from .core.graph import get_graph_service
        _graph_service = get_graph_service()
    return _graph_service


def get_storage():
    """Lazy-load StorageService."""
    global _storage_service
    if _storage_service is None:
        from .core.storage import get_storage_service
        _storage_service = get_storage_service()
    return _storage_service


def get_extractor():
    """Lazy-load ExtractorService."""
    global _extractor_service
    if _extractor_service is None:
        from .core.extractor import get_extractor_service
        _extractor_service = get_extractor_service()
    return _extractor_service


def get_tokens():
    """Lazy-load TokenManager."""
    global _token_manager
    if _token_manager is None:
        from .auth.token_manager import get_token_manager
        _token_manager = get_token_manager()
    return _token_manager


# =============================================================================
# OUTILS MCP - Gestion des Mémoires
# =============================================================================

@mcp.tool()
async def memory_create(
    memory_id: str,
    name: str,
    description: Optional[str] = None
) -> dict:
    """
    Crée une nouvelle mémoire (namespace isolé).
    
    Args:
        memory_id: Identifiant unique (ex: "quoteflow-legal")
        name: Nom lisible de la mémoire
        description: Description optionnelle
        
    Returns:
        Informations sur la mémoire créée
    """
    try:
        memory = await get_graph().create_memory(
            memory_id=memory_id,
            name=name,
            description=description
        )
        return {
            "status": "created",
            "memory_id": memory.id,
            "name": memory.name,
            "description": memory.description
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Erreur création: {str(e)}"}


@mcp.tool()
async def memory_delete(memory_id: str) -> dict:
    """
    Supprime une mémoire et tout son contenu.
    
    ⚠️ ATTENTION: Cette opération est irréversible !
    
    Args:
        memory_id: ID de la mémoire à supprimer
        
    Returns:
        Statut de la suppression
    """
    try:
        deleted = await get_graph().delete_memory(memory_id)
        if deleted:
            return {"status": "deleted", "memory_id": memory_id}
        return {"status": "not_found", "memory_id": memory_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def memory_list() -> dict:
    """
    Liste toutes les mémoires disponibles.
    
    Returns:
        Liste des mémoires avec leurs métadonnées
    """
    try:
        memories = await get_graph().list_memories()
        return {
            "status": "ok",
            "count": len(memories),
            "memories": [
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description,
                    "created_at": m.created_at.isoformat() if m.created_at else None
                }
                for m in memories
            ]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def memory_stats(memory_id: str) -> dict:
    """
    Récupère les statistiques d'une mémoire.
    
    Args:
        memory_id: ID de la mémoire
        
    Returns:
        Statistiques (documents, entités, relations, top entités)
    """
    try:
        stats = await get_graph().get_memory_stats(memory_id)
        return {
            "status": "ok",
            "memory_id": memory_id,
            "document_count": stats.document_count,
            "entity_count": stats.entity_count,
            "relation_count": stats.relation_count,
            "top_entities": stats.top_entities
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# OUTILS MCP - Ingestion de Documents
# =============================================================================

@mcp.tool()
async def memory_ingest(
    memory_id: str,
    content_base64: str,
    filename: str,
    metadata: Optional[Dict[str, Any]] = None,
    force: bool = False
) -> dict:
    """
    Ingère un document dans une mémoire.
    
    Le document est:
    1. Stocké sur S3
    2. Analysé par le LLM pour extraire entités/relations
    3. Les entités et relations sont ajoutées au graphe
    
    Args:
        memory_id: ID de la mémoire cible
        content_base64: Contenu du document encodé en base64
        filename: Nom du fichier
        metadata: Métadonnées additionnelles (optionnel)
        force: Si True, réingère même si le document existe déjà
        
    Returns:
        Résultat de l'ingestion avec statistiques
    """
    try:
        # Décoder le contenu
        content = base64.b64decode(content_base64)
        
        # Vérifier si la mémoire existe
        memory = await get_graph().get_memory(memory_id)
        if not memory:
            return {"status": "error", "message": f"Mémoire '{memory_id}' non trouvée"}
        
        # Calculer le hash pour déduplication
        doc_hash = get_storage().compute_hash(content)
        
        # Vérifier si déjà ingéré
        existing = await get_graph().get_document_by_hash(memory_id, doc_hash)
        if existing and not force:
            return {
                "status": "already_exists",
                "document_id": existing.id,
                "filename": existing.filename,
                "message": "Document déjà ingéré (utilisez force=true pour réingérer)"
            }
        
        # Upload vers S3
        s3_result = await get_storage().upload_document(
            memory_id=memory_id,
            filename=filename,
            content=content,
            metadata=metadata
        )
        
        # Extraire le texte du document
        text = _extract_text(content, filename)
        
        if not text:
            return {
                "status": "warning",
                "message": "Document uploadé mais extraction texte impossible",
                "s3_uri": s3_result["uri"]
            }
        
        # Extraction des entités/relations via LLM
        extraction = await get_extractor().extract_from_text(text)
        
        # Créer le document dans le graphe
        doc_id = str(uuid.uuid4())
        document = await get_graph().add_document(
            memory_id=memory_id,
            doc_id=doc_id,
            uri=s3_result["uri"],
            filename=filename,
            doc_hash=doc_hash,
            metadata=metadata
        )
        
        # Ajouter les entités et relations
        graph_result = await get_graph().add_entities_and_relations(
            memory_id=memory_id,
            doc_id=doc_id,
            extraction=extraction
        )
        
        return {
            "status": "ok",
            "document_id": doc_id,
            "filename": filename,
            "s3_uri": s3_result["uri"],
            "size_bytes": s3_result["size_bytes"],
            "entities_extracted": len(extraction.entities),
            "relations_extracted": len(extraction.relations),
            "summary": extraction.summary,
            "key_topics": extraction.key_topics
        }
        
    except Exception as e:
        print(f"❌ [Ingest] Erreur: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}


def _extract_text(content: bytes, filename: str) -> Optional[str]:
    """Extrait le texte d'un document."""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    try:
        if ext == 'txt' or ext == 'md':
            return content.decode('utf-8', errors='ignore')
        
        elif ext == 'pdf':
            from pypdf import PdfReader
            from io import BytesIO
            reader = PdfReader(BytesIO(content))
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        
        elif ext == 'docx':
            from docx import Document
            from io import BytesIO
            doc = Document(BytesIO(content))
            text = "\n".join([para.text for para in doc.paragraphs])
            return text
        
        else:
            # Tenter de décoder comme texte
            return content.decode('utf-8', errors='ignore')
            
    except Exception as e:
        print(f"⚠️ [Extract] Erreur extraction texte: {e}", file=sys.stderr)
        return None


# =============================================================================
# OUTILS MCP - Recherche
# =============================================================================

@mcp.tool()
async def memory_search(
    memory_id: str,
    query: str,
    limit: int = 10
) -> dict:
    """
    Recherche dans une mémoire (graph-first).
    
    Recherche les entités et documents correspondant à la requête.
    Utilise principalement le graphe, pas de RAG vectoriel.
    
    Args:
        memory_id: ID de la mémoire
        query: Requête de recherche
        limit: Nombre max de résultats
        
    Returns:
        Entités trouvées avec leurs documents liés
    """
    try:
        # Recherche d'entités
        entities = await get_graph().search_entities(memory_id, search_query=query, limit=limit)
        
        # Pour chaque entité, récupérer un peu de contexte
        results = []
        for entity in entities[:5]:  # Limiter pour performance
            context = await get_graph().get_entity_context(
                memory_id, entity["name"], depth=1
            )
            results.append({
                "entity": entity,
                "documents": context.documents[:3],  # Max 3 docs par entité
                "related_entities": context.related_entities[:5]
            })
        
        return {
            "status": "ok",
            "query": query,
            "memory_id": memory_id,
            "result_count": len(results),
            "results": results
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def memory_get_context(
    memory_id: str,
    entity_name: str,
    depth: int = 1
) -> dict:
    """
    Récupère le contexte complet d'une entité.
    
    Retourne tout ce qu'on sait sur une entité:
    - Documents qui la mentionnent
    - Entités reliées
    - Types de relations
    
    Args:
        memory_id: ID de la mémoire
        entity_name: Nom de l'entité
        depth: Profondeur de traversée (1 = voisins directs)
        
    Returns:
        Contexte complet de l'entité
    """
    try:
        context = await get_graph().get_entity_context(
            memory_id, entity_name, depth
        )
        
        return {
            "status": "ok",
            "entity_name": context.entity_name,
            "entity_type": context.entity_type,
            "depth": context.depth,
            "documents": context.documents,
            "related_entities": context.related_entities,
            "relations": context.relations
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# OUTILS MCP - Admin / Tokens
# =============================================================================

@mcp.tool()
async def admin_create_token(
    client_name: str,
    permissions: Optional[List[str]] = None,
    memory_ids: Optional[List[str]] = None,
    expires_in_days: Optional[int] = None
) -> dict:
    """
    Crée un nouveau token d'accès pour un client.
    
    ⚠️ Le token retourné ne sera affiché qu'une seule fois !
    
    Args:
        client_name: Nom du client (ex: "quoteflow")
        permissions: Permissions ["read", "write", "admin"]
        memory_ids: IDs des mémoires autorisées (vide = toutes)
        expires_in_days: Expiration en jours (optionnel)
        
    Returns:
        Token généré (à conserver précieusement)
    """
    try:
        token = await get_tokens().create_token(
            client_name=client_name,
            permissions=permissions or ["read", "write"],
            memory_ids=memory_ids or [],
            expires_in_days=expires_in_days
        )
        
        return {
            "status": "ok",
            "client_name": client_name,
            "token": token,
            "permissions": permissions or ["read", "write"],
            "memory_ids": memory_ids or [],
            "message": "⚠️ Conservez ce token, il ne sera plus affiché !"
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def admin_list_tokens() -> dict:
    """
    Liste tous les tokens actifs.
    
    Note: Les tokens eux-mêmes ne sont pas affichés, seulement leurs métadonnées.
    
    Returns:
        Liste des tokens avec leurs infos
    """
    try:
        tokens = await get_tokens().list_tokens()
        
        return {
            "status": "ok",
            "count": len(tokens),
            "tokens": [
                {
                    "client_name": t.client_name,
                    "permissions": t.permissions,
                    "memory_ids": t.memory_ids,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                    "token_hash_prefix": t.token_hash[:8] + "..."
                }
                for t in tokens
            ]
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def admin_revoke_token(token_hash_prefix: str) -> dict:
    """
    Révoque un token.
    
    Args:
        token_hash_prefix: Début du hash du token (8+ caractères)
        
    Returns:
        Statut de la révocation
    """
    try:
        # Trouver le token par son préfixe
        tokens = await get_tokens().list_tokens(include_revoked=False)
        
        matching = [t for t in tokens if t.token_hash.startswith(token_hash_prefix)]
        
        if not matching:
            return {"status": "error", "message": "Token non trouvé"}
        
        if len(matching) > 1:
            return {"status": "error", "message": "Préfixe ambigu, soyez plus précis"}
        
        # Révoquer
        success = await get_tokens().revoke_token(matching[0].token_hash)
        
        if success:
            return {
                "status": "ok",
                "message": f"Token révoqué pour '{matching[0].client_name}'"
            }
        return {"status": "error", "message": "Échec révocation"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# OUTILS MCP - Diagnostic
# =============================================================================

@mcp.tool()
async def system_health() -> dict:
    """
    Vérifie l'état de santé du système.
    
    Teste les connexions à tous les services (S3, Neo4j, LLMaaS).
    
    Returns:
        État de chaque service
    """
    results = {}
    
    # Test S3
    try:
        results["s3"] = await get_storage().test_connection()
    except Exception as e:
        results["s3"] = {"status": "error", "message": str(e)}
    
    # Test Neo4j
    try:
        results["neo4j"] = await get_graph().test_connection()
    except Exception as e:
        results["neo4j"] = {"status": "error", "message": str(e)}
    
    # Test LLMaaS
    try:
        results["llmaas"] = await get_extractor().test_connection()
    except Exception as e:
        results["llmaas"] = {"status": "error", "message": str(e)}
    
    # Statut global
    all_ok = all(r.get("status") == "ok" for r in results.values())
    
    return {
        "status": "ok" if all_ok else "degraded",
        "services": results
    }


# =============================================================================
# Point d'entrée
# =============================================================================

def main():
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(description="MCP Memory Server")
    parser.add_argument("--port", type=int, default=settings.mcp_server_port)
    parser.add_argument("--host", type=str, default=settings.mcp_server_host)
    parser.add_argument("--debug", action="store_true", default=settings.mcp_server_debug)
    args = parser.parse_args()
    
    # Récupérer l'app ASGI de FastMCP
    base_app = mcp.sse_app()
    
    # Empiler les middlewares
    # 1. Auth (vérifie le token)
    # 2. Logging (si debug)
    app = AuthMiddleware(base_app, debug=args.debug)
    app = LoggingMiddleware(app, debug=args.debug)
    
    # Afficher le banner
    print("=" * 70, file=sys.stderr)
    print("🧠 MCP Memory Server - Démarrage", file=sys.stderr)
    print(f"📡 Écoute sur http://{args.host}:{args.port}", file=sys.stderr)
    print(f"🔒 Auth     : Bearer Token (ou ADMIN_BOOTSTRAP_KEY)", file=sys.stderr)
    print(f"🐛 Debug    : {'ACTIVÉ' if args.debug else 'Désactivé'}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("Outils disponibles:", file=sys.stderr)
    print("  - memory_create, memory_delete, memory_list, memory_stats", file=sys.stderr)
    print("  - memory_ingest, memory_search, memory_get_context", file=sys.stderr)
    print("  - admin_create_token, admin_list_tokens, admin_revoke_token", file=sys.stderr)
    print("  - system_health", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    
    # Lancer le serveur
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
