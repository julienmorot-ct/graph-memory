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
  - document ingest/list/delete
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
    show_answer, show_entity_context, show_storage_check,
    show_cleanup_result, console
)

# =============================================================================
# Groupe principal
# =============================================================================

@click.group(invoke_without_command=True)
@click.option("--url", envvar="MCP_SERVER_URL", default=BASE_URL, help="URL du serveur MCP")
@click.option("--token", envvar="ADMIN_BOOTSTRAP_KEY", default=TOKEN, help="Token d'authentification")
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
@click.pass_context
def document_ingest(ctx, memory_id, file_path, force):
    """📥 Ingérer un document dans une mémoire."""
    async def _run():
        try:
            with open(file_path, "rb") as f:
                content_bytes = f.read()
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
            filename = os.path.basename(file_path)
            client = MCPClient(ctx.obj["url"], ctx.obj["token"])

            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
                p.add_task(f"Ingestion de {filename}…", total=None)
                result = await client.call_tool("memory_ingest", {
                    "memory_id": memory_id,
                    "content_base64": content_b64,
                    "filename": filename,
                    "force": force,
                })

            if result.get("status") == "ok":
                show_ingest_result(result)
            elif result.get("status") == "already_exists":
                console.print(f"[yellow]⚠️ Déjà ingéré: {result.get('document_id')} (--force pour réingérer)[/yellow]")
            else:
                show_error(result.get("message", str(result)))
        except Exception as e:
            show_error(str(e))
    asyncio.run(_run())


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
# Shell (délègue à shell.py)
# =============================================================================

@cli.command()
@click.pass_context
def shell(ctx):
    """🐚 Mode shell interactif."""
    from .shell import run_shell
    run_shell(ctx.obj["url"], ctx.obj["token"])
