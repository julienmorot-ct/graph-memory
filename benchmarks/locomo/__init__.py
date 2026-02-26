"""
LoCoMo Benchmark — Evaluating Very Long-Term Conversational Memory

Implementation of the LoCoMo evaluation framework for testing long-term
conversational memory in the graph-memory system.

Based on the paper:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

Tasks:
    1. Question Answering (QA) — 5 reasoning categories
    2. Event Summarization — temporal event graph extraction
    3. Multi-modal Dialogue Generation (future)

Usage:
    from benchmarks.locomo import LoCoMoDataset, QATask, EventSummarizationTask
    from benchmarks.locomo.adapters import GraphMemoryAdapter
    from benchmarks.locomo.runners import BenchmarkRunner
"""

__version__ = "0.1.0"
__author__ = "Cloud Temple"

from benchmarks.locomo.data_loader import LoCoMoDataset
from benchmarks.locomo.models import (
    Conversation,
    DialogTurn,
    EventSummary,
    LoCoMoSample,
    QAAnnotation,
    QACategory,
    Session,
    SessionEvents,
)
from benchmarks.locomo.tasks.event_summarization import EventSummarizationTask
from benchmarks.locomo.tasks.question_answering import QATask

__all__ = [
    # Core models
    "LoCoMoSample",
    "QAAnnotation",
    "QACategory",
    "DialogTurn",
    "Session",
    "Conversation",
    "EventSummary",
    "SessionEvents",
    # Dataset
    "LoCoMoDataset",
    # Tasks
    "QATask",
    "EventSummarizationTask",
]
