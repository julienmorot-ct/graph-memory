# -*- coding: utf-8 -*-
"""
Progression d'ingestion en temps réel — Module partagé.

Factorise la logique de progression commune entre :
  - commands.py (CLI Click : `document ingest`)
  - shell.py    (Shell interactif : `ingest`)

Composants :
  - create_progress_state()     : État initial de progression
  - make_progress_bar()         : Barre ASCII  █████░░░░░ 50%
  - create_progress_callback()  : Parser des messages SSE → mise à jour d'état
  - run_ingest_with_progress()  : Coroutine complète (Rich Live + appel MCP)
"""

import asyncio
import re
import time

from rich.live import Live
from rich.text import Text

from .display import console

# =============================================================================
# État de progression
# =============================================================================


def create_progress_state() -> dict:
    """Crée un nouvel état de progression pour une ingestion."""
    return {
        "phase": "init",  # init, upload, extract_text, extraction, neo4j, chunking, embedding, qdrant, done
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


# =============================================================================
# Barre de progression ASCII
# =============================================================================


def make_progress_bar(current: int, total: int, width: int = 20) -> str:
    """
    Génère une barre de progression ASCII.

    Exemple : █████████░░░░░░░░░░░ 45%
    """
    if total <= 0:
        return ""
    pct = min(current / total, 1.0)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {pct * 100:.0f}%"


# =============================================================================
# Parser des messages SSE serveur
# =============================================================================


def create_progress_callback(state: dict):
    """
    Crée un callback async qui parse les messages SSE du serveur
    et met à jour l'état de progression.

    Les messages proviennent de ctx.info() côté serveur MCP et sont
    interceptés via le hook _received_notification du SDK MCP.

    Args:
        state: dict créé par create_progress_state()

    Returns:
        Coroutine async compatible avec MCPClient.call_tool(on_progress=...)
    """

    async def on_progress(msg: str):
        st = state
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
            m = re.search(r"(\d+)\s*chunks?\s*\(", msg)
            if m:
                st["extraction_total"] = int(m.group(1))
            st["phase"] = "extraction"
            st["phase_label"] = "🔍 Extraction LLM"
            st["extraction_current"] = 0
        elif "Chunk " in msg and "terminé" in msg:
            m = re.search(r"Chunk\s+(\d+)/(\d+)", msg)
            if m:
                st["extraction_current"] = int(m.group(1))
                st["extraction_total"] = int(m.group(2))
            # Extraire cumul entités/relations
            m2 = re.search(r"cumul:\s*(\d+)E\s*(\d+)R", msg)
            if m2:
                st["entities"] = int(m2.group(1))
                st["relations"] = int(m2.group(2))
        elif "Extraction terminée" in msg:
            m = re.search(r"(\d+)\s*entités.*?(\d+)\s*relations", msg)
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
            m = re.search(r"(\d+)\s*chunks", msg)
            if m:
                st["chunks_rag"] = int(m.group(1))
            st["phase_label"] = f"✅ {st['chunks_rag']} chunks RAG"

        # Phase RAG : embedding
        elif "Embedding batch" in msg:
            st["phase"] = "embedding"
            m = re.search(r"batch\s+(\d+)/(\d+)", msg)
            if m:
                st["embedding_current"] = int(m.group(1)) - 1  # en cours, pas terminé
                st["embedding_total"] = int(m.group(2))
            st["phase_label"] = "🔢 Embedding"
        elif "Batch " in msg and "OK" in msg:
            m = re.search(r"Batch\s+(\d+)/(\d+)", msg)
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

    return on_progress


# =============================================================================
# Coroutine principale : ingestion avec affichage Rich Live
# =============================================================================


async def run_ingest_with_progress(client, tool_args: dict) -> dict:
    """
    Exécute une ingestion MCP avec affichage de progression en temps réel.

    Gère :
    - Rich Live display rafraîchi 4x/seconde
    - Barres ASCII pour extraction LLM et embedding
    - Compteurs entités/relations en temps réel
    - Timer (mm:ss)

    Args:
        client:    MCPClient connecté
        tool_args: Arguments pour memory_ingest (memory_id, content_base64, etc.)

    Returns:
        dict: Résultat de l'appel MCP, enrichi de _elapsed_seconds
    """
    t0 = time.monotonic()
    state = create_progress_state()
    on_progress = create_progress_callback(state)

    with Live(console=console, refresh_per_second=4, transient=True) as live:

        async def _update_display():
            while True:
                elapsed = time.monotonic() - t0
                m, s = divmod(int(elapsed), 60)
                st = state

                lines = []
                lines.append(f"  [bold]{st['phase_label']}[/bold]  [dim]⏱ {m:02d}:{s:02d}[/dim]")

                # Barre extraction LLM
                if st["extraction_total"] > 0:
                    bar = make_progress_bar(st["extraction_current"], st["extraction_total"])
                    color = (
                        "green" if st["extraction_current"] >= st["extraction_total"] else "yellow"
                    )
                    lines.append(
                        f"  [{color}]🔍 Extraction: {bar} "
                        f"({st['extraction_current']}/{st['extraction_total']} chunks)[/{color}]"
                    )
                    if st["entities"] or st["relations"]:
                        lines.append(
                            f"  [dim]   → {st['entities']} entités, {st['relations']} relations[/dim]"
                        )

                # Barre embedding
                if st["embedding_total"] > 0:
                    bar = make_progress_bar(st["embedding_current"], st["embedding_total"])
                    color = "green" if st["embedding_current"] >= st["embedding_total"] else "cyan"
                    lines.append(
                        f"  [{color}]🔢 Embedding:  {bar} "
                        f"({st['embedding_current']}/{st['embedding_total']} batches)[/{color}]"
                    )

                text = Text.from_markup("\n".join(lines))
                live.update(text)
                await asyncio.sleep(0.25)

        display_task = asyncio.create_task(_update_display())
        try:
            result = await client.call_tool("memory_ingest", tool_args, on_progress=on_progress)
        finally:
            display_task.cancel()

    elapsed = time.monotonic() - t0
    result["_elapsed_seconds"] = round(elapsed, 1)
    return result
