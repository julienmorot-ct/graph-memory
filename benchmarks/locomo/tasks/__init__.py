"""
LoCoMo benchmark evaluation tasks.

Tasks:
    - QATask: Question Answering across 5 reasoning categories
    - EventSummarizationTask: Temporal event graph extraction
"""

from benchmarks.locomo.tasks.event_summarization import EventSummarizationTask
from benchmarks.locomo.tasks.question_answering import QATask

__all__ = [
    "QATask",
    "EventSummarizationTask",
]
