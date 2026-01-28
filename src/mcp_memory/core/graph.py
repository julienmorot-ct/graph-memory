# -*- coding: utf-8 -*-
"""
GraphService - Client Neo4j pour le Knowledge Graph.

Gère toutes les opérations sur le graphe de connaissances :
- CRUD pour les mémoires, documents, entités, relations
- Requêtes de recherche et de contexte
- Statistiques
"""

import sys
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import ServiceUnavailable, AuthError

from ..config import get_settings
from .models import (
    Memory, MemoryStats, Document, DocumentMetadata,
    ExtractedEntity, ExtractedRelation, ExtractionResult,
    SearchResult, GraphContext, SearchMode
)


class GraphService:
    """
    Service de gestion du Knowledge Graph (Neo4j).
    
    Utilise des labels préfixés par memory_id pour l'isolation multi-tenant.
    Ex: quoteflow_legal_Document, quoteflow_legal_Entity
    """
    
    def __init__(self):
        """Initialise la connexion Neo4j."""
        settings = get_settings()
        
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_lifetime=3600,
            max_connection_pool_size=50,
            connection_acquisition_timeout=60
        )
        self._database = settings.neo4j_database
    
    async def close(self):
        """Ferme la connexion Neo4j."""
        await self._driver.close()
    
    @asynccontextmanager
    async def session(self) -> AsyncSession:
        """Context manager pour obtenir une session Neo4j."""
        session = self._driver.session(database=self._database)
        try:
            yield session
        finally:
            await session.close()
    
    def _ns(self, memory_id: str) -> str:
        """Retourne le préfixe namespace pour les labels."""
        # Remplace les caractères non-alphanumériques par _
        safe_id = "".join(c if c.isalnum() else "_" for c in memory_id)
        return safe_id
    
    # =========================================================================
    # Test de connexion
    # =========================================================================
    
    async def test_connection(self) -> dict:
        """Teste la connexion Neo4j."""
        try:
            async with self.session() as session:
                result = await session.run("RETURN 1 AS test")
                record = await result.single()
                
                # Récupérer quelques stats
                stats_result = await session.run(
                    "CALL apoc.meta.stats() YIELD nodeCount, relCount "
                    "RETURN nodeCount, relCount"
                )
                stats = await stats_result.single()
                
                return {
                    "status": "ok",
                    "database": self._database,
                    "node_count": stats["nodeCount"] if stats else 0,
                    "rel_count": stats["relCount"] if stats else 0,
                    "message": "Connexion Neo4j réussie"
                }
                
        except AuthError:
            return {
                "status": "error",
                "database": self._database,
                "message": "Authentification Neo4j échouée"
            }
        except ServiceUnavailable:
            return {
                "status": "error",
                "database": self._database,
                "message": "Neo4j non disponible"
            }
        except Exception as e:
            return {
                "status": "error",
                "database": self._database,
                "message": f"Erreur Neo4j: {str(e)}"
            }
    
    # =========================================================================
    # Gestion des Mémoires
    # =========================================================================
    
    async def create_memory(
        self,
        memory_id: str,
        name: str,
        description: Optional[str] = None,
        owner_token: Optional[str] = None
    ) -> Memory:
        """
        Crée une nouvelle mémoire (namespace).
        
        Crée un nœud :Memory pour tracker les métadonnées.
        """
        ns = self._ns(memory_id)
        
        async with self.session() as session:
            # Vérifier si la mémoire existe déjà
            check = await session.run(
                "MATCH (m:Memory {id: $id}) RETURN m",
                id=memory_id
            )
            existing = await check.single()
            
            if existing:
                raise ValueError(f"La mémoire '{memory_id}' existe déjà")
            
            # Créer la mémoire
            result = await session.run(
                """
                CREATE (m:Memory {
                    id: $id,
                    name: $name,
                    description: $description,
                    namespace: $namespace,
                    owner_token_hash: $owner_token,
                    created_at: datetime()
                })
                RETURN m
                """,
                id=memory_id,
                name=name,
                description=description,
                namespace=ns,
                owner_token=owner_token
            )
            
            record = await result.single()
            node = record["m"]
            
            print(f"🧠 [Graph] Mémoire créée: {memory_id} (ns: {ns})", file=sys.stderr)
            
            return Memory(
                id=memory_id,
                name=name,
                description=description,
                created_at=node["created_at"].to_native() if node.get("created_at") else datetime.utcnow(),
                owner_token=owner_token
            )
    
    async def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Récupère une mémoire par son ID."""
        async with self.session() as session:
            result = await session.run(
                "MATCH (m:Memory {id: $id}) RETURN m",
                id=memory_id
            )
            record = await result.single()
            
            if not record:
                return None
            
            node = record["m"]
            return Memory(
                id=node["id"],
                name=node["name"],
                description=node.get("description"),
                created_at=node["created_at"].to_native() if node.get("created_at") else datetime.utcnow()
            )
    
    async def delete_memory(self, memory_id: str) -> bool:
        """
        Supprime une mémoire et tous ses nœuds associés.
        
        ATTENTION: Opération destructive !
        """
        ns = self._ns(memory_id)
        
        async with self.session() as session:
            # Supprimer tous les nœuds du namespace
            # Les labels dynamiques ne sont pas supportés directement,
            # donc on utilise apoc ou on supprime par propriété memory_id
            await session.run(
                """
                MATCH (n)
                WHERE n.memory_id = $memory_id
                DETACH DELETE n
                """,
                memory_id=memory_id
            )
            
            # Supprimer le nœud Memory
            result = await session.run(
                """
                MATCH (m:Memory {id: $id})
                DELETE m
                RETURN count(m) as deleted
                """,
                id=memory_id
            )
            
            record = await result.single()
            deleted = record["deleted"] > 0 if record else False
            
            if deleted:
                print(f"🗑️ [Graph] Mémoire supprimée: {memory_id}", file=sys.stderr)
            
            return deleted
    
    async def list_memories(self) -> List[Memory]:
        """Liste toutes les mémoires."""
        async with self.session() as session:
            result = await session.run(
                "MATCH (m:Memory) RETURN m ORDER BY m.created_at DESC"
            )
            
            memories = []
            async for record in result:
                node = record["m"]
                memories.append(Memory(
                    id=node["id"],
                    name=node["name"],
                    description=node.get("description"),
                    created_at=node["created_at"].to_native() if node.get("created_at") else datetime.utcnow()
                ))
            
            return memories
    
    # =========================================================================
    # Gestion des Documents
    # =========================================================================
    
    async def add_document(
        self,
        memory_id: str,
        doc_id: str,
        uri: str,
        filename: str,
        doc_hash: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Document:
        """Ajoute un document au graphe."""
        import json
        
        async with self.session() as session:
            # Neo4j n'accepte que les types primitifs, convertir metadata en JSON string
            metadata_json = json.dumps(metadata) if metadata else "{}"
            
            result = await session.run(
                """
                CREATE (d:Document {
                    id: $doc_id,
                    memory_id: $memory_id,
                    uri: $uri,
                    filename: $filename,
                    hash: $hash,
                    ingested_at: datetime(),
                    metadata_json: $metadata_json
                })
                RETURN d
                """,
                doc_id=doc_id,
                memory_id=memory_id,
                uri=uri,
                filename=filename,
                hash=doc_hash,
                metadata_json=metadata_json
            )
            
            record = await result.single()
            node = record["d"]
            
            print(f"📄 [Graph] Document ajouté: {filename} ({doc_id})", file=sys.stderr)
            
            return Document(
                id=doc_id,
                memory_id=memory_id,
                uri=uri,
                filename=filename,
                hash=doc_hash,
                ingested_at=node["ingested_at"].to_native(),
                metadata=DocumentMetadata(
                    filename=filename,
                    custom=metadata or {}
                )
            )
    
    async def get_document_by_hash(self, memory_id: str, doc_hash: str) -> Optional[Document]:
        """Trouve un document par son hash."""
        async with self.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {memory_id: $memory_id, hash: $hash})
                RETURN d
                """,
                memory_id=memory_id,
                hash=doc_hash
            )
            
            record = await result.single()
            if not record:
                return None
            
            node = record["d"]
            return Document(
                id=node["id"],
                memory_id=node["memory_id"],
                uri=node["uri"],
                filename=node["filename"],
                hash=node["hash"],
                ingested_at=node["ingested_at"].to_native(),
                metadata=DocumentMetadata(
                    filename=node["filename"],
                    custom=node.get("metadata", {})
                )
            )
    
    async def delete_document(self, memory_id: str, doc_id: str) -> bool:
        """Supprime un document et ses relations."""
        async with self.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {id: $doc_id, memory_id: $memory_id})
                DETACH DELETE d
                RETURN count(d) as deleted
                """,
                doc_id=doc_id,
                memory_id=memory_id
            )
            
            record = await result.single()
            return record["deleted"] > 0 if record else False
    
    # =========================================================================
    # Gestion des Entités et Relations
    # =========================================================================
    
    async def add_entities_and_relations(
        self,
        memory_id: str,
        doc_id: str,
        extraction: ExtractionResult
    ) -> Dict[str, int]:
        """
        Ajoute les entités et relations extraites au graphe.
        
        Utilise MERGE pour éviter les doublons d'entités.
        """
        entities_created = 0
        relations_created = 0
        
        async with self.session() as session:
            # Ajouter/Merger les entités
            for entity in extraction.entities:
                result = await session.run(
                    """
                    MERGE (e:Entity {name: $name, memory_id: $memory_id})
                    ON CREATE SET 
                        e.type = $type,
                        e.description = $description,
                        e.created_at = datetime(),
                        e.mention_count = 1
                    ON MATCH SET 
                        e.mention_count = e.mention_count + 1,
                        e.description = CASE WHEN $description IS NOT NULL 
                            THEN $description ELSE e.description END
                    WITH e
                    MATCH (d:Document {id: $doc_id})
                    MERGE (d)-[r:MENTIONS]->(e)
                    ON CREATE SET r.count = 1
                    ON MATCH SET r.count = r.count + 1
                    RETURN e
                    """,
                    name=entity.name,
                    memory_id=memory_id,
                    type=entity.type,
                    description=entity.description,
                    doc_id=doc_id
                )
                await result.consume()
                entities_created += 1
            
            # Ajouter les relations entre entités
            for relation in extraction.relations:
                result = await session.run(
                    """
                    MATCH (from:Entity {name: $from_name, memory_id: $memory_id})
                    MATCH (to:Entity {name: $to_name, memory_id: $memory_id})
                    MERGE (from)-[r:RELATED_TO {type: $rel_type}]->(to)
                    ON CREATE SET 
                        r.description = $description,
                        r.weight = $weight,
                        r.created_at = datetime()
                    RETURN r
                    """,
                    from_name=relation.from_entity,
                    to_name=relation.to_entity,
                    memory_id=memory_id,
                    rel_type=relation.type,
                    description=relation.description,
                    weight=relation.weight
                )
                await result.consume()
                relations_created += 1
        
        print(f"🔗 [Graph] Ajouté: {entities_created} entités, {relations_created} relations", file=sys.stderr)
        
        return {
            "entities_created": entities_created,
            "relations_created": relations_created
        }
    
    # =========================================================================
    # Recherche et Contexte
    # =========================================================================
    
    async def search_entities(
        self,
        memory_id: str,
        search_query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Recherche des entités par nom (fuzzy matching).
        
        Tokenise la requête pour des résultats plus pertinents.
        Ex: "Cloud Temple" trouvera "Cloud Temple SAS", "Contrat Cloud Temple", etc.
        """
        # Tokeniser la requête (mots individuels)
        tokens = [t.strip() for t in search_query.lower().split() if len(t.strip()) > 2]
        
        if not tokens:
            return []
        
        async with self.session() as session:
            # Recherche avec TOUS les tokens (AND)
            result = await session.run(
                """
                MATCH (e:Entity {memory_id: $memory_id})
                WHERE ALL(token IN $tokens WHERE 
                    toLower(e.name) CONTAINS token 
                    OR toLower(e.description) CONTAINS token
                )
                RETURN e.name as name, e.type as type, e.description as description,
                       e.mention_count as mentions
                ORDER BY e.mention_count DESC
                LIMIT $limit
                """,
                memory_id=memory_id,
                tokens=tokens,
                limit=limit
            )
            
            entities = []
            async for record in result:
                entities.append({
                    "name": record["name"],
                    "type": record["type"],
                    "description": record["description"],
                    "mentions": record["mentions"]
                })
            
            # Si aucun résultat avec AND, réessayer avec OR (plus permissif)
            if not entities and len(tokens) > 1:
                result = await session.run(
                    """
                    MATCH (e:Entity {memory_id: $memory_id})
                    WHERE ANY(token IN $tokens WHERE 
                        toLower(e.name) CONTAINS token 
                        OR toLower(e.description) CONTAINS token
                    )
                    RETURN e.name as name, e.type as type, e.description as description,
                           e.mention_count as mentions
                    ORDER BY e.mention_count DESC
                    LIMIT $limit
                    """,
                    memory_id=memory_id,
                    tokens=tokens,
                    limit=limit
                )
                
                async for record in result:
                    entities.append({
                        "name": record["name"],
                        "type": record["type"],
                        "description": record["description"],
                        "mentions": record["mentions"]
                    })
            
            return entities
    
    async def get_entity_context(
        self,
        memory_id: str,
        entity_name: str,
        depth: int = 1
    ) -> GraphContext:
        """
        Récupère le contexte complet d'une entité.
        
        Retourne:
        - L'entité elle-même
        - Les documents qui la mentionnent
        - Les entités reliées (jusqu'à depth niveaux)
        - Les relations
        
        Note: Utilise une recherche tolérante si le nom exact n'est pas trouvé.
        """
        async with self.session() as session:
            # Essayer d'abord avec le nom exact
            result = await session.run(
                """
                MATCH (e:Entity {name: $name, memory_id: $memory_id})
                OPTIONAL MATCH (d:Document)-[:MENTIONS]->(e)
                OPTIONAL MATCH (e)-[r:RELATED_TO]-(other:Entity)
                RETURN e, collect(DISTINCT d) as docs, 
                       collect(DISTINCT {entity: other, relation: r}) as related
                """,
                name=entity_name,
                memory_id=memory_id
            )
            
            record = await result.single()
            
            # Si pas trouvé, essayer une recherche tolérante (CONTAINS)
            if not record or not record["e"]:
                result = await session.run(
                    """
                    MATCH (e:Entity {memory_id: $memory_id})
                    WHERE toLower(e.name) CONTAINS toLower($name)
                    OPTIONAL MATCH (d:Document)-[:MENTIONS]->(e)
                    OPTIONAL MATCH (e)-[r:RELATED_TO]-(other:Entity)
                    RETURN e, collect(DISTINCT d) as docs, 
                           collect(DISTINCT {entity: other, relation: r}) as related
                    LIMIT 1
                    """,
                    name=entity_name,
                    memory_id=memory_id
                )
                record = await result.single()
            
            if not record or not record["e"]:
                return GraphContext(
                    entity_name=entity_name,
                    depth=depth,
                    documents=[],
                    related_entities=[],
                    relations=[]
                )
            
            entity = record["e"]
            documents = [
                {"id": d["id"], "filename": d["filename"], "uri": d["uri"]}
                for d in record["docs"] if d
            ]
            
            related_entities = []
            relations = []
            for item in record["related"]:
                if item["entity"]:
                    related_entities.append({
                        "name": item["entity"]["name"],
                        "type": item["entity"]["type"]
                    })
                if item["relation"]:
                    relations.append({
                        "type": item["relation"]["type"],
                        "description": item["relation"].get("description")
                    })
            
            return GraphContext(
                entity_name=entity_name,
                entity_type=entity.get("type"),
                depth=depth,
                documents=documents,
                related_entities=related_entities,
                relations=relations
            )
    
    # =========================================================================
    # Statistiques
    # =========================================================================
    
    async def get_memory_stats(self, memory_id: str) -> MemoryStats:
        """Récupère les statistiques d'une mémoire."""
        async with self.session() as session:
            result = await session.run(
                """
                MATCH (m:Memory {id: $memory_id})
                OPTIONAL MATCH (d:Document {memory_id: $memory_id})
                OPTIONAL MATCH (e:Entity {memory_id: $memory_id})
                WITH m, count(DISTINCT d) as doc_count, count(DISTINCT e) as entity_count
                OPTIONAL MATCH (:Entity {memory_id: $memory_id})-[r:RELATED_TO]-()
                RETURN doc_count, entity_count, count(DISTINCT r) as rel_count
                """,
                memory_id=memory_id
            )
            
            record = await result.single()
            
            if not record:
                return MemoryStats(memory_id=memory_id)
            
            # Top entités
            top_result = await session.run(
                """
                MATCH (e:Entity {memory_id: $memory_id})
                RETURN e.name as name, e.type as type, e.mention_count as mentions
                ORDER BY e.mention_count DESC
                LIMIT 10
                """,
                memory_id=memory_id
            )
            
            top_entities = []
            async for r in top_result:
                top_entities.append({
                    "name": r["name"],
                    "type": r["type"],
                    "mentions": r["mentions"]
                })
            
            return MemoryStats(
                memory_id=memory_id,
                document_count=record["doc_count"],
                entity_count=record["entity_count"],
                relation_count=record["rel_count"],
                top_entities=top_entities
            )


# Singleton pour usage global
_graph_service: Optional[GraphService] = None


def get_graph_service() -> GraphService:
    """Retourne l'instance singleton du GraphService."""
    global _graph_service
    if _graph_service is None:
        _graph_service = GraphService()
    return _graph_service
