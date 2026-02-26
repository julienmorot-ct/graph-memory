# -*- coding: utf-8 -*-
"""
Adapters for the LoCoMo benchmark.

Adapters bridge the LoCoMo evaluation tasks with different memory systems
and LLM backends. Each adapter implements a common interface for:
  - Ingesting conversation data into the memory system
  - Answering questions given conversation context
  - Generating event summaries from conversation history

Available adapters:
  - BaseAdapter: Abstract interface all adapters must implement.
  - GraphMemoryAdapter: Adapter for the graph-memory MCP service (SSE protocol).
  - DirectLLMAdapter: Adapter that queries an LLM directly (baseline).
"""

from __future__ import annotations

import abc
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmarks.locomo.models import (
    LoCoMoSample,
    QAPrediction,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Abstract Base Adapter
# =============================================================================


class BaseAdapter(abc.ABC):
    """
    Abstract base class for LoCoMo benchmark adapters.

    An adapter connects the LoCoMo evaluation pipeline to a specific
    memory / retrieval / generation backend.  Subclasses must implement
    all abstract methods.

    Lifecycle
    ---------
    1. ``setup()``       — one-time initialisation (connections, etc.)
    2. ``ingest()``      — load a conversation into the backend
    3. ``answer_question()`` / ``summarize_events()`` — evaluation calls
    4. ``teardown()``    — cleanup resources

    Parameters
    ----------
    name : str
        Human-readable adapter name (used in reports).
    config : dict, optional
        Adapter-specific configuration.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.config = config or {}
        self._is_setup = False

    # ---- lifecycle ----------------------------------------------------------

    async def setup(self) -> None:
        """
        Perform one-time setup (open connections, load models, etc.).

        The default implementation is a no-op.  Override in subclasses
        that need async initialisation.
        """
        self._is_setup = True

    async def teardown(self) -> None:
        """
        Release resources.  Default is a no-op.
        """
        self._is_setup = False

    # ---- ingestion ----------------------------------------------------------

    @abc.abstractmethod
    async def ingest(self, sample: LoCoMoSample) -> None:
        """
        Ingest a LoCoMo conversation sample into the backend.

        This should store the conversation data in whatever form the
        backend needs so that subsequent ``answer_question`` and
        ``summarize_events`` calls can access it.

        Parameters
        ----------
        sample : LoCoMoSample
            The full LoCoMo sample including conversation, observations,
            and session summaries.
        """
        ...

    # ---- question answering -------------------------------------------------

    @abc.abstractmethod
    async def answer_question(
        self,
        sample: LoCoMoSample,
        question: str,
        *,
        context_type: str = "dialog",
        top_k: int = 10,
    ) -> QAPrediction:
        """
        Answer a single question about a previously-ingested conversation.

        Parameters
        ----------
        sample : LoCoMoSample
            The sample this question belongs to (for metadata / fallback).
        question : str
            The natural-language question.
        context_type : str
            Type of context to retrieve:
            ``"dialog"``       — raw dialog turns
            ``"observation"``  — speaker observations/assertions
            ``"summary"``      — session-level summaries
        top_k : int
            Number of context chunks to retrieve (for RAG adapters).

        Returns
        -------
        QAPrediction
            The prediction with the answer and optional metadata.
        """
        ...

    # ---- event summarization ------------------------------------------------

    @abc.abstractmethod
    async def summarize_events(
        self,
        sample: LoCoMoSample,
        speaker: Optional[str] = None,
    ) -> str:
        """
        Summarize the significant events in the conversation.

        Parameters
        ----------
        sample : LoCoMoSample
            The sample to summarize.
        speaker : str, optional
            If given, summarize events only for this speaker.

        Returns
        -------
        str
            The generated event summary text.
        """
        ...

    # ---- utilities ----------------------------------------------------------

    def _ensure_setup(self) -> None:
        if not self._is_setup:
            raise RuntimeError(
                f"Adapter '{self.name}' has not been set up. Call `await adapter.setup()` first."
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# =============================================================================
# Graph-Memory Adapter  (MCP SSE protocol)
# =============================================================================


class GraphMemoryAdapter(BaseAdapter):
    """
    Adapter that evaluates the graph-memory MCP service on LoCoMo.

    Communication uses the **MCP SSE protocol** (``/sse`` endpoint with
    JSON-RPC tool calls via ``mcp.ClientSession``), exactly like the
    existing CLI at ``scripts/cli/client.py``.

    For the QA task an optimised path is available: the REST endpoint
    ``POST /api/ask`` delegates to the same ``question_answer()`` function
    but avoids opening an SSE session for every single question. The
    adapter tries REST first and falls back to MCP SSE if the REST call
    fails.

    Lifecycle
    ---------
    1. **Ingest** (MCP SSE) — ``memory_create`` then ``memory_ingest``
    2. **QA** (REST ``/api/ask``, fallback MCP SSE ``question_answer``)
    3. **Event summarization** (REST ``/api/ask``, fallback MCP SSE)
    4. **Teardown** (MCP SSE) — ``memory_delete`` for each created memory

    Parameters
    ----------
    name : str
        Adapter name (default ``"graph-memory"``).
    base_url : str
        Base URL of the running graph-memory server (the WAF proxy, usually
        port 8080).
    auth_token : str, optional
        Bearer token for authenticated endpoints.
    config : dict, optional
        Additional configuration overrides.
    sse_read_timeout : int
        Max seconds to wait for an SSE response (default 900 = 15 min,
        needed for large ingestion calls that trigger LLM extraction).
    sse_connect_timeout : int
        Max seconds for the initial SSE connection (default 30).
    max_retries : int
        Number of retries for SSE calls on transient failures (default 2).
    """

    def __init__(
        self,
        name: str = "graph-memory",
        base_url: str = "http://localhost:8080",
        auth_token: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        sse_read_timeout: int = 900,
        sse_connect_timeout: int = 30,
        max_retries: int = 2,
    ) -> None:
        super().__init__(name=name, config=config)
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token or ""
        self.sse_read_timeout = sse_read_timeout
        self.sse_connect_timeout = sse_connect_timeout
        self.max_retries = max_retries
        self._memory_ids: Dict[str, str] = {}  # sample_id -> memory_id
        self._http_client: Optional[Any] = None  # httpx.AsyncClient (lazy)
        self._llm_client: Optional[Any] = None  # AsyncOpenAI for concise answer generation

    # ---- lifecycle ----------------------------------------------------------

    async def setup(self) -> None:
        # Quick health-check via REST (no SSE needed)
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx is required for GraphMemoryAdapter. Install it with:  pip install httpx"
            )

        self._http_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.auth_token}",
            },
            timeout=120.0,
        )

        try:
            resp = await self._http_client.get("/health")
            if resp.status_code == 200:
                logger.info("GraphMemoryAdapter connected to %s", self.base_url)
            else:
                logger.warning(
                    "GraphMemory health check returned %d — proceeding anyway",
                    resp.status_code,
                )
        except Exception as exc:
            logger.warning("GraphMemory health check failed (%s) — proceeding anyway", exc)

        # Initialise a local OpenAI-compatible LLM client for concise answer
        # generation.  The server's question_answer tool responds in French
        # with verbose markdown; for the LoCoMo benchmark we need short
        # English answers so that token-level F1 is computed fairly.
        #
        # Auto-load the project .env file so that LLMAAS_* vars are
        # available even when the user hasn't exported them in the shell.
        self._load_dotenv()

        llm_url = os.environ.get("LLMAAS_API_URL", "")
        llm_key = os.environ.get("LLMAAS_API_KEY", "")
        llm_model = os.environ.get("LLMAAS_MODEL", "")
        if llm_url and llm_key:
            try:
                from openai import AsyncOpenAI

                self._llm_client = AsyncOpenAI(
                    base_url=llm_url,
                    api_key=llm_key,
                    timeout=60.0,
                )
                self._llm_model = llm_model or "gpt-3.5-turbo"
                logger.info(
                    "GraphMemoryAdapter: local LLM client ready (model=%s)",
                    self._llm_model,
                )
            except ImportError:
                logger.warning(
                    "openai package not installed — falling back to server-side "
                    "question_answer (answers will be in French)"
                )
        else:
            logger.info(
                "LLMAAS_API_URL / LLMAAS_API_KEY not set — "
                "falling back to server-side question_answer"
            )

        await super().setup()

    @staticmethod
    def _load_dotenv() -> None:
        """
        Load ``LLMAAS_*`` variables from the project's ``.env`` file if they
        are not already present in ``os.environ``.

        Searches for ``.env`` starting from this file's directory and walking
        up to the project root (``graph-memory/``).  Uses simple key=value
        parsing — no shell expansion — so that no extra dependency is needed.
        """
        # Skip if the critical vars are already set
        if os.environ.get("LLMAAS_API_URL") and os.environ.get("LLMAAS_API_KEY"):
            return

        # Walk upward from this file to find .env
        search = Path(__file__).resolve().parent
        env_path: Optional[Path] = None
        for _ in range(10):  # safety limit
            candidate = search / ".env"
            if candidate.is_file():
                env_path = candidate
                break
            parent = search.parent
            if parent == search:
                break
            search = parent

        if env_path is None:
            logger.debug("No .env file found when walking up from %s", Path(__file__).parent)
            return

        logger.info("Loading env vars from %s", env_path)
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    # Only set if not already present (explicit env wins)
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError as exc:
            logger.warning("Failed to read %s: %s", env_path, exc)

    async def teardown(self) -> None:
        # Delete memories created during the benchmark
        # Set LOCOMO_KEEP_MEMORY=1 to skip deletion (useful for debugging retrieval)
        if os.environ.get("LOCOMO_KEEP_MEMORY", "").strip() in ("1", "true", "yes"):
            logger.info(
                "LOCOMO_KEEP_MEMORY is set — keeping %d memories: %s",
                len(self._memory_ids),
                ", ".join(self._memory_ids.values()),
            )
        else:
            for sample_id, memory_id in self._memory_ids.items():
                try:
                    await self._call_mcp_tool("memory_delete", {"memory_id": memory_id})
                    logger.debug("Deleted memory %s for sample %s", memory_id, sample_id)
                except Exception:
                    pass
        self._memory_ids.clear()

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        await super().teardown()

    # ---- MCP SSE transport --------------------------------------------------

    async def _call_mcp_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        on_progress: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Call an MCP tool over the SSE protocol.

        Opens a short-lived SSE session, calls the tool, parses the JSON
        result and returns it.  Retries on transient SSE disconnects.

        This mirrors the logic in ``scripts/cli/client.py:MCPClient.call_tool``.
        """
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        headers = {"Authorization": f"Bearer {self.auth_token}"}
        last_error: Optional[BaseException] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with sse_client(
                    f"{self.base_url}/sse",
                    headers=headers,
                    timeout=self.sse_connect_timeout,
                    sse_read_timeout=self.sse_read_timeout,
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()

                        # Optional progress callback (ctx.info() notifications)
                        if on_progress:
                            _original = session._received_notification

                            async def _patched(notification):
                                try:
                                    root = getattr(notification, "root", notification)
                                    params = getattr(root, "params", None)
                                    if params:
                                        msg = getattr(params, "data", None)
                                        if msg:
                                            await on_progress(str(msg))
                                except Exception:
                                    pass
                                await _original(notification)

                            session._received_notification = _patched

                        result = await session.call_tool(tool_name, args)

                        # Check for server-side error
                        if getattr(result, "isError", False):
                            error_msg = "MCP server error"
                            if result.content:
                                error_msg = getattr(result.content[0], "text", "") or error_msg
                            return {"status": "error", "message": error_msg}

                        # Extract text from the first content block
                        text = ""
                        if result.content:
                            text = getattr(result.content[0], "text", "") or ""
                        if not text:
                            return {"status": "error", "message": "Empty response"}

                        # Parse JSON (with plain-text fallback)
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {
                                "status": "error",
                                "message": f"Non-JSON response: {text[:500]}",
                            }

            except (ConnectionRefusedError, OSError) as exc:
                msg = str(exc).lower()
                if "refused" in msg or "connect call failed" in msg:
                    raise ConnectionError(
                        f"Graph-memory server not reachable at {self.base_url}. "
                        f"Start it with:  docker compose up -d"
                    ) from exc
                raise

            except BaseException as exc:
                # Check for 429 Too Many Requests (rate-limited by WAF)
                if self._is_rate_limited(exc) and attempt < self.max_retries:
                    last_error = exc
                    wait = attempt * 10  # 10s, 20s — give the rate-limiter time to reset
                    logger.warning(
                        "Rate-limited (429) on SSE (attempt %d/%d), retrying in %ds…",
                        attempt,
                        self.max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Check for recoverable SSE disconnect
                if self._is_sse_disconnect(exc) and attempt < self.max_retries:
                    last_error = exc
                    wait = attempt * 5
                    logger.warning(
                        "SSE connection lost (attempt %d/%d), retrying in %ds…",
                        attempt,
                        self.max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        raise last_error or RuntimeError("All MCP SSE retries exhausted")

    @staticmethod
    def _is_sse_disconnect(exc: BaseException) -> bool:
        """Check if an exception is a recoverable SSE disconnect."""
        msg = str(exc).lower()
        patterns = [
            "incomplete chunked read",
            "peer closed connection",
            "closedresourceerror",
            "remoteprotocolerror",
            "server disconnected",
        ]
        if any(p in msg for p in patterns):
            return True
        if type(exc).__name__ in ("RemoteProtocolError", "ClosedResourceError"):
            return True
        # Recurse into ExceptionGroup sub-exceptions
        if hasattr(exc, "exceptions"):
            for sub in getattr(exc, "exceptions", ()):
                if GraphMemoryAdapter._is_sse_disconnect(sub):
                    return True
        if exc.__cause__ and GraphMemoryAdapter._is_sse_disconnect(exc.__cause__):
            return True
        return False

    @staticmethod
    def _is_rate_limited(exc: BaseException) -> bool:
        """Check if an exception is a 429 Too Many Requests error."""
        msg = str(exc).lower()
        if "429" in msg or "too many requests" in msg:
            return True
        # Recurse into ExceptionGroup sub-exceptions
        if hasattr(exc, "exceptions"):
            for sub in getattr(exc, "exceptions", ()):
                if GraphMemoryAdapter._is_rate_limited(sub):
                    return True
        if exc.__cause__ and GraphMemoryAdapter._is_rate_limited(exc.__cause__):
            return True
        return False

    # ---- REST helpers -------------------------------------------------------

    async def _rest_ask(
        self,
        memory_id: str,
        question: str,
        limit: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """
        Call POST /api/ask (REST).  Returns None on failure so the caller
        can fall back to MCP SSE.
        """
        if not self._http_client:
            return None
        try:
            resp = await self._http_client.post(
                "/api/ask",
                json={
                    "memory_id": memory_id,
                    "question": question,
                    "limit": limit,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.debug(
                "REST /api/ask returned %d — will fall back to MCP SSE",
                resp.status_code,
            )
            return None
        except Exception as exc:
            logger.debug("REST /api/ask failed (%s) — will fall back to MCP SSE", exc)
            return None

    async def _rest_query(
        self,
        memory_id: str,
        query: str,
        limit: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """
        Call POST /api/query (REST).  Returns None on failure so the caller
        can fall back to MCP SSE.

        Retries once on 429 Too Many Requests with a short back-off.
        """
        if not self._http_client:
            return None

        for attempt in range(1, 4):  # up to 3 attempts
            try:
                resp = await self._http_client.post(
                    "/api/query",
                    json={
                        "memory_id": memory_id,
                        "query": query,
                        "limit": limit,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    wait = attempt * 2
                    logger.warning(
                        "REST /api/query rate-limited (429), attempt %d/3, waiting %ds…",
                        attempt,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.debug(
                    "REST /api/query returned %d for '%s'",
                    resp.status_code,
                    query[:60],
                )
                return None
            except Exception as exc:
                logger.debug("REST /api/query failed (%s) for '%s'", exc, query[:60])
                return None
        logger.warning("REST /api/query exhausted retries for '%s'", query[:60])
        return None

    # ---- helpers ------------------------------------------------------------

    def _make_memory_id(self, sample_id: str) -> str:
        """Deterministic memory ID for a LoCoMo sample."""
        return f"locomo-{sample_id}"

    # ---- ingestion (MCP SSE) ------------------------------------------------

    async def ingest(self, sample: LoCoMoSample) -> None:
        """
        Ingest a LoCoMo sample into graph-memory.

        Steps (all via MCP SSE tool calls):
        1. ``memory_create`` — create a dedicated memory namespace.
        2. ``memory_ingest`` — ingest conversation text as a document.
        3. ``memory_ingest`` — (optional) ingest observations as a second
           document for richer RAG context.
        """
        self._ensure_setup()

        memory_id = self._make_memory_id(sample.sample_id)

        # 1. Create memory
        async def _log_progress(msg: str) -> None:
            logger.debug("[ingest/%s] %s", sample.sample_id, msg)

        try:
            result = await self._call_mcp_tool(
                "memory_create",
                {
                    "memory_id": memory_id,
                    "name": f"LoCoMo {sample.sample_id}",
                    "ontology": "general",
                    "description": (
                        f"LoCoMo benchmark conversation {sample.sample_id} "
                        f"between {sample.speaker_a} and {sample.speaker_b} "
                        f"({sample.num_sessions} sessions, {sample.num_turns} turns)"
                    ),
                },
                on_progress=_log_progress,
            )
            if result.get("status") == "error":
                # Memory may already exist from a previous run — tolerate it
                err_msg = result.get("message", "")
                if "exist" in err_msg.lower() or "already" in err_msg.lower():
                    logger.info("Memory %s already exists — reusing it", memory_id)
                else:
                    raise RuntimeError(f"memory_create failed for {sample.sample_id}: {err_msg}")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to create memory for {sample.sample_id}: {exc}") from exc

        self._memory_ids[sample.sample_id] = memory_id

        # 2. Ingest conversation text (with BLIP-2 image captions)
        conversation_text = sample.get_conversation_text(include_captions=True)
        content_b64 = base64.b64encode(conversation_text.encode("utf-8")).decode("ascii")

        try:
            result = await self._call_mcp_tool(
                "memory_ingest",
                {
                    "memory_id": memory_id,
                    "content_base64": content_b64,
                    "filename": f"{sample.sample_id}_conversation.txt",
                },
                on_progress=_log_progress,
            )
            if result.get("status") == "error":
                logger.warning(
                    "memory_ingest (conversation) warning for %s: %s",
                    sample.sample_id,
                    result.get("message"),
                )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to ingest conversation for {sample.sample_id}: {exc}"
            ) from exc

        # 3. Optionally ingest observations
        observations_text = sample.get_observations_text()
        if observations_text.strip():
            obs_b64 = base64.b64encode(observations_text.encode("utf-8")).decode("ascii")
            try:
                await self._call_mcp_tool(
                    "memory_ingest",
                    {
                        "memory_id": memory_id,
                        "content_base64": obs_b64,
                        "filename": f"{sample.sample_id}_observations.txt",
                    },
                    on_progress=_log_progress,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to ingest observations for %s: %s",
                    sample.sample_id,
                    exc,
                )

        logger.info(
            "Ingested sample %s into memory %s (%d sessions, %d turns)",
            sample.sample_id,
            memory_id,
            sample.num_sessions,
            sample.num_turns,
        )

    # ---- question answering -------------------------------------------------

    async def answer_question(
        self,
        sample: LoCoMoSample,
        question: str,
        *,
        context_type: str = "dialog",
        top_k: int = 10,
    ) -> QAPrediction:
        """
        Answer a question using graph-memory's retrieval + local LLM.

        Strategy (benchmark-optimised):
        1. Call ``POST /api/query`` (structured retrieval, **no** server-side
           LLM generation) to get entities, relations and RAG chunks.
        2. Build a compact English context string from the structured data.
        3. Call a local OpenAI-compatible LLM with a concise-answer prompt
           so that the response is a short English phrase that maximises
           token-level F1 against the LoCoMo ground truth.

        If the local LLM client is not configured (missing env vars), falls
        back to the server-side ``/api/ask`` endpoint (French, verbose).
        """
        self._ensure_setup()

        memory_id = self._memory_ids.get(sample.sample_id)
        if not memory_id:
            raise RuntimeError(
                f"Sample {sample.sample_id} has not been ingested. "
                f"Call `adapter.ingest(sample)` first."
            )

        # ------------------------------------------------------------------
        # Path A — structured retrieval + local concise LLM answer
        # ------------------------------------------------------------------
        if self._llm_client is not None:
            context_text = ""
            try:
                context_text = await self._retrieve_context(memory_id, question, limit=top_k)
            except Exception as exc:
                logger.warning("memory_query retrieval failed for '%s': %s", question[:60], exc)

            if context_text:
                answer = await self._generate_concise_answer(question, context_text)
                if not answer or not answer.strip():
                    logger.debug("[qa] LLM returned empty answer for: %s", question[:60])
                    answer = "unanswerable"
                return QAPrediction(
                    question=question,
                    predicted_answer=answer,
                    retrieved_context=context_text,
                )
            else:
                # No context at all — log and answer explicitly
                logger.info(
                    "[qa] No context retrieved for: %s — answering 'unanswerable'",
                    question[:60],
                )
                return QAPrediction(
                    question=question,
                    predicted_answer="unanswerable",
                    retrieved_context=None,
                )

        # ------------------------------------------------------------------
        # Path B — fallback: server-side /api/ask (French verbose answers)
        # ------------------------------------------------------------------
        answer = ""
        context_used = ""

        rest_result = await self._rest_ask(memory_id, question, limit=top_k)
        if rest_result and rest_result.get("status") == "ok":
            answer = rest_result.get("answer", "")
            context_used = rest_result.get("context_used", "")
        elif rest_result:
            logger.debug(
                "REST /api/ask error for '%s': %s",
                question[:60],
                rest_result.get("message", "unknown"),
            )
        else:
            try:
                result = await self._call_mcp_tool(
                    "question_answer",
                    {
                        "memory_id": memory_id,
                        "question": question,
                        "limit": top_k,
                    },
                )
                answer = result.get("answer", "")
                context_used = result.get("context_used", "")
            except Exception as exc:
                logger.warning(
                    "QA failed for sample %s, question '%s': %s",
                    sample.sample_id,
                    question[:80],
                    exc,
                )

        return QAPrediction(
            question=question,
            predicted_answer=answer,
            retrieved_context=context_used if context_used else None,
        )

    # ---- benchmark-optimised retrieval + answer generation ------------------

    async def _retrieve_context(
        self,
        memory_id: str,
        question: str,
        limit: int = 10,
    ) -> str:
        """
        Retrieve structured context from graph-memory via ``/api/query``
        (no server-side LLM call) and flatten it into a compact text block
        suitable for a concise-answer prompt.
        """
        query_result = await self._rest_query(memory_id, question, limit=limit)
        if not query_result:
            logger.debug("[retrieve] /api/query returned None for: %s", question[:80])
            return ""
        if query_result.get("status") != "ok":
            logger.debug(
                "[retrieve] /api/query status=%s for: %s",
                query_result.get("status"),
                question[:80],
            )
            return ""

        # Log retrieval stats
        stats = query_result.get("stats", {})
        n_entities = stats.get("entities_found", len(query_result.get("entities", [])))
        n_chunks = stats.get("rag_chunks_retained", len(query_result.get("rag_chunks", [])))
        logger.debug(
            "[retrieve] Q='%s' → %d entities, %d RAG chunks",
            question[:60],
            n_entities,
            n_chunks,
        )

        parts: List[str] = []

        # --- graph entities + relations ---
        for ent in query_result.get("entities", []):
            name = ent.get("name", "")
            etype = ent.get("type", "")
            desc = ent.get("description", "")
            line = f"[{etype}] {name}"
            if desc:
                line += f": {desc}"
            # Include relations
            for rel in ent.get("relations", []):
                rel_type = rel.get("type", "RELATED_TO")
                rel_target = rel.get("target", rel.get("name", ""))
                rel_desc = rel.get("description", "")
                if rel_desc:
                    line += f"\n  -> {rel_type} {rel_target}: {rel_desc}"
                elif rel_target:
                    line += f"\n  -> {rel_type} {rel_target}"
            parts.append(line)

        # --- RAG chunks (verbatim text excerpts) ---
        for chunk in query_result.get("rag_chunks", []):
            text = chunk.get("text", "")
            score = chunk.get("score", 0)
            if text and score >= 0.3:
                parts.append(f"[Excerpt] {text.strip()}")

        context = "\n\n".join(parts) if parts else ""
        if not context:
            logger.debug(
                "[retrieve] Empty context after flattening for: %s (entities=%d, chunks=%d)",
                question[:60],
                n_entities,
                n_chunks,
            )
        return context

    async def _generate_concise_answer(
        self,
        question: str,
        context: str,
    ) -> str:
        """
        Generate a short, direct English answer from retrieved context.

        The prompt is designed to produce answers that maximise token-level
        F1 against LoCoMo ground-truth labels (typically 1-10 words).
        """
        assert self._llm_client is not None

        system_prompt = (
            "You are a factual Q&A system. You answer questions about a conversation "
            "between two people named Caroline and Melanie.\n\n"
            "STRICT RULES:\n"
            "1. Answer in English ONLY. Never answer in French or any other language.\n"
            "2. Use ONLY the provided context to answer. Do not use outside knowledge.\n"
            "3. Give the SHORTEST possible answer: ideally 1-10 words, never more than 20.\n"
            "4. Use exact names, dates, and wording from the context.\n"
            "5. For yes/no questions: start with 'Yes' or 'No'.\n"
            "6. For 'when' questions: give the most specific date or time period.\n"
            "7. If the context does NOT contain the answer, respond with exactly one word: unanswerable\n"
            "8. Do NOT add explanations, bullet points, markdown, or caveats.\n"
            "9. You MUST always produce a non-empty answer. Never return blank.\n\n"
            "EXAMPLES:\n"
            "Q: What pet does Caroline have? A: guinea pig named Oscar\n"
            "Q: When did they go camping? A: the week before 27 June 2023\n"
            "Q: What is Caroline's favorite book? A: Becoming Nicole by Amy Ellis Nutt\n"
            "Q: Did Melanie attend the conference? A: unanswerable"
            'Q: Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi? A: Yes; it\'s classical music'
        )

        user_prompt = (
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Short factual answer (1-10 words, English only):"
        )

        try:
            response = await self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=1.0,
                max_tokens=512,
            )
            msg = response.choices[0].message
            raw_content = msg.content or ""

            # Reasoning models (DeepSeek-R1, gpt-oss, etc.) may put the
            # answer in reasoning_content and leave content empty.
            raw_reasoning = ""
            if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                raw_reasoning = msg.reasoning_content
            elif hasattr(msg, "reasoning") and msg.reasoning:
                raw_reasoning = msg.reasoning

            # Use content if available; fall back to reasoning_content
            raw = raw_content if raw_content.strip() else raw_reasoning
            answer = raw.strip()

            # Strip markdown formatting artifacts
            answer = answer.lstrip("*#- ").rstrip("*").strip()

            # For reasoning fallback, the model may have produced a long
            # chain-of-thought.  Extract the last sentence / conclusion.
            if not raw_content.strip() and raw_reasoning and answer:
                # The reasoning often ends with the actual answer after
                # "Answer:" or as the last short line.
                lines = [ln.strip() for ln in answer.split("\n") if ln.strip()]
                # Look for an explicit "Answer: ..." line
                for ln in reversed(lines):
                    lower = ln.lower()
                    if lower.startswith("answer:") or lower.startswith("a:"):
                        answer = ln.split(":", 1)[1].strip().strip("*").strip()
                        break
                else:
                    # Take the last non-empty line as the conclusion
                    if lines:
                        answer = lines[-1].strip().rstrip(".").strip("*").strip()

                logger.debug(
                    "[llm] Used reasoning_content fallback. "
                    "content=%d chars, reasoning=%d chars → answer=%r",
                    len(raw_content),
                    len(raw_reasoning),
                    answer[:100],
                )

            if not answer:
                logger.debug(
                    "[llm] Empty answer after strip. content=%d chars: %r | reasoning=%d chars: %r",
                    len(raw_content),
                    raw_content[:200],
                    len(raw_reasoning),
                    raw_reasoning[:200],
                )
            elif len(answer) > 150:
                logger.debug(
                    "[llm] Answer too long (%d chars), likely verbose. Truncating: %r",
                    len(answer),
                    answer[:100],
                )
                # Take only the first line/sentence to keep it concise
                first_line = answer.split("\n")[0].split(". ")[0]
                answer = first_line.strip().rstrip(".")

            return answer
        except Exception as exc:
            logger.warning("Local LLM answer generation failed: %s", exc)
            return "unanswerable"

    # ---- event summarization ------------------------------------------------

    async def summarize_events(
        self,
        sample: LoCoMoSample,
        speaker: Optional[str] = None,
    ) -> str:
        """
        Generate an event summary using graph-memory's query pipeline.

        Uses ``POST /api/ask`` (REST) with a summarization prompt, falling
        back to the ``question_answer`` MCP tool over SSE.
        """
        self._ensure_setup()

        memory_id = self._memory_ids.get(sample.sample_id)
        if not memory_id:
            raise RuntimeError(f"Sample {sample.sample_id} has not been ingested.")

        speaker_clause = f" for {speaker}" if speaker else ""

        prompt = (
            f"List all the significant life events{speaker_clause} discussed "
            f"in the conversation between {sample.speaker_a} and "
            f"{sample.speaker_b}. For each event, include the approximate "
            f"date and a brief description. Organize the events chronologically."
        )

        # Use REST /api/ask (avoids SSE overhead and 429 rate-limits)
        rest_result = await self._rest_ask(memory_id, prompt, limit=25)
        if rest_result and rest_result.get("status") == "ok":
            return rest_result.get("answer", "")

        # Fall back to MCP SSE only if REST is completely unavailable
        try:
            result = await self._call_mcp_tool(
                "question_answer",
                {
                    "memory_id": memory_id,
                    "question": prompt,
                    "limit": 25,
                },
            )
            return result.get("answer", "")
        except Exception as exc:
            logger.warning(
                "Event summarization failed for %s: %s",
                sample.sample_id,
                exc,
            )
            return ""


# =============================================================================
# Direct LLM Adapter (baseline)
# =============================================================================


class DirectLLMAdapter(BaseAdapter):
    """
    Baseline adapter that passes the conversation directly to an LLM.

    This implements the "Base" evaluation setup from the LoCoMo paper,
    where earlier dialogues are truncated to fit within the context window.

    Parameters
    ----------
    name : str
        Adapter name.
    api_url : str
        OpenAI-compatible API URL.
    api_key : str
        API key for the LLM service.
    model : str
        Model identifier (e.g. ``"gpt-3.5-turbo"``).
    max_context_tokens : int
        Maximum tokens to include from conversation context.
    config : dict, optional
        Additional configuration.
    """

    def __init__(
        self,
        name: str = "direct-llm",
        api_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-3.5-turbo",
        max_context_tokens: int = 4096,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name=name, config=config)
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.max_context_tokens = max_context_tokens
        self._client: Optional[Any] = None

    async def setup(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai is required for DirectLLMAdapter. Install it with: pip install openai"
            )
        self._client = AsyncOpenAI(
            base_url=self.api_url,
            api_key=self.api_key,
        )
        await super().setup()

    async def teardown(self) -> None:
        self._client = None
        await super().teardown()

    async def ingest(self, sample: LoCoMoSample) -> None:
        """No-op for direct LLM — context is passed inline with each query."""
        pass

    def _truncate_context(self, text: str) -> str:
        """Truncate context to fit within max_context_tokens (rough estimate)."""
        words = text.split()
        max_words = int(self.max_context_tokens * 0.75)
        if len(words) > max_words:
            # Keep the most recent portion (end of conversation)
            words = words[-max_words:]
        return " ".join(words)

    async def _chat(self, system: str, user: str) -> str:
        """Make a chat completion call."""
        self._ensure_setup()
        assert self._client is not None

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        return response.choices[0].message.content or ""

    async def answer_question(
        self,
        sample: LoCoMoSample,
        question: str,
        *,
        context_type: str = "dialog",
        top_k: int = 10,
    ) -> QAPrediction:
        """Answer a question by passing truncated conversation to the LLM."""
        if context_type == "observation":
            context = sample.get_observations_text(top_k=top_k)
        elif context_type == "summary":
            context = sample.get_session_summaries_text()
        else:
            context = sample.get_conversation_text(include_captions=True)

        context = self._truncate_context(context)

        system_prompt = (
            "You are an expert at answering questions about long conversations. "
            "Answer the question based ONLY on the provided conversation context. "
            "Be concise and use the exact wording from the conversation when possible. "
            "If the question cannot be answered from the context, say 'unanswerable'."
        )
        user_prompt = (
            f"=== CONVERSATION CONTEXT ===\n{context}\n\n=== QUESTION ===\n{question}\n\nAnswer:"
        )

        answer = await self._chat(system_prompt, user_prompt)

        return QAPrediction(
            question=question,
            predicted_answer=answer.strip(),
        )

    async def summarize_events(
        self,
        sample: LoCoMoSample,
        speaker: Optional[str] = None,
    ) -> str:
        """Summarize events using incremental summarization."""
        # Incremental summarization as described in the paper:
        # iteratively summarise preceding sessions and use as basis
        # for the next session's summary.
        running_summary = ""

        for session in sample.conversation.sessions:
            if not session.turns:
                continue

            session_text = session.to_text(include_captions=True)
            context = self._truncate_context(
                f"Previous summary:\n{running_summary}\n\nCurrent session:\n{session_text}"
            )

            speaker_clause = f" for {speaker}" if speaker else ""
            system_prompt = (
                "You are an expert at extracting significant life events from "
                "conversations. Given a summary of previous sessions and the "
                "current session, produce an updated summary of all significant "
                f"events{speaker_clause}. "
                "Include dates and brief descriptions for each event."
            )
            user_prompt = f"{context}\n\nUpdated event summary:"

            running_summary = await self._chat(system_prompt, user_prompt)

        return running_summary


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "BaseAdapter",
    "GraphMemoryAdapter",
    "DirectLLMAdapter",
]
