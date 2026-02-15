# -*- coding: utf-8 -*-
"""
Helpers d'affichage Rich pour la CLI MCP Memory.

Fournit des fonctions réutilisables pour formater et afficher :
  - Tables (mémoires, documents, entités, relations)
  - Panels (info, erreur, résumé)
  - Statistiques de graphe
"""

from collections import Counter, defaultdict
from typing import List, Dict, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


# =============================================================================
# Affichage des mémoires
# =============================================================================

def show_memories_table(memories: List[dict], current_memory: str = None):
    """Affiche la liste des mémoires dans un tableau."""
    if not memories:
        console.print("[yellow]Aucune mémoire trouvée.[/yellow]")
        return

    table = Table(title=f"📚 Mémoires ({len(memories)})", show_header=True)
    table.add_column("ID", style="cyan bold", no_wrap=True)
    table.add_column("Nom", style="white")
    table.add_column("Ontologie", style="magenta")
    table.add_column("Description", style="dim", max_width=30)
    table.add_column("", width=3)

    for m in memories:
        marker = "→" if m.get("id") == current_memory else ""
        table.add_row(
            m.get("id", ""),
            m.get("name", ""),
            m.get("ontology", "?"),
            (m.get("description", "") or "")[:30],
            marker,
        )

    console.print(table)
    console.print("[dim]Utilisez: use <ID>[/dim]")


# =============================================================================
# Affichage des documents
# =============================================================================

def show_documents_table(docs: List[dict], memory_id: str):
    """Affiche la liste des documents dans un tableau."""
    if not docs:
        console.print(f"[yellow]Aucun document dans '{memory_id}'.[/yellow]")
        return

    table = Table(title=f"📄 Documents de {memory_id} ({len(docs)})")
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Fichier", style="white")
    table.add_column("Ingéré le", style="green", width=12)

    for i, d in enumerate(docs, 1):
        doc_id = d.get("id", "")
        ingested = d.get("ingested_at", "")[:10] if d.get("ingested_at") else "-"
        table.add_row(
            str(i),
            doc_id,
            d.get("filename", ""),
            ingested,
        )

    console.print(table)


# =============================================================================
# Affichage du graphe (résumé complet)
# =============================================================================

def show_graph_summary(graph_data: dict, memory_id: str):
    """
    Affiche un résumé complet et lisible du graphe d'une mémoire.

    Inclut :
      - Compteurs globaux (entités, relations, documents)
      - Entités par type (tableau)
      - Relations par type (tableau)
      - Liste des documents
      - Top 5 nœuds les plus connectés
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    docs = graph_data.get("documents", [])

    # --- Panneau de résumé ---
    entity_nodes = [n for n in nodes if n.get("node_type") == "entity"]
    non_mention_edges = [e for e in edges if e.get("type") != "MENTIONS"]

    console.print(Panel.fit(
        f"[bold]Entités:[/bold] [cyan]{len(entity_nodes)}[/cyan]  "
        f"[bold]Relations:[/bold] [cyan]{len(non_mention_edges)}[/cyan]  "
        f"[bold]Documents:[/bold] [cyan]{len(docs)}[/cyan]  "
        f"[bold]MENTIONS:[/bold] [dim]{len(edges) - len(non_mention_edges)}[/dim]",
        title=f"📊 Graphe: {memory_id}",
        border_style="blue",
    ))

    # --- Entités par type ---
    by_type = defaultdict(list)
    for n in entity_nodes:
        by_type[n.get("type", "Unknown")].append(n)

    table_ent = Table(title="📦 Entités par type", show_header=True)
    table_ent.add_column("Type", style="magenta bold")
    table_ent.add_column("Nb", style="cyan", justify="right", width=4)
    table_ent.add_column("Exemples", style="white")

    for etype in sorted(by_type, key=lambda t: -len(by_type[t])):
        entities = by_type[etype]
        examples = ", ".join(e.get("label", "?")[:30] for e in entities[:4])
        if len(entities) > 4:
            examples += f" … (+{len(entities) - 4})"
        table_ent.add_row(etype, str(len(entities)), examples)

    console.print(table_ent)

    # --- Relations par type ---
    rel_types = Counter(e.get("type", "?") for e in non_mention_edges)
    if rel_types:
        table_rel = Table(title="🔗 Relations par type", show_header=True)
        table_rel.add_column("Type", style="blue bold")
        table_rel.add_column("Nb", style="cyan", justify="right", width=4)

        for rtype, count in rel_types.most_common():
            table_rel.add_row(rtype, str(count))

        console.print(table_rel)

    # --- Documents ---
    if docs:
        console.print("\n[bold]📄 Documents:[/bold]")
        for d in docs:
            console.print(f"  • [cyan]{d.get('filename', '?')}[/cyan]  [dim]({d.get('id', '?')[:8]}…)[/dim]")

    # --- Top nœuds connectés ---
    hub_count: Counter = Counter()
    for e in non_mention_edges:
        hub_count[e.get("from", "")] += 1
        hub_count[e.get("to", "")] += 1

    if hub_count:
        console.print("\n[bold]🏢 Top 5 nœuds (nb relations):[/bold]")
        for name, c in hub_count.most_common(5):
            console.print(f"  {name}: [cyan]{c}[/cyan]")


# =============================================================================
# Affichage d'une entité et son contexte
# =============================================================================

def show_entity_context(context: dict):
    """Affiche le contexte d'une entité (relations, documents, voisins)."""
    name = context.get("entity_name", "?")
    etype = context.get("entity_type", "?")

    console.print(Panel.fit(
        f"[bold]Nom:[/bold] [cyan]{name}[/cyan]\n"
        f"[bold]Type:[/bold] [magenta]{etype}[/magenta]",
        title="🔍 Entité",
        border_style="cyan",
    ))

    # Relations
    relations = context.get("relations", [])
    if relations:
        table = Table(title=f"🔗 Relations ({len(relations)})", show_header=True)
        table.add_column("Type", style="blue bold")
        table.add_column("Vers", style="white")
        table.add_column("Description", style="dim", max_width=40)

        for r in relations:
            table.add_row(
                r.get("type", "?"),
                r.get("target", r.get("to", "?")),
                (r.get("description", "") or "")[:40],
            )
        console.print(table)

    # Documents
    documents = context.get("documents", [])
    if documents:
        console.print(f"\n[bold]📄 Mentionné dans {len(documents)} document(s):[/bold]")
        for d in documents:
            if isinstance(d, dict):
                console.print(f"  • [cyan]{d.get('filename', d.get('id', '?'))}[/cyan]")
            else:
                console.print(f"  • [cyan]{d}[/cyan]")

    # Entités liées
    related = context.get("related_entities", [])
    if related:
        console.print(f"\n[bold]🔗 Entités liées ({len(related)}):[/bold]")
        for r in related:
            if isinstance(r, dict):
                console.print(f"  • [{r.get('type', '?')}] [white]{r.get('name', '?')}[/white]")
            else:
                console.print(f"  • [white]{r}[/white]")


# =============================================================================
# Affichage d'ingestion
# =============================================================================

def _colorize_step(msg: str) -> str:
    """Colorie une étape d'ingestion selon son type."""
    # Mapping emoji → couleur Rich
    color_map = {
        "📦": "cyan",      # Décodage
        "📤": "blue",      # Upload S3
        "📄": "white",     # Extraction texte
        "🔍": "yellow",    # LLM extraction
        "📊": "magenta",   # Neo4j
        "🧩": "cyan",      # RAG/Chunking
        "🔢": "blue",      # Embedding
        "📦": "cyan",      # Stockage Qdrant
        "✅": "green",     # Succès
        "🔄": "yellow",    # Force/suppression
        "🏁": "green bold", # Terminé
    }
    for emoji, color in color_map.items():
        if msg.startswith(emoji):
            return f"[{color}]{msg}[/{color}]"
    return msg


def show_ingest_result(result: dict):
    """Affiche le résultat d'une ingestion avec timeline colorée + panneau enrichi."""
    doc_id = result.get("document_id", "?")
    filename = result.get("filename", "?")
    e_new = result.get("entities_created", 0)
    e_merged = result.get("entities_merged", 0)
    r_new = result.get("relations_created", 0)
    r_merged = result.get("relations_merged", 0)
    chunks = result.get("chunks_stored", 0)
    elapsed = result.get("elapsed_seconds", result.get("_elapsed_seconds", None))
    size_bytes = result.get("size_bytes", 0)

    # === Timeline des étapes (si disponible) ===
    steps = result.get("steps", [])
    if steps:
        step_lines = []
        for step in steps:
            t = step.get("t", 0)
            msg = step.get("msg", "")
            m, s = divmod(int(t), 60)
            colored = _colorize_step(msg)
            step_lines.append(f"  [dim]{m:02d}:{s:02d}[/dim]  {colored}")
        console.print(Panel.fit(
            "\n".join(step_lines),
            title="📋 Pipeline d'ingestion",
            border_style="blue",
        ))

    # === Panneau résultat ===
    timing_str = ""
    if elapsed is not None:
        m, s = divmod(int(elapsed), 60)
        timing_str = f"  [dim]⏱ {m:02d}:{s:02d}[/dim]"

    size_str = _format_size(size_bytes) if size_bytes else ""

    lines = []
    lines.append(f"[bold]Fichier:[/bold]   [cyan]{filename}[/cyan]" + (f"  ({size_str})" if size_str else ""))
    lines.append(f"[bold]ID:[/bold]        [dim]{doc_id}[/dim]")
    lines.append(f"[bold]Entités:[/bold]   [cyan]{e_new}[/cyan] nouvelles + [yellow]{e_merged}[/yellow] fusionnées = [bold]{e_new + e_merged}[/bold]")
    lines.append(f"[bold]Relations:[/bold] [cyan]{r_new}[/cyan] nouvelles + [yellow]{r_merged}[/yellow] fusionnées = [bold]{r_new + r_merged}[/bold]")
    if chunks > 0:
        lines.append(f"[bold]RAG:[/bold]       [green]{chunks}[/green] chunks vectorisés")

    # Types d'entités (compact)
    entity_types = result.get("entity_types", {})
    if entity_types:
        types_str = " ".join(
            f"[magenta]{t}[/magenta]:{c}"
            for t, c in sorted(entity_types.items(), key=lambda x: -x[1])
        )
        lines.append(f"[bold]Types E:[/bold]   {types_str}")

    # Types de relations (compact)
    relation_types = result.get("relation_types", {})
    if relation_types:
        rels_str = " ".join(
            f"[blue]{t}[/blue]:{c}"
            for t, c in sorted(relation_types.items(), key=lambda x: -x[1])
        )
        lines.append(f"[bold]Types R:[/bold]   {rels_str}")

    # Sujets
    topics = result.get("key_topics", [])
    if topics:
        lines.append(f"[bold]Sujets:[/bold]    [dim]{', '.join(topics[:6])}[/dim]")

    # Résumé
    summary = result.get("summary", "")
    if summary:
        lines.append(f"[bold]Résumé:[/bold]    [dim]{summary[:150]}{'…' if len(summary) > 150 else ''}[/dim]")

    console.print(Panel.fit(
        "\n".join(lines),
        title=f"✅ Document ingéré{timing_str}",
        border_style="green",
    ))


# =============================================================================
# Utilitaires
# =============================================================================

def show_error(msg: str):
    """Affiche un message d'erreur."""
    console.print(f"[red]❌ {msg}[/red]")


def show_success(msg: str):
    """Affiche un message de succès."""
    console.print(f"[green]✅ {msg}[/green]")


def show_warning(msg: str):
    """Affiche un avertissement."""
    console.print(f"[yellow]⚠️ {msg}[/yellow]")


def show_storage_check(result: dict):
    """
    Affiche le rapport de vérification S3 dans un format lisible.
    
    Affiche :
    - Panneau résumé (docs accessibles, manquants, orphelins)
    - Tableau des documents vérifiés (avec statut)
    - Tableau des fichiers orphelins sur S3
    """
    if result.get("status") != "ok":
        show_error(result.get("message", "Erreur lors du check S3"))
        return
    
    scope = result.get("scope", "all")
    graph_docs = result.get("graph_documents", {})
    orphans = result.get("s3_orphans", {})
    
    # --- Panneau résumé ---
    summary = result.get("summary", "")
    console.print(Panel.fit(
        f"[bold]Scope:[/bold] [cyan]{scope}[/cyan]  "
        f"[bold]Mémoires:[/bold] [cyan]{result.get('memories_checked', 0)}[/cyan]  "
        f"[bold]Objets S3:[/bold] [cyan]{result.get('s3_total_objects', 0)}[/cyan]\n\n"
        f"{summary}",
        title="🔍 Vérification S3",
        border_style="blue",
    ))
    
    # --- Tableau des documents du graphe ---
    details = graph_docs.get("details", [])
    if details:
        table = Table(
            title=f"📄 Documents dans le graphe ({graph_docs.get('total', 0)})",
            show_header=True
        )
        table.add_column("Statut", width=3)
        table.add_column("Mémoire", style="cyan", max_width=20)
        table.add_column("Fichier", style="white", max_width=30)
        table.add_column("Taille", style="dim", justify="right", width=10)
        table.add_column("Type", style="dim", max_width=15)
        
        for d in details:
            status_icon = {
                "ok": "[green]✅[/green]",
                "missing": "[red]❌[/red]",
                "error": "[yellow]⚠️[/yellow]",
            }.get(d.get("status", ""), "❓")
            
            size = d.get("size_bytes", 0)
            size_str = _format_size(size) if size > 0 else "-"
            
            table.add_row(
                status_icon,
                d.get("memory_id", "?"),
                d.get("filename", d.get("key", "?"))[:30],
                size_str,
                d.get("content_type", "")[:15] if d.get("content_type") else "-",
            )
        
        console.print(table)
    
    # --- Tableau des orphelins ---
    orphan_files = orphans.get("files", [])
    if orphan_files:
        table = Table(
            title=f"⚠️ Fichiers orphelins S3 ({orphans.get('count', 0)}, {orphans.get('total_size', '?')})",
            show_header=True,
            border_style="yellow"
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Clé S3", style="yellow", max_width=50)
        table.add_column("Taille", style="dim", justify="right", width=10)
        table.add_column("Modifié le", style="dim", width=12)
        
        for i, o in enumerate(orphan_files, 1):
            table.add_row(
                str(i),
                o.get("key", "?")[:50],
                _format_size(o.get("size", 0)),
                str(o.get("last_modified", ""))[:10],
            )
        
        console.print(table)
        console.print("[dim]Pour nettoyer: cleanup (dry run) ou cleanup --force (suppression)[/dim]")
    elif graph_docs.get("total", 0) > 0:
        console.print("[green]✅ Aucun fichier orphelin sur S3. Stockage propre ![/green]")


def show_cleanup_result(result: dict):
    """Affiche le résultat du nettoyage S3."""
    if result.get("status") != "ok":
        show_error(result.get("message", "Erreur"))
        return
    
    message = result.get("message", "")
    console.print(f"\n{message}")
    
    if result.get("dry_run") and result.get("files"):
        files = result["files"]
        table = Table(title="📋 Fichiers à supprimer", show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Clé S3", style="yellow", max_width=50)
        table.add_column("Taille", style="dim", justify="right", width=10)
        
        for i, f in enumerate(files, 1):
            table.add_row(
                str(i),
                f.get("key", "?")[:50],
                _format_size(f.get("size", 0)),
            )
        console.print(table)


def _format_size(size_bytes: int) -> str:
    """Convertit des bytes en taille lisible."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# =============================================================================
# Affichage des tokens
# =============================================================================

def show_tokens_table(tokens: List[dict]):
    """Affiche la liste des tokens dans un tableau."""
    if not tokens:
        console.print("[yellow]Aucun token trouvé.[/yellow]")
        return

    table = Table(title=f"🔑 Tokens ({len(tokens)})", show_header=True)
    table.add_column("Client", style="cyan bold", no_wrap=True)
    table.add_column("Email", style="white", max_width=25)
    table.add_column("Hash (ID)", style="yellow", no_wrap=True)
    table.add_column("Permissions", style="magenta")
    table.add_column("Mémoires", style="green")
    table.add_column("Créé le", style="dim", width=12)
    table.add_column("Expire", style="dim", width=12)

    for t in tokens:
        perms = ", ".join(t.get("permissions", []))
        memories = t.get("memory_ids", [])
        mem_str = ", ".join(memories) if memories else "[dim]toutes[/dim]"
        created = (t.get("created_at") or "")[:10]
        expires = (t.get("expires_at") or "jamais")[:10]
        email = t.get("email") or "[dim]-[/dim]"
        token_hash = t.get("token_hash", t.get("token_hash_prefix", "?"))

        table.add_row(
            t.get("client_name", "?"),
            email,
            token_hash,
            perms,
            mem_str,
            created,
            expires,
        )

    console.print(table)
    console.print("[dim]💡 Copiez le Hash pour: token revoke <hash>, token grant <hash> ...[/dim]")


def show_token_created(result: dict):
    """Affiche le résultat de création d'un token."""
    email_line = f"\n[bold]Email:[/bold]       [white]{result['email']}[/white]" if result.get('email') else ""
    console.print(Panel.fit(
        f"[bold]Client:[/bold]      [cyan]{result.get('client_name', '?')}[/cyan]{email_line}\n"
        f"[bold]Token:[/bold]       [green bold]{result.get('token', '?')}[/green bold]\n"
        f"[bold]Permissions:[/bold] [magenta]{', '.join(result.get('permissions', []))}[/magenta]\n"
        f"[bold]Mémoires:[/bold]    {', '.join(result.get('memory_ids', [])) or '[dim]toutes[/dim]'}",
        title="🔑 Token créé",
        border_style="green",
    ))
    console.print("[yellow]⚠️  Conservez ce token précieusement, il ne sera plus affiché ![/yellow]")


def show_token_updated(result: dict):
    """Affiche le résultat d'une mise à jour de token."""
    prev = result.get("previous_memories", [])
    curr = result.get("current_memories", [])
    console.print(Panel.fit(
        f"[bold]Client:[/bold]      [cyan]{result.get('client_name', '?')}[/cyan]\n"
        f"[bold]Hash:[/bold]        [dim]{result.get('token_hash_prefix', '?')}[/dim]\n"
        f"[bold]Avant:[/bold]       {', '.join(prev) if prev else '[dim]toutes[/dim]'}\n"
        f"[bold]Après:[/bold]       {', '.join(curr) if curr else '[dim]toutes[/dim]'}",
        title="🔑 Token mis à jour",
        border_style="cyan",
    ))


def show_answer(answer: str, entities: list = None, source_documents: list = None):
    """Affiche une réponse Q&A avec les documents sources."""
    console.print(Panel.fit(
        Markdown(answer),
        title="💡 Réponse",
        border_style="green",
    ))

    # Documents sources
    if source_documents:
        console.print(f"\n[bold]📄 Documents sources ({len(source_documents)}):[/bold]")
        for doc in source_documents:
            if isinstance(doc, dict):
                console.print(f"  • [cyan]{doc.get('filename', '?')}[/cyan]  [dim]({doc.get('id', '?')[:8]}…)[/dim]")
            else:
                console.print(f"  • [cyan]{doc}[/cyan]")

    # Entités liées
    if entities:
        console.print(f"[dim]Entités liées: {', '.join(str(e) for e in entities)}[/dim]")
