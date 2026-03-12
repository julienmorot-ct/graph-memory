#!/usr/bin/env python3
"""
Audit de la qualité d'une ontologie sur une mémoire graph-memory.

Analyse :
- Distribution des entités par type
- Distribution des relations par type
- Types hors ontologie (LLM qui invente des types)
- Entités hub (trop connectées)
- Entités orphelines (peu connectées)
- Qualité des noms (auto-suffisants ?)

Usage :
    python3 scripts/audit_ontology.py <memory_id> [--url URL] [--token TOKEN]
"""

import json
import sys
import os
import asyncio
from collections import Counter, defaultdict

# Ajouter le répertoire parent pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cli import BASE_URL, TOKEN
from cli.client import MCPClient


# Types définis dans l'ontologie software-development
ONTO_ENTITY_TYPES = {
    "Package", "Module", "Layer", "Class", "Function", "Middleware",
    "DataModel", "Enum", "MCPTool", "APIEndpoint", "Protocol",
    "ExternalService", "Dependency", "ConfigParameter", "DesignPattern",
    "Algorithm", "TestCase", "Documentation", "Feature",
    "InfraComponent", "SecurityBoundary",  # v1.2
}

ONTO_RELATION_TYPES = {
    "CONTAINS", "PART_OF", "BELONGS_TO_LAYER", "DEPENDS_ON", "IMPORTS",
    "USES", "CALLS", "INHERITS_FROM", "IMPLEMENTS", "RETURNS", "ACCEPTS",
    "PRODUCES", "STORES_IN", "EXPOSES", "DELEGATES_TO", "CONFIGURED_BY",
    "TESTED_BY", "DOCUMENTED_IN", "IMPLEMENTS_FEATURE",
    "UPDATES", "READS",  # v1.1
    "PROTECTS", "ROUTES_TO",  # v1.2
}


def print_bar(label, count, total, width=30):
    """Affiche une barre de progression ASCII."""
    pct = count / total * 100 if total > 0 else 0
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    print(f"  {label:25s} {count:4d} ({pct:5.1f}%) {bar}")


def audit_graph(data):
    """Effectue l'audit complet du graphe."""
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    documents = data.get("documents", [])

    # Séparer entités et documents
    entities = [n for n in nodes if n.get("node_type") == "entity"]
    entity_types = Counter(n.get("type", "Unknown") for n in entities)
    
    # L'API REST retourne "label" pour le nom, et "from"/"to" pour les arêtes

    # Relations (exclure MENTIONS qui sont les liens doc→entité)
    rels = [e for e in edges if e.get("type") != "MENTIONS"]
    rel_types = Counter(e.get("type", "Unknown") for e in rels)

    mentions = [e for e in edges if e.get("type") == "MENTIONS"]

    # ═══════════════════════════════════════════════════════════
    # Header
    # ═══════════════════════════════════════════════════════════
    print("=" * 65)
    print("📊 AUDIT ONTOLOGIE software-development")
    print(f"   {len(entities)} entités | {len(rels)} relations | {len(mentions)} mentions | {len(documents)} documents")
    print("=" * 65)

    # ═══════════════════════════════════════════════════════════
    # 1. Distribution des entités
    # ═══════════════════════════════════════════════════════════
    print()
    print("📦 1. DISTRIBUTION DES ENTITÉS PAR TYPE")
    print("-" * 65)
    total_e = sum(entity_types.values())
    for t, count in entity_types.most_common():
        marker = "  " if t in ONTO_ENTITY_TYPES else "⚠️"
        print_bar(f"{marker} {t}", count, total_e)

    # ═══════════════════════════════════════════════════════════
    # 2. Distribution des relations
    # ═══════════════════════════════════════════════════════════
    print()
    print("🔗 2. DISTRIBUTION DES RELATIONS PAR TYPE")
    print("-" * 65)
    total_r = sum(rel_types.values())
    for t, count in rel_types.most_common():
        marker = "  " if t in ONTO_RELATION_TYPES else "⚠️"
        print_bar(f"{marker} {t}", count, total_r)

    # ═══════════════════════════════════════════════════════════
    # 3. Types hors ontologie
    # ═══════════════════════════════════════════════════════════
    print()
    print("🔍 3. TYPES HORS ONTOLOGIE (inventés par le LLM)")
    print("-" * 65)

    off_entity = {t: c for t, c in entity_types.items() if t not in ONTO_ENTITY_TYPES}
    off_rel = {t: c for t, c in rel_types.items() if t not in ONTO_RELATION_TYPES}

    if off_entity:
        print(f"  ⚠️  {len(off_entity)} types d'entités hors ontologie ({sum(off_entity.values())} entités) :")
        for t, c in sorted(off_entity.items(), key=lambda x: -x[1]):
            # Trouver des exemples
            examples = [n.get("label", "?")[:50] for n in entities if n.get("type") == t][:3]
            print(f"     - {t} ({c}x) → ex: {', '.join(examples)}")
    else:
        print("  ✅ Aucun type d'entité hors ontologie !")

    print()
    if off_rel:
        print(f"  ⚠️  {len(off_rel)} types de relations hors ontologie ({sum(off_rel.values())} relations) :")
        for t, c in sorted(off_rel.items(), key=lambda x: -x[1]):
            print(f"     - {t} ({c}x)")
    else:
        print("  ✅ Aucun type de relation hors ontologie !")

    # ═══════════════════════════════════════════════════════════
    # 4. Analyse des hubs (entités trop connectées)
    # ═══════════════════════════════════════════════════════════
    print()
    print("🏠 4. TOP 15 ENTITÉS LES PLUS CONNECTÉES (risque hub)")
    print("-" * 65)

    # L'API utilise "from"/"to" pour les arêtes (pas source/target)
    # et les arêtes référencent les entités par leur LABEL (pas par ID)
    degree = defaultdict(int)
    for e in edges:
        s = e.get("from", "")
        t = e.get("to", "")
        if s:
            degree[s] += 1
        if t:
            degree[t] += 1

    # Mapper les labels vers les nœuds
    label_map = {n.get("label", ""): n for n in nodes}
    for label, deg in sorted(degree.items(), key=lambda x: -x[1])[:15]:
        node = label_map.get(label, {})
        ntype = node.get("type", "?")
        node_type = node.get("node_type", "?")
        flag = "🔴" if deg > 50 else "🟡" if deg > 20 else "🟢"
        print(f"  {flag} {deg:4d} liens  {ntype:20s}  {label[:50]}")

    # ═══════════════════════════════════════════════════════════
    # 5. Entités orphelines (faiblement connectées)
    # ═══════════════════════════════════════════════════════════
    # Les arêtes utilisent les labels, pas les IDs
    entity_labels = {n.get("label", "") for n in entities}
    orphans = [n for n in entities if degree.get(n.get("label", ""), 0) <= 1]
    print()
    print(f"🔌 5. ENTITÉS ORPHELINES (≤1 lien) : {len(orphans)}/{len(entities)} ({len(orphans)/len(entities)*100:.0f}%)")
    print("-" * 65)
    orphan_types = Counter(n.get("type", "?") for n in orphans)
    for t, c in orphan_types.most_common(10):
        print(f"     {t}: {c} orphelines")

    # ═══════════════════════════════════════════════════════════
    # 6. Qualité des noms
    # ═══════════════════════════════════════════════════════════
    print()
    print("📝 6. QUALITÉ DES NOMS D'ENTITÉS")
    print("-" * 65)

    short_names = [n for n in entities if len(n.get("label", "")) < 10]
    long_names = [n for n in entities if len(n.get("label", "")) > 100]
    with_parens = [n for n in entities if "(" in n.get("label", "")]
    with_desc = [n for n in entities if n.get("description", "")]
    
    print(f"  Noms < 10 caractères (trop courts ?) : {len(short_names)}")
    if short_names:
        examples = [n.get("label", "?") for n in short_names[:5]]
        print(f"     ex: {', '.join(examples)}")
    print(f"  Noms > 100 caractères (trop longs ?) : {len(long_names)}")
    if long_names:
        examples = [n.get("label", "?")[:60] + "..." for n in long_names[:3]]
        print(f"     ex: {', '.join(examples)}")
    print(f"  Avec parenthèses descriptives        : {len(with_parens)}/{len(entities)}")
    print(f"  Avec champ description                : {len(with_desc)}/{len(entities)}")

    # ═══════════════════════════════════════════════════════════
    # 7. Taux de fusion (déduplication via MENTIONS)
    # ═══════════════════════════════════════════════════════════
    print()
    print("🔄 7. FUSION INTER-DOCUMENTS")
    print("-" * 65)
    # Compter les documents par entité via les arêtes MENTIONS
    # MENTIONS va de doc_id → entity_label
    docs_map = {d.get("id", ""): d.get("filename", "?") for d in documents}
    entity_doc_count = defaultdict(set)
    for m in mentions:
        doc_id = m.get("from", "")
        entity_label = m.get("to", "")
        if doc_id in docs_map:
            entity_doc_count[entity_label].add(docs_map[doc_id])
    
    multi_doc_labels = {label for label, docs in entity_doc_count.items() if len(docs) > 1}
    multi_doc = [n for n in entities if n.get("label", "") in multi_doc_labels]
    
    print(f"  Entités référencées dans >1 document : {len(multi_doc)}/{len(entities)} ({len(multi_doc)/len(entities)*100:.0f}%)")
    if multi_doc:
        by_type = Counter(n.get("type", "?") for n in multi_doc)
        print(f"  Types les plus fusionnés :")
        for t, c in by_type.most_common(5):
            print(f"     {t}: {c} entités partagées")
        print(f"  Exemples d'entités multi-docs :")
        for n in multi_doc[:5]:
            label = n.get("label", "?")
            docs = entity_doc_count.get(label, set())
            print(f"     {label[:45]} → {', '.join(sorted(docs))}")

    # ═══════════════════════════════════════════════════════════
    # Résumé
    # ═══════════════════════════════════════════════════════════
    print()
    print("=" * 65)
    print("📋 RÉSUMÉ DE L'AUDIT")
    print("=" * 65)
    
    # Score
    on_onto_e = sum(c for t, c in entity_types.items() if t in ONTO_ENTITY_TYPES)
    on_onto_r = sum(c for t, c in rel_types.items() if t in ONTO_RELATION_TYPES)
    pct_onto_e = on_onto_e / total_e * 100 if total_e > 0 else 0
    pct_onto_r = on_onto_r / total_r * 100 if total_r > 0 else 0
    pct_orphan = len(orphans) / len(entities) * 100 if entities else 0
    pct_fusion = len(multi_doc) / len(entities) * 100 if entities else 0
    hubs = sum(1 for d in degree.values() if d > 50)

    print(f"  Conformité entités  : {pct_onto_e:.0f}% dans l'ontologie {'✅' if pct_onto_e > 95 else '⚠️' if pct_onto_e > 80 else '❌'}")
    print(f"  Conformité relations: {pct_onto_r:.0f}% dans l'ontologie {'✅' if pct_onto_r > 95 else '⚠️' if pct_onto_r > 80 else '❌'}")
    print(f"  Entités orphelines  : {pct_orphan:.0f}% {'✅' if pct_orphan < 20 else '⚠️' if pct_orphan < 40 else '❌'}")
    print(f"  Fusion cross-docs   : {pct_fusion:.0f}% {'✅' if pct_fusion > 10 else '⚠️'}")
    print(f"  Nœuds hub (>50)     : {hubs} {'✅' if hubs == 0 else '⚠️' if hubs < 5 else '❌'}")
    print(f"  Types hors ontologie: {len(off_entity)} entités, {len(off_rel)} relations {'✅' if len(off_entity) + len(off_rel) == 0 else '⚠️'}")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Audit d'ontologie sur une mémoire")
    parser.add_argument("memory_id", help="ID de la mémoire à auditer")
    parser.add_argument("--url", default=BASE_URL, help="URL du serveur MCP")
    parser.add_argument("--token", default=TOKEN, help="Token d'authentification")
    args = parser.parse_args()

    client = MCPClient(args.url, args.token)
    print(f"🔄 Chargement du graphe '{args.memory_id}'...")
    data = await client.get_graph(args.memory_id)

    if data.get("status") != "ok":
        print(f"❌ Erreur: {data.get('message', 'graphe non trouvé')}")
        sys.exit(1)

    audit_graph(data)


if __name__ == "__main__":
    asyncio.run(main())
