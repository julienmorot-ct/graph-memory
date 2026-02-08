#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧠 MCP Memory CLI - Outil en ligne de commande pour piloter le serveur MCP Memory.

Usage:
    mcp-cli [OPTIONS] COMMAND [ARGS]...
    mcp-cli shell              # Mode interactif
    
Exemples:
    mcp-cli health             # Vérifier le serveur
    mcp-cli memory list        # Lister les mémoires
    mcp-cli memory delete ID   # Supprimer une mémoire
    mcp-cli shell              # Mode shell interactif
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional

# Ajouter le chemin src au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.progress import Progress, SpinnerColumn, TextColumn
except ImportError:
    print("❌ Dépendances manquantes. Installer avec:")
    print("   pip install click rich")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

# Configuration
BASE_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8002")
TOKEN = os.getenv("ADMIN_BOOTSTRAP_KEY", "admin_bootstrap_key_change_me")
DEBUG = False  # Mode debug global

console = Console()

# ============================================================================
# CLIENT MCP
# ============================================================================

class MCPClient:
    """Client pour communiquer avec le serveur MCP Memory."""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self._session = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        pass
    
    async def _fetch(self, endpoint: str) -> dict:
        """Faire une requête GET simple."""
        import aiohttp
        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    raise Exception(f"HTTP {response.status}: {text}")
    
    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Appeler un outil MCP via SSE."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError:
            raise ImportError("Package 'mcp' non installé")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        
        async with sse_client(f"{self.base_url}/sse", headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return json.loads(result.content[0].text)
    
    # Raccourcis API REST
    async def health(self) -> dict:
        return await self._fetch("/health")
    
    async def list_memories(self) -> dict:
        return await self._fetch("/api/memories")
    
    async def get_graph(self, memory_id: str) -> dict:
        return await self._fetch(f"/api/graph/{memory_id}")


# ============================================================================
# COMMANDES CLI
# ============================================================================

@click.group(invoke_without_command=True)
@click.option('--url', envvar='MCP_SERVER_URL', default=BASE_URL, help='URL du serveur MCP')
@click.option('--token', envvar='ADMIN_BOOTSTRAP_KEY', default=TOKEN, help='Token d\'authentification')
@click.pass_context
def cli(ctx, url, token):
    """🧠 MCP Memory CLI - Pilotez votre serveur MCP Memory.
    
    Utilisez 'mcp-cli COMMAND --help' pour l'aide sur chaque commande.
    
    Exemples:
    
    \b
      mcp-cli health              # État du serveur
      mcp-cli memory list         # Lister les mémoires
      mcp-cli memory delete ID    # Supprimer une mémoire
      mcp-cli shell               # Mode interactif
    """
    ctx.ensure_object(dict)
    ctx.obj['url'] = url
    ctx.obj['token'] = token
    
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ============================================================================
# HEALTH
# ============================================================================

@cli.command()
@click.pass_context
def health(ctx):
    """🏥 Vérifier l'état du serveur MCP."""
    async def _health():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Vérification...", total=None)
                # Utiliser l'API memories comme test de santé
                result = await client.list_memories()
            
            if result.get('status') == 'ok':
                console.print(Panel.fit(
                    f"[bold green]✅ Serveur OK[/bold green]\n\n"
                    f"URL: [cyan]{ctx.obj['url']}[/cyan]\n"
                    f"Mémoires: [green]{result.get('count', 0)}[/green]",
                    title="🏥 État du serveur",
                    border_style="green"
                ))
            else:
                console.print(f"[yellow]⚠️ Serveur répond mais erreur: {result.get('message')}[/yellow]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur connexion: {e}[/red]")
    
    asyncio.run(_health())


# ============================================================================
# MEMORY
# ============================================================================

@cli.group()
def memory():
    """📚 Gérer les mémoires."""
    pass


@memory.command('list')
@click.pass_context
def memory_list(ctx):
    """📋 Lister toutes les mémoires."""
    async def _list():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            result = await client.list_memories()
            
            if result.get('status') != 'ok':
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                return
            
            memories = result.get('memories', [])
            
            if not memories:
                console.print("[yellow]Aucune mémoire trouvée.[/yellow]")
                return
            
            table = Table(title=f"📚 Mémoires ({len(memories)})")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Nom", style="white")
            table.add_column("Ontologie", style="magenta")
            table.add_column("Description", style="dim")
            table.add_column("Créée le", style="green")
            
            for m in memories:
                created = m.get('created_at', '')[:10] if m.get('created_at') else '-'
                table.add_row(
                    m.get('id', ''),
                    m.get('name', ''),
                    m.get('ontology', 'default'),
                    (m.get('description', '') or '')[:30],
                    created
                )
            
            console.print(table)
            
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_list())


@memory.command('create')
@click.argument('memory_id')
@click.option('--name', '-n', default=None, help='Nom de la mémoire')
@click.option('--description', '-d', default=None, help='Description')
@click.option('--ontology', '-o', required=True, help='Ontologie à utiliser (OBLIGATOIRE: legal, cloud, etc.)')
@click.pass_context
def memory_create(ctx, memory_id, name, description, ontology):
    """➕ Créer une nouvelle mémoire."""
    async def _create():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Création...", total=None)
                result = await client.call_tool('memory_create', {
                    'memory_id': memory_id,
                    'name': name or memory_id,
                    'description': description or '',
                    'ontology': ontology
                })
            
            if result.get('status') in ('ok', 'created'):
                console.print(f"[green]✅ Mémoire '{memory_id}' créée avec succès![/green]")
                if result.get('ontology'):
                    console.print(f"   Ontologie: [cyan]{result.get('ontology')}[/cyan]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message', result)}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_create())


@memory.command('delete')
@click.argument('memory_id')
@click.option('--force', '-f', is_flag=True, help='Ne pas demander de confirmation')
@click.pass_context
def memory_delete(ctx, memory_id, force):
    """🗑️  Supprimer une mémoire."""
    async def _delete():
        try:
            if not force:
                if not Confirm.ask(f"[yellow]Supprimer la mémoire '{memory_id}' ?[/yellow]"):
                    console.print("[dim]Annulé.[/dim]")
                    return
            
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Suppression...", total=None)
                result = await client.call_tool('memory_delete', {
                    'memory_id': memory_id
                })
            
            if result.get('status') in ('ok', 'deleted'):
                console.print(f"[green]✅ Mémoire '{memory_id}' supprimée![/green]")
            elif result.get('deleted'):
                console.print(f"[green]✅ Mémoire '{memory_id}' supprimée![/green]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message', result)}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_delete())


@memory.command('graph')
@click.argument('memory_id')
@click.option('--format', '-f', type=click.Choice(['table', 'json']), default='table')
@click.pass_context
def memory_graph(ctx, memory_id, format):
    """📊 Afficher le graphe d'une mémoire."""
    async def _graph():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Chargement...", total=None)
                result = await client.get_graph(memory_id)
            
            if result.get('status') != 'ok':
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                return
            
            if format == 'json':
                console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
                return
            
            # Affichage table
            nodes = result.get('nodes', [])
            edges = result.get('edges', [])
            docs = result.get('documents', [])
            
            console.print(Panel.fit(
                f"[bold]Entités:[/bold] [cyan]{len(nodes)}[/cyan]  "
                f"[bold]Relations:[/bold] [cyan]{len(edges)}[/cyan]  "
                f"[bold]Documents:[/bold] [cyan]{len(docs)}[/cyan]",
                title=f"📊 Graphe: {memory_id}",
                border_style="blue"
            ))
            
            # Table des entités par type
            from collections import defaultdict
            by_type = defaultdict(list)
            for n in nodes:
                by_type[n.get('type', 'Unknown')].append(n)
            
            for entity_type, entities in sorted(by_type.items()):
                table = Table(title=f"[cyan]{entity_type}[/cyan] ({len(entities)})", show_header=True)
                table.add_column("Label", style="white")
                table.add_column("Description", style="dim", max_width=50)
                
                for e in entities[:10]:
                    table.add_row(
                        e.get('label', '')[:40],
                        (e.get('description', '') or '')[:50]
                    )
                
                if len(entities) > 10:
                    table.add_row(f"[dim]... et {len(entities)-10} autres[/dim]", "")
                
                console.print(table)
            
            # Documents
            if docs:
                console.print("\n[bold]📄 Documents:[/bold]")
                for d in docs:
                    console.print(f"  • [cyan]{d.get('filename')}[/cyan]")
                    console.print(f"    [dim]{d.get('uri')}[/dim]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_graph())


# ============================================================================
# DOCUMENT
# ============================================================================

@cli.group()
def document():
    """📄 Gérer les documents."""
    pass


@document.command('ingest')
@click.argument('memory_id')
@click.argument('file_path', type=click.Path(exists=True))
@click.pass_context
def document_ingest(ctx, memory_id, file_path):
    """📥 Ingérer un document dans une mémoire."""
    async def _ingest():
        try:
            import base64
            
            with open(file_path, 'rb') as f:
                content_bytes = f.read()
            
            # Encoder en base64 comme attendu par memory_ingest
            content_base64 = base64.b64encode(content_bytes).decode('utf-8')
            filename = os.path.basename(file_path)
            
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task(f"Ingestion de {filename}...", total=None)
                result = await client.call_tool('memory_ingest', {
                    'memory_id': memory_id,
                    'content_base64': content_base64,
                    'filename': filename
                })
            
            if result.get('status') == 'ok':
                doc_id = result.get('document_id', '?')
                e_new = result.get('entities_created', 0)
                e_merged = result.get('entities_merged', 0)
                r_new = result.get('relations_created', 0)
                r_merged = result.get('relations_merged', 0)
                
                console.print(f"[green]✅ Document ingéré![/green]")
                console.print(f"   ID: [cyan]{doc_id}[/cyan]")
                console.print(f"   Entités: [cyan]{e_new}[/cyan] nouvelles + [yellow]{e_merged}[/yellow] fusionnées = [bold]{e_new + e_merged}[/bold]")
                console.print(f"   Relations: [cyan]{r_new}[/cyan] nouvelles + [yellow]{r_merged}[/yellow] fusionnées = [bold]{r_new + r_merged}[/bold]")
                
                # Types d'entités
                entity_types = result.get('entity_types', {})
                if entity_types:
                    types_str = ", ".join(f"[magenta]{t}[/magenta]:{c}" for t, c in sorted(entity_types.items(), key=lambda x: -x[1]))
                    console.print(f"   Types entités: {types_str}")
                
                # Types de relations
                relation_types = result.get('relation_types', {})
                if relation_types:
                    rels_str = ", ".join(f"[blue]{t}[/blue]:{c}" for t, c in sorted(relation_types.items(), key=lambda x: -x[1]))
                    console.print(f"   Types relations: {rels_str}")
                
                # Sujets clés
                topics = result.get('key_topics', [])
                if topics:
                    console.print(f"   Sujets: [dim]{', '.join(topics[:5])}[/dim]")
                
                if result.get('summary'):
                    console.print(f"   Résumé: [dim]{result.get('summary')[:120]}...[/dim]")
            elif result.get('status') == 'already_exists':
                console.print(f"[yellow]⚠️ Document déjà ingéré: {result.get('document_id')}[/yellow]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_ingest())


@document.command('list')
@click.argument('memory_id')
@click.pass_context
def document_list(ctx, memory_id):
    """📋 Lister les documents d'une mémoire."""
    async def _list():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Chargement...", total=None)
                result = await client.get_graph(memory_id)
            
            if result.get('status') != 'ok':
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                return
            
            docs = result.get('documents', [])
            
            if not docs:
                console.print(f"[yellow]Aucun document dans la mémoire '{memory_id}'.[/yellow]")
                return
            
            table = Table(title=f"📄 Documents de {memory_id} ({len(docs)})")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Fichier", style="white")
            table.add_column("URI S3", style="dim", max_width=60)
            table.add_column("Ingéré le", style="green")
            
            for d in docs:
                doc_id = d.get('id', '')  # ID complet, pas de troncature !
                ingested = d.get('ingested_at', '')[:10] if d.get('ingested_at') else '-'
                table.add_row(
                    doc_id,
                    d.get('filename', ''),
                    d.get('uri', ''),
                    ingested
                )
            
            console.print(table)
            
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_list())


@document.command('show')
@click.argument('memory_id')
@click.argument('document_id')
@click.pass_context
def document_show(ctx, memory_id, document_id):
    """👁️  Afficher le contenu d'un document."""
    async def _show():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Chargement...", total=None)
                result = await client.call_tool('document_get', {
                    'memory_id': memory_id,
                    'document_id': document_id
                })
            
            if result.get('status') == 'ok':
                doc = result.get('document', {})
                console.print(Panel.fit(
                    f"[bold]ID:[/bold] [cyan]{document_id}[/cyan]\n"
                    f"[bold]Fichier:[/bold] [cyan]{doc.get('filename', '?')}[/cyan]\n"
                    f"[bold]URI:[/bold] [dim]{doc.get('uri', '?')}[/dim]\n"
                    f"[bold]Hash:[/bold] [dim]{doc.get('hash', '?')}[/dim]",
                    title=f"📄 Document",
                    border_style="blue"
                ))
                
                content = result.get('content', '')
                if content:
                    console.print("\n[bold]Contenu:[/bold]")
                    console.print(Panel(content[:2000] + ('...' if len(content) > 2000 else ''), border_style="dim"))
            else:
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_show())


@document.command('delete')
@click.argument('memory_id')
@click.argument('document_id')
@click.option('--force', '-f', is_flag=True, help='Ne pas demander de confirmation')
@click.pass_context
def document_delete(ctx, memory_id, document_id, force):
    """🗑️  Supprimer un document et ses relations du graphe."""
    async def _delete():
        try:
            if not force:
                console.print("[yellow]⚠️  Cela supprimera aussi les relations MENTIONS du graphe.[/yellow]")
                if not Confirm.ask(f"Supprimer le document '{document_id}' ?"):
                    console.print("[dim]Annulé.[/dim]")
                    return
            
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Suppression...", total=None)
                result = await client.call_tool('document_delete', {
                    'memory_id': memory_id,
                    'document_id': document_id
                })
            
            if result.get('status') in ('ok', 'deleted'):
                console.print(f"[green]✅ Document supprimé![/green]")
                relations = result.get('relations_deleted', 0)
                entities = result.get('entities_deleted', 0)
                if relations:
                    console.print(f"   Relations MENTIONS supprimées: [cyan]{relations}[/cyan]")
                if entities:
                    console.print(f"   Entités orphelines supprimées: [cyan]{entities}[/cyan]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message', result)}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_delete())


# ============================================================================
# ONTOLOGY
# ============================================================================

@cli.command('ontologies')
@click.pass_context
def list_ontologies(ctx):
    """📖 Lister les ontologies disponibles."""
    async def _list():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Chargement...", total=None)
                result = await client.call_tool('ontology_list', {})
            
            if result.get('status') == 'ok':
                ontologies = result.get('ontologies', [])
                
                table = Table(title=f"📖 Ontologies disponibles ({len(ontologies)})")
                table.add_column("Nom", style="cyan")
                table.add_column("Description", style="white")
                table.add_column("Types d'entités", style="dim")
                
                for o in ontologies:
                    entity_count = o.get('entity_types_count', 0)
                    relation_count = o.get('relation_types_count', 0)
                    
                    table.add_row(
                        o.get('name', ''),
                        o.get('description', '')[:50],
                        f"{entity_count} types, {relation_count} relations"
                    )
                
                console.print(table)
                console.print("\n[dim]Utilisation: mcp-cli memory create ID -o <ontologie>[/dim]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    asyncio.run(_list())


# ============================================================================
# QUESTION
# ============================================================================

@cli.command('ask')
@click.argument('memory_id')
@click.argument('question')
@click.option('--debug', '-d', is_flag=True, help='Afficher les détails de recherche')
@click.pass_context
def ask(ctx, memory_id, question, debug):
    """❓ Poser une question sur une mémoire."""
    async def _ask():
        try:
            client = MCPClient(ctx.obj['url'], ctx.obj['token'])
            
            if debug:
                console.print(f"\n[bold cyan]🔍 DEBUG - Question:[/bold cyan]")
                console.print(f"   Memory: [cyan]{memory_id}[/cyan]")
                console.print(f"   Question: [cyan]{question}[/cyan]")
                console.print(f"   URL: [dim]{ctx.obj['url']}[/dim]")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Recherche...", total=None)
                result = await client.call_tool('question_answer', {
                    'memory_id': memory_id,
                    'question': question
                })
            
            if debug:
                console.print(f"\n[bold cyan]🔍 DEBUG - Résultat complet:[/bold cyan]")
                console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
            
            if result.get('status') == 'ok':
                if debug:
                    console.print(f"\n[bold cyan]🔍 DEBUG - Entités trouvées:[/bold cyan]")
                    for e in result.get('entities', []):
                        console.print(f"   • [green]{e}[/green]")
                    
                    console.print(f"\n[bold cyan]🔍 DEBUG - Contexte utilisé:[/bold cyan]")
                    console.print(Panel(result.get('context_used', ''), border_style="dim"))
                
                console.print(Panel.fit(
                    Markdown(result.get('answer', '')),
                    title="💡 Réponse",
                    border_style="green"
                ))
                
                entities = result.get('entities', [])
                if entities and not debug:
                    console.print(f"\n[dim]Entités liées: {', '.join(entities[:5])}[/dim]")
            else:
                console.print(f"[red]❌ Erreur: {result.get('message')}[/red]")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
            if debug:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
    
    asyncio.run(_ask())


# ============================================================================
# SHELL INTERACTIF
# ============================================================================

@cli.command()
@click.pass_context
def shell(ctx):
    """🐚 Mode shell interactif."""
    
    console.print(Panel.fit(
        "[bold cyan]🧠 MCP Memory Shell[/bold cyan]\n\n"
        "Tapez [green]help[/green] pour la liste des commandes.\n"
        "Tapez [yellow]exit[/yellow] ou [yellow]quit[/yellow] pour quitter.",
        border_style="cyan"
    ))
    
    client = MCPClient(ctx.obj['url'], ctx.obj['token'])
    current_memory = None
    debug_mode = False  # Mode debug désactivé par défaut
    
    COMMANDS = {
        'help': 'Afficher l\'aide',
        'health': 'État du serveur',
        'list': 'Lister les mémoires',
        'use <id>': 'Sélectionner une mémoire',
        'info': 'Informations sur la mémoire courante',
        'graph': 'Afficher le graphe',
        'entities': 'Lister les entités',
        'delete': 'Supprimer la mémoire courante',
        'delete <id>': 'Supprimer une mémoire',
        'ask <question>': 'Poser une question',
        'debug': 'Activer/désactiver le mode debug',
        'clear': 'Effacer l\'écran',
        'exit': 'Quitter'
    }
    
    def show_help():
        table = Table(title="📖 Commandes disponibles")
        table.add_column("Commande", style="cyan")
        table.add_column("Description", style="white")
        for cmd, desc in COMMANDS.items():
            table.add_row(cmd, desc)
        console.print(table)
    
    async def run_command(cmd: str):
        nonlocal current_memory, debug_mode
        
        parts = cmd.strip().split(maxsplit=1)
        if not parts:
            return
        
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''
        
        try:
            if command in ('exit', 'quit', 'q'):
                console.print("[dim]Au revoir! 👋[/dim]")
                sys.exit(0)
            
            elif command == 'help':
                show_help()
            
            elif command == 'debug':
                debug_mode = not debug_mode
                status = "[green]ACTIVÉ[/green]" if debug_mode else "[dim]désactivé[/dim]"
                console.print(f"🔍 Mode debug: {status}")
            
            elif command == 'clear':
                console.clear()
            
            elif command == 'health':
                result = await client.health()
                status = result.get('status', 'unknown')
                if status == 'healthy':
                    console.print(f"[green]✅ Serveur OK[/green] - v{result.get('version', '?')}")
                else:
                    console.print(f"[red]❌ {status}[/red]")
            
            elif command == 'list':
                result = await client.list_memories()
                if result.get('status') == 'ok':
                    for m in result.get('memories', []):
                        marker = "[cyan]→[/cyan]" if m['id'] == current_memory else " "
                        console.print(f" {marker} [white]{m['id']}[/white] - {m.get('name', '')}")
                else:
                    console.print(f"[red]{result.get('message')}[/red]")
            
            elif command == 'use':
                if args:
                    current_memory = args
                    console.print(f"[green]✓[/green] Mémoire sélectionnée: [cyan]{current_memory}[/cyan]")
                else:
                    console.print("[yellow]Usage: use <memory_id>[/yellow]")
            
            elif command == 'info':
                if not current_memory:
                    console.print("[yellow]Aucune mémoire sélectionnée. Utilisez 'use <id>'[/yellow]")
                else:
                    result = await client.get_graph(current_memory)
                    if result.get('status') == 'ok':
                        console.print(f"[bold]Mémoire:[/bold] [cyan]{current_memory}[/cyan]")
                        console.print(f"  Entités: [green]{result.get('node_count', 0)}[/green]")
                        console.print(f"  Relations: [green]{result.get('edge_count', 0)}[/green]")
                        console.print(f"  Documents: [green]{result.get('document_count', 0)}[/green]")
            
            elif command == 'graph':
                mem = args or current_memory
                if not mem:
                    console.print("[yellow]Usage: graph <memory_id> ou 'use' d'abord[/yellow]")
                else:
                    result = await client.get_graph(mem)
                    if result.get('status') == 'ok':
                        console.print(f"[bold]📊 Graphe {mem}[/bold]")
                        for n in result.get('nodes', [])[:20]:
                            console.print(f"  • [{n.get('type')}] {n.get('label')}")
                        if len(result.get('nodes', [])) > 20:
                            console.print(f"  [dim]... et {len(result['nodes'])-20} autres[/dim]")
            
            elif command == 'entities':
                mem = current_memory
                if not mem:
                    console.print("[yellow]Sélectionnez une mémoire avec 'use <id>'[/yellow]")
                else:
                    result = await client.get_graph(mem)
                    if result.get('status') == 'ok':
                        from collections import Counter
                        types = Counter(n.get('type', '?') for n in result.get('nodes', []))
                        for t, count in types.most_common():
                            console.print(f"  [{t}]: [cyan]{count}[/cyan]")
            
            elif command == 'delete':
                mem = args or current_memory
                if not mem:
                    console.print("[yellow]Usage: delete <memory_id>[/yellow]")
                elif Confirm.ask(f"[yellow]Supprimer '{mem}' ?[/yellow]"):
                    result = await client.call_tool('memory_delete', {'memory_id': mem})
                    if result.get('status') == 'ok':
                        console.print(f"[green]✅ Mémoire '{mem}' supprimée[/green]")
                        if mem == current_memory:
                            current_memory = None
                    else:
                        console.print(f"[red]❌ {result.get('message')}[/red]")
            
            elif command == 'ask':
                if not args:
                    console.print("[yellow]Usage: ask <question>[/yellow]")
                elif not current_memory:
                    console.print("[yellow]Sélectionnez une mémoire avec 'use <id>'[/yellow]")
                else:
                    if debug_mode:
                        console.print(f"\n[bold cyan]🔍 DEBUG - Requête:[/bold cyan]")
                        console.print(f"   Memory: [cyan]{current_memory}[/cyan]")
                        console.print(f"   Question: [cyan]{args}[/cyan]")
                    
                    result = await client.call_tool('question_answer', {
                        'memory_id': current_memory,
                        'question': args
                    })
                    
                    if debug_mode:
                        console.print(f"\n[bold cyan]🔍 DEBUG - Résultat complet:[/bold cyan]")
                        console.print(Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"))
                    
                    if result.get('status') == 'ok':
                        if debug_mode:
                            console.print(f"\n[bold cyan]🔍 DEBUG - Entités trouvées:[/bold cyan]")
                            for e in result.get('entities', []):
                                console.print(f"   • [green]{e}[/green]")
                            
                            console.print(f"\n[bold cyan]🔍 DEBUG - Contexte utilisé:[/bold cyan]")
                            console.print(Panel(result.get('context_used', ''), border_style="dim"))
                        
                        console.print(Panel(Markdown(result.get('answer', '')), title="💡", border_style="green"))
                        
                        if not debug_mode:
                            entities = result.get('entities', [])
                            if entities:
                                console.print(f"[dim]Entités: {', '.join(entities[:5])}[/dim]")
                    else:
                        console.print(f"[red]❌ {result.get('message')}[/red]")
            
            else:
                console.print(f"[red]Commande inconnue: {command}[/red]. Tapez 'help'.")
                
        except Exception as e:
            console.print(f"[red]❌ Erreur: {e}[/red]")
    
    # Boucle principale du shell
    while True:
        try:
            prompt_mem = f"[cyan]{current_memory}[/cyan]" if current_memory else "[dim]no memory[/dim]"
            cmd = Prompt.ask(f"\n🧠 {prompt_mem}")
            asyncio.run(run_command(cmd))
        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C - Tapez 'exit' pour quitter[/dim]")
        except EOFError:
            console.print("\n[dim]Au revoir! 👋[/dim]")
            break


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    cli()
