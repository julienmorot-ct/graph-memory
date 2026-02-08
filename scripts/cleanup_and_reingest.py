#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de nettoyage : supprime la mémoire JURIDIQUE et la recrée proprement.
Puis ingère CGA et CGV.
"""

import asyncio
import json
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from scripts.mcp_cli import MCPClient

BASE_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8002")
TOKEN = os.getenv("ADMIN_BOOTSTRAP_KEY", "admin_bootstrap_key_change_me")

# Documents à ingérer
DOCS = [
    "MATIERE/JURIDIQUE/Q1-2026/Contrat/Conditions Générales/Conditions Générales d'Achat/CT.AM.JUR.CGA - [CLIENT]_Conditions Generales d'Achat Cloud Temple_[DATE].v.1.1.docx",
    "MATIERE/JURIDIQUE/Q1-2026/Contrat/Conditions Générales/Conditions Générales de Vente/CT.AM.JUR.CGV - [CLIENT]_Conditions Générales de Vente_[DATE].docx",
]


async def main():
    client = MCPClient(BASE_URL, TOKEN)
    
    # Étape 1 : Lister les documents actuels
    print("=" * 60)
    print("📋 État actuel de la mémoire JURIDIQUE")
    print("=" * 60)
    try:
        graph = await client.get_graph("JURIDIQUE")
        if graph.get("status") == "ok":
            docs = graph.get("documents", [])
            nodes = [n for n in graph.get("nodes", []) if n.get("node_type") == "entity"]
            edges = graph.get("edges", [])
            print(f"   Documents: {len(docs)}")
            print(f"   Entités: {len(nodes)}")
            print(f"   Relations: {len(edges)}")
            for d in docs:
                print(f"   📄 {d.get('id', '?')[:8]}... → {d.get('filename', '?')}")
        else:
            print(f"   ⚠️ Mémoire pas trouvée ou vide")
    except Exception as e:
        print(f"   ⚠️ Erreur: {e}")

    # Étape 2 : Supprimer la mémoire
    print("\n" + "=" * 60)
    print("🗑️  Suppression de la mémoire JURIDIQUE")
    print("=" * 60)
    try:
        result = await client.call_tool("memory_delete", {"memory_id": "JURIDIQUE"})
        print(f"   Résultat: {result}")
    except Exception as e:
        print(f"   ⚠️ Erreur suppression: {e}")

    # Étape 3 : Recréer la mémoire
    print("\n" + "=" * 60)
    print("➕ Recréation de la mémoire JURIDIQUE avec ontologie legal")
    print("=" * 60)
    result = await client.call_tool("memory_create", {
        "memory_id": "JURIDIQUE",
        "name": "Corpus Juridique Cloud Temple",
        "description": "Documents contractuels Cloud Temple Q1-2026",
        "ontology": "legal"
    })
    print(f"   Résultat: {result.get('status')} - ontologie: {result.get('ontology')}")

    # Étape 4 : Ingérer les documents
    print("\n" + "=" * 60)
    print("📥 Ingestion des documents")
    print("=" * 60)
    for doc_path in DOCS:
        filename = os.path.basename(doc_path)
        print(f"\n   📄 {filename}")
        
        with open(doc_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        
        result = await client.call_tool("memory_ingest", {
            "memory_id": "JURIDIQUE",
            "content_base64": content,
            "filename": filename
        })
        
        if result.get("status") == "ok":
            e_new = result.get("entities_created", 0)
            e_merged = result.get("entities_merged", 0)
            r_new = result.get("relations_created", 0)
            r_merged = result.get("relations_merged", 0)
            print(f"   ✅ Ingéré! ID: {result.get('document_id', '?')[:8]}...")
            print(f"      Entités: {e_new} nouvelles + {e_merged} fusionnées = {e_new + e_merged}")
            print(f"      Relations: {r_new} nouvelles + {r_merged} fusionnées = {r_new + r_merged}")
            
            entity_types = result.get("entity_types", {})
            if entity_types:
                types_str = ", ".join(f"{t}:{c}" for t, c in sorted(entity_types.items(), key=lambda x: -x[1]))
                print(f"      Types entités: {types_str}")
            
            relation_types = result.get("relation_types", {})
            if relation_types:
                rels_str = ", ".join(f"{t}:{c}" for t, c in sorted(relation_types.items(), key=lambda x: -x[1]))
                print(f"      Types relations: {rels_str}")
        else:
            print(f"   ❌ Erreur: {result.get('message', result)}")

    # Étape 5 : Vérification finale
    print("\n" + "=" * 60)
    print("📊 Vérification finale du graphe")
    print("=" * 60)
    try:
        graph = await client.get_graph("JURIDIQUE")
        if graph.get("status") == "ok":
            docs = graph.get("documents", [])
            nodes = [n for n in graph.get("nodes", []) if n.get("node_type") == "entity"]
            edges = [e for e in graph.get("edges", []) if e.get("type") != "MENTIONS"]
            
            print(f"   Documents: {len(docs)}")
            print(f"   Entités: {len(nodes)}")
            print(f"   Relations (hors MENTIONS): {len(edges)}")
            
            # Types de relations
            from collections import Counter
            rel_types = Counter(e.get("type", "?") for e in edges)
            print(f"\n   Types de relations:")
            for t, c in rel_types.most_common():
                print(f"      {t}: {c}")
            
            # Hub check
            hub_count = Counter()
            for e in edges:
                hub_count[e.get("from", "")] += 1
                hub_count[e.get("to", "")] += 1
            print(f"\n   Top 5 nœuds (nb relations):")
            for name, c in hub_count.most_common(5):
                print(f"      {name}: {c}")
            
            # Doublons ?
            filenames = [d.get("filename") for d in docs]
            dupes = [f for f in filenames if filenames.count(f) > 1]
            if dupes:
                print(f"\n   ⚠️ DOUBLONS DÉTECTÉS: {set(dupes)}")
            else:
                print(f"\n   ✅ Aucun doublon de document!")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Terminé!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
