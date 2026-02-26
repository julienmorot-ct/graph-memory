#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LoCoMo Benchmark Runner — CLI Entry Point.

Run the LoCoMo (Long-term Conversational Memory) benchmark against the
graph-memory service or a direct LLM baseline.

Reference:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

Usage examples
--------------

    # Run QA task with graph-memory adapter (all categories)
    python -m benchmarks.locomo.run_benchmark \\
        --data data/locomo10.json \\
        --adapter graph-memory \\
        --task qa \\
        --graph-memory-url http://localhost:8002

    # Run QA task with direct LLM baseline (truncated context)
    python -m benchmarks.locomo.run_benchmark \\
        --data data/locomo10.json \\
        --adapter direct-llm \\
        --task qa \\
        --llm-model gpt-3.5-turbo \\
        --max-context 4096

    # Run event summarization with graph-memory
    python -m benchmarks.locomo.run_benchmark \\
        --data data/locomo10.json \\
        --adapter graph-memory \\
        --task event-summarization

    # Run both tasks on a specific sample
    python -m benchmarks.locomo.run_benchmark \\
        --data data/locomo10.json \\
        --adapter graph-memory \\
        --task all \\
        --samples conv-26

    # Just print dataset statistics
    python -m benchmarks.locomo.run_benchmark \\
        --data data/locomo10.json \\
        --stats-only

Environment variables
---------------------
    GRAPH_MEMORY_URL     — Base URL of the graph-memory MCP server
    GRAPH_MEMORY_TOKEN   — Bearer token for graph-memory auth
    LLMAAS_API_URL       — OpenAI-compatible API URL for direct LLM adapter
    LLMAAS_API_KEY       — API key for the LLM service
    LLMAAS_MODEL         — Model identifier (e.g. gpt-3.5-turbo)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so that ``benchmarks.*`` imports work
# when running the script directly.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent  # graph-memory/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchmarks.locomo.data_loader import LoCoMoDataset
from benchmarks.locomo.models import BenchmarkResult, QACategory

logger = logging.getLogger("locomo.benchmark")


# ===================================================================
# CLI argument parser
# ===================================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="locomo-benchmark",
        description=(
            "Run the LoCoMo long-term conversational memory benchmark "
            "against graph-memory or a direct LLM baseline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- required ---
    p.add_argument(
        "--data",
        type=str,
        required=True,
        help="Path to the LoCoMo JSON file (e.g. data/locomo10.json).",
    )

    # --- task selection ---
    p.add_argument(
        "--task",
        type=str,
        choices=["qa", "event-summarization", "all"],
        default="qa",
        help="Which evaluation task to run (default: qa).",
    )

    # --- adapter selection ---
    p.add_argument(
        "--adapter",
        type=str,
        choices=["graph-memory", "direct-llm"],
        default="graph-memory",
        help="Which adapter to use (default: graph-memory).",
    )

    # --- sample filtering ---
    p.add_argument(
        "--samples",
        type=str,
        nargs="*",
        default=None,
        help=(
            "Specific sample IDs to evaluate (e.g. conv-26 conv-30). "
            "If omitted, all samples in the dataset are used."
        ),
    )

    # --- QA-specific options ---
    qa_group = p.add_argument_group("QA task options")
    qa_group.add_argument(
        "--context-type",
        type=str,
        choices=["dialog", "observation", "summary"],
        default="dialog",
        help="Type of retrieval context for RAG-based QA (default: dialog).",
    )
    qa_group.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of context chunks to retrieve (default: 10).",
    )
    qa_group.add_argument(
        "--qa-categories",
        type=int,
        nargs="*",
        default=None,
        help=(
            "QA categories to evaluate (1-5). "
            "1=single-hop, 2=temporal, 3=commonsense, 4=open-domain, 5=adversarial. "
            "If omitted, all categories are evaluated."
        ),
    )

    # --- Event summarization options ---
    evt_group = p.add_argument_group("Event summarization options")
    evt_group.add_argument(
        "--per-speaker",
        action="store_true",
        default=False,
        help="Evaluate event summarization per-speaker (default: combined).",
    )

    # --- Graph-memory adapter options ---
    gm_group = p.add_argument_group("Graph-memory adapter options")
    gm_group.add_argument(
        "--graph-memory-url",
        type=str,
        default=None,
        help=(
            "Base URL of the graph-memory MCP server. "
            "Falls back to GRAPH_MEMORY_URL env var, then http://localhost:8080."
        ),
    )
    gm_group.add_argument(
        "--graph-memory-token",
        type=str,
        default=None,
        help="Bearer token for graph-memory. Falls back to GRAPH_MEMORY_TOKEN env var.",
    )

    # --- Direct LLM adapter options ---
    llm_group = p.add_argument_group("Direct LLM adapter options")
    llm_group.add_argument(
        "--llm-api-url",
        type=str,
        default=None,
        help="OpenAI-compatible API URL. Falls back to LLMAAS_API_URL env var.",
    )
    llm_group.add_argument(
        "--llm-api-key",
        type=str,
        default=None,
        help="API key for the LLM. Falls back to LLMAAS_API_KEY env var.",
    )
    llm_group.add_argument(
        "--llm-model",
        type=str,
        default=None,
        help=(
            "Model identifier (e.g. gpt-3.5-turbo, gpt-4-turbo). "
            "Falls back to LLMAAS_MODEL env var."
        ),
    )
    llm_group.add_argument(
        "--max-context",
        type=int,
        default=4096,
        help="Max context tokens for the direct LLM adapter (default: 4096).",
    )

    # --- output options ---
    out_group = p.add_argument_group("Output options")
    out_group.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write JSON results to (default: stdout summary only).",
    )
    out_group.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Log individual question / event results.",
    )
    out_group.add_argument(
        "--stats-only",
        action="store_true",
        default=False,
        help="Only print dataset statistics and exit (no evaluation).",
    )
    out_group.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        help="Max concurrent adapter calls during QA evaluation (default: 1).",
    )

    return p


# ===================================================================
# Adapter factory
# ===================================================================


def _create_adapter(args: argparse.Namespace) -> Any:
    """Instantiate the selected adapter based on CLI args."""
    if args.adapter == "graph-memory":
        from benchmarks.locomo.adapters import GraphMemoryAdapter

        base_url = args.graph_memory_url or os.environ.get(
            "GRAPH_MEMORY_URL", "http://localhost:8080"
        )
        token = args.graph_memory_token or os.environ.get("GRAPH_MEMORY_TOKEN")

        return GraphMemoryAdapter(
            name="graph-memory",
            base_url=base_url,
            auth_token=token,
        )

    elif args.adapter == "direct-llm":
        from benchmarks.locomo.adapters import DirectLLMAdapter

        api_url = args.llm_api_url or os.environ.get("LLMAAS_API_URL", "https://api.openai.com/v1")
        api_key = args.llm_api_key or os.environ.get("LLMAAS_API_KEY", "")
        model = args.llm_model or os.environ.get("LLMAAS_MODEL", "gpt-3.5-turbo")

        if not api_key:
            logger.warning(
                "No API key provided for direct-llm adapter. "
                "Set --llm-api-key or LLMAAS_API_KEY env var."
            )

        return DirectLLMAdapter(
            name=f"direct-llm-{model}",
            api_url=api_url,
            api_key=api_key,
            model=model,
            max_context_tokens=args.max_context,
        )

    else:
        raise ValueError(f"Unknown adapter: {args.adapter}")


# ===================================================================
# Task execution
# ===================================================================


async def run_qa_task(
    dataset: LoCoMoDataset,
    adapter: Any,
    args: argparse.Namespace,
) -> BenchmarkResult:
    """Run the Question Answering task."""
    from benchmarks.locomo.tasks.question_answering import QATask

    categories = None
    if args.qa_categories:
        categories = [QACategory(c) for c in args.qa_categories]

    task = QATask(
        adapter=adapter,
        context_type=args.context_type,
        top_k=args.top_k,
        categories=categories,
        max_concurrent=args.max_concurrent,
        verbose=args.verbose,
    )

    result = await task._run_async(dataset, ingest=True)

    # Print summary table
    print()
    print("=" * 70)
    print("  LoCoMo QA Task Results")
    print("=" * 70)
    print(task.summary_table())
    print()

    return result


async def run_event_summarization_task(
    dataset: LoCoMoDataset,
    adapter: Any,
    args: argparse.Namespace,
) -> BenchmarkResult:
    """Run the Event Summarization task."""
    from benchmarks.locomo.tasks.event_summarization import EventSummarizationTask

    task = EventSummarizationTask(
        adapter=adapter,
        per_speaker=args.per_speaker,
        verbose=args.verbose,
    )

    result = await task._run_async(dataset, ingest=True)

    # Print summary table
    print()
    print("=" * 70)
    print("  LoCoMo Event Summarization Results")
    print("=" * 70)
    print(task.summary_table())
    print()

    if args.verbose:
        print(task.detailed_report())
        print()

    return result


# ===================================================================
# Result serialisation
# ===================================================================


def _result_to_dict(result: BenchmarkResult) -> Dict[str, Any]:
    """Convert a BenchmarkResult to a JSON-serialisable dict."""
    return {
        "benchmark_name": result.benchmark_name,
        "model_name": result.model_name,
        "adapter_type": result.adapter_type,
        "overall_scores": result.overall_scores,
        "config": result.config,
        "task_results": [
            {
                "sample_id": tr.sample_id,
                "task_name": tr.task_name,
                "overall_score": tr.overall_score,
                "category_scores": tr.category_scores,
                "num_predictions": tr.num_predictions,
                "metadata": tr.metadata,
            }
            for tr in result.task_results
        ],
    }


def _merge_results(results: List[BenchmarkResult]) -> Dict[str, Any]:
    """Merge multiple BenchmarkResult objects into a single output dict."""
    merged: Dict[str, Any] = {
        "benchmark": "LoCoMo",
        "tasks": {},
    }
    for result in results:
        task_name = result.task_results[0].task_name if result.task_results else "unknown"
        merged["tasks"][task_name] = _result_to_dict(result)
    return merged


# ===================================================================
# Main entry point
# ===================================================================


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    # --- Load dataset ---
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: Data file not found: {data_path}", file=sys.stderr)
        return 1

    print(f"Loading LoCoMo dataset from {data_path}…")
    dataset = LoCoMoDataset.from_file(data_path)

    # --- Filter samples ---
    if args.samples:
        missing = [s for s in args.samples if s not in dataset]
        if missing:
            print(
                f"WARNING: Sample(s) not found in dataset: {missing}",
                file=sys.stderr,
            )
        dataset = dataset.filter_by_ids(args.samples)
        if len(dataset) == 0:
            print("ERROR: No matching samples found.", file=sys.stderr)
            return 1

    # --- Stats only ---
    if args.stats_only:
        dataset.print_stats()
        return 0

    dataset.print_stats()
    print()

    # --- Create adapter ---
    adapter = _create_adapter(args)

    # --- Run tasks ---
    all_results: List[BenchmarkResult] = []
    tasks_to_run: List[str] = []

    if args.task in ("qa", "all"):
        tasks_to_run.append("qa")
    if args.task in ("event-summarization", "all"):
        tasks_to_run.append("event-summarization")

    t0 = time.monotonic()

    for task_name in tasks_to_run:
        print(f"\n{'=' * 70}")
        print(f"  Running task: {task_name}")
        print(f"  Adapter:      {adapter.name}")
        print(f"  Samples:      {len(dataset)}")
        print(f"{'=' * 70}\n")

        if task_name == "qa":
            result = await run_qa_task(dataset, adapter, args)
        elif task_name == "event-summarization":
            result = await run_event_summarization_task(dataset, adapter, args)
        else:
            print(f"Unknown task: {task_name}", file=sys.stderr)
            continue

        all_results.append(result)

    total_elapsed = time.monotonic() - t0

    # --- Print overall summary ---
    print()
    print("=" * 70)
    print("  LoCoMo Benchmark — Overall Summary")
    print("=" * 70)
    print(f"  Adapter:        {args.adapter}")
    print(f"  Tasks run:      {', '.join(tasks_to_run)}")
    print(f"  Samples:        {len(dataset)}")
    print(f"  Total time:     {total_elapsed:.1f}s")
    print()

    for result in all_results:
        task_label = result.task_results[0].task_name if result.task_results else "unknown"
        print(f"  [{task_label}]")
        for key, val in sorted(result.overall_scores.items()):
            print(f"    {key:30s}  {val:.4f}")
        print()

    print("=" * 70)

    # --- Write JSON output ---
    if args.output:
        output_path = Path(args.output)
        output_data = _merge_results(all_results)
        output_data["total_elapsed_seconds"] = round(total_elapsed, 2)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\nResults written to {output_path}")

    return 0


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # --- Configure logging ---
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Quieten noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nBenchmark interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.exception("Benchmark failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
