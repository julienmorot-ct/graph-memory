# -*- coding: utf-8 -*-
"""
Shell interactif MCP Memory avec prompt_toolkit.

Fonctionnalités :
  - Autocomplétion des commandes (Tab)
  - Historique persistant (flèches haut/bas)
  - Édition avancée (Ctrl+A/E/W, etc.)
  - Commandes de navigation dans une mémoire

Commandes :
  health            État du serveur
  list              Lister les mémoires
  use <id>          Sélectionner une mémoire
  create <id> <o>   Créer une mémoire
  info              Résumé de la mémoire courante
  graph             Graphe complet (types, relations, docs)
  docs              Lister les documents
  ingest <path>     Ingérer un document
  ingestdir <path>  Ingérer un répertoire (récursif)
  deldoc <id>       Supprimer un document
  entities          Entités par type
  entity <nom>      Contexte d'une entité
  relations [TYPE]  Relations par type
  ask <question>    Poser une question
  check             Vérifier cohérence S3/graphe
  cleanup           Nettoyer orphelins S3
  ontologies        Lister les ontologies
  limit [N]         Voir/changer le limit
  delete [id]       Supprimer mémoire
  debug             Activer/désactiver le debug
  clear             Effacer l'écran
  help              Aide
  exit              Quitter
"""

import sys
import json
import asyncio
import os
import base64
from collections import Counter

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown

from .client import MCPClient
from .display import (
    show_memories_table, show_documents_table, show_graph_summary,
    show_ingest_result, show_error, show_success, show_warning,
    show_answer, show_entity_context, show_storage_check,
    show_cleanup_result, show_tokens_table, show_token_created,
    show_token_updated, console
)


# =============================================================================
# Autocomplétion prompt_toolkit
# =============================================================================

# Liste des commandes du shell
SHELL_COMMANDS = [
    "help", "health", "list", "use", "info", "graph", "docs",
    "entities", "entity", "relations", "ask", "check", "cleanup",
    "create", "ingest", "ingestdir", "deldoc", "ontologies",
    "tokens", "token-create", "token-revoke", "token-grant",
    "token-ungrant", "token-set",
    "limit", "delete", "debug", "clear", "exit", "quit",
]


def _get_completer():
    """Crée un completer pour prompt_toolkit."""
    try:
        from prompt_toolkit.completion import WordCompleter
        return WordCompleter(SHELL_COMMANDS, ignore_case=True)
    except ImportError:
        return None


def _get_history():
    """Crée un historique persistant pour prompt_toolkit."""
    try:
        from prompt_toolkit.history import FileHistory
        history_path = os.path.expanduser("~/.mcp_memory_history")
        return FileHistory(history_path)
    except ImportError:
        return None


def _prompt_input(prompt_text: str, completer=None, history=None) -> str:
    """
    Lit une ligne avec prompt_toolkit si disponible, sinon fallback input().

    Fonctionnalités :
      - Tab : autocomplétion des commandes
      - ↑/↓ : historique
      - Ctrl+A/E : début/fin de ligne
      - Ctrl+W : supprimer mot
      - Ctrl+C : annuler la ligne
    """
    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import HTML
        return pt_prompt(
            HTML(prompt_text),
            completer=completer,
            history=history,
            complete_while_typing=False,
        )
    except ImportError:
        # Fallback sans prompt_toolkit
        return input(prompt_text.replace("<b>", "").replace("</b>", ""))


# =============================================================================
# Résolution du memory_id
# =============================================================================

def _resolve_memory_id(candidate: str, known_ids: list) -> str:
    """
    Extrait le memory_id valide d'une saisie utilisateur.

    Gère les cas où l'utilisateur copie la ligne entière du tableau
    (ex: "JURIDIQUE – Corpus Juridique Cloud Temple" → "JURIDIQUE").
    """
    candidate = candidate.strip().strip('"').strip("'")

    # Essayer de couper avant un séparateur
    for sep in [" – ", " - ", "  "]:
        if sep in candidate:
            candidate = candidate.split(sep)[0].strip()
            break

    # Vérifier dans les IDs connus
    if candidate in known_ids:
        return candidate

    # Recherche partielle (case insensitive)
    for kid in known_ids:
        if kid.lower() == candidate.lower():
            return kid

    return candidate  # Retourner tel quel si pas trouvé


# =============================================================================
# Handlers de commandes
# =============================================================================

async def cmd_list(client: MCPClient, state: dict):
    """Liste les mémoires."""
    result = await client.list_memories()
    if result.get("status") == "ok":
        show_memories_table(result.get("memories", []), state.get("memory"))
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_use(client: MCPClient, state: dict, args: str):
    """Sélectionne une mémoire (avec validation)."""
    if not args:
        show_warning("Usage: use <memory_id>")
        return

    result = await client.list_memories()
    if result.get("status") != "ok":
        state["memory"] = args
        console.print(f"[green]✓[/green] Mémoire: [cyan]{args}[/cyan] (non validée)")
        return

    known_ids = [m["id"] for m in result.get("memories", [])]
    resolved = _resolve_memory_id(args, known_ids)

    if resolved in known_ids:
        state["memory"] = resolved
        mem_info = next((m for m in result["memories"] if m["id"] == resolved), {})
        console.print(
            f"[green]✓[/green] Mémoire: [cyan bold]{resolved}[/cyan bold]"
            f" ({mem_info.get('name', '')})"
        )
    else:
        show_error(f"Mémoire '{resolved}' non trouvée.")
        console.print(f"[dim]Disponibles: {', '.join(known_ids)}[/dim]")


async def cmd_info(client: MCPClient, state: dict):
    """Affiche les infos de la mémoire courante."""
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return

    result = await client.get_graph(mem)
    if result.get("status") == "ok":
        console.print(f"[bold]Mémoire:[/bold] [cyan]{mem}[/cyan]")
        console.print(f"  Entités:   [green]{result.get('node_count', 0)}[/green]")
        console.print(f"  Relations: [green]{result.get('edge_count', 0)}[/green]")
        console.print(f"  Documents: [green]{result.get('document_count', 0)}[/green]")
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_graph(client: MCPClient, state: dict, args: str):
    """Affiche le graphe complet de la mémoire."""
    mem = args or state.get("memory")
    if not mem:
        show_warning("Usage: graph [memory_id] ou 'use' d'abord")
        return

    result = await client.get_graph(mem)
    if result.get("status") == "ok":
        show_graph_summary(result, mem)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_docs(client: MCPClient, state: dict):
    """Liste les documents de la mémoire courante."""
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return

    result = await client.get_graph(mem)
    if result.get("status") == "ok":
        show_documents_table(result.get("documents", []), mem)
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_entities(client: MCPClient, state: dict):
    """Affiche les entités par type avec leurs documents sources."""
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return

    result = await client.get_graph(mem)
    if result.get("status") != "ok":
        show_error(result.get("message", "Erreur"))
        return

    nodes = [n for n in result.get("nodes", []) if n.get("node_type") == "entity"]
    if not nodes:
        show_warning("Aucune entité dans cette mémoire.")
        return

    # Construire un mapping entité → documents via les relations MENTIONS
    # Note: les edges doc→entité ont from="doc:UUID", les entity→entity ont from="nom"
    edges = result.get("edges", [])
    # Mapping avec les deux formats possibles: "UUID" et "doc:UUID"
    docs_by_id = {}
    for d in result.get("documents", []):
        did = d.get("id", "")
        fname = d.get("filename", "?")
        docs_by_id[did] = fname
        docs_by_id[f"doc:{did}"] = fname  # Format utilisé dans get_full_graph

    entity_docs = {}  # entity_label -> set of filenames
    for e in edges:
        if e.get("type") == "MENTIONS":
            from_id = e.get("from", "")
            to_label = e.get("to", "")
            # Vérifier si c'est un lien document→entité (from contient un ID de document)
            fname = docs_by_id.get(from_id, "")
            if fname:
                if to_label not in entity_docs:
                    entity_docs[to_label] = set()
                entity_docs[to_label].add(fname)

    from collections import defaultdict
    by_type = defaultdict(list)
    for n in nodes:
        by_type[n.get("type", "?")].append(n)

    for etype in sorted(by_type, key=lambda t: -len(by_type[t])):
        entities = by_type[etype]
        table = Table(
            title=f"[magenta]{etype}[/magenta] ({len(entities)})",
            show_header=True, show_lines=False
        )
        table.add_column("Nom", style="white")
        table.add_column("Description", style="dim", max_width=40)
        table.add_column("Document(s)", style="cyan")

        for e in entities:
            label = e.get("label", "?")
            doc_list = entity_docs.get(label, set())
            doc_str = ", ".join(sorted(doc_list)) if doc_list else "-"
            table.add_row(
                label[:40],
                (e.get("description", "") or "")[:40],
                doc_str,
            )
        console.print(table)


async def cmd_entity(client: MCPClient, state: dict, args: str):
    """Affiche le contexte d'une entité."""
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return
    if not args:
        show_warning("Usage: entity <nom de l'entité>")
        return

    result = await client.call_tool("memory_get_context", {
        "memory_id": mem, "entity_name": args, "depth": 1
    })
    if result.get("status") == "ok":
        show_entity_context(result)
    else:
        show_error(result.get("message", "Entité non trouvée"))


async def cmd_relations(client: MCPClient, state: dict, args: str = ""):
    """
    Affiche les relations. Sans argument : résumé par type.
    Avec un type en argument : détail de toutes les relations de ce type.
    
    Exemples :
        relations              → résumé par type
        relations MENTIONS     → toutes les relations MENTIONS
        relations HAS_AMOUNT   → toutes les relations HAS_AMOUNT
    """
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return

    result = await client.get_graph(mem)
    if result.get("status") != "ok":
        show_error(result.get("message", "Erreur"))
        return

    edges = result.get("edges", [])
    if not edges:
        show_warning("Aucune relation dans cette mémoire.")
        return

    type_filter = args.strip().upper() if args.strip() else None

    if type_filter:
        # --- Mode détaillé : toutes les relations d'un type ---
        filtered = [e for e in edges if e.get("type", "").upper() == type_filter]
        if not filtered:
            available = sorted(set(e.get("type", "?") for e in edges))
            show_error(f"Type '{type_filter}' non trouvé.")
            console.print(f"[dim]Types disponibles: {', '.join(available)}[/dim]")
            return

        table = Table(
            title=f"🔗 {type_filter} ({len(filtered)} relations)",
            show_header=True
        )
        table.add_column("De", style="white")
        table.add_column("→", style="dim", width=2)
        table.add_column("Vers", style="cyan")
        table.add_column("Description", style="dim", max_width=40)

        for e in filtered:
            table.add_row(
                e.get("from", "?")[:35],
                "→",
                e.get("to", "?")[:35],
                (e.get("description", "") or "")[:40],
            )
        console.print(table)
    else:
        # --- Mode résumé : types avec compteurs ---
        rel_types = Counter(e.get("type", "?") for e in edges)

        table = Table(title=f"🔗 Relations ({len(edges)} total)", show_header=True)
        table.add_column("Type", style="blue bold")
        table.add_column("Nombre", style="cyan", justify="right")
        table.add_column("Exemples", style="dim")

        for rtype, count in rel_types.most_common():
            examples = [e for e in edges if e.get("type") == rtype][:3]
            ex_str = ", ".join(
                f"{e.get('from', '?')} → {e.get('to', '?')}" for e in examples
            )
            table.add_row(rtype, str(count), ex_str[:60])

        console.print(table)
        console.print("[dim]Deepdive: relations <TYPE> (ex: relations HAS_DURATION)[/dim]")


async def cmd_ask(client: MCPClient, state: dict, args: str, debug: bool):
    """Pose une question sur la mémoire courante."""
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return
    if not args:
        show_warning("Usage: ask <votre question>")
        return

    limit = state.get("limit", 10)
    result = await client.call_tool("question_answer", {
        "memory_id": mem, "question": args, "limit": limit
    })

    if debug:
        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))

    if result.get("status") == "ok":
        show_answer(
            result.get("answer", ""),
            result.get("entities", []),
            result.get("source_documents", []),
        )
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_check(client: MCPClient, state: dict, args: str):
    """
    Vérifie la cohérence S3 / graphe.
    
    Sans argument : vérifie toutes les mémoires.
    Avec un memory_id : vérifie uniquement cette mémoire.
    """
    params = {}
    if args.strip():
        params["memory_id"] = args.strip()
    elif state.get("memory"):
        params["memory_id"] = state["memory"]
    
    console.print("[dim]🔍 Vérification S3 en cours...[/dim]")
    result = await client.call_tool("storage_check", params)
    show_storage_check(result)


async def cmd_cleanup(client: MCPClient, state: dict, force: bool = False):
    """
    Nettoie les fichiers orphelins sur S3.
    
    force=False : dry run (liste seulement).
    force=True : supprime réellement.
    """
    console.print("[dim]🧹 Analyse des orphelins S3...[/dim]")
    result = await client.call_tool("storage_cleanup", {"dry_run": not force})
    show_cleanup_result(result)


async def cmd_health(client: MCPClient, state: dict):
    """Vérifie l'état du serveur."""
    try:
        result = await client.list_memories()
        if result.get("status") == "ok":
            console.print(Panel.fit(
                f"[bold green]✅ Serveur OK[/bold green]\n\n"
                f"URL: [cyan]{client.base_url}[/cyan]\n"
                f"Mémoires: [green]{result.get('count', 0)}[/green]",
                title="🏥 État du serveur", border_style="green"
            ))
        else:
            show_error(f"Serveur répond mais erreur: {result.get('message')}")
    except Exception as e:
        show_error(f"Connexion impossible: {e}")


async def cmd_create(client: MCPClient, state: dict, args: str):
    """
    Crée une nouvelle mémoire.
    
    Usage: create <memory_id> <ontology> [nom] [description]
    Exemple: create JURIDIQUE legal "Corpus Juridique" "Documents contractuels"
    """
    if not args:
        show_warning("Usage: create <memory_id> <ontology> [nom] [description]")
        console.print("[dim]Exemple: create JURIDIQUE legal \"Corpus Juridique\"[/dim]")
        return

    parts = args.split(maxsplit=3)
    if len(parts) < 2:
        show_warning("Usage: create <memory_id> <ontology> [nom] [description]")
        return

    memory_id = parts[0]
    ontology = parts[1]
    name = parts[2].strip('"').strip("'") if len(parts) > 2 else memory_id
    description = parts[3].strip('"').strip("'") if len(parts) > 3 else ""

    result = await client.call_tool("memory_create", {
        "memory_id": memory_id,
        "name": name,
        "description": description,
        "ontology": ontology,
    })
    if result.get("status") in ("ok", "created"):
        show_success(f"Mémoire '{memory_id}' créée (ontologie: {result.get('ontology')})")
        state["memory"] = memory_id
        console.print(f"[green]✓[/green] Mémoire sélectionnée: [cyan bold]{memory_id}[/cyan bold]")
    else:
        show_error(result.get("message", str(result)))


async def cmd_ingest(client: MCPClient, state: dict, args: str):
    """
    Ingère un document dans la mémoire courante.
    
    Usage: ingest <chemin_fichier> [--force]
    """
    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>' avant d'ingérer")
        return
    if not args:
        show_warning("Usage: ingest <chemin_fichier> [--force]")
        return

    force = "--force" in args
    file_path = args.replace("--force", "").strip()

    if not os.path.isfile(file_path):
        show_error(f"Fichier non trouvé: {file_path}")
        return

    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    file_ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else '?'

    def _fmt_size(n):
        for u in ['B', 'KB', 'MB', 'GB']:
            if n < 1024:
                return f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} TB"

    # Affichage pré-vol
    console.print(Panel.fit(
        f"[bold]Fichier:[/bold]  [cyan]{filename}[/cyan]\n"
        f"[bold]Taille:[/bold]  [cyan]{_fmt_size(file_size)}[/cyan]  "
        f"[bold]Type:[/bold] [cyan]{file_ext}[/cyan]  "
        f"[bold]Mémoire:[/bold] [cyan]{mem}[/cyan]"
        + (f"\n[bold]Mode:[/bold]   [yellow]Force (ré-ingestion)[/yellow]" if force else ""),
        title="📥 Ingestion", border_style="blue",
    ))

    try:
        import time as _time
        from datetime import datetime, timezone
        from rich.progress import Progress, SpinnerColumn, TextColumn

        with open(file_path, "rb") as f:
            content_bytes = f.read()
        content_b64 = base64.b64encode(content_bytes).decode("utf-8")
        
        # Métadonnées enrichies
        source_path = os.path.abspath(file_path)
        mtime = os.path.getmtime(file_path)
        source_modified_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        t0 = _time.monotonic()

        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            TextColumn("[dim]{task.fields[elapsed]}[/dim]"),
            console=console, transient=True,
        ) as p:
            task = p.add_task(
                f"S3 → LLM → Neo4j → Qdrant",
                total=None, elapsed="",
            )
            
            import asyncio
            async def _update_timer():
                while True:
                    elapsed = _time.monotonic() - t0
                    m, s = divmod(int(elapsed), 60)
                    p.update(task, elapsed=f"⏱ {m:02d}:{s:02d}")
                    await asyncio.sleep(1)
            
            timer_task = asyncio.create_task(_update_timer())
            try:
                result = await client.call_tool("memory_ingest", {
                    "memory_id": mem,
                    "content_base64": content_b64,
                    "filename": filename,
                    "force": force,
                    "source_path": source_path,
                    "source_modified_at": source_modified_at,
                })
            finally:
                timer_task.cancel()
        
        elapsed = _time.monotonic() - t0

        if result.get("status") == "ok":
            result["_elapsed_seconds"] = round(elapsed, 1)
            show_ingest_result(result)
        elif result.get("status") == "already_exists":
            console.print(f"[yellow]⚠️ Déjà ingéré: {result.get('document_id')} (--force pour réingérer)[/yellow]")
        else:
            show_error(result.get("message", str(result)))
    except Exception as e:
        show_error(str(e))


async def cmd_ingestdir(client: MCPClient, state: dict, args: str):
    """
    Ingère un répertoire entier dans la mémoire courante (récursif).
    
    Usage: ingestdir <chemin> [--exclude PATTERN] [--confirm] [--force]
    Exemple: ingestdir ./MATIERE/JURIDIQUE --exclude *.tmp
    """
    import fnmatch
    from pathlib import Path
    from rich.prompt import Confirm

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".docx", ".pdf", ".csv"}

    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>' avant d'ingérer")
        return
    if not args:
        show_warning("Usage: ingestdir <chemin> [--exclude PATTERN] [--confirm] [--force]")
        return

    # Parser les options depuis la ligne de commande brute
    confirm_mode = "--confirm" in args
    force_mode = "--force" in args
    
    # Extraire les patterns d'exclusion
    exclude_patterns = []
    remaining = args
    while "--exclude" in remaining:
        idx = remaining.index("--exclude")
        after = remaining[idx + 9:].strip()
        parts = after.split(maxsplit=1)
        if parts:
            exclude_patterns.append(parts[0])
            remaining = remaining[:idx] + (parts[1] if len(parts) > 1 else "")
        else:
            remaining = remaining[:idx]
    
    # Nettoyer le chemin
    dir_path = remaining.replace("--confirm", "").replace("--force", "").strip()
    
    if not dir_path:
        show_warning("Usage: ingestdir <chemin> [--exclude PATTERN] [--confirm] [--force]")
        return
    
    if not os.path.isdir(dir_path):
        show_error(f"Répertoire non trouvé: {dir_path}")
        return

    # --- 1. Scanner ---
    console.print(f"[dim]📁 Scan de {dir_path}...[/dim]")
    all_files = []
    excluded_files = []
    unsupported_files = []

    for root, dirs, files in os.walk(dir_path):
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, dir_path)

            is_excluded = False
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(fname, pattern):
                    is_excluded = True
                    break
            if is_excluded:
                excluded_files.append(rel_path)
                continue

            ext = Path(fname).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                unsupported_files.append(rel_path)
                continue

            all_files.append({
                "path": fpath,
                "rel_path": rel_path,
                "filename": fname,
                "size": os.path.getsize(fpath),
            })

    if not all_files:
        show_warning(f"Aucun fichier supporté dans {dir_path}")
        if unsupported_files:
            console.print(f"[dim]{len(unsupported_files)} fichiers non supportés ignorés[/dim]")
        return

    # --- 2. Vérifier les doublons ---
    graph_result = await client.get_graph(mem)
    existing = set()
    if graph_result.get("status") == "ok":
        for d in graph_result.get("documents", []):
            existing.add(d.get("filename", ""))

    to_ingest = []
    already = []
    for f in all_files:
        if f["filename"] in existing and not force_mode:
            already.append(f)
        else:
            to_ingest.append(f)

    # --- 3. Résumé ---
    total_size = sum(f["size"] for f in to_ingest)
    console.print(Panel.fit(
        f"[bold]Répertoire:[/bold]  [cyan]{os.path.abspath(dir_path)}[/cyan]\n"
        f"[bold]Mémoire:[/bold]     [cyan]{mem}[/cyan]\n\n"
        f"[bold]Fichiers trouvés:[/bold]  [green]{len(all_files)}[/green]"
        + (f"  [yellow]Exclus: {len(excluded_files)}[/yellow]" if excluded_files else "")
        + (f"  [dim]Non supportés: {len(unsupported_files)}[/dim]" if unsupported_files else "")
        + (f"  [yellow]Déjà ingérés: {len(already)}[/yellow]" if already else "")
        + f"\n[bold]À ingérer:[/bold]      [green bold]{len(to_ingest)}[/green bold]",
        title="📁 Import en masse",
        border_style="blue",
    ))

    if not to_ingest:
        show_success("Tous les fichiers sont déjà ingérés !")
        return

    # Liste
    for i, f in enumerate(to_ingest, 1):
        console.print(f"  [dim]{i}.[/dim] {f['rel_path']}")

    # --- 4. Ingestion ---
    ingested = 0
    skipped = 0
    errors = 0

    for i, f in enumerate(to_ingest, 1):
        if confirm_mode:
            if not Confirm.ask(f"[{i}/{len(to_ingest)}] Ingérer [cyan]{f['rel_path']}[/cyan] ?"):
                skipped += 1
                continue

        console.print(f"[dim][{i}/{len(to_ingest)}] 📥 {f['filename']}...[/dim]")
        try:
            from datetime import datetime, timezone

            with open(f["path"], "rb") as fh:
                content_bytes = fh.read()
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            
            # Métadonnées enrichies : chemin relatif dans l'arborescence + date de modification
            mtime = os.path.getmtime(f["path"])
            source_modified_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

            result = await client.call_tool("memory_ingest", {
                "memory_id": mem,
                "content_base64": content_b64,
                "filename": f["filename"],
                "force": force_mode,
                "source_path": f["rel_path"],
                "source_modified_at": source_modified_at,
            })

            if result.get("status") == "ok":
                e_total = result.get("entities_created", 0) + result.get("entities_merged", 0)
                r_total = result.get("relations_created", 0) + result.get("relations_merged", 0)
                console.print(f"  [green]✅[/green] {f['filename']}: {e_total} entités, {r_total} relations")
                ingested += 1
            elif result.get("status") == "already_exists":
                console.print(f"  [yellow]⏭️[/yellow] {f['filename']}: déjà ingéré")
                skipped += 1
            else:
                console.print(f"  [red]❌[/red] {f['filename']}: {result.get('message', '?')}")
                errors += 1
        except Exception as e:
            console.print(f"  [red]❌[/red] {f['filename']}: {e}")
            errors += 1

    # --- 5. Résumé final ---
    console.print(Panel.fit(
        f"[green]✅ Ingérés: {ingested}[/green]  "
        f"[yellow]⏭️ Skippés: {skipped}[/yellow]  "
        f"[red]❌ Erreurs: {errors}[/red]",
        title="📊 Résultat",
        border_style="green" if errors == 0 else "yellow",
    ))


async def cmd_deldoc(client: MCPClient, state: dict, args: str):
    """
    Supprime un document de la mémoire courante.
    
    Usage: deldoc <document_id>
    """
    from rich.prompt import Confirm

    mem = state.get("memory")
    if not mem:
        show_warning("Sélectionnez une mémoire avec 'use <id>'")
        return
    if not args:
        show_warning("Usage: deldoc <document_id>")
        console.print("[dim]Utilisez 'docs' pour voir les IDs des documents.[/dim]")
        return

    doc_id = args.strip()
    if not Confirm.ask(f"[yellow]Supprimer le document '{doc_id}' de '{mem}' ?[/yellow]"):
        console.print("[dim]Annulé.[/dim]")
        return

    result = await client.call_tool("document_delete", {
        "memory_id": mem, "document_id": doc_id
    })
    if result.get("status") in ("ok", "deleted"):
        show_success(f"Document supprimé ({result.get('entities_deleted', 0)} entités orphelines nettoyées)")
    else:
        show_error(result.get("message", str(result)))


async def cmd_ontologies(client: MCPClient, state: dict):
    """Liste les ontologies disponibles."""
    result = await client.call_tool("ontology_list", {})
    if result.get("status") == "ok":
        ontologies = result.get("ontologies", [])
        table = Table(title=f"📖 Ontologies ({len(ontologies)})")
        table.add_column("Nom", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Types", style="dim")
        for o in ontologies:
            table.add_row(
                o.get("name", ""),
                o.get("description", "")[:50],
                f"{o.get('entity_types_count', 0)} entités, {o.get('relation_types_count', 0)} relations"
            )
        console.print(table)
    else:
        show_error(result.get("message", "Erreur"))


# =============================================================================
# Handlers token
# =============================================================================

async def cmd_tokens(client: MCPClient, state: dict):
    """Liste tous les tokens actifs."""
    result = await client.call_tool("admin_list_tokens", {})
    if result.get("status") == "ok":
        show_tokens_table(result.get("tokens", []))
    else:
        show_error(result.get("message", "Erreur"))


async def cmd_token_create(client: MCPClient, state: dict, args: str):
    """
    Crée un token pour un client.

    Usage: token-create <client_name> [perms] [memories] [--email addr]
    Exemples:
        token-create quoteflow
        token-create quoteflow --email user@example.com
        token-create quoteflow read,write JURIDIQUE,CLOUD --email user@example.com
        token-create admin-bot admin
    """
    if not args:
        show_warning("Usage: token-create <client_name> [permissions] [memories] [--email addr]")
        console.print("[dim]Exemples:[/dim]")
        console.print("[dim]  token-create quoteflow[/dim]")
        console.print("[dim]  token-create quoteflow --email user@example.com[/dim]")
        console.print("[dim]  token-create quoteflow read,write JURIDIQUE,CLOUD --email user@example.com[/dim]")
        return

    # Extraire --email si présent
    email = None
    if "--email" in args:
        idx = args.index("--email")
        after = args[idx + 7:].strip()
        email_parts = after.split(maxsplit=1)
        if email_parts:
            email = email_parts[0]
            # Reconstruire args sans --email et sa valeur
            args = args[:idx].strip()
            if len(email_parts) > 1:
                args += " " + email_parts[1]
            args = args.strip()

    parts = args.split() if args else []
    if not parts:
        show_warning("Usage: token-create <client_name> [permissions] [memories] [--email addr]")
        return

    client_name = parts[0]
    perms = parts[1].split(",") if len(parts) > 1 else ["read", "write"]
    memories = parts[2].split(",") if len(parts) > 2 else []

    params = {
        "client_name": client_name,
        "permissions": perms,
        "memory_ids": memories,
    }
    if email:
        params["email"] = email

    result = await client.call_tool("admin_create_token", params)
    if result.get("status") == "ok":
        show_token_created(result)
    else:
        show_error(result.get("message", str(result)))


async def cmd_token_revoke(client: MCPClient, state: dict, args: str):
    """Révoque un token par préfixe de hash."""
    from rich.prompt import Confirm

    if not args:
        show_warning("Usage: token-revoke <hash_prefix>")
        console.print("[dim]Utilisez 'tokens' pour voir les préfixes de hash.[/dim]")
        return

    hash_prefix = args.strip()
    if not Confirm.ask(f"[yellow]Révoquer le token '{hash_prefix}...' ?[/yellow]"):
        console.print("[dim]Annulé.[/dim]")
        return

    result = await client.call_tool("admin_revoke_token", {"token_hash_prefix": hash_prefix})
    if result.get("status") == "ok":
        show_success(result.get("message", "Token révoqué"))
    else:
        show_error(result.get("message", str(result)))


async def cmd_token_grant(client: MCPClient, state: dict, args: str):
    """
    Ajoute des mémoires à un token.

    Usage: token-grant <hash_prefix> <memory1> [memory2] ...
    """
    if not args:
        show_warning("Usage: token-grant <hash_prefix> <memory1> [memory2] ...")
        return

    parts = args.split()
    if len(parts) < 2:
        show_warning("Usage: token-grant <hash_prefix> <memory1> [memory2] ...")
        return

    hash_prefix = parts[0]
    memories = parts[1:]

    result = await client.call_tool("admin_update_token", {
        "token_hash_prefix": hash_prefix,
        "add_memories": memories,
    })
    if result.get("status") == "ok":
        show_token_updated(result)
    else:
        show_error(result.get("message", str(result)))


async def cmd_token_ungrant(client: MCPClient, state: dict, args: str):
    """
    Retire des mémoires d'un token.

    Usage: token-ungrant <hash_prefix> <memory1> [memory2] ...
    """
    if not args:
        show_warning("Usage: token-ungrant <hash_prefix> <memory1> [memory2] ...")
        return

    parts = args.split()
    if len(parts) < 2:
        show_warning("Usage: token-ungrant <hash_prefix> <memory1> [memory2] ...")
        return

    hash_prefix = parts[0]
    memories = parts[1:]

    result = await client.call_tool("admin_update_token", {
        "token_hash_prefix": hash_prefix,
        "remove_memories": memories,
    })
    if result.get("status") == "ok":
        show_token_updated(result)
    else:
        show_error(result.get("message", str(result)))


async def cmd_token_set(client: MCPClient, state: dict, args: str):
    """
    Remplace la liste complète des mémoires d'un token.

    Usage: token-set <hash_prefix> [memory1] [memory2] ...
    Sans mémoire = accès à TOUTES les mémoires.
    """
    if not args:
        show_warning("Usage: token-set <hash_prefix> [memory1] [memory2] ...")
        console.print("[dim]Sans mémoire = accès à toutes les mémoires[/dim]")
        return

    parts = args.split()
    hash_prefix = parts[0]
    memories = parts[1:] if len(parts) > 1 else []

    result = await client.call_tool("admin_update_token", {
        "token_hash_prefix": hash_prefix,
        "set_memories": memories,
    })
    if result.get("status") == "ok":
        show_token_updated(result)
    else:
        show_error(result.get("message", str(result)))


# =============================================================================
# Handlers divers
# =============================================================================

async def cmd_delete(client: MCPClient, state: dict, args: str):
    """Supprime une mémoire ou un document."""
    from rich.prompt import Confirm

    mem = args or state.get("memory")
    if not mem:
        show_warning("Usage: delete <memory_id>")
        return

    if Confirm.ask(f"[yellow]Supprimer la mémoire '{mem}' ?[/yellow]"):
        result = await client.call_tool("memory_delete", {"memory_id": mem})
        if result.get("status") in ("ok", "deleted"):
            show_success(f"Mémoire '{mem}' supprimée")
            if mem == state.get("memory"):
                state["memory"] = None
        else:
            show_error(result.get("message", str(result)))


# =============================================================================
# Boucle principale du shell
# =============================================================================

def run_shell(url: str, token: str):
    """Point d'entrée du shell interactif."""

    console.print(Panel.fit(
        "[bold cyan]🧠 MCP Memory Shell[/bold cyan]\n\n"
        "Tab : autocomplétion  •  ↑↓ : historique  •  Ctrl+C : annuler\n"
        "Tapez [green]help[/green] pour les commandes, [yellow]exit[/yellow] pour quitter.",
        border_style="cyan",
    ))

    client = MCPClient(url, token)
    state = {"memory": None, "debug": False, "limit": 10}

    completer = _get_completer()
    history = _get_history()

    # Table d'aide (organisée par catégorie)
    HELP = {
        # --- Serveur ---
        "health":       "État du serveur (URL, nb mémoires)",
        # --- Mémoires ---
        "list":         "Lister les mémoires",
        "use <id>":     "Sélectionner une mémoire",
        "create <id> <onto>": "Créer une mémoire (ex: create LEGAL legal)",
        "info":         "Résumé de la mémoire courante",
        "graph":        "Graphe complet (types, relations, documents)",
        "delete":       "Supprimer la mémoire courante (+ S3)",
        # --- Documents ---
        "docs":         "Lister les documents",
        "ingest <path>":"Ingérer un fichier (--force pour réingérer)",
        "ingestdir <p>":"Ingérer un répertoire (--exclude, --confirm, --force)",
        "deldoc <id>":  "Supprimer un document",
        # --- Exploration ---
        "entities":     "Entités par type (avec descriptions)",
        "entity <n>":   "Contexte d'une entité (relations, documents, voisins)",
        "relations":    "Relations par type (avec exemples)",
        "ask <q>":      "Poser une question",
        # --- Stockage ---
        "check":        "Vérifier cohérence S3/graphe (docs accessibles, orphelins)",
        "cleanup":      "Lister les orphelins S3 (--force pour supprimer)",
        # --- Ontologies ---
        "ontologies":   "Lister les ontologies disponibles",
        # --- Tokens ---
        "tokens":           "Lister les tokens actifs",
        "token-create <c>": "Créer un token (ex: token-create quoteflow read,write JURIDIQUE)",
        "token-revoke <h>": "Révoquer un token (par préfixe de hash)",
        "token-grant <h> <m>":  "Autoriser un token à accéder à des mémoires",
        "token-ungrant <h> <m>":"Retirer l'accès d'un token à des mémoires",
        "token-set <h> [m]":    "Remplacer les mémoires d'un token (vide=toutes)",
        # --- Config ---
        "limit [N]":    "Voir/changer le limit de recherche (défaut: 10)",
        "debug":        "Activer/désactiver le debug",
        "clear":        "Effacer l'écran",
        "help":         "Afficher cette aide",
        "exit":         "Quitter",
    }

    def show_help():
        table = Table(title="📖 Commandes", show_header=True)
        table.add_column("Commande", style="cyan")
        table.add_column("Description", style="white")
        for cmd, desc in HELP.items():
            table.add_row(cmd, desc)
        console.print(table)

    # Boucle principale
    while True:
        try:
            mem_label = state["memory"] or "no memory"
            prompt_text = f"\n🧠 <b>{mem_label}</b>: "

            cmd = _prompt_input(prompt_text, completer=completer, history=history)
            if not cmd.strip():
                continue

            parts = cmd.strip().split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            # Dispatch
            if command in ("exit", "quit", "q"):
                console.print("[dim]Au revoir! 👋[/dim]")
                break

            elif command == "help":
                show_help()

            elif command == "debug":
                state["debug"] = not state["debug"]
                status = "[green]ACTIVÉ[/green]" if state["debug"] else "[dim]désactivé[/dim]"
                console.print(f"🔍 Debug: {status}")

            elif command == "clear":
                console.clear()

            elif command == "list":
                asyncio.run(cmd_list(client, state))

            elif command == "use":
                asyncio.run(cmd_use(client, state, args))

            elif command == "info":
                asyncio.run(cmd_info(client, state))

            elif command == "graph":
                asyncio.run(cmd_graph(client, state, args))

            elif command == "docs":
                asyncio.run(cmd_docs(client, state))

            elif command == "entities":
                asyncio.run(cmd_entities(client, state))

            elif command == "entity":
                asyncio.run(cmd_entity(client, state, args))

            elif command == "relations":
                asyncio.run(cmd_relations(client, state, args))

            elif command == "ask":
                asyncio.run(cmd_ask(client, state, args, state["debug"]))

            elif command == "limit":
                if args.strip():
                    try:
                        new_limit = int(args.strip())
                        if new_limit < 1:
                            raise ValueError
                        state["limit"] = new_limit
                        console.print(f"[green]✓[/green] Limit: [cyan]{new_limit}[/cyan] entités par recherche")
                    except ValueError:
                        show_error("Usage: limit <nombre> (ex: limit 20)")
                else:
                    console.print(f"Limit actuel: [cyan]{state['limit']}[/cyan] entités par recherche")

            elif command == "check":
                asyncio.run(cmd_check(client, state, args))

            elif command == "cleanup":
                force = "--force" in args.lower() if args else False
                if force:
                    from rich.prompt import Confirm
                    if not Confirm.ask("[yellow]⚠️ Supprimer les fichiers orphelins S3 ?[/yellow]"):
                        console.print("[dim]Annulé.[/dim]")
                        continue
                asyncio.run(cmd_cleanup(client, state, force=force))

            elif command == "delete":
                asyncio.run(cmd_delete(client, state, args))

            elif command == "health":
                asyncio.run(cmd_health(client, state))

            elif command == "create":
                asyncio.run(cmd_create(client, state, args))

            elif command == "ingest":
                asyncio.run(cmd_ingest(client, state, args))

            elif command == "ingestdir":
                asyncio.run(cmd_ingestdir(client, state, args))

            elif command == "deldoc":
                asyncio.run(cmd_deldoc(client, state, args))

            elif command == "ontologies":
                asyncio.run(cmd_ontologies(client, state))

            # --- Token commands ---
            elif command == "tokens":
                asyncio.run(cmd_tokens(client, state))

            elif command == "token-create":
                asyncio.run(cmd_token_create(client, state, args))

            elif command == "token-revoke":
                asyncio.run(cmd_token_revoke(client, state, args))

            elif command == "token-grant":
                asyncio.run(cmd_token_grant(client, state, args))

            elif command == "token-ungrant":
                asyncio.run(cmd_token_ungrant(client, state, args))

            elif command == "token-set":
                asyncio.run(cmd_token_set(client, state, args))

            else:
                show_error(f"Commande inconnue: '{command}'. Tapez 'help'.")

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — tapez 'exit' pour quitter[/dim]")
        except EOFError:
            console.print("\n[dim]Au revoir! 👋[/dim]")
            break
        except Exception as e:
            show_error(str(e))
