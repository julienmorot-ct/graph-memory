#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script CLI pour visualiser le graphe d'une mémoire en mode texte.

Affiche les entités groupées par type et leurs relations.

Usage:
    python scripts/view_graph.py <memory_id>
    python scripts/view_graph.py --list  # Liste les mémoires disponibles
    python scripts/view_graph.py <memory_id> --format tree  # Affichage arbre
    python scripts/view_graph.py <memory_id> --format json  # Export JSON
"""

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

# Charger .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

BASE_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080")
BOOTSTRAP_KEY = os.getenv("ADMIN_BOOTSTRAP_KEY", "admin_bootstrap_key_change_me")


# Couleurs ANSI pour le terminal
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


# Couleurs par type d'entité
TYPE_COLORS = {
    "Organization": Colors.BLUE,
    "Person": Colors.GREEN,
    "LegalRepresentative": Colors.GREEN,
    "Certification": Colors.CYAN,
    "Amount": Colors.YELLOW,
    "Duration": Colors.YELLOW,
    "SLA": Colors.YELLOW,
    "Clause": Colors.RED,
    "Other": Colors.END,
}


def get_color(entity_type: str) -> str:
    """Retourne la couleur pour un type d'entité."""
    return TYPE_COLORS.get(entity_type, Colors.END)


async def list_memories():
    """Liste toutes les mémoires disponibles."""
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError:
        print("❌ Le package 'mcp' n'est pas installé.")
        return

    headers = {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}

    try:
        async with sse_client(f"{BASE_URL}/sse", headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("memory_list", {})
                response = json.loads(getattr(result.content[0], "text", "{}"))

                if response.get("status") == "ok":
                    memories = response.get("memories", [])
                    print(f"\n{Colors.BOLD}📚 Mémoires disponibles ({len(memories)}){Colors.END}\n")

                    if not memories:
                        print("   Aucune mémoire trouvée.")
                    else:
                        for m in memories:
                            print(
                                f"   {Colors.CYAN}•{Colors.END} {Colors.BOLD}{m['id']}{Colors.END}"
                            )
                            print(f"      Nom: {m['name']}")
                            if m.get("description"):
                                print(f"      Description: {m['description']}")
                            print()
                else:
                    print(f"❌ Erreur: {response.get('message')}")

    except ConnectionRefusedError:
        print(f"❌ Impossible de se connecter à {BASE_URL}")


async def view_graph(memory_id: str, format: str = "text"):
    """Affiche le graphe d'une mémoire."""
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError:
        print("❌ Le package 'mcp' n'est pas installé.")
        return

    headers = {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}

    try:
        async with sse_client(f"{BASE_URL}/sse", headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Récupérer le graphe complet
                result = await session.call_tool(
                    "memory_graph", {"memory_id": memory_id, "format": "full"}
                )
                response = json.loads(getattr(result.content[0], "text", "{}"))

                if response.get("status") != "ok":
                    print(f"❌ Erreur: {response.get('message')}")
                    return

                nodes = response.get("nodes", [])
                edges = response.get("edges", [])

                if format == "json":
                    print(json.dumps(response, indent=2, ensure_ascii=False))
                    return

                if format == "tree":
                    display_tree(memory_id, nodes, edges)
                else:
                    display_text(memory_id, nodes, edges)

    except ConnectionRefusedError:
        print(f"❌ Impossible de se connecter à {BASE_URL}")


def display_text(memory_id: str, nodes: list, edges: list):
    """Affichage texte classique du graphe."""
    print()
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}🧠 GRAPHE DE LA MÉMOIRE: {memory_id}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}")

    # Statistiques
    print(f"\n{Colors.HEADER}📊 Statistiques{Colors.END}")
    print(f"   Entités: {len(nodes)}")
    print(f"   Relations: {len(edges)}")

    # Grouper les entités par type
    entities_by_type = defaultdict(list)
    for node in nodes:
        entities_by_type[node["type"]].append(node)

    # Afficher les entités par type
    print(f"\n{Colors.HEADER}{'─' * 70}{Colors.END}")
    print(f"{Colors.HEADER}🔵 ENTITÉS{Colors.END}")
    print(f"{Colors.HEADER}{'─' * 70}{Colors.END}")

    for entity_type in sorted(entities_by_type.keys()):
        entities = entities_by_type[entity_type]
        color = get_color(entity_type)
        print(f"\n{color}[{entity_type}]{Colors.END} ({len(entities)})")

        for e in sorted(entities, key=lambda x: -x.get("mentions", 0)):
            mentions = e.get("mentions", 1)
            desc = (
                f" - {e['description'][:50]}..."
                if e.get("description") and len(e.get("description", "")) > 50
                else (f" - {e['description']}" if e.get("description") else "")
            )
            print(f"   {color}•{Colors.END} {e['label']}{desc} ({mentions} mentions)")

    # Afficher les relations
    print(f"\n{Colors.HEADER}{'─' * 70}{Colors.END}")
    print(f"{Colors.HEADER}🔗 RELATIONS{Colors.END}")
    print(f"{Colors.HEADER}{'─' * 70}{Colors.END}")

    # Grouper les relations par type
    relations_by_type = defaultdict(list)
    for edge in edges:
        relations_by_type[edge["type"]].append(edge)

    for rel_type in sorted(relations_by_type.keys()):
        rels = relations_by_type[rel_type]
        print(f"\n{Colors.YELLOW}[{rel_type}]{Colors.END} ({len(rels)})")

        for r in rels:  # Afficher toutes les relations
            print(f"   {r['from']} → {r['to']}")

    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.END}\n")


def display_tree(memory_id: str, nodes: list, edges: list):
    """Affichage en arbre du graphe."""
    print()
    print(f"{Colors.BOLD}🌳 ARBRE DU GRAPHE: {memory_id}{Colors.END}")
    print()

    # Créer un index des nœuds
    node_index = {n["id"]: n for n in nodes}

    # Créer un graphe d'adjacence
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge["from"]].append((edge["to"], edge["type"]))

    # Trouver les nœuds racines (ceux qui ont le plus de connexions sortantes)
    outgoing_count = {n["id"]: 0 for n in nodes}
    incoming_count = {n["id"]: 0 for n in nodes}

    for edge in edges:
        outgoing_count[edge["from"]] += 1
        incoming_count[edge["to"]] += 1

    # Trier par importance (mentions + connexions)
    roots = sorted(nodes, key=lambda n: -(n.get("mentions", 0) + outgoing_count.get(n["id"], 0)))

    visited = set()

    def print_node(node_id: str, prefix: str = "", is_last: bool = True, depth: int = 0):
        if node_id in visited or depth > 3:  # Limiter la profondeur
            return
        visited.add(node_id)

        node = node_index.get(node_id, {"label": node_id, "type": "Unknown"})
        color = get_color(node.get("type", "Unknown"))

        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{color}{node['label']}{Colors.END} ({node.get('type', '?')})")

        # Afficher les enfants
        children = adjacency.get(node_id, [])
        new_prefix = prefix + ("    " if is_last else "│   ")

        for i, (child_id, rel_type) in enumerate(children[:5]):  # Limiter les enfants
            is_last_child = i == len(children[:5]) - 1
            print_node(child_id, new_prefix, is_last_child, depth + 1)

        if len(children) > 5:
            print(f"{new_prefix}└── ... et {len(children) - 5} autres")

    # Afficher les arbres à partir des nœuds les plus importants
    for i, root in enumerate(roots[:10]):  # Top 10 racines
        if root["id"] not in visited:
            print_node(root["id"], "", i == len(roots[:10]) - 1, 0)
            print()


def main():
    parser = argparse.ArgumentParser(description="Visualiser le graphe d'une mémoire MCP")
    parser.add_argument("memory_id", nargs="?", help="ID de la mémoire à visualiser")
    parser.add_argument("--list", "-l", action="store_true", help="Liste les mémoires disponibles")
    parser.add_argument(
        "--format",
        "-f",
        choices=["text", "tree", "json"],
        default="text",
        help="Format d'affichage (text, tree, json)",
    )
    parser.add_argument("--url", default=BASE_URL, help="URL du serveur MCP")

    args = parser.parse_args()

    if args.list or not args.memory_id:
        asyncio.run(list_memories())
    else:
        asyncio.run(view_graph(args.memory_id, args.format))


if __name__ == "__main__":
    main()
