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
from .auth.middleware import AuthMiddleware, LoggingMiddleware, StaticFilesMiddleware
from .auth.context import check_memory_access, current_auth


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
    ontology: str,
    description: Optional[str] = None
) -> dict:
    """
    Crée une nouvelle mémoire (namespace isolé).
    
    L'ontologie est OBLIGATOIRE et copiée sur S3 pour persistance et versioning.
    
    Args:
        memory_id: Identifiant unique (ex: "quoteflow-legal")
        name: Nom lisible de la mémoire
        ontology: Nom de l'ontologie à utiliser (OBLIGATOIRE: legal, cloud, managed-services, technical)
        description: Description optionnelle
        
    Returns:
        Informations sur la mémoire créée
    """
    try:
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        # Vérifier que l'ontologie existe et la récupérer
        from .core.ontology import get_ontology_manager
        ontology_manager = get_ontology_manager()
        ontology_data = ontology_manager.get_ontology(ontology)
        
        if not ontology_data:
            available = [o["name"] for o in ontology_manager.list_ontologies()]
            return {
                "status": "error",
                "message": f"Ontologie '{ontology}' non trouvée. Disponibles: {available}"
            }
        
        # Stocker l'ontologie sur S3 pour la mémoire
        import yaml
        ontology_yaml = yaml.dump(ontology_data, allow_unicode=True, default_flow_style=False)
        ontology_bytes = ontology_yaml.encode('utf-8')
        
        ontology_s3_result = await get_storage().upload_document(
            memory_id=memory_id,
            filename=f"_ontology_{ontology}.yaml",
            content=ontology_bytes,
            metadata={"type": "ontology", "ontology_name": ontology}
        )
        
        print(f"📝 [Memory] Ontologie '{ontology}' stockée: {ontology_s3_result['uri']}", file=sys.stderr)
        
        # Créer la mémoire dans le graphe avec l'URI S3 de l'ontologie
        memory = await get_graph().create_memory(
            memory_id=memory_id,
            name=name,
            description=description,
            ontology=ontology,
            ontology_uri=ontology_s3_result["uri"]
        )
        
        return {
            "status": "created",
            "memory_id": memory.id,
            "name": memory.name,
            "description": memory.description,
            "ontology": memory.ontology,
            "ontology_uri": ontology_s3_result["uri"]
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Erreur création: {str(e)}"}


@mcp.tool()
async def memory_delete(memory_id: str) -> dict:
    """
    Supprime une mémoire et tout son contenu (graphe + S3).
    
    ⚠️ ATTENTION: Cette opération est irréversible !
    Supprime le namespace Neo4j ET tous les fichiers S3 associés.
    
    Args:
        memory_id: ID de la mémoire à supprimer
        
    Returns:
        Statut de la suppression avec détails S3
    """
    try:
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        # 1. Supprimer tous les fichiers S3 de la mémoire
        s3_result = {"deleted_count": 0, "error_count": 0}
        try:
            s3_result = await get_storage().delete_prefix(f"{memory_id}/")
            print(f"🗑️ [S3] Nettoyage mémoire {memory_id}: {s3_result['deleted_count']} fichiers supprimés", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ [S3] Erreur nettoyage S3 pour {memory_id}: {e}", file=sys.stderr)
        
        # 2. Supprimer du graphe Neo4j
        deleted = await get_graph().delete_memory(memory_id)
        
        if deleted:
            return {
                "status": "deleted",
                "memory_id": memory_id,
                "s3_files_deleted": s3_result.get("deleted_count", 0),
                "s3_errors": s3_result.get("error_count", 0)
            }
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
                    "ontology": m.ontology,
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
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
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
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
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
        
        # Si force=True et document existant, supprimer l'ancien d'abord
        if existing and force:
            print(f"🔄 [Ingest] Force: suppression de l'ancien document {existing.id}", file=sys.stderr)
            delete_result = await get_graph().delete_document(memory_id, existing.id)
            print(f"🔄 [Ingest] Ancien supprimé: {delete_result.get('entities_deleted', 0)} entités orphelines, "
                  f"{delete_result.get('relations_deleted', 0)} relations", file=sys.stderr)
        
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
        
        # Extraction des entités/relations via LLM avec l'ontologie de la mémoire
        if not memory.ontology:
            return {
                "status": "error",
                "message": f"La mémoire '{memory_id}' n'a pas d'ontologie définie. "
                           f"Recréez-la avec une ontologie valide."
            }
        extraction = await get_extractor().extract_with_ontology(text, memory.ontology)
        
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
        
        # Compter les types de relations
        from collections import Counter
        relation_types = Counter(r.type for r in extraction.relations)
        entity_types = Counter(e.type.value if hasattr(e.type, 'value') else str(e.type) for e in extraction.entities)
        
        return {
            "status": "ok",
            "document_id": doc_id,
            "filename": filename,
            "s3_uri": s3_result["uri"],
            "size_bytes": s3_result["size_bytes"],
            "entities_extracted": len(extraction.entities),
            "relations_extracted": len(extraction.relations),
            "entities_created": graph_result.get("entities_created", 0),
            "entities_merged": graph_result.get("entities_merged", 0),
            "relations_created": graph_result.get("relations_created", 0),
            "relations_merged": graph_result.get("relations_merged", 0),
            "entity_types": dict(entity_types),
            "relation_types": dict(relation_types),
            "summary": extraction.summary,
            "key_topics": extraction.key_topics
        }
        
    except Exception as e:
        print(f"❌ [Ingest] Erreur: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}


def _extract_text(content: bytes, filename: str) -> Optional[str]:
    """
    Extrait le texte d'un document.
    
    Formats supportés: txt, md, html, docx, pdf, csv
    """
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    try:
        # Texte brut et Markdown
        if ext in ('txt', 'md'):
            return content.decode('utf-8', errors='ignore')
        
        # HTML
        elif ext in ('html', 'htm'):
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content.decode('utf-8', errors='ignore'), 'html.parser')
            # Supprimer scripts et styles
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator='\n', strip=True)
            return text
        
        # PDF
        elif ext == 'pdf':
            from pypdf import PdfReader
            from io import BytesIO
            reader = PdfReader(BytesIO(content))
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n".join(text_parts)
        
        # DOCX (Word)
        elif ext == 'docx':
            from docx import Document
            from io import BytesIO
            doc = Document(BytesIO(content))
            
            text_parts = []
            
            # Extraire les paragraphes
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Extraire le texte des tableaux
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        text_parts.append(row_text)
            
            return "\n".join(text_parts)
        
        # CSV
        elif ext == 'csv':
            import csv
            from io import StringIO
            
            # Décoder le contenu
            text_content = content.decode('utf-8', errors='ignore')
            reader = csv.reader(StringIO(text_content))
            
            rows = []
            for row in reader:
                rows.append(" | ".join(row))
            
            return "\n".join(rows)
        
        else:
            # Tenter de décoder comme texte (fallback)
            return content.decode('utf-8', errors='ignore')
            
    except Exception as e:
        print(f"⚠️ [Extract] Erreur extraction texte ({ext}): {e}", file=sys.stderr)
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
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        # Recherche d'entités
        entities = await get_graph().search_entities(memory_id, search_query=query, limit=limit)
        
        # Pour chaque entité, récupérer le contexte complet
        results = []
        for entity in entities:
            context = await get_graph().get_entity_context(
                memory_id, entity["name"], depth=1
            )
            results.append({
                "entity": entity,
                "documents": context.documents,
                "related_entities": context.related_entities
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
async def question_answer(
    memory_id: str,
    question: str,
    limit: int = 10
) -> dict:
    """
    Pose une question sur une mémoire et obtient une réponse basée sur le graphe.
    
    Utilise le graphe de connaissances pour répondre à la question.
    Recherche les entités pertinentes puis génère une réponse avec le LLM.
    
    Args:
        memory_id: ID de la mémoire
        question: Question en langage naturel
        limit: Nombre max d'entités à rechercher (défaut: 10)
        
    Returns:
        Réponse générée avec les entités liées
    """
    try:
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        # 1. Rechercher les entités pertinentes
        entities = await get_graph().search_entities(memory_id, search_query=question, limit=limit)
        
        if not entities:
            return {
                "status": "ok",
                "answer": "Je n'ai pas trouvé d'informations pertinentes dans cette mémoire pour répondre à votre question.",
                "entities": []
            }
        
        # 2. Récupérer le contexte de chaque entité + documents sources
        context_parts = []
        entity_names = []
        source_documents = {}  # doc_id -> {filename, id}
        
        for entity in entities:
            entity_names.append(entity["name"])
            ctx = await get_graph().get_entity_context(memory_id, entity["name"], depth=1)
            
            # Collecter les documents sources et les associer à l'entité
            entity_doc_names = []
            for doc in ctx.documents:
                if isinstance(doc, dict):
                    doc_id = doc.get('id', '')
                    doc_filename = doc.get('filename', doc_id)
                    if doc_id:
                        if doc_id not in source_documents:
                            source_documents[doc_id] = {
                                "id": doc_id,
                                "filename": doc_filename,
                            }
                        entity_doc_names.append(doc_filename)
            
            # Construire le contexte texte AVEC le document source
            doc_ref = f" [Source: {', '.join(entity_doc_names)}]" if entity_doc_names else ""
            ctx_text = f"- {entity['name']} ({entity.get('type', '?')}){doc_ref}"
            if entity.get('description'):
                ctx_text += f": {entity['description']}"
            
            for rel in ctx.relations:
                ctx_text += f"\n  → {rel.get('type', 'RELATED_TO')}: {rel.get('description', '')}"
            
            related = [r['name'] for r in ctx.related_entities]
            if related:
                ctx_text += f"\n  Lié à: {', '.join(related)}"
            
            context_parts.append(ctx_text)
        
        # 3. Construire la liste des documents pour le prompt
        doc_list = "\n".join(
            f"  - {doc['filename']}" for doc in source_documents.values()
        )
        
        # 4. Générer la réponse avec le LLM
        context = "\n".join(context_parts)
        
        prompt = f"""Tu es un assistant expert qui répond à des questions basées sur un graphe de connaissances multi-documents.

Documents sources disponibles :
{doc_list}

Contexte extrait du graphe (chaque entité indique son document source entre crochets) :
{context}

Question de l'utilisateur : {question}

CONSIGNES :
- Réponds de manière concise et précise en te basant UNIQUEMENT sur le contexte fourni.
- Cite systématiquement le document source quand tu affirmes quelque chose (ex: "Selon les CGA, …", "L'article X de la CGV prévoit que…").
- Si une information provient de plusieurs documents, précise lesquels.
- Si le contexte ne permet pas de répondre complètement, dis-le clairement.
- Utilise le format Markdown pour structurer ta réponse.
"""
        
        answer = await get_extractor().generate_answer(prompt)
        
        return {
            "status": "ok",
            "answer": answer,
            "entities": entity_names,
            "source_documents": list(source_documents.values()),
            "context_used": context
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
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
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
    expires_in_days: Optional[int] = None,
    email: Optional[str] = None
) -> dict:
    """
    Crée un nouveau token d'accès pour un client.
    
    ⚠️ Le token retourné ne sera affiché qu'une seule fois !
    
    Args:
        client_name: Nom du client (ex: "quoteflow")
        permissions: Permissions ["read", "write", "admin"]
        memory_ids: IDs des mémoires autorisées (vide = toutes)
        expires_in_days: Expiration en jours (optionnel)
        email: Adresse email du propriétaire (optionnel)
        
    Returns:
        Token généré (à conserver précieusement)
    """
    try:
        token = await get_tokens().create_token(
            client_name=client_name,
            permissions=permissions or ["read", "write"],
            memory_ids=memory_ids or [],
            expires_in_days=expires_in_days,
            email=email
        )
        
        return {
            "status": "ok",
            "client_name": client_name,
            "email": email,
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
                    "email": t.email,
                    "permissions": t.permissions,
                    "memory_ids": t.memory_ids,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                    "token_hash": t.token_hash
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


@mcp.tool()
async def admin_update_token(
    token_hash_prefix: str,
    add_memories: Optional[List[str]] = None,
    remove_memories: Optional[List[str]] = None,
    set_memories: Optional[List[str]] = None
) -> dict:
    """
    Met à jour les mémoires autorisées d'un token.
    
    Trois modes (mutuellement exclusifs avec set_memories) :
    - add_memories: Ajoute des mémoires à la liste existante
    - remove_memories: Retire des mémoires de la liste existante
    - set_memories: Remplace toute la liste ([] = accès à TOUTES les mémoires)
    
    Args:
        token_hash_prefix: Début du hash du token (8+ caractères)
        add_memories: Mémoires à ajouter (ex: ["JURIDIQUE", "CLOUD"])
        remove_memories: Mémoires à retirer (ex: ["JURIDIQUE"])
        set_memories: Remplacer toute la liste (ex: ["CLOUD"], ou [] pour tout autoriser)
        
    Returns:
        Anciennes et nouvelles mémoires autorisées
    """
    try:
        # Trouver le token par son préfixe
        tokens = await get_tokens().list_tokens(include_revoked=False)
        matching = [t for t in tokens if t.token_hash.startswith(token_hash_prefix)]
        
        if not matching:
            return {"status": "error", "message": "Token non trouvé"}
        
        if len(matching) > 1:
            return {"status": "error", "message": "Préfixe ambigu, soyez plus précis"}
        
        # Vérifier que les mémoires existent (si on en ajoute)
        memories_to_check = (add_memories or []) + (set_memories or [])
        if memories_to_check:
            existing_memories = await get_graph().list_memories()
            existing_ids = {m.id for m in existing_memories}
            unknown = [m for m in memories_to_check if m not in existing_ids]
            if unknown:
                return {
                    "status": "error",
                    "message": f"Mémoires inconnues: {unknown}. Disponibles: {sorted(existing_ids)}"
                }
        
        # Mettre à jour
        result = await get_tokens().update_token_memories(
            token_hash=matching[0].token_hash,
            add_memories=add_memories,
            remove_memories=remove_memories,
            set_memories=set_memories
        )
        
        if result:
            return {
                "status": "ok",
                "client_name": result["client_name"],
                "token_hash_prefix": result["token_hash"][:8] + "...",
                "previous_memories": result["previous_memories"],
                "current_memories": result["current_memories"],
                "message": (
                    "Accès à toutes les mémoires" if not result["current_memories"]
                    else f"Accès restreint à: {result['current_memories']}"
                )
            }
        return {"status": "error", "message": "Token non trouvé ou inactif"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# OUTILS MCP - Diagnostic
# =============================================================================

@mcp.tool()
async def memory_graph(memory_id: str, format: str = "full") -> dict:
    """
    Récupère le graphe complet d'une mémoire (entités, relations et documents).
    
    Utile pour visualiser ou exporter le graphe de connaissances.
    Inclut les documents avec leur URI S3 pour permettre la récupération.
    
    Args:
        memory_id: ID de la mémoire
        format: "full" (tout), "nodes" (entités+docs), "edges" (relations), "documents" (liste docs avec URI S3)
        
    Returns:
        nodes: Liste des entités et documents avec leurs propriétés
        edges: Liste des relations entre entités et documents
        documents: Liste des documents avec id, filename, uri S3
    """
    try:
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        graph_data = await get_graph().get_full_graph(memory_id)
        
        if format == "nodes":
            return {
                "status": "ok",
                "memory_id": memory_id,
                "node_count": len(graph_data["nodes"]),
                "nodes": graph_data["nodes"]
            }
        elif format == "edges":
            return {
                "status": "ok",
                "memory_id": memory_id,
                "edge_count": len(graph_data["edges"]),
                "edges": graph_data["edges"]
            }
        elif format == "documents":
            return {
                "status": "ok",
                "memory_id": memory_id,
                "document_count": len(graph_data["documents"]),
                "documents": graph_data["documents"]
            }
        else:  # full
            return {
                "status": "ok",
                "memory_id": memory_id,
                "node_count": len(graph_data["nodes"]),
                "edge_count": len(graph_data["edges"]),
                "document_count": len(graph_data["documents"]),
                "nodes": graph_data["nodes"],
                "edges": graph_data["edges"],
                "documents": graph_data["documents"]
            }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def document_list(memory_id: str) -> dict:
    """
    Liste tous les documents d'une mémoire.
    
    Args:
        memory_id: ID de la mémoire
        
    Returns:
        Liste des documents avec leurs métadonnées
    """
    try:
        graph_data = await get_graph().get_full_graph(memory_id)
        docs = graph_data.get("documents", [])
        
        return {
            "status": "ok",
            "memory_id": memory_id,
            "count": len(docs),
            "documents": docs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def document_get(memory_id: str, document_id: str) -> dict:
    """
    Récupère les informations et le contenu d'un document.
    
    Args:
        memory_id: ID de la mémoire
        document_id: ID du document
        
    Returns:
        Métadonnées et contenu du document
    """
    try:
        # Récupérer les infos du document depuis le graphe
        doc_info = await get_graph().get_document(memory_id, document_id)
        
        if not doc_info:
            return {"status": "error", "message": f"Document '{document_id}' non trouvé"}
        
        # Récupérer le contenu depuis S3
        content = None
        if doc_info.get("uri"):
            try:
                # Extraire memory_id et clé de l'URI
                uri = doc_info["uri"]
                content_bytes = await get_storage().download_document(memory_id, uri)
                content = content_bytes.decode('utf-8', errors='ignore')
            except Exception as e:
                content = f"[Erreur lecture S3: {e}]"
        
        return {
            "status": "ok",
            "document": {
                "id": doc_info.get("id"),
                "filename": doc_info.get("filename"),
                "uri": doc_info.get("uri"),
                "hash": doc_info.get("hash"),
                "ingested_at": doc_info.get("ingested_at")
            },
            "content": content
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def document_delete(memory_id: str, document_id: str) -> dict:
    """
    Supprime un document du graphe ET de S3.
    
    Supprime :
    - Le fichier S3 associé
    - Le nœud Document dans Neo4j
    - Les relations MENTIONS du document
    - Les entités orphelines (non mentionnées par d'autres documents)
    - Les relations RELATED_TO impliquant des entités orphelines
    
    Args:
        memory_id: ID de la mémoire
        document_id: ID du document à supprimer
        
    Returns:
        Statut de la suppression avec compteurs (graphe + S3)
    """
    try:
        # Vérifier l'accès à la mémoire
        access_err = check_memory_access(memory_id)
        if access_err:
            return access_err
        
        # 1. Récupérer l'URI S3 avant suppression du graphe
        doc_info = await get_graph().get_document(memory_id, document_id)
        s3_deleted = False
        
        if doc_info and doc_info.get("uri"):
            # 2. Supprimer le fichier S3
            try:
                s3_deleted = await get_storage().delete_document(memory_id, doc_info["uri"])
                print(f"🗑️ [S3] Fichier supprimé: {doc_info['uri']}", file=sys.stderr)
            except Exception as e:
                print(f"⚠️ [S3] Erreur suppression S3 pour {doc_info['uri']}: {e}", file=sys.stderr)
        
        # 3. Supprimer du graphe Neo4j
        result = await get_graph().delete_document(memory_id, document_id)
        
        if result.get("deleted"):
            return {
                "status": "deleted",
                "document_id": document_id,
                "relations_deleted": result.get("relations_deleted", 0),
                "entities_deleted": result.get("entities_deleted", 0),
                "s3_deleted": s3_deleted
            }
        return {"status": "error", "message": "Document non trouvé"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def ontology_list() -> dict:
    """
    Liste toutes les ontologies disponibles.
    
    Les ontologies définissent les règles d'extraction pour différents domaines.
    Chaque mémoire DOIT avoir une ontologie. Exemples:
    - legal: Documents juridiques et contractuels
    - cloud: Infrastructure cloud et certifications
    - managed-services: Infogérance et services managés
    - technical: Documentation technique et API
    
    Returns:
        Liste des ontologies avec leurs métadonnées
    """
    try:
        from .core.ontology import get_ontology_manager
        ontology_manager = get_ontology_manager()
        ontologies = ontology_manager.list_ontologies()
        
        return {
            "status": "ok",
            "count": len(ontologies),
            "ontologies": ontologies
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def storage_check(memory_id: Optional[str] = None) -> dict:
    """
    Vérifie la cohérence entre le graphe Neo4j et le stockage S3.
    
    Pour chaque mémoire (ou une mémoire spécifique) :
    1. Vérifie que chaque document du graphe est accessible sur S3
    2. Détecte les fichiers orphelins sur S3 (pas de référence dans le graphe)
    3. Retourne un rapport complet avec statistiques
    
    Args:
        memory_id: ID d'une mémoire spécifique (optionnel, toutes si omis)
        
    Returns:
        Rapport de cohérence S3/Graphe avec documents OK, manquants et orphelins
    """
    try:
        # 1. Récupérer les mémoires à vérifier
        if memory_id:
            memory = await get_graph().get_memory(memory_id)
            if not memory:
                return {"status": "error", "message": f"Mémoire '{memory_id}' non trouvée"}
            memories = [memory]
        else:
            memories = await get_graph().list_memories()
        
        # 2. Collecter toutes les URIs des documents référencés dans le graphe
        graph_uris = set()          # URIs référencées dans Neo4j
        graph_uri_details = {}      # URI -> {memory_id, filename, doc_id}
        memory_prefixes = set()     # Préfixes S3 des mémoires connues
        
        for mem in memories:
            mid = mem.id
            memory_prefixes.add(f"{mid}/")
            graph_data = await get_graph().get_full_graph(mid)
            
            for doc in graph_data.get("documents", []):
                uri = doc.get("uri", "")
                if uri:
                    graph_uris.add(uri)
                    graph_uri_details[uri] = {
                        "memory_id": mid,
                        "filename": doc.get("filename", "?"),
                        "doc_id": doc.get("id", "?")
                    }
        
        # 3. Vérifier l'accessibilité S3 de chaque document du graphe
        check_result = await get_storage().check_documents(list(graph_uris))
        
        # Enrichir les détails avec les infos du graphe
        for detail in check_result.get("details", []):
            uri = detail.get("uri", "")
            if uri in graph_uri_details:
                detail["memory_id"] = graph_uri_details[uri]["memory_id"]
                detail["filename"] = graph_uri_details[uri]["filename"]
                detail["doc_id"] = graph_uri_details[uri]["doc_id"]
        
        # 4. Lister tous les objets S3 pour détecter les orphelins
        all_s3_objects = await get_storage().list_all_objects()
        
        # Convertir les URIs du graphe en clés S3 pour comparaison
        graph_keys = set()
        for uri in graph_uris:
            try:
                key = get_storage()._parse_key(uri)
                graph_keys.add(key)
            except ValueError:
                pass
        
        # Ajouter les ontologies comme fichiers légitimes (pas orphelins)
        # Les fichiers _ontology_*.yaml sont des fichiers de config, pas des orphelins
        
        # Détecter les orphelins : sur S3 mais pas dans le graphe
        orphans = []
        for obj in all_s3_objects:
            key = obj["key"]
            
            # Ignorer les fichiers de health check
            if key.startswith("_health_check/"):
                continue
            
            # Ignorer les ontologies (fichiers légitimes)
            # Le pattern est {hash[:8]}__ontology_{name}.yaml (double _ car hash + _ontology)
            if "_ontology_" in key:
                continue
            
            # Si la clé n'est pas référencée dans le graphe → orphelin
            if key not in graph_keys:
                orphans.append({
                    "key": key,
                    "uri": obj["uri"],
                    "size": obj["size"],
                    "last_modified": obj["last_modified"]
                })
        
        # 5. Construire le rapport
        def _human_size(size_bytes):
            """Convertit des bytes en taille lisible."""
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024
            return f"{size_bytes:.1f} TB"
        
        orphan_total_size = sum(o["size"] for o in orphans)
        
        report = {
            "status": "ok",
            "scope": memory_id or "all",
            "memories_checked": len(memories),
            "graph_documents": {
                "total": check_result["total"],
                "accessible": check_result["accessible"],
                "missing": check_result["missing"],
                "errors": check_result["errors"],
                "total_size": _human_size(check_result["total_size_bytes"]),
                "total_size_bytes": check_result["total_size_bytes"],
                "details": check_result["details"]
            },
            "s3_orphans": {
                "count": len(orphans),
                "total_size": _human_size(orphan_total_size),
                "total_size_bytes": orphan_total_size,
                "files": orphans
            },
            "s3_total_objects": len(all_s3_objects),
            "summary": (
                f"✅ {check_result['accessible']}/{check_result['total']} docs accessibles"
                + (f", ❌ {check_result['missing']} manquants" if check_result['missing'] > 0 else "")
                + (f", ⚠️ {len(orphans)} orphelins S3 ({_human_size(orphan_total_size)})" if orphans else "")
            )
        }
        
        return report
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def storage_cleanup(dry_run: bool = True) -> dict:
    """
    Nettoie les fichiers orphelins sur S3.
    
    Un fichier orphelin est un objet S3 qui n'est référencé par aucun document
    dans le graphe Neo4j (ni par une ontologie de mémoire).
    
    ⚠️ Par défaut, mode dry_run=True : liste les fichiers sans les supprimer.
    Passez dry_run=False pour effectuer la suppression.
    
    Args:
        dry_run: Si True, liste seulement. Si False, supprime réellement.
        
    Returns:
        Liste des fichiers orphelins (supprimés ou à supprimer)
    """
    try:
        # 1. Exécuter le check complet pour identifier les orphelins
        check = await storage_check()
        
        if check.get("status") != "ok":
            return check
        
        orphans = check.get("s3_orphans", {}).get("files", [])
        
        if not orphans:
            return {
                "status": "ok",
                "message": "Aucun fichier orphelin trouvé. Le S3 est propre ! 🧹",
                "orphans_found": 0,
                "deleted": 0,
                "dry_run": dry_run
            }
        
        if dry_run:
            return {
                "status": "ok",
                "message": f"🔍 {len(orphans)} fichiers orphelins trouvés ({check['s3_orphans']['total_size']}). "
                           f"Relancez avec dry_run=false pour les supprimer.",
                "orphans_found": len(orphans),
                "deleted": 0,
                "dry_run": True,
                "files": orphans
            }
        
        # 2. Supprimer les orphelins
        keys_to_delete = [o["key"] for o in orphans]
        delete_result = await get_storage().delete_objects(keys_to_delete)
        
        return {
            "status": "ok",
            "message": f"🗑️ {delete_result['deleted_count']} fichiers orphelins supprimés "
                       f"({check['s3_orphans']['total_size']} libérés).",
            "orphans_found": len(orphans),
            "deleted": delete_result["deleted_count"],
            "errors": delete_result["error_count"],
            "dry_run": False,
            "files": orphans
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
    
    # Empiler les middlewares (le dernier wrappé est le premier exécuté)
    # Flux requête : AuthMiddleware → LoggingMiddleware → StaticFilesMiddleware → MCP app
    app = StaticFilesMiddleware(base_app)
    app = LoggingMiddleware(app, debug=args.debug)
    app = AuthMiddleware(app, debug=args.debug)
    
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
    print("  - admin_create_token, admin_list_tokens, admin_revoke_token, admin_update_token", file=sys.stderr)
    print("  - storage_check, storage_cleanup, system_health", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    
    # Lancer le serveur
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
