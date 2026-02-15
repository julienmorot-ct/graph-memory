#!/usr/bin/env python3
"""
Test comparatif des seuils RAG (0.50, 0.55, 0.60) pour BGE-M3.

Ce script interroge directement Qdrant et l'API d'embedding
pour simuler les 3 seuils sans reconstruire le serveur.
"""

import os
import sys
import json
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# Charger .env
load_dotenv()

LLMAAS_API_URL = os.getenv("LLMAAS_API_URL", "https://api.ai.cloud-temple.com")
LLMAAS_API_KEY = os.getenv("LLMAAS_API_KEY", "")
LLMAAS_EMBEDDING_MODEL = os.getenv("LLMAAS_EMBEDDING_MODEL", "bge-m3:567m")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_PREFIX = os.getenv("QDRANT_COLLECTION_PREFIX", "memory_")
MEMORY_ID = "JURIDIQUE"

THRESHOLDS = [0.50, 0.55, 0.58, 0.60, 0.65]
CHUNK_LIMIT = 15  # Plus que 8 pour voir la distribution complète

QUESTIONS = [
    "réversibilité",
    "résiliation",
    "Quelles sont les conditions de résiliation du contrat ?",
    "Quelles sont les obligations du prestataire en matière de sécurité ?",
    "force majeure",
]


# Client OpenAI pour les embeddings (même approche que embedder.py)
_openai_client = OpenAI(
    base_url=LLMAAS_API_URL,
    api_key=LLMAAS_API_KEY,
)


def get_embedding(text: str) -> list:
    """Appelle l'API d'embedding BGE-M3 via le client OpenAI."""
    response = _openai_client.embeddings.create(
        model=LLMAAS_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def search_qdrant(client: QdrantClient, collection: str, embedding: list, limit: int):
    """Recherche vectorielle dans Qdrant."""
    results = client.query_points(
        collection_name=collection,
        query=embedding,
        limit=limit,
        with_payload=True,
    )
    return results.points


def main():
    # Connexion Qdrant
    safe_id = "".join(c if c.isalnum() else "_" for c in MEMORY_ID)
    collection = f"{QDRANT_PREFIX}{safe_id}"
    
    client = QdrantClient(url=QDRANT_URL, timeout=30)
    
    # Vérifier la collection
    try:
        info = client.get_collection(collection_name=collection)
        print(f"📦 Collection: {collection} ({info.points_count} chunks)\n")
    except Exception as e:
        print(f"❌ Collection {collection} introuvable: {e}")
        sys.exit(1)
    
    print("=" * 90)
    print(f"{'COMPARAISON DES SEUILS RAG':^90}")
    print(f"{'(BGE-M3 embeddings, distance cosinus)':^90}")
    print("=" * 90)
    
    # Tableau récapitulatif
    summary = []
    
    for question in QUESTIONS:
        print(f"\n{'─' * 90}")
        print(f"❓ Question: \"{question}\"")
        print(f"{'─' * 90}")
        
        # Embedding de la question
        try:
            emb = get_embedding(question)
        except Exception as e:
            print(f"   ❌ Erreur embedding: {e}")
            continue
        
        # Recherche Qdrant (tous les chunks, pas de filtre doc_id)
        points = search_qdrant(client, collection, emb, CHUNK_LIMIT)
        
        if not points:
            print("   (aucun chunk trouvé)")
            continue
        
        # Afficher tous les chunks avec scores
        print(f"\n   {'#':>3} {'Score':>7} {'0.50':>5} {'0.55':>5} {'0.60':>5} {'0.65':>5}  Section / Aperçu")
        print(f"   {'─'*3} {'─'*7} {'─'*5} {'─'*5} {'─'*5} {'─'*5}  {'─'*50}")
        
        counts = {t: 0 for t in THRESHOLDS}
        
        for i, point in enumerate(points):
            payload = point.payload or {}
            score = point.score
            section = payload.get("section_title") or payload.get("article_number") or "—"
            # Tronquer section
            if len(section) > 40:
                section = section[:37] + "..."
            text_preview = (payload.get("text", "")[:50]).replace("\n", " ").strip()
            
            # Marquer pour chaque seuil
            marks = {}
            for t in THRESHOLDS:
                if score >= t:
                    marks[t] = "  ✅"
                    counts[t] += 1
                else:
                    marks[t] = "  ❌"
            
            print(f"   {i+1:>3} {score:>7.4f} {marks[0.50]} {marks[0.55]} {marks[0.60]} {marks[0.65]}  {section}")
        
        # Résumé pour cette question
        print(f"\n   📊 Chunks retenus par seuil:")
        for t in THRESHOLDS:
            bar = "█" * counts[t] + "░" * (len(points) - counts[t])
            print(f"      {t:.2f} → {counts[t]:>2}/{len(points)} {bar}")
        
        summary.append({"question": question, "total": len(points), "counts": counts})
    
    # Tableau récapitulatif final
    print(f"\n\n{'=' * 90}")
    print(f"{'RÉSUMÉ COMPARATIF':^90}")
    print(f"{'=' * 90}")
    print(f"\n{'Question':<55} {'0.50':>6} {'0.55':>6} {'0.60':>6} {'0.65':>6}")
    print(f"{'─'*55} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
    
    totals = {t: 0 for t in THRESHOLDS}
    for s in summary:
        q = s["question"][:52] + "..." if len(s["question"]) > 55 else s["question"]
        print(f"{q:<55} {s['counts'][0.50]:>5}  {s['counts'][0.55]:>5}  {s['counts'][0.60]:>5}  {s['counts'][0.65]:>5}")
        for t in THRESHOLDS:
            totals[t] += s["counts"][t]
    
    print(f"{'─'*55} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
    print(f"{'TOTAL':>55} {totals[0.50]:>5}  {totals[0.55]:>5}  {totals[0.60]:>5}  {totals[0.65]:>5}")
    
    total_possible = sum(s["total"] for s in summary)
    print(f"\n💡 Sur {total_possible} chunks candidats au total:")
    for t in THRESHOLDS:
        pct = totals[t] / total_possible * 100 if total_possible > 0 else 0
        print(f"   Seuil {t:.2f} : {totals[t]:>3} retenus ({pct:.0f}%)")


if __name__ == "__main__":
    main()
