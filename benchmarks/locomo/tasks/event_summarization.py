# -*- coding: utf-8 -*-
"""
LoCoMo Event Summarization Task.

Implements the event summarization evaluation task from the LoCoMo benchmark,
which measures a system's ability to comprehend long-range causal and temporal
connections in dialogues by extracting event graphs.

The ground-truth event graphs are linked to each LLM speaker and serve as
the correct answers. Models are tasked with extracting significant life events
from the conversation history and organizing them chronologically.

Metrics:
    - FactScore: Precision, recall, and F1 based on atomic fact decomposition.
      * Precision: fraction of predicted atomic facts that match reference.
      * Recall: fraction of reference atomic facts covered by prediction.
      * F1: harmonic mean of precision and recall.

Reference:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

Usage:
    from benchmarks.locomo.tasks.event_summarization import EventSummarizationTask
    from benchmarks.locomo.adapters import GraphMemoryAdapter
    from benchmarks.locomo.data_loader import LoCoMoDataset

    dataset = LoCoMoDataset.from_file("data/locomo10.json")
    adapter = GraphMemoryAdapter(base_url="http://localhost:8002")
    task = EventSummarizationTask(adapter=adapter)

    await task.setup()
    result = await task.evaluate(dataset[0])
    print(task.summary_table())
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from benchmarks.locomo.metrics import (
    compute_event_summarization_metrics,
    compute_factscore,
)
from benchmarks.locomo.models import (
    BenchmarkResult,
    EventPrediction,
    EventSummary,
    LoCoMoSample,
    SessionEvents,
    TaskResult,
)

logger = logging.getLogger(__name__)


def _flatten_ground_truth_events(
    event_summary: EventSummary,
    speaker: Optional[str] = None,
) -> str:
    """
    Flatten the structured event summary ground truth into a single text
    block suitable for comparison with model output.

    Events are ordered by session key and include speaker attribution
    and date information.

    Parameters
    ----------
    event_summary : EventSummary
        The ground-truth event summary from the LoCoMo dataset.
    speaker : str, optional
        If provided, only include events for this speaker.

    Returns
    -------
    str
        Flattened text representation of all ground-truth events.
    """
    lines: list[str] = []

    # Sort session keys by session number for chronological order
    def _session_sort_key(key: str) -> int:
        try:
            # e.g. "events_session_3" -> 3
            parts = key.replace("events_session_", "")
            return int(parts)
        except (ValueError, IndexError):
            return 0

    for session_key in sorted(event_summary.sessions.keys(), key=_session_sort_key):
        session_events: SessionEvents = event_summary.sessions[session_key]

        if not session_events.all_events:
            continue

        date_str = f" ({session_events.date})" if session_events.date else ""

        if speaker is None or speaker == session_events.speaker_a_name:
            for event in session_events.speaker_a_events:
                lines.append(f"[{session_events.speaker_a_name}]{date_str}: {event}")

        if speaker is None or speaker == session_events.speaker_b_name:
            for event in session_events.speaker_b_events:
                lines.append(f"[{session_events.speaker_b_name}]{date_str}: {event}")

    return "\n".join(lines)


def _get_event_list(
    event_summary: EventSummary,
    speaker: Optional[str] = None,
) -> List[str]:
    """
    Extract ground-truth events as a flat list of strings.

    Parameters
    ----------
    event_summary : EventSummary
        The ground-truth event summary.
    speaker : str, optional
        If provided, only include events for this speaker.

    Returns
    -------
    list of str
        List of event description strings.
    """
    events: List[str] = []
    for session_events in event_summary.sessions.values():
        if speaker is None or speaker == session_events.speaker_a_name:
            events.extend(session_events.speaker_a_events)
        if speaker is None or speaker == session_events.speaker_b_name:
            events.extend(session_events.speaker_b_events)
    return events


class EventSummarizationTask:
    """
    LoCoMo Event Summarization evaluation task.

    Evaluates a memory system's ability to extract and summarize the
    significant life events discussed by speakers in a very long-term
    conversation.

    The task follows the paper's approach:
      - The event graphs linked to each speaker serve as ground truth.
      - Models extract event information from conversation history.
      - FactScore (precision, recall, F1) is used to measure factual
        accuracy of the generated summaries against the ground-truth
        event graphs.

    Parameters
    ----------
    adapter : BaseAdapter
        The adapter connecting to the memory / LLM system under test.
    per_speaker : bool
        If ``True``, generate and evaluate separate summaries for each
        speaker.  If ``False`` (default), generate a single combined
        summary for both speakers.
    verbose : bool
        If ``True``, log individual session/speaker results.
    """

    TASK_NAME = "event_summarization"

    def __init__(
        self,
        adapter: Any,  # BaseAdapter — use Any to avoid circular import
        per_speaker: bool = False,
        verbose: bool = False,
    ) -> None:
        self.adapter = adapter
        self.per_speaker = per_speaker
        self.verbose = verbose

        # Internal state
        self._predictions: List[EventPrediction] = []
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
    # Core evaluation
    # ------------------------------------------------------------------

    async def _evaluate_for_speaker(
        self,
        sample: LoCoMoSample,
        speaker: Optional[str] = None,
    ) -> EventPrediction:
        """
        Generate an event summary for one speaker (or both) and score it.

        Parameters
        ----------
        sample : LoCoMoSample
            The conversation sample.
        speaker : str, optional
            If given, summarize events for this speaker only.

        Returns
        -------
        EventPrediction
            Scored prediction with FactScore metrics.
        """
        speaker_label = speaker or "all"

        # Get ground-truth events
        gt_events = _get_event_list(sample.event_summary, speaker=speaker)
        gt_text = _flatten_ground_truth_events(sample.event_summary, speaker=speaker)

        if not gt_events:
            logger.debug(
                "No ground-truth events for sample %s, speaker %s — skipping",
                sample.sample_id,
                speaker_label,
            )
            return EventPrediction(
                session_key=f"{sample.sample_id}_{speaker_label}",
                predicted_events=[],
                ground_truth_events=gt_events,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
            )

        # Generate summary via adapter
        try:
            predicted_text = await self.adapter.summarize_events(
                sample=sample,
                speaker=speaker,
            )
        except Exception as exc:
            logger.error(
                "Event summarization failed for sample %s, speaker %s: %s",
                sample.sample_id,
                speaker_label,
                exc,
            )
            predicted_text = ""

        # Parse predicted text into individual event lines
        predicted_events: List[str] = []
        if predicted_text:
            for line in predicted_text.strip().split("\n"):
                line = line.strip()
                # Skip empty lines and section headers
                if line and len(line) > 5 and not line.startswith("==="):
                    # Remove common bullet/number prefixes
                    cleaned = line.lstrip("- •·0123456789.) ")
                    if cleaned:
                        predicted_events.append(cleaned)

        # Compute FactScore
        scores = compute_factscore(
            prediction=predicted_text,
            reference=gt_text,
        )

        prediction = EventPrediction(
            session_key=f"{sample.sample_id}_{speaker_label}",
            predicted_events=predicted_events,
            ground_truth_events=gt_events,
            precision=scores["precision"],
            recall=scores["recall"],
            f1_score=scores["f1"],
        )

        if self.verbose:
            logger.info(
                "[%s / %s] Events: predicted=%d, ground_truth=%d | P=%.3f R=%.3f F1=%.3f",
                sample.sample_id,
                speaker_label,
                len(predicted_events),
                len(gt_events),
                scores["precision"],
                scores["recall"],
                scores["f1"],
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
        Evaluate event summarization for a single LoCoMo sample.

        Parameters
        ----------
        sample : LoCoMoSample
            The conversation sample to evaluate.
        ingest : bool
            If ``True``, ingest the sample into the adapter before
            evaluation.

        Returns
        -------
        TaskResult
            Aggregated event summarization results for this sample.
        """
        if ingest:
            logger.info(
                "Ingesting sample %s for event summarization…",
                sample.sample_id,
            )
            await self.adapter.ingest(sample)

        t0 = time.monotonic()
        predictions: List[EventPrediction] = []

        if self.per_speaker:
            # Evaluate separately for each speaker
            for speaker in [sample.speaker_a, sample.speaker_b]:
                pred = await self._evaluate_for_speaker(sample, speaker=speaker)
                predictions.append(pred)
        else:
            # Single combined evaluation
            pred = await self._evaluate_for_speaker(sample, speaker=None)
            predictions.append(pred)

        elapsed = time.monotonic() - t0
        self._predictions.extend(predictions)

        # Aggregate scores
        precisions = [p.precision for p in predictions]
        recalls = [p.recall for p in predictions]
        f1s = [p.f1_score for p in predictions]

        n = len(predictions)
        mean_precision = sum(precisions) / n if n else 0.0
        mean_recall = sum(recalls) / n if n else 0.0
        mean_f1 = sum(f1s) / n if n else 0.0

        category_scores: Dict[str, float] = {
            "factscore_precision": mean_precision,
            "factscore_recall": mean_recall,
            "factscore_f1": mean_f1,
        }

        # Per-speaker breakdown (if evaluated per-speaker)
        if self.per_speaker:
            for pred in predictions:
                # session_key format: "conv-26_SpeakerName"
                speaker_label = (
                    pred.session_key.split("_", 1)[-1] if "_" in pred.session_key else "unknown"
                )
                category_scores[f"{speaker_label}_precision"] = pred.precision
                category_scores[f"{speaker_label}_recall"] = pred.recall
                category_scores[f"{speaker_label}_f1"] = pred.f1_score

        # Count events
        total_predicted = sum(len(p.predicted_events) for p in predictions)
        total_gt = sum(len(p.ground_truth_events) for p in predictions)
        category_scores["total_predicted_events"] = float(total_predicted)
        category_scores["total_ground_truth_events"] = float(total_gt)

        result = TaskResult(
            sample_id=sample.sample_id,
            task_name=self.TASK_NAME,
            overall_score=mean_f1,
            category_scores=category_scores,
            num_predictions=n,
            metadata={
                "elapsed_seconds": round(elapsed, 2),
                "per_speaker": self.per_speaker,
                "adapter": self.adapter.name,
            },
        )

        logger.info(
            "Sample %s — Event Sum. P=%.4f R=%.4f F1=%.4f  (predicted=%d, gt=%d, %.1fs)",
            sample.sample_id,
            mean_precision,
            mean_recall,
            mean_f1,
            total_predicted,
            total_gt,
            elapsed,
        )

        return result

    # ------------------------------------------------------------------
    # Dataset-level evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        samples: Any,  # LoCoMoDataset or list[LoCoMoSample] or LoCoMoSample
        *,
        ingest: bool = True,
    ) -> BenchmarkResult:
        """
        Evaluate event summarization across one or more LoCoMo samples.

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
            sample_list = samples.samples
        else:
            sample_list = list(samples)

        self._predictions = []
        bench = BenchmarkResult(
            model_name=self.adapter.name,
            adapter_type=type(self.adapter).__name__,
            config={
                "per_speaker": self.per_speaker,
            },
        )

        t0 = time.monotonic()

        for i, sample in enumerate(sample_list):
            logger.info(
                "=== Event Summarization — sample %d/%d: %s ===",
                i + 1,
                len(sample_list),
                sample.sample_id,
            )
            result = await self.evaluate_sample(sample, ingest=ingest)
            bench.add_task_result(result)

        total_elapsed = time.monotonic() - t0
        bench.compute_overall()

        # Compute global metrics across all predictions
        if self._predictions:
            all_pred_texts = ["\n".join(p.predicted_events) for p in self._predictions]
            all_gt_texts = ["\n".join(p.ground_truth_events) for p in self._predictions]
            global_metrics = compute_event_summarization_metrics(
                predictions=all_pred_texts,
                references=all_gt_texts,
            )
            bench.overall_scores["event_sum_precision"] = global_metrics["precision"]
            bench.overall_scores["event_sum_recall"] = global_metrics["recall"]
            bench.overall_scores["event_sum_f1"] = global_metrics["f1"]

        logger.info(
            "Event Summarization complete — %d samples, P=%.4f R=%.4f F1=%.4f  (%.1fs)",
            len(sample_list),
            bench.overall_scores.get("event_sum_precision", 0.0),
            bench.overall_scores.get("event_sum_recall", 0.0),
            bench.overall_scores.get("event_sum_f1", 0.0),
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
    def predictions(self) -> List[EventPrediction]:
        """Access the list of predictions from the last evaluation run."""
        return list(self._predictions)

    def summary_table(self) -> str:
        """
        Return a formatted summary table of the last evaluation run.

        Returns
        -------
        str
            Markdown-formatted table of event summarization results.
        """
        if not self._predictions:
            return "(no predictions yet — run evaluate() first)"

        lines = [
            "| Sample / Speaker       | Predicted | Ground Truth | Precision | Recall  | F1 Score |",
            "|------------------------|----------:|-------------:|----------:|--------:|---------:|",
        ]

        total_predicted = 0
        total_gt = 0
        total_precision: List[float] = []
        total_recall: List[float] = []
        total_f1: List[float] = []

        for pred in self._predictions:
            n_pred = len(pred.predicted_events)
            n_gt = len(pred.ground_truth_events)
            total_predicted += n_pred
            total_gt += n_gt
            total_precision.append(pred.precision)
            total_recall.append(pred.recall)
            total_f1.append(pred.f1_score)

            label = pred.session_key[:22]
            lines.append(
                f"| {label:22s} | {n_pred:9d} | {n_gt:12d} | "
                f"{pred.precision:9.4f} | {pred.recall:7.4f} | {pred.f1_score:8.4f} |"
            )

        # Overall row
        n = len(self._predictions)
        if n > 0:
            mean_p = sum(total_precision) / n
            mean_r = sum(total_recall) / n
            mean_f1 = sum(total_f1) / n

            lines.append(
                "|------------------------|----------:|-------------:|----------:|--------:|---------:|"
            )
            lines.append(
                f"| {'Overall':22s} | {total_predicted:9d} | {total_gt:12d} | "
                f"{mean_p:9.4f} | {mean_r:7.4f} | {mean_f1:8.4f} |"
            )

        return "\n".join(lines)

    def detailed_report(self) -> str:
        """
        Generate a detailed textual report of the evaluation.

        Includes per-prediction details such as lists of predicted vs
        ground-truth events and the FactScore breakdown.

        Returns
        -------
        str
            Multi-line detailed report.
        """
        if not self._predictions:
            return "(no predictions yet — run evaluate() first)"

        sections: List[str] = [
            "=" * 70,
            "  LoCoMo Event Summarization — Detailed Report",
            f"  Adapter: {self.adapter.name}",
            f"  Per-speaker: {self.per_speaker}",
            f"  Total predictions: {len(self._predictions)}",
            "=" * 70,
            "",
        ]

        for pred in self._predictions:
            sections.append(f"--- {pred.session_key} ---")
            sections.append(
                f"  FactScore:  P={pred.precision:.4f}  R={pred.recall:.4f}  F1={pred.f1_score:.4f}"
            )
            sections.append(f"  Predicted events ({len(pred.predicted_events)}):")
            for i, evt in enumerate(pred.predicted_events[:20], 1):
                sections.append(f"    {i:3d}. {evt[:120]}")
            if len(pred.predicted_events) > 20:
                sections.append(f"    ... and {len(pred.predicted_events) - 20} more")

            sections.append(f"  Ground-truth events ({len(pred.ground_truth_events)}):")
            for i, evt in enumerate(pred.ground_truth_events[:20], 1):
                sections.append(f"    {i:3d}. {evt[:120]}")
            if len(pred.ground_truth_events) > 20:
                sections.append(f"    ... and {len(pred.ground_truth_events) - 20} more")
            sections.append("")

        # Global summary
        if self._predictions:
            n = len(self._predictions)
            mean_p = sum(p.precision for p in self._predictions) / n
            mean_r = sum(p.recall for p in self._predictions) / n
            mean_f1 = sum(p.f1_score for p in self._predictions) / n

            sections.extend(
                [
                    "=" * 70,
                    f"  Overall:  P={mean_p:.4f}  R={mean_r:.4f}  F1={mean_f1:.4f}",
                    "=" * 70,
                ]
            )

        return "\n".join(sections)
