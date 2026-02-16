# -*- coding: utf-8 -*-
"""
Commandes Click pour la CLI MCP Memory.

Commandes disponibles :
  - health            : Vérifier l'état du serveur
  - memory list       : Lister les mémoires
  - memory create     : Créer une mémoire
  - memory delete     : Supprimer une mémoire
  - memory graph      : Afficher le graphe
  - memory info       : Résumé d'une mémoire (stats)
  - memory entities   : Entités par type
  - memory entity     : Contexte d'une entité
  - memory relations  : Relations par type
  - document ingest/ingest-dir/list/delete
  - storage check     : Vérifier cohérence S3/graphe
  - storage cleanup   : Nettoyer les orphelins S3
  - ontologies        : Lister les ontologies
  - ask               : Poser une question
  - shell             : Mode interactif
"""

import os
import sys
import json
import asyncio
import base64

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.syntax import Syntax

from .client import MCPClient
from . import BASE_URL, TOKEN
from .display import (
    show_memories_table, show_documents_table, show_graph_summary,
    show_ingest_result, show_error, show_success, show_warning,
    show_answer, show_query_result, show_entity_context, show_storage_check,
    show_cleanup_result, show_tokens_table, show_token_created,
    show_token_updated, console
)

# =============================================================================
# Groupe principal
# =============================================================================

@click.group(invoke_without_command=True)
@click.option("--url", envvar=["MCP_URL", "MCP_SERVER_URL"], default=BASE_URL, help="URL du serveur MCP")
@click.option("--token", envvar=["MCP_TOKEN", "ADMIN_BOOTSTRAP_KEY"], default=TOKEN, help="Token d'authentification")
@click.pass_context
def cli(ctx, url, token):
    """🧠 MCP Memory CLI - Pilotez votre serveur MCP Memory.

    \b
    Exemples:
      mcp-cli health              # État du serveur
      mcp-cli memory list         # Lister les mémoires
      mcp-cli memory graph ID     # Graphe d'une mémoire
      mcp-cli shell               # Mode interactif
    """
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["token"] = token
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# =============================================================================
# Health
# =============================================================================

@cli.command()
@click.pass_context
def health(ctx):
    """🏥 Vérifier l'état du serveur MCP."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.list_memories()
            if result.get("status") == "ok":
                from rich.panel import Panel
                console.print(Panel.fit(
                    f"[bold green]✅ Serveur OK[/bold green]\n\n"
                    f"URL: [cyan]{ctx.obj['url']}[/cyan]\n"
                    f"Mémoires: [green]{result.get('count', 0)}[/green]",
                    title="🏥 État du serveur", border_style="green"
                ))
            else:
                show_error(f"Serveur répond mais erreur: {result.get('message')}")
        except Exception as e:
            show_error(f"Connexion impossible: {e}")
    asyncio.run(_run())


# =============================================================================
# Memory
# =============================================================================

@cli.group()
def memory():
    """📚 Gérer les mémoires."""
    pass


@memory.command("list")
@click.pass_context
def memory_list(ctx):
    """📋 Lister toutes les mémoires."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.list_memories()
            if result.get("status") == "ok":
                show_memories_table(result.get("memories", []))
            else:
                show_error(result.get("message", "Erreur inconnue"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("create")
@click.argument("memory_id")
@click.option("--name", "-n", default=None, help="Nom de la mémoire")
@click.option("--description", "-d", default=None, help="Description")
@click.option("--ontology", "-o", required=True, help="Ontologie (OBLIGATOIRE)")
@click.pass_context
def memory_create(ctx, memory_id, name, description, ontology):
    """➕ Créer une nouvelle mémoire."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("memory_create", {
                "memory_id": memory_id,
                "name": name or memory_id,
                "description": description or "",
                "ontology": ontology,
            })
            if result.get("status") in ("ok", "created"):
                show_success(f"Mémoire '{memory_id}' créée (ontologie: {result.get('ontology')})")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("delete")
@click.argument("memory_id")
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def memory_delete(ctx, memory_id, force):
    """🗑️  Supprimer une mémoire."""
    async def _run():
        if not force and not Confirm.ask(f"[yellow]Supprimer '{memory_id}' ?[/yellow]"):
            console.print("[dim]Annulé.[/dim]")
            return
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("memory_delete", {"memory_id": memory_id})
            if result.get("status") in ("ok", "deleted"):
                show_success(f"Mémoire '{memory_id}' supprimée!")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("graph")
@click.argument("memory_id")
@click.option("--format", "-f", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def memory_graph(ctx, memory_id, format):
    """📊 Afficher le graphe d'une mémoire."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.get_graph(memory_id)
            if result.get("status") != "ok":
                show_error(result.get("message", "Erreur"))
                return
            if format == "json":
                console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
            else:
                show_graph_summary(result, memory_id)
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("info")
@click.argument("memory_id")
@click.pass_context
def memory_info(ctx, memory_id):
    """ℹ️  Résumé d'une mémoire (entités, relations, documents)."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.get_graph(memory_id)
            if result.get("status") == "ok":
                from rich.panel import Panel
                nodes = result.get("nodes", [])
                edges = result.get("edges", [])
                docs = result.get("documents", [])
                entity_nodes = [n for n in nodes if n.get("node_type") == "entity"]
                non_mention = [e for e in edges if e.get("type") != "MENTIONS"]
                console.print(Panel.fit(
                    f"[bold]Mémoire:[/bold]   [cyan]{memory_id}[/cyan]\n"
                    f"[bold]Entités:[/bold]   [green]{len(entity_nodes)}[/green]\n"
                    f"[bold]Relations:[/bold] [green]{len(non_mention)}[/green]\n"
                    f"[bold]MENTIONS:[/bold]  [dim]{len(edges) - len(non_mention)}[/dim]\n"
                    f"[bold]Documents:[/bold] [green]{len(docs)}[/green]",
                    title=f"ℹ️  Info: {memory_id}",
                    border_style="cyan",
                ))
            else:
                show_error(result.get("message", "Erreur"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("entities")
@click.argument("memory_id")
@click.option("--format", "-f", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def memory_entities(ctx, memory_id, format):
    """📦 Lister les entités par type (avec documents sources)."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.get_graph(memory_id)
            if result.get("status") != "ok":
                show_error(result.get("message", "Erreur"))
                return

            nodes = [n for n in result.get("nodes", []) if n.get("node_type") == "entity"]
            if not nodes:
                show_warning("Aucune entité dans cette mémoire.")
                return

            if format == "json":
                console.print(Syntax(json.dumps(nodes, indent=2, ensure_ascii=False), "json"))
                return

            # Mapping entité → documents via MENTIONS
            edges = result.get("edges", [])
            docs_by_id = {}
            for d in result.get("documents", []):
                did = d.get("id", "")
                fname = d.get("filename", "?")
                docs_by_id[did] = fname
                docs_by_id[f"doc:{did}"] = fname

            entity_docs = {}
            for e in edges:
                if e.get("type") == "MENTIONS":
                    from_id = e.get("from", "")
                    to_label = e.get("to", "")
                    fname = docs_by_id.get(from_id, "")
                    if fname:
                        entity_docs.setdefault(to_label, set()).add(fname)

            from collections import defaultdict
            from rich.table import Table
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

                for ent in entities:
                    label = ent.get("label", "?")
                    doc_list = entity_docs.get(label, set())
                    doc_str = ", ".join(sorted(doc_list)) if doc_list else "-"
                    table.add_row(
                        label[:40],
                        (ent.get("description", "") or "")[:40],
                        doc_str,
                    )
                console.print(table)
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("entity")
@click.argument("memory_id")
@click.argument("entity_name")
@click.option("--depth", default=1, help="Profondeur de traversée (défaut: 1)")
@click.pass_context
def memory_entity(ctx, memory_id, entity_name, depth):
    """🔍 Contexte d'une entité (relations, documents, voisins)."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("memory_get_context", {
                "memory_id": memory_id,
                "entity_name": entity_name,
                "depth": depth,
            })
            if result.get("status") == "ok":
                show_entity_context(result)
            else:
                show_error(result.get("message", "Entité non trouvée"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@memory.command("relations")
@click.argument("memory_id")
@click.option("--type", "-t", "rel_type", default=None, help="Filtrer par type de relation")
@click.option("--format", "-f", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def memory_relations(ctx, memory_id, rel_type, format):
    """🔗 Relations par type (résumé ou détail avec --type)."""
    async def _run():
        try:
            from collections import Counter
            from rich.table import Table

            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.get_graph(memory_id)
            if result.get("status") != "ok":
                show_error(result.get("message", "Erreur"))
                return

            edges = result.get("edges", [])
            if not edges:
                show_warning("Aucune relation dans cette mémoire.")
                return

            if format == "json":
                data = edges if not rel_type else [
                    e for e in edges if e.get("type", "").upper() == rel_type.upper()
                ]
                console.print(Syntax(json.dumps(data, indent=2, ensure_ascii=False), "json"))
                return

            if rel_type:
                # Mode détaillé : toutes les relations d'un type
                filtered = [e for e in edges if e.get("type", "").upper() == rel_type.upper()]
                if not filtered:
                    available = sorted(set(e.get("type", "?") for e in edges))
                    show_error(f"Type '{rel_type}' non trouvé.")
                    console.print(f"[dim]Types disponibles: {', '.join(available)}[/dim]")
                    return

                table = Table(
                    title=f"🔗 {rel_type.upper()} ({len(filtered)} relations)",
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
                # Mode résumé : compteurs par type
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
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Storage (check / cleanup)
# =============================================================================

@cli.group()
def storage():
    """💾 Vérification et nettoyage du stockage S3."""
    pass


@storage.command("check")
@click.argument("memory_id", required=False, default=None)
@click.pass_context
def storage_check(ctx, memory_id):
    """🔍 Vérifier la cohérence S3/graphe (docs accessibles, orphelins)."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            params = {}
            if memory_id:
                params["memory_id"] = memory_id
            console.print("[dim]🔍 Vérification S3 en cours...[/dim]")
            result = await client.call_tool("storage_check", params)
            show_storage_check(result)
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@storage.command("cleanup")
@click.option("--force", "-f", is_flag=True, help="Supprimer réellement (sinon dry run)")
@click.pass_context
def storage_cleanup(ctx, force):
    """🧹 Nettoyer les fichiers orphelins sur S3 (dry run par défaut)."""
    async def _run():
        try:
            if force and not Confirm.ask("[yellow]⚠️ Supprimer les fichiers orphelins S3 ?[/yellow]"):
                console.print("[dim]Annulé.[/dim]")
                return
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            console.print("[dim]🧹 Analyse des orphelins S3...[/dim]")
            result = await client.call_tool("storage_cleanup", {"dry_run": not force})
            show_cleanup_result(result)
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Document
# =============================================================================

@cli.group()
def document():
    """📄 Gérer les documents."""
    pass


@document.command("ingest")
@click.argument("memory_id")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--force", "-f", is_flag=True, help="Forcer la ré-ingestion")
@click.option("--source-path", default=None, help="Chemin source d'origine (défaut: chemin du fichier)")
@click.pass_context
def document_ingest(ctx, memory_id, file_path, force, source_path):
    """📥 Ingérer un document dans une mémoire."""
    async def _run():
        try:
            import time as _time
            from datetime import datetime, timezone
            from rich.live import Live
            from rich.table import Table
            from rich.panel import Panel

            with open(file_path, "rb") as f:
                content_bytes = f.read()
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            filename = os.path.basename(file_path)
            file_size = len(content_bytes)
            file_ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else '?'
            
            # Affichage pré-vol
            console.print(Panel.fit(
                f"[bold]Fichier:[/bold]  [cyan]{filename}[/cyan]\n"
                f"[bold]Taille:[/bold]  [cyan]{_format_size_simple(file_size)}[/cyan]  "
                f"[bold]Type:[/bold] [cyan]{file_ext}[/cyan]  "
                f"[bold]Mémoire:[/bold] [cyan]{memory_id}[/cyan]"
                + (f"\n[bold]Mode:[/bold]   [yellow]Force (ré-ingestion)[/yellow]" if force else ""),
                title="📥 Ingestion", border_style="blue",
            ))
            
            # Métadonnées enrichies
            effective_source_path = source_path or os.path.abspath(file_path)
            mtime = os.path.getmtime(file_path)
            source_modified_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            
            t0 = _time.monotonic()
            import asyncio
            import re as _re
            
            # État de progression parsé depuis les messages serveur
            _progress_state = {
                "phase": "init",          # init, upload, extract_text, extraction, neo4j, chunking, embedding, qdrant, done
                "phase_label": "⏳ Connexion...",
                "extraction_current": 0,
                "extraction_total": 0,
                "embedding_current": 0,
                "embedding_total": 0,
                "entities": 0,
                "relations": 0,
                "chunks_rag": 0,
                "last_msg": "",
            }
            
            def _make_bar(current, total, width=20):
                """Génère une barre de progression ASCII."""
                if total <= 0:
                    return ""
                pct = min(current / total, 1.0)
                filled = int(width * pct)
                bar = "█" * filled + "░" * (width - filled)
                return f"{bar} {pct*100:.0f}%"
            
            async def _on_progress(msg: str):
                """Parse les messages serveur et met à jour l'état de progression."""
                st = _progress_state
                st["last_msg"] = msg
                
                # Phase S3
                if "Upload S3" in msg and "terminé" not in msg:
                    st["phase"] = "upload"
                    st["phase_label"] = "📤 Upload S3"
                elif "Upload S3 terminé" in msg:
                    st["phase_label"] = "✅ Upload S3"
                
                # Phase extraction texte
                elif "Extraction texte" in msg:
                    st["phase"] = "extract_text"
                    st["phase_label"] = "📄 Extraction texte"
                elif "Texte extrait" in msg:
                    st["phase_label"] = "✅ Texte extrait"
                
                # Phase extraction LLM
                elif "Extraction LLM:" in msg:
                    m = _re.search(r'(\d+)\s*chunks?\s*\(', msg)
                    if m:
                        st["extraction_total"] = int(m.group(1))
                    st["phase"] = "extraction"
                    st["phase_label"] = "🔍 Extraction LLM"
                    st["extraction_current"] = 0
                elif "Chunk " in msg and "terminé" in msg:
                    m = _re.search(r'Chunk\s+(\d+)/(\d+)', msg)
                    if m:
                        st["extraction_current"] = int(m.group(1))
                        st["extraction_total"] = int(m.group(2))
                    # Extraire cumul entités/relations
                    m2 = _re.search(r'cumul:\s*(\d+)E\s*(\d+)R', msg)
                    if m2:
                        st["entities"] = int(m2.group(1))
                        st["relations"] = int(m2.group(2))
                elif "Extraction terminée" in msg:
                    m = _re.search(r'(\d+)\s*entités.*?(\d+)\s*relations', msg)
                    if m:
                        st["entities"] = int(m.group(1))
                        st["relations"] = int(m.group(2))
                    st["extraction_current"] = st["extraction_total"]
                    st["phase_label"] = "✅ Extraction LLM"
                
                # Phase Neo4j
                elif "Stockage dans le graphe" in msg:
                    st["phase"] = "neo4j"
                    st["phase_label"] = "📊 Stockage Neo4j"
                
                # Phase RAG : chunking
                elif "Chunking sémantique" in msg:
                    st["phase"] = "chunking"
                    st["phase_label"] = "🧩 Chunking RAG"
                elif "Chunking terminé" in msg:
                    m = _re.search(r'(\d+)\s*chunks', msg)
                    if m:
                        st["chunks_rag"] = int(m.group(1))
                    st["phase_label"] = f"✅ {st['chunks_rag']} chunks RAG"
                
                # Phase RAG : embedding
                elif "Embedding batch" in msg:
                    st["phase"] = "embedding"
                    m = _re.search(r'batch\s+(\d+)/(\d+)', msg)
                    if m:
                        st["embedding_current"] = int(m.group(1)) - 1  # en cours, pas terminé
                        st["embedding_total"] = int(m.group(2))
                    st["phase_label"] = "🔢 Embedding"
                elif "Batch " in msg and "OK" in msg:
                    m = _re.search(r'Batch\s+(\d+)/(\d+)', msg)
                    if m:
                        st["embedding_current"] = int(m.group(1))
                        st["embedding_total"] = int(m.group(2))
                
                # Phase Qdrant stockage
                elif "Stockage Qdrant" in msg:
                    st["phase"] = "qdrant"
                    st["phase_label"] = "📦 Stockage Qdrant"
                elif "RAG:" in msg and "chunks vectorisés" in msg:
                    st["embedding_current"] = st["embedding_total"]
                    st["phase_label"] = "✅ RAG vectoriel"
                
                # Terminé
                elif "Ingestion terminée" in msg:
                    st["phase"] = "done"
                    st["phase_label"] = "🏁 Terminé"
            
            # Affichage en temps réel avec Rich Live
            from rich.text import Text
            
            with Live(console=console, refresh_per_second=4, transient=True) as live:
                async def _update_display():
                    while True:
                        elapsed = _time.monotonic() - t0
                        m, s = divmod(int(elapsed), 60)
                        st = _progress_state
                        
                        lines = []
                        lines.append(f"  [bold]{st['phase_label']}[/bold]  [dim]⏱ {m:02d}:{s:02d}[/dim]")
                        
                        # Barre extraction LLM
                        if st["extraction_total"] > 0:
                            bar = _make_bar(st["extraction_current"], st["extraction_total"])
                            color = "green" if st["extraction_current"] >= st["extraction_total"] else "yellow"
                            lines.append(f"  [{color}]🔍 Extraction: {bar} ({st['extraction_current']}/{st['extraction_total']} chunks)[/{color}]")
                            if st["entities"] or st["relations"]:
                                lines.append(f"  [dim]   → {st['entities']} entités, {st['relations']} relations[/dim]")
                        
                        # Barre embedding
                        if st["embedding_total"] > 0:
                            bar = _make_bar(st["embedding_current"], st["embedding_total"])
                            color = "green" if st["embedding_current"] >= st["embedding_total"] else "cyan"
                            lines.append(f"  [{color}]🔢 Embedding:  {bar} ({st['embedding_current']}/{st['embedding_total']} batches)[/{color}]")
                        
                        text = Text.from_markup("\n".join(lines))
                        live.update(text)
                        await asyncio.sleep(0.25)
                
                display_task = asyncio.create_task(_update_display())
                try:
                    result = await client.call_tool("memory_ingest", {
                        "memory_id": memory_id,
                        "content_base64": content_b64,
                        "filename": filename,
                        "force": force,
                        "source_path": effective_source_path,
                        "source_modified_at": source_modified_at,
                    }, on_progress=_on_progress)
                finally:
                    display_task.cancel()
            
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
    asyncio.run(_run())


@document.command("ingest-dir")
@click.argument("memory_id")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--exclude", "-e", multiple=True, help="Patterns à exclure (glob, ex: '*.tmp'). Répétable.")
@click.option("--confirm", "-c", is_flag=True, help="Demander confirmation pour chaque fichier")
@click.option("--force", "-f", is_flag=True, help="Forcer la ré-ingestion des fichiers déjà présents")
@click.pass_context
def document_ingest_dir(ctx, memory_id, directory, exclude, confirm, force):
    """📁 Ingérer un répertoire entier (récursif).

    \b
    Parcourt le répertoire et ses sous-répertoires pour trouver les fichiers
    supportés (.txt, .md, .html, .docx, .pdf, .csv).

    \b
    Exemples:
      document ingest-dir JURIDIQUE ./MATIERE/JURIDIQUE
      document ingest-dir JURIDIQUE ./docs -e '*.tmp' -e '__pycache__/*'
      document ingest-dir JURIDIQUE ./docs --confirm
      document ingest-dir JURIDIQUE ./docs --force
    """
    import fnmatch
    from pathlib import Path
    from rich.table import Table
    from rich.panel import Panel

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".docx", ".pdf", ".csv"}

    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])

            # --- 1. Scanner le répertoire ---
            console.print(f"[dim]📁 Scan de {directory}...[/dim]")
            all_files = []
            excluded_files = []
            unsupported_files = []

            for root, dirs, files in os.walk(directory):
                for fname in sorted(files):
                    fpath = os.path.join(root, fname)
                    rel_path = os.path.relpath(fpath, directory)

                    # Vérifier les patterns d'exclusion
                    is_excluded = False
                    for pattern in exclude:
                        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(fname, pattern):
                            is_excluded = True
                            break
                    if is_excluded:
                        excluded_files.append(rel_path)
                        continue

                    # Vérifier l'extension
                    ext = Path(fname).suffix.lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        unsupported_files.append(rel_path)
                        continue

                    file_size = os.path.getsize(fpath)
                    all_files.append({
                        "path": fpath,
                        "rel_path": rel_path,
                        "filename": fname,
                        "size": file_size,
                    })

            if not all_files:
                show_warning(f"Aucun fichier supporté trouvé dans {directory}")
                if unsupported_files:
                    console.print(f"[dim]Formats non supportés: {len(unsupported_files)} fichiers ignorés[/dim]")
                    console.print(f"[dim]Extensions supportées: {', '.join(sorted(SUPPORTED_EXTENSIONS))}[/dim]")
                return

            # --- 2. Vérifier les doublons (par filename) ---
            graph_result = await client.get_graph(memory_id)
            existing_filenames = set()
            if graph_result.get("status") == "ok":
                for d in graph_result.get("documents", []):
                    existing_filenames.add(d.get("filename", ""))

            to_ingest = []
            already_present = []
            for f in all_files:
                if f["filename"] in existing_filenames and not force:
                    already_present.append(f)
                else:
                    to_ingest.append(f)

            # --- 3. Afficher le résumé ---
            total_size = sum(f["size"] for f in to_ingest)
            size_str = _format_size_simple(total_size)

            summary_lines = [
                f"[bold]Répertoire:[/bold]  [cyan]{os.path.abspath(directory)}[/cyan]",
                f"[bold]Mémoire:[/bold]     [cyan]{memory_id}[/cyan]",
                f"",
                f"[bold]Fichiers trouvés:[/bold]     [green]{len(all_files)}[/green]",
            ]
            if excluded_files:
                summary_lines.append(f"[bold]Exclus (patterns):[/bold]  [yellow]{len(excluded_files)}[/yellow]")
            if unsupported_files:
                summary_lines.append(f"[bold]Non supportés:[/bold]      [dim]{len(unsupported_files)}[/dim]")
            if already_present:
                summary_lines.append(f"[bold]Déjà ingérés:[/bold]      [yellow]{len(already_present)}[/yellow] (skip)")
            summary_lines.append(f"[bold]À ingérer:[/bold]          [green bold]{len(to_ingest)}[/green bold] ({size_str})")

            console.print(Panel.fit(
                "\n".join(summary_lines),
                title="📁 Import en masse",
                border_style="blue",
            ))

            if not to_ingest:
                show_success("Tous les fichiers sont déjà ingérés !")
                return

            # Liste des fichiers à ingérer
            table = Table(title=f"📄 Fichiers à ingérer ({len(to_ingest)})", show_header=True)
            table.add_column("#", style="dim", width=3)
            table.add_column("Fichier", style="white")
            table.add_column("Taille", style="dim", justify="right", width=10)

            for i, f in enumerate(to_ingest, 1):
                table.add_row(str(i), f["rel_path"], _format_size_simple(f["size"]))
            console.print(table)

            # --- 4. Ingestion ---
            ingested = 0
            skipped = 0
            errors = 0

            for i, f in enumerate(to_ingest, 1):
                # Confirmation fichier par fichier si demandé
                if confirm:
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
                        "memory_id": memory_id,
                        "content_base64": content_b64,
                        "filename": f["filename"],
                        "force": force,
                        "source_path": f["rel_path"],
                        "source_modified_at": source_modified_at,
                    })

                    if result.get("status") == "ok":
                        e_new = result.get("entities_created", 0)
                        e_merged = result.get("entities_merged", 0)
                        r_new = result.get("relations_created", 0)
                        r_merged = result.get("relations_merged", 0)
                        console.print(
                            f"  [green]✅[/green] {f['filename']}: "
                            f"[cyan]{e_new}+{e_merged}[/cyan] entités, "
                            f"[cyan]{r_new}+{r_merged}[/cyan] relations"
                        )
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

        except Exception as e:
            show_error(str(e))

    asyncio.run(_run())


def _format_size_simple(size_bytes: int) -> str:
    """Convertit des bytes en taille lisible."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


@document.command("list")
@click.argument("memory_id")
@click.pass_context
def document_list(ctx, memory_id):
    """📋 Lister les documents d'une mémoire."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.get_graph(memory_id)
            if result.get("status") == "ok":
                show_documents_table(result.get("documents", []), memory_id)
            else:
                show_error(result.get("message", "Erreur"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@document.command("delete")
@click.argument("memory_id")
@click.argument("document_id")
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def document_delete(ctx, memory_id, document_id, force):
    """🗑️  Supprimer un document."""
    async def _run():
        if not force and not Confirm.ask(f"Supprimer '{document_id}' ?"):
            console.print("[dim]Annulé.[/dim]")
            return
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("document_delete", {
                "memory_id": memory_id, "document_id": document_id
            })
            if result.get("status") in ("ok", "deleted"):
                show_success(f"Document supprimé ({result.get('entities_deleted', 0)} entités orphelines nettoyées)")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Ontologies
# =============================================================================

@cli.command("ontologies")
@click.pass_context
def list_ontologies(ctx):
    """📖 Lister les ontologies disponibles."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("ontology_list", {})
            if result.get("status") == "ok":
                from rich.table import Table
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
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Question / Réponse
# =============================================================================

@cli.command("ask")
@click.argument("memory_id")
@click.argument("question")
@click.option("--limit", "-l", default=10, help="Max entités à rechercher (défaut: 10)")
@click.option("--debug", "-d", is_flag=True, help="Afficher les détails")
@click.pass_context
def ask(ctx, memory_id, question, limit, debug):
    """❓ Poser une question sur une mémoire."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
                p.add_task("Recherche…", total=None)
                result = await client.call_tool("question_answer", {
                    "memory_id": memory_id, "question": question, "limit": limit
                })
            if debug:
                console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
            if result.get("status") == "ok":
                show_answer(result.get("answer", ""), result.get("entities", []), result.get("source_documents", []))
            else:
                show_error(result.get("message", "Erreur"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Query (données structurées sans LLM)
# =============================================================================

@cli.command("query")
@click.argument("memory_id")
@click.argument("query_text")
@click.option("--limit", "-l", default=10, help="Max entités à rechercher (défaut: 10)")
@click.option("--json", "-j", "output_json", is_flag=True, help="Sortie JSON brute")
@click.pass_context
def query(ctx, memory_id, query_text, limit, output_json):
    """📊 Interroger une mémoire (données structurées, sans LLM)."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
                p.add_task("Recherche…", total=None)
                result = await client.call_tool("memory_query", {
                    "memory_id": memory_id, "query": query_text, "limit": limit
                })
            if output_json:
                console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
            elif result.get("status") == "ok":
                show_query_result(result)
            else:
                show_error(result.get("message", "Erreur"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Token (gestion des tokens d'accès)
# =============================================================================

@cli.group()
def token():
    """🔑 Gérer les tokens d'accès clients."""
    pass


@token.command("list")
@click.pass_context
def token_list(ctx):
    """📋 Lister tous les tokens actifs."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("admin_list_tokens", {})
            if result.get("status") == "ok":
                show_tokens_table(result.get("tokens", []))
            else:
                show_error(result.get("message", "Erreur"))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@token.command("create")
@click.argument("client_name")
@click.option("--permissions", "-p", default="read,write", help="Permissions (virgules: read,write,admin)")
@click.option("--memories", "-m", default="", help="Mémoires autorisées (virgules, vide=toutes)")
@click.option("--email", default=None, help="Adresse email du propriétaire du token")
@click.option("--expires", "-e", type=int, default=None, help="Expiration en jours")
@click.pass_context
def token_create(ctx, client_name, permissions, memories, email, expires):
    """➕ Créer un token pour un client.

    \b
    Exemples:
      token create quoteflow
      token create quoteflow --email user@example.com
      token create quoteflow -p read,write -m JURIDIQUE,CLOUD
      token create admin-bot -p admin -e 30
    """
    async def _run():
        try:
            perms_list = [p.strip() for p in permissions.split(",") if p.strip()]
            mem_list = [m.strip() for m in memories.split(",") if m.strip()]

            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            params = {
                "client_name": client_name,
                "permissions": perms_list,
                "memory_ids": mem_list,
            }
            if email:
                params["email"] = email
            if expires:
                params["expires_in_days"] = expires

            result = await client.call_tool("admin_create_token", params)
            if result.get("status") == "ok":
                show_token_created(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@token.command("revoke")
@click.argument("hash_prefix")
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def token_revoke(ctx, hash_prefix, force):
    """🚫 Révoquer un token (par préfixe de hash)."""
    async def _run():
        if not force and not Confirm.ask(f"[yellow]Révoquer le token '{hash_prefix}...' ?[/yellow]"):
            console.print("[dim]Annulé.[/dim]")
            return
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("admin_revoke_token", {"token_hash_prefix": hash_prefix})
            if result.get("status") == "ok":
                show_success(result.get("message", "Token révoqué"))
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@token.command("grant")
@click.argument("hash_prefix")
@click.argument("memory_ids", nargs=-1, required=True)
@click.pass_context
def token_grant(ctx, hash_prefix, memory_ids):
    """✅ Autoriser un token à accéder à des mémoires.

    \b
    Exemples:
      token grant abc12345 JURIDIQUE CLOUD
    """
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("admin_update_token", {
                "token_hash_prefix": hash_prefix,
                "add_memories": list(memory_ids),
            })
            if result.get("status") == "ok":
                show_token_updated(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@token.command("ungrant")
@click.argument("hash_prefix")
@click.argument("memory_ids", nargs=-1, required=True)
@click.pass_context
def token_ungrant(ctx, hash_prefix, memory_ids):
    """🚫 Retirer l'accès d'un token à des mémoires.

    \b
    Exemples:
      token ungrant abc12345 JURIDIQUE
    """
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("admin_update_token", {
                "token_hash_prefix": hash_prefix,
                "remove_memories": list(memory_ids),
            })
            if result.get("status") == "ok":
                show_token_updated(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@token.command("set-memories")
@click.argument("hash_prefix")
@click.argument("memory_ids", nargs=-1)
@click.pass_context
def token_set_memories(ctx, hash_prefix, memory_ids):
    """🔄 Remplacer la liste des mémoires d'un token.

    \b
    Sans argument : accès à TOUTES les mémoires.
    Avec arguments : accès restreint aux mémoires listées.

    \b
    Exemples:
      token set-memories abc12345 JURIDIQUE CLOUD   # Restreindre
      token set-memories abc12345                     # Toutes les mémoires
    """
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("admin_update_token", {
                "token_hash_prefix": hash_prefix,
                "set_memories": list(memory_ids),
            })
            if result.get("status") == "ok":
                show_token_updated(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Backup / Restore
# =============================================================================

@cli.group()
def backup():
    """💾 Backup et restauration des mémoires."""
    pass


@backup.command("create")
@click.argument("memory_id")
@click.option("--description", "-d", default=None, help="Description du backup")
@click.pass_context
def backup_create(ctx, memory_id, description):
    """💾 Créer un backup complet d'une mémoire."""
    async def _run():
        try:
            from .display import show_backup_result
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            params = {"memory_id": memory_id}
            if description:
                params["description"] = description
            console.print(f"[dim]💾 Backup de '{memory_id}' en cours...[/dim]")
            result = await client.call_tool("backup_create", params)
            if result.get("status") == "ok":
                show_backup_result(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@backup.command("list")
@click.argument("memory_id", required=False, default=None)
@click.pass_context
def backup_list(ctx, memory_id):
    """📋 Lister les backups disponibles."""
    async def _run():
        try:
            from .display import show_backups_table
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            params = {}
            if memory_id:
                params["memory_id"] = memory_id
            result = await client.call_tool("backup_list", params)
            if result.get("status") == "ok":
                show_backups_table(result.get("backups", []))
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@backup.command("restore")
@click.argument("backup_id")
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def backup_restore(ctx, backup_id, force):
    """📥 Restaurer une mémoire depuis un backup.

    \b
    ⚠️ La mémoire NE DOIT PAS exister (supprimez-la d'abord si nécessaire).

    \b
    Exemples:
      backup restore JURIDIQUE/2026-02-16T15-30-00
    """
    async def _run():
        try:
            from .display import show_restore_result
            if not force and not Confirm.ask(
                f"[yellow]Restaurer depuis '{backup_id}' ?[/yellow]\n"
                f"[dim]La mémoire ne doit pas exister.[/dim]"
            ):
                console.print("[dim]Annulé.[/dim]")
                return
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            console.print(f"[dim]📥 Restauration de '{backup_id}' en cours...[/dim]")
            result = await client.call_tool("backup_restore", {"backup_id": backup_id})
            if result.get("status") == "ok":
                show_restore_result(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@backup.command("download")
@click.argument("backup_id")
@click.option("--output", "-o", default=None, help="Fichier de sortie (défaut: backup-{id}.tar.gz)")
@click.option("--include-documents", is_flag=True, help="Inclure les documents originaux")
@click.pass_context
def backup_download(ctx, backup_id, output, include_documents):
    """📦 Télécharger un backup en archive tar.gz."""
    async def _run():
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            console.print(f"[dim]📦 Téléchargement de '{backup_id}'...[/dim]")
            result = await client.call_tool("backup_download", {
                "backup_id": backup_id,
                "include_documents": include_documents,
            })
            if result.get("status") == "ok":
                # Décoder et écrire le fichier
                content_b64 = result.get("content_base64", "")
                archive_bytes = base64.b64decode(content_b64)
                
                out_file = output or result.get("filename", f"backup-{backup_id.replace('/', '-')}.tar.gz")
                with open(out_file, "wb") as f:
                    f.write(archive_bytes)
                
                show_success(f"Archive sauvée: {out_file} ({_format_size_simple(len(archive_bytes))})")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@backup.command("delete")
@click.argument("backup_id")
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def backup_delete(ctx, backup_id, force):
    """🗑️  Supprimer un backup."""
    async def _run():
        if not force and not Confirm.ask(f"[yellow]Supprimer le backup '{backup_id}' ?[/yellow]"):
            console.print("[dim]Annulé.[/dim]")
            return
        try:
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("backup_delete", {"backup_id": backup_id})
            if result.get("status") == "ok":
                show_success(f"Backup supprimé: {backup_id} ({result.get('files_deleted', 0)} fichiers)")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


@backup.command("restore-file")
@click.argument("archive_path", type=click.Path(exists=True))
@click.option("--force", "-f", is_flag=True, help="Pas de confirmation")
@click.pass_context
def backup_restore_file(ctx, archive_path, force):
    """📦 Restaurer depuis une archive tar.gz locale (avec documents S3)."""
    import os
    file_size = os.path.getsize(archive_path)
    size_mb = file_size / (1024 * 1024)
    
    if not force and not Confirm.ask(
        f"[yellow]Restaurer depuis '{archive_path}' ({size_mb:.1f} MB) ?\n"
        f"La mémoire ne doit pas exister.[/yellow]"
    ):
        console.print("[dim]Annulé.[/dim]")
        return
    
    async def _run():
        try:
            import base64
            from .display import show_restore_result
            console.print(f"📦 Lecture de l'archive ({size_mb:.1f} MB)...")
            with open(archive_path, "rb") as f:
                archive_bytes = f.read()
            archive_b64 = base64.b64encode(archive_bytes).decode("ascii")
            
            console.print("📥 Envoi au serveur pour restauration...")
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])
            result = await client.call_tool("backup_restore_archive", {
                "archive_base64": archive_b64
            })
            
            if result.get("status") == "ok":
                show_restore_result(result)
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


# =============================================================================
# Shell (délègue à shell.py)
# =============================================================================

@cli.command()
@click.pass_context
def shell(ctx):
    """🐚 Mode shell interactif."""
    from .shell import run_shell
    run_shell(ctx.obj["url"], ctx.obj["token"])
