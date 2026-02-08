# -*- coding: utf-8 -*-
"""
ExtractorService - Extraction d'entités et relations via LLMaaS.

Utilise l'API LLMaaS Cloud Temple (compatible OpenAI) pour extraire
les entités, relations et concepts à partir de texte.
"""

import sys
import json
from typing import Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential

from openai import AsyncOpenAI
from openai import APIError, APITimeoutError

from ..config import get_settings
from .models import (
    ExtractionResult, ExtractedEntity, ExtractedRelation,
    EntityType, RelationType
)
from .ontology import Ontology, get_ontology_manager


# Prompt d'extraction MINIMAL (fallback sans ontologie).
# Toute la logique métier (types d'entités, relations, règles) vient de l'ontologie.
# Ce prompt n'est utilisé que par extract_from_text() quand aucune ontologie n'est chargée.
EXTRACTION_PROMPT = """Tu es un expert en extraction d'information structurée. Analyse le document suivant et extrait les entités et relations importantes.

DOCUMENT:
---
{document_text}
---

INSTRUCTIONS:
1. Identifie les entités nommées (personnes, organisations, lieux, concepts, valeurs)
2. Identifie les relations entre ces entités
3. Fournis un bref résumé

Les noms d'entités doivent être explicites et inclure les valeurs quand pertinent.
Crée des relations ENTRE les entités les plus spécifiques, pas tout vers une entité centrale.
Utilise des types de relations descriptifs (SIGNED_BY, HAS_DURATION, DEFINES, etc.) plutôt que RELATED_TO.

Réponds UNIQUEMENT avec un JSON valide:
```json
{{
  "entities": [
    {{"name": "Nom de l'entité", "type": "Person|Organization|Concept|Other", "description": "Description courte"}}
  ],
  "relations": [
    {{"from_entity": "Nom entité source", "to_entity": "Nom entité cible", "type": "TYPE_RELATION", "description": "Description"}}
  ],
  "summary": "Résumé du document en 2-3 phrases",
  "key_topics": ["sujet1", "sujet2"]
}}
```
"""


class ExtractorService:
    """
    Service d'extraction via LLMaaS.
    
    Utilise le modèle gpt-oss:120b de Cloud Temple pour extraire
    les entités et relations structurées depuis un texte.
    """
    
    def __init__(self):
        """Initialise le client OpenAI compatible."""
        settings = get_settings()
        
        self._client = AsyncOpenAI(
            base_url=settings.llmaas_base_url,
            api_key=settings.llmaas_api_key,
            timeout=settings.extraction_timeout_seconds
        )
        self._model = settings.llmaas_model
        self._max_tokens = settings.llmaas_max_tokens
        self._temperature = settings.llmaas_temperature
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def extract_from_text(
        self,
        text: str,
        max_text_length: int = 50000
    ) -> ExtractionResult:
        """
        Extrait les entités et relations d'un texte.
        
        Args:
            text: Texte à analyser
            max_text_length: Longueur max du texte (tronqué sinon)
            
        Returns:
            ExtractionResult avec entités, relations, résumé
        """
        # Tronquer si nécessaire
        if len(text) > max_text_length:
            text = text[:max_text_length] + "\n\n[Document tronqué...]"
        
        prompt = EXTRACTION_PROMPT.format(document_text=text)
        
        try:
            print(f"🔍 [Extractor] Extraction en cours ({len(text)} chars)...", file=sys.stderr)
            
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant spécialisé dans l'extraction d'information structurée. Tu réponds uniquement en JSON valide."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature
                # Note: response_format non supporté par LLMaaS Cloud Temple
            )
            
            # Parser la réponse - DEBUG COMPLET
            print(f"🔍 [Extractor] DEBUG response type: {type(response)}", file=sys.stderr)
            print(f"🔍 [Extractor] DEBUG choices count: {len(response.choices)}", file=sys.stderr)
            if response.choices:
                print(f"🔍 [Extractor] DEBUG message: {response.choices[0].message}", file=sys.stderr)
                print(f"🔍 [Extractor] DEBUG finish_reason: {response.choices[0].finish_reason}", file=sys.stderr)
            
            content = response.choices[0].message.content
            if content is None:
                print(f"⚠️ [Extractor] Réponse LLM vide - message complet: {response.choices[0].message}", file=sys.stderr)
                return ExtractionResult(summary=None)
            
            print(f"🔍 [Extractor] DEBUG content length: {len(content)}", file=sys.stderr)
            result = self._parse_extraction(content)
            
            print(f"✅ [Extractor] Extrait: {len(result.entities)} entités, {len(result.relations)} relations", file=sys.stderr)
            
            return result
            
        except APITimeoutError:
            print(f"⏰ [Extractor] Timeout - le document est peut-être trop long", file=sys.stderr)
            raise
        except APIError as e:
            print(f"❌ [Extractor] Erreur API: {e}", file=sys.stderr)
            raise
    
    def _parse_extraction(self, content: str, known_relation_types: Optional[set] = None) -> ExtractionResult:
        """
        Parse la réponse JSON du LLM.
        
        Args:
            content: Contenu JSON brut du LLM
            known_relation_types: Types de relations connus (depuis l'ontologie).
                                   Si None, utilise BASE_RELATION_TYPES.
        """
        try:
            # Nettoyer le contenu (parfois le LLM ajoute des ```json)
            content = content.strip()
            if content.startswith("```"):
                # Trouver le premier { et le dernier }
                start = content.find("{")
                end = content.rfind("}") + 1
                content = content[start:end]
            
            data = json.loads(content)
            
            # Parser les entités
            entities = []
            for e in data.get("entities", []):
                entity_type = self._parse_entity_type(e.get("type", "Other"))
                entities.append(ExtractedEntity(
                    name=e.get("name", "").strip(),
                    type=entity_type,
                    description=e.get("description")
                ))
            
            # Parser les relations — avec les types connus de l'ontologie
            relations = []
            for r in data.get("relations", []):
                rel_type = self._parse_relation_type(
                    r.get("type", "RELATED_TO"),
                    known_types=known_relation_types
                )
                relations.append(ExtractedRelation(
                    from_entity=r.get("from_entity", "").strip(),
                    to_entity=r.get("to_entity", "").strip(),
                    type=rel_type,
                    description=r.get("description")
                ))
            
            return ExtractionResult(
                entities=entities,
                relations=relations,
                summary=data.get("summary"),
                key_topics=data.get("key_topics", [])
            )
            
        except json.JSONDecodeError as e:
            print(f"⚠️ [Extractor] Erreur parsing JSON: {e}", file=sys.stderr)
            print(f"   Contenu reçu: {content[:200]}...", file=sys.stderr)
            # Retourner un résultat vide plutôt que crasher
            return ExtractionResult(summary=None)
    
    @staticmethod
    def _parse_entity_type(type_str: str) -> EntityType:
        """Convertit une string en EntityType."""
        type_map = {
            "person": EntityType.PERSON,
            "organization": EntityType.ORGANIZATION,
            "concept": EntityType.CONCEPT,
            "location": EntityType.LOCATION,
            "date": EntityType.DATE,
            "product": EntityType.PRODUCT,
            "service": EntityType.SERVICE,
            "clause": EntityType.CLAUSE,
            "certification": EntityType.CERTIFICATION,
            "metric": EntityType.METRIC,
            "duration": EntityType.DURATION,
            "amount": EntityType.AMOUNT,
        }
        return type_map.get(type_str.lower(), EntityType.OTHER)
    
    # Types de base (utilisés quand aucune ontologie n'est chargée)
    BASE_RELATION_TYPES = {
        "MENTIONS", "DEFINES", "RELATED_TO", "BELONGS_TO",
        "SIGNED_BY", "CREATED_BY", "REFERENCES", "CONTAINS",
        "HAS_VALUE", "CERTIFIES", "PART_OF",
    }
    
    @staticmethod
    def _parse_relation_type(type_str: str, known_types: Optional[set] = None) -> str:
        """
        Convertit une string en type de relation.
        
        Accepte les types définis par l'ontologie (dynamique).
        Les types inconnus qui ont un format valide (MAJ + underscores) sont acceptés tels quels.
        
        Args:
            type_str: Type brut retourné par le LLM
            known_types: Set de types connus (provenant de l'ontologie). Si None, utilise BASE_RELATION_TYPES.
        """
        # Normaliser : majuscules, underscores
        normalized = type_str.strip().upper().replace(" ", "_").replace("-", "_")
        
        # Types connus depuis l'ontologie (ou base par défaut)
        valid_types = known_types or ExtractorService.BASE_RELATION_TYPES
        
        if normalized in valid_types:
            return normalized
        
        # Accepter tout type au format valide (MAJ + underscores) — le LLM peut inventer
        if normalized.replace("_", "").isalpha() and normalized == normalized.upper():
            return normalized
        
        return "RELATED_TO"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def extract_with_ontology(
        self,
        text: str,
        ontology_name: str = "default",
        max_text_length: int = 50000
    ) -> ExtractionResult:
        """
        Extrait les entités et relations d'un texte en utilisant une ontologie.
        
        Args:
            text: Texte à analyser
            ontology_name: Nom de l'ontologie à utiliser (ex: "legal", "cloud")
            max_text_length: Longueur max du texte (tronqué sinon)
            
        Returns:
            ExtractionResult avec entités, relations, résumé
        """
        # Charger l'ontologie — OBLIGATOIRE
        ontology_manager = get_ontology_manager()
        ontology = ontology_manager.get_ontology(ontology_name)
        
        if not ontology:
            available = [o["name"] for o in ontology_manager.list_ontologies()]
            raise ValueError(
                f"Ontologie '{ontology_name}' introuvable. "
                f"Ontologies disponibles: {available}. "
                f"Chaque mémoire DOIT avoir une ontologie valide."
            )
        
        # Tronquer si nécessaire
        if len(text) > max_text_length:
            text = text[:max_text_length] + "\n\n[Document tronqué...]"
        
        # Construire le prompt avec l'ontologie
        prompt = ontology.build_prompt(text)
        
        try:
            print(f"🔍 [Extractor] Extraction avec ontologie '{ontology.name}' ({len(text)} chars)...", file=sys.stderr)
            
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant spécialisé dans l'extraction d'information structurée. Tu réponds uniquement en JSON valide."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature
            )
            
            content = response.choices[0].message.content
            if content is None:
                print(f"⚠️ [Extractor] Réponse LLM vide", file=sys.stderr)
                return ExtractionResult(summary=None)
            
            # Extraire les types de relations depuis l'ontologie chargée
            ontology_relation_types = {
                rt.name.upper() for rt in ontology.relation_types
            } | self.BASE_RELATION_TYPES  # Union avec les types de base
            
            print(f"🔗 [Extractor] Types de relations ontologie '{ontology.name}': {sorted(ontology_relation_types)}", file=sys.stderr)
            
            result = self._parse_extraction(content, known_relation_types=ontology_relation_types)
            
            print(f"✅ [Extractor] Extrait ({ontology.name}): {len(result.entities)} entités, {len(result.relations)} relations", file=sys.stderr)
            
            return result
            
        except APITimeoutError:
            print(f"⏰ [Extractor] Timeout - le document est peut-être trop long", file=sys.stderr)
            raise
        except APIError as e:
            print(f"❌ [Extractor] Erreur API: {e}", file=sys.stderr)
            raise

    async def test_connection(self) -> dict:
        """Teste la connexion au LLMaaS."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "Réponds juste 'OK'"}],
                max_tokens=10
            )
            
            return {
                "status": "ok",
                "model": self._model,
                "message": "Connexion LLMaaS réussie"
            }
            
        except APIError as e:
            return {
                "status": "error",
                "model": self._model,
                "message": f"Erreur LLMaaS: {str(e)}"
            }


    async def generate_answer(self, prompt: str) -> str:
        """
        Génère une réponse à partir d'un prompt.
        
        Utilisé pour le Q&A sur le graphe de connaissances.
        
        Args:
            prompt: Prompt complet avec contexte et question
            
        Returns:
            Réponse générée par le LLM
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant expert qui répond à des questions basées sur un graphe de connaissances. Réponds de manière concise et précise."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Plus déterministe pour les réponses factuelles
                max_tokens=1000
            )
            
            return response.choices[0].message.content or "Pas de réponse générée."
            
        except Exception as e:
            print(f"❌ [Extractor] Erreur génération réponse: {e}", file=sys.stderr)
            return f"Erreur lors de la génération de la réponse: {str(e)}"


# Singleton pour usage global
_extractor_service: Optional[ExtractorService] = None


def get_extractor_service() -> ExtractorService:
    """Retourne l'instance singleton du ExtractorService."""
    global _extractor_service
    if _extractor_service is None:
        _extractor_service = ExtractorService()
    return _extractor_service
