# -*- coding: utf-8 -*-
"""
LoCoMo Question Answering Task.

Implements the QA evaluation task from the LoCoMo benchmark, which measures
a system's ability to recall and reason over very long-term conversational
context across 5 distinct reasoning categories:

    1. Single-hop:       Answer from a single session
    2. Temporal:         Time-related reasoning
    3. Commonsense:      Integration with world knowledge
    4. Open-domain:      Multi-hop synthesis across sessions
    5. Adversarial:      Unanswerable / speaker-swapped questions

Reference:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

Usage:
    from benchmarks.locomo.tasks.question_answering import QATask
    from benchmarks.locomo.adapters import GraphMemoryAdapter
    from benchmarks.locomo.data_loader import LoCoMoDataset

    dataset = LoCoMoDataset.from_file("data/locomo10.json")
    adapter = GraphMemoryAdapter(base_url="http://localhost:8002")
    task = QATask(adapter=adapter)

    await task.setup()
    result = await task.evaluate(dataset[0])
    print(result.summary())
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from benchmarks.locomo.metrics import (
    compute_exact_match,
    compute_f1,
    compute_qa_metrics,
    evaluate_adversarial,
)
from benchmarks.locomo.models import (
    BenchmarkResult,
    EventPrediction,
    LoCoMoSample,
    QAAnnotation,
    QACategory,
    QAPrediction,
    TaskResult,
)

logger = logging.getLogger(__name__)

# Category label map for consistent reporting
_CATEGORY_LABELS: Dict[int, str] = {
    1: "single_hop",
    2: "temporal",
    3: "commonsense",
    4: "open_domain",
    5: "adversarial",
}


class QATask:
    """
    LoCoMo Question Answering evaluation task.

    Evaluates a memory system's ability to answer questions about very
    long-term conversations.  Questions are classified into 5 reasoning
    categories, and the primary metric is the token-level F1 score with
    normalised answers (following the original paper).

    Parameters
    ----------
    adapter : BaseAdapter
        The adapter connecting to the memory / LLM system under test.
    context_type : str
        Type of retrieval context to use:
        ``"dialog"``       — raw dialog turns (default)
        ``"observation"``  — speaker observations / assertions
        ``"summary"``      — session-level summaries
    top_k : int
        Number of context chunks to retrieve (for RAG-based adapters).
    categories : list of QACategory, optional
        If provided, only evaluate questions in these categories.
        Default is all 5 categories.
    max_concurrent : int
        Maximum number of concurrent QA requests to the adapter.
    verbose : bool
        If ``True``, log individual question results.
    """

    TASK_NAME = "question_answering"

    def __init__(
        self,
        adapter: Any,  # BaseAdapter — use Any to avoid circular import issues
        context_type: str = "dialog",
        top_k: int = 10,
        categories: Optional[Sequence[QACategory]] = None,
        max_concurrent: int = 5,
        verbose: bool = False,
    ) -> None:
        self.adapter = adapter
        self.context_type = context_type
        self.top_k = top_k
        self.categories = set(categories) if categories else None
        self.max_concurrent = max_concurrent
        self.verbose = verbose

        # Internal state
        self._predictions: List[QAPrediction] = []
        self._is_setup = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Set up the adapter (if not already done)."""
        if not self._is_setup:
            await self.adapter.setup()
            self._is_setup = True

    async def teardown(self) -> None:
        """Tear down the adapter."""
        if self._is_setup:
            await self.adapter.teardown()
            self._is_setup = False

    # ------------------------------------------------------------------
    # Single question evaluation
    # ------------------------------------------------------------------

    async def _evaluate_single_question(
        self,
        sample: LoCoMoSample,
        qa: QAAnnotation,
        semaphore: asyncio.Semaphore,
        question_index: int = 0,
        total_questions: int = 0,
    ) -> QAPrediction:
        """
        Evaluate a single QA pair and return a scored prediction.

        For adversarial questions (category 5), uses the specialised
        adversarial evaluation that checks whether the model was tricked
        into providing the wrong-speaker answer.
        """
        progress_prefix = f"[{question_index}/{total_questions}]" if total_questions else ""

        async with semaphore:
            logger.info(
                "%s Asking: %s",
                progress_prefix,
                qa.question[:100],
            )
            try:
                prediction = await self.adapter.answer_question(
                    sample=sample,
                    question=qa.question,
                    context_type=self.context_type,
                    top_k=self.top_k,
                )
            except Exception as exc:
                logger.error(
                    "%s Adapter failed on question '%s' (sample %s): %s",
                    progress_prefix,
                    qa.question[:80],
                    sample.sample_id,
                    exc,
                )
                prediction = QAPrediction(
                    question=qa.question,
                    predicted_answer="",
                )

        # --- Scoring ---
        prediction.category = qa.category
        prediction.evidence_ids = list(qa.evidence)

        ground_truth = qa.expected_answer

        if qa.is_adversarial:
            adv_result = evaluate_adversarial(
                prediction=prediction.predicted_answer,
                adversarial_answer=(
                    str(qa.adversarial_answer) if qa.adversarial_answer is not None else None
                ),
                ground_truth_answer=ground_truth,
            )
            prediction.f1_score = adv_result["f1"]
            prediction.exact_match = adv_result["f1"] >= 0.99
            prediction.ground_truth = ground_truth or "(adversarial — unanswerable)"
        elif ground_truth is not None:
            prediction.f1_score = compute_f1(prediction.predicted_answer, ground_truth)
            prediction.exact_match = compute_exact_match(prediction.predicted_answer, ground_truth)
            prediction.ground_truth = ground_truth
        else:
            # No ground truth available — skip scoring
            prediction.f1_score = 0.0
            prediction.exact_match = False
            prediction.ground_truth = None

        cat_label = _CATEGORY_LABELS.get(qa.category, f"cat_{qa.category}")
        if self.verbose:
            logger.info(
                "%s [%s] F1=%.3f | A: %s | GT: %s",
                progress_prefix,
                cat_label,
                prediction.f1_score,
                prediction.predicted_answer[:80],
                (prediction.ground_truth or "—")[:80],
            )
        else:
            # Always log a brief progress line so the user sees activity
            logger.info(
                "%s [%s] F1=%.3f  Q: %s",
                progress_prefix,
                cat_label,
                prediction.f1_score,
                qa.question[:70],
            )

        return prediction

    # ------------------------------------------------------------------
    # Sample-level evaluation
    # ------------------------------------------------------------------

    async def evaluate_sample(
        self,
        sample: LoCoMoSample,
        *,
        ingest: bool = True,
    ) -> TaskResult:
        """
        Evaluate all QA questions for a single LoCoMo sample.

        Parameters
        ----------
        sample : LoCoMoSample
            The conversation sample to evaluate.
        ingest : bool
            If ``True``, ingest the sample into the adapter before
            evaluation.  Set to ``False`` if the sample was already
            ingested in a previous step.

        Returns
        -------
        TaskResult
            Aggregated QA results for this sample, including per-category
            breakdowns.
        """
        if ingest:
            logger.info(
                "Ingesting sample %s (%d sessions, %d turns)…",
                sample.sample_id,
                sample.num_sessions,
                sample.num_turns,
            )
            await self.adapter.ingest(sample)

        # Filter questions by selected categories
        questions = sample.qa
        if self.categories:
            cat_values = {c.value for c in self.categories}
            questions = [q for q in questions if q.category in cat_values]

        if not questions:
            logger.warning(
                "No QA questions to evaluate for sample %s (filter: %s)",
                sample.sample_id,
                self.categories,
            )
            return TaskResult(
                sample_id=sample.sample_id,
                task_name=self.TASK_NAME,
                overall_score=0.0,
                num_predictions=0,
            )

        logger.info(
            "Evaluating %d QA questions for sample %s (concurrency=%d)…",
            len(questions),
            sample.sample_id,
            self.max_concurrent,
        )

        # Run questions concurrently with semaphore-based throttling
        semaphore = asyncio.Semaphore(self.max_concurrent)
        t0 = time.monotonic()

        tasks = [
            self._evaluate_single_question(
                sample,
                qa,
                semaphore,
                question_index=i + 1,
                total_questions=len(questions),
            )
            for i, qa in enumerate(questions)
        ]
        predictions: List[QAPrediction] = await asyncio.gather(*tasks)

        elapsed = time.monotonic() - t0
        self._predictions.extend(predictions)

        # --- Aggregate scores ---
        all_f1: List[float] = [p.f1_score for p in predictions]
        overall_f1 = sum(all_f1) / len(all_f1) if all_f1 else 0.0

        # Per-category breakdown
        category_f1: Dict[str, List[float]] = {}
        category_em: Dict[str, List[float]] = {}
        for pred in predictions:
            label = _CATEGORY_LABELS.get(pred.category, f"cat_{pred.category}")
            category_f1.setdefault(label, []).append(pred.f1_score)
            category_em.setdefault(label, []).append(1.0 if pred.exact_match else 0.0)

        category_scores: Dict[str, float] = {}
        for label, scores in category_f1.items():
            mean_f1 = sum(scores) / len(scores) if scores else 0.0
            mean_em = (
                sum(category_em[label]) / len(category_em[label]) if category_em.get(label) else 0.0
            )
            category_scores[f"{label}_f1"] = mean_f1
            category_scores[f"{label}_em"] = mean_em
            category_scores[f"{label}_count"] = float(len(scores))

        # Adversarial-specific metrics
        adversarial_preds = [p for p in predictions if p.category == QACategory.ADVERSARIAL]
        if adversarial_preds:
            tricked_count = sum(
                1 for p in adversarial_preds if p.f1_score == 0.0 and not p.exact_match
            )
            category_scores["adversarial_tricked_rate"] = tricked_count / len(adversarial_preds)

        result = TaskResult(
            sample_id=sample.sample_id,
            task_name=self.TASK_NAME,
            overall_score=overall_f1,
            category_scores=category_scores,
            num_predictions=len(predictions),
            metadata={
                "elapsed_seconds": round(elapsed, 2),
                "context_type": self.context_type,
                "top_k": self.top_k,
                "adapter": self.adapter.name,
            },
        )

        logger.info(
            "Sample %s — QA F1: %.4f  (n=%d, %.1fs)",
            sample.sample_id,
            overall_f1,
            len(predictions),
            elapsed,
        )

        return result

    # ------------------------------------------------------------------
    # Dataset-level evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        samples: Any,  # LoCoMoDataset or list of LoCoMoSample
        *,
        ingest: bool = True,
    ) -> BenchmarkResult:
        """
        Evaluate the QA task across one or more LoCoMo samples.

        Parameters
        ----------
        samples : LoCoMoDataset or list[LoCoMoSample] or LoCoMoSample
            The sample(s) to evaluate.
        ingest : bool
            If ``True``, ingest each sample before evaluation.

        Returns
        -------
        BenchmarkResult
            Aggregated benchmark results.
        """
        # Normalise input to a list of samples
        if isinstance(samples, LoCoMoSample):
            sample_list = [samples]
        elif hasattr(samples, "samples"):
            # LoCoMoDataset
            sample_list = samples.samples
        else:
            sample_list = list(samples)

        self._predictions = []
        bench = BenchmarkResult(
            model_name=self.adapter.name,
            adapter_type=type(self.adapter).__name__,
            config={
                "context_type": self.context_type,
                "top_k": self.top_k,
                "categories": ([c.label for c in self.categories] if self.categories else "all"),
            },
        )

        t0 = time.monotonic()

        for i, sample in enumerate(sample_list):
            logger.info(
                "=== QA Task — sample %d/%d: %s ===",
                i + 1,
                len(sample_list),
                sample.sample_id,
            )
            result = await self.evaluate_sample(sample, ingest=ingest)
            bench.add_task_result(result)

        total_elapsed = time.monotonic() - t0
        bench.compute_overall()

        # Also compute a global per-category breakdown across all samples
        all_preds = self._predictions
        if all_preds:
            metrics = compute_qa_metrics(
                predictions=[p.predicted_answer for p in all_preds],
                ground_truths=[p.ground_truth or "" for p in all_preds],
                categories=[p.category for p in all_preds],
            )
            bench.overall_scores["qa_f1"] = metrics["overall_f1"]
            bench.overall_scores["qa_em"] = metrics["overall_em"]
            if "per_category" in metrics:
                for cat_label, cat_metrics in metrics["per_category"].items():
                    bench.overall_scores[f"qa_{cat_label}_f1"] = cat_metrics["f1"]
                    bench.overall_scores[f"qa_{cat_label}_em"] = cat_metrics["em"]

        logger.info(
            "QA Task complete — %d samples, %d questions, overall F1=%.4f  (%.1fs)",
            len(sample_list),
            len(all_preds),
            bench.overall_scores.get("qa_f1", 0.0),
            total_elapsed,
        )

        return bench

    # ------------------------------------------------------------------
    # Convenience: synchronous entry point
    # ------------------------------------------------------------------

    def run(
        self,
        samples: Any,
        *,
        ingest: bool = True,
    ) -> BenchmarkResult:
        """
        Synchronous wrapper around :meth:`evaluate`.

        Creates a new event loop if one is not running, or uses
        ``asyncio.run`` to execute the evaluation.

        Parameters
        ----------
        samples : LoCoMoDataset or list[LoCoMoSample] or LoCoMoSample
            Sample(s) to evaluate.
        ingest : bool
            If ``True``, ingest each sample before evaluation.

        Returns
        -------
        BenchmarkResult
        """
        return asyncio.run(self._run_async(samples, ingest=ingest))

    async def _run_async(
        self,
        samples: Any,
        *,
        ingest: bool = True,
    ) -> BenchmarkResult:
        """Full async lifecycle: setup → evaluate → teardown."""
        await self.setup()
        try:
            return await self.evaluate(samples, ingest=ingest)
        finally:
            await self.teardown()

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    @property
    def predictions(self) -> List[QAPrediction]:
        """Access the list of predictions from the last evaluation run."""
        return list(self._predictions)

    def summary_table(self) -> str:
        """
        Return a formatted summary table of the last evaluation run.

        Returns
        -------
        str
            Markdown-formatted table of per-category F1 scores.
        """
        if not self._predictions:
            return "(no predictions yet — run evaluate() first)"

        # Group by category
        by_cat: Dict[str, List[QAPrediction]] = {}
        for p in self._predictions:
            label = _CATEGORY_LABELS.get(p.category, f"cat_{p.category}")
            by_cat.setdefault(label, []).append(p)

        lines = [
            "| Category       | Count | F1 Score | EM Score |",
            "|----------------|------:|---------:|---------:|",
        ]

        total_f1 = []
        total_em = []

        for label in [
            "single_hop",
            "temporal",
            "commonsense",
            "open_domain",
            "adversarial",
        ]:
            preds = by_cat.get(label, [])
            if not preds:
                lines.append(f"| {label:14s} |     0 |      — |      — |")
                continue
            f1s = [p.f1_score for p in preds]
            ems = [1.0 if p.exact_match else 0.0 for p in preds]
            mean_f1 = sum(f1s) / len(f1s)
            mean_em = sum(ems) / len(ems)
            total_f1.extend(f1s)
            total_em.extend(ems)
            lines.append(f"| {label:14s} | {len(preds):5d} | {mean_f1:7.4f} | {mean_em:7.4f} |")

        # Overall
        if total_f1:
            overall_f1 = sum(total_f1) / len(total_f1)
            overall_em = sum(total_em) / len(total_em)
            lines.append("|----------------|------:|---------:|---------:|")
            lines.append(
                f"| {'Overall':14s} | {len(total_f1):5d} | {overall_f1:7.4f} | {overall_em:7.4f} |"
            )

        return "\n".join(lines)
