# -*- coding: utf-8 -*-
"""
Pydantic data models for the LoCoMo benchmark dataset.

These models represent the structure of the LoCoMo dataset as described in:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

The dataset consists of very long-term conversations (~300 turns, ~9K tokens,
up to 35 sessions) annotated for:
    - Question Answering (5 reasoning categories)
    - Event Summarization
    - Multi-modal Dialogue Generation
"""

from enum import IntEnum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class QACategory(IntEnum):
    """
    Question answering reasoning categories from the LoCoMo benchmark.

    Categories:
        1 - Single-hop: answers based on a single session
        2 - Temporal reasoning: time-related data cues
        3 - Open-domain / commonsense knowledge: integrating speaker info
            with external knowledge
        4 - Multi-hop: synthesizing information from multiple sessions
        5 - Adversarial: designed to trick the agent (unanswerable or
            speaker-swapped questions)
    """

    SINGLE_HOP = 1
    TEMPORAL = 2
    COMMONSENSE = 3
    OPEN_DOMAIN = 4
    ADVERSARIAL = 5

    @property
    def label(self) -> str:
        _labels = {
            1: "single_hop",
            2: "temporal",
            3: "commonsense",
            4: "open_domain",
            5: "adversarial",
        }
        return _labels[self.value]

    @property
    def description(self) -> str:
        _descriptions = {
            1: "Single-hop retrieval: answer from a single session",
            2: "Temporal reasoning: time-related data cues",
            3: "Commonsense / world knowledge: external knowledge integration",
            4: "Multi-hop retrieval: synthesize info across sessions",
            5: "Adversarial: unanswerable or speaker-swapped questions",
        }
        return _descriptions[self.value]


# =============================================================================
# QA Annotations
# =============================================================================


class QAAnnotation(BaseModel):
    """
    A single question-answer annotation from the LoCoMo dataset.

    Attributes:
        question: The question text.
        answer: The ground-truth answer (may be absent for adversarial Qs).
        evidence: List of dialog turn IDs containing the answer evidence
                  (e.g. ["D1:3", "D2:8"]).
        category: QA reasoning category (1-5).
        adversarial_answer: For adversarial questions (cat 5), the answer
                           that would be correct if the speaker were swapped.
    """

    question: str
    answer: Optional[Union[str, int, float]] = None
    evidence: List[str] = Field(default_factory=list)
    category: int = Field(..., ge=1, le=5)
    adversarial_answer: Optional[Union[str, int, float]] = None

    @property
    def qa_category(self) -> QACategory:
        return QACategory(self.category)

    @property
    def is_adversarial(self) -> bool:
        return self.category == QACategory.ADVERSARIAL

    @property
    def expected_answer(self) -> Optional[str]:
        """
        Return the expected answer as a string.

        For adversarial questions without a direct answer field, the model
        should ideally refuse to answer or indicate the question is
        unanswerable. If an ``answer`` field is present on an adversarial
        question (e.g. "No"), that is the expected response.
        """
        if self.answer is not None:
            return str(self.answer)
        return None

    class Config:
        use_enum_values = True


# =============================================================================
# Dialogue / Conversation models
# =============================================================================


class DialogTurn(BaseModel):
    """
    A single turn in a conversation session.

    Attributes:
        speaker: Name of the speaker for this turn.
        dia_id: Unique dialog turn identifier (e.g. "D1:3").
        text: The text content of this turn.
        img_url: Optional list of image URLs shared in this turn.
        blip_caption: Optional BLIP-2 generated caption for the image.
        query: Optional search query used to retrieve the image.
    """

    speaker: str
    dia_id: str
    text: str
    img_url: Optional[List[str]] = None
    blip_caption: Optional[str] = None
    query: Optional[str] = None

    @property
    def has_image(self) -> bool:
        return self.img_url is not None and len(self.img_url) > 0

    @property
    def session_number(self) -> int:
        """Extract session number from dia_id like 'D3:5' -> 3."""
        try:
            d_part = self.dia_id.split(":")[0]  # "D3"
            return int(d_part[1:])
        except (IndexError, ValueError):
            return -1

    @property
    def turn_number(self) -> int:
        """Extract turn number from dia_id like 'D3:5' -> 5."""
        try:
            return int(self.dia_id.split(":")[1])
        except (IndexError, ValueError):
            return -1

    def to_text_with_caption(self) -> str:
        """
        Return text with image caption appended (for text-only evaluation).

        Following the paper's approach of replacing images with BLIP-2 captions
        for the QA and event summarization tasks.
        """
        parts = [self.text]
        if self.blip_caption:
            parts.append(f"[Image: {self.blip_caption}]")
        return " ".join(parts)


class Session(BaseModel):
    """
    A single conversation session with a timestamp and list of turns.

    Attributes:
        session_id: Integer session number (1-based).
        date_time: Timestamp string (e.g. "1:56 pm on 8 May, 2023").
        turns: List of dialog turns in this session.
    """

    session_id: int
    date_time: str
    turns: List[DialogTurn] = Field(default_factory=list)

    @property
    def num_turns(self) -> int:
        return len(self.turns)

    @property
    def speakers(self) -> List[str]:
        return list({t.speaker for t in self.turns})

    def to_text(self, include_captions: bool = True) -> str:
        """Serialize session to text for LLM consumption."""
        lines = [f"[Session {self.session_id} — {self.date_time}]"]
        for turn in self.turns:
            if include_captions:
                content = turn.to_text_with_caption()
            else:
                content = turn.text
            lines.append(f"{turn.speaker}: {content}")
        return "\n".join(lines)


class Conversation(BaseModel):
    """
    A full multi-session conversation between two speakers.

    Attributes:
        speaker_a: Name of the first speaker.
        speaker_b: Name of the second speaker.
        sessions: Ordered list of conversation sessions.
    """

    speaker_a: str
    speaker_b: str
    sessions: List[Session] = Field(default_factory=list)

    @property
    def num_sessions(self) -> int:
        return len(self.sessions)

    @property
    def num_turns(self) -> int:
        return sum(s.num_turns for s in self.sessions)

    @property
    def total_tokens_estimate(self) -> int:
        """Rough token count (words / 0.75)."""
        total_words = sum(len(t.text.split()) for s in self.sessions for t in s.turns)
        return int(total_words / 0.75)

    def to_text(self, include_captions: bool = True) -> str:
        """Serialize full conversation to text."""
        parts = [
            f"Conversation between {self.speaker_a} and {self.speaker_b}",
            "=" * 60,
        ]
        for session in self.sessions:
            parts.append(session.to_text(include_captions=include_captions))
            parts.append("")
        return "\n".join(parts)

    def get_turns_by_id(self, dia_ids: List[str]) -> List[DialogTurn]:
        """Retrieve specific turns by their dialog IDs."""
        id_set = set(dia_ids)
        result = []
        for session in self.sessions:
            for turn in session.turns:
                if turn.dia_id in id_set:
                    result.append(turn)
        return result


# =============================================================================
# Event Summarization models
# =============================================================================


class SessionEvents(BaseModel):
    """
    Events for a single session, per speaker.

    Attributes:
        speaker_a_events: List of event strings for speaker A.
        speaker_b_events: List of event strings for speaker B.
        date: Date string for this session.
        speaker_a_name: Name of speaker A.
        speaker_b_name: Name of speaker B.
    """

    speaker_a_events: List[str] = Field(default_factory=list)
    speaker_b_events: List[str] = Field(default_factory=list)
    date: str = ""
    speaker_a_name: str = ""
    speaker_b_name: str = ""

    @property
    def all_events(self) -> List[str]:
        return self.speaker_a_events + self.speaker_b_events

    @property
    def num_events(self) -> int:
        return len(self.all_events)


class EventSummary(BaseModel):
    """
    Complete event summary ground truth for a conversation.

    Attributes:
        sessions: Mapping from session key to SessionEvents.
    """

    sessions: Dict[str, SessionEvents] = Field(default_factory=dict)

    @property
    def total_events(self) -> int:
        return sum(se.num_events for se in self.sessions.values())

    def get_all_events_flat(self) -> List[str]:
        """Return all events across all sessions as a flat list."""
        events = []
        for se in self.sessions.values():
            events.extend(se.all_events)
        return events


# =============================================================================
# Observation models
# =============================================================================


class Observation(BaseModel):
    """
    A single observation (assertion) about a speaker extracted from dialog.

    Attributes:
        text: The observation text.
        evidence: Dialog turn ID(s) that support this observation.
    """

    text: str
    evidence: Union[str, List[str]] = ""

    @property
    def evidence_ids(self) -> List[str]:
        if isinstance(self.evidence, list):
            return self.evidence
        if isinstance(self.evidence, str) and self.evidence:
            return [self.evidence]
        return []


class SessionObservations(BaseModel):
    """
    Observations for a single session, keyed by speaker name.

    Attributes:
        observations: Mapping from speaker name to list of observations.
    """

    observations: Dict[str, List[Observation]] = Field(default_factory=dict)


# =============================================================================
# Top-level LoCoMo Sample
# =============================================================================


class LoCoMoSample(BaseModel):
    """
    A single sample from the LoCoMo dataset.

    Each sample represents one very long-term conversation with all its
    annotations for the QA, event summarization, and dialog generation tasks.

    Attributes:
        sample_id: Unique identifier (e.g. "conv-26").
        conversation: The full multi-session conversation.
        qa: List of QA annotations.
        event_summary: Ground truth event summaries per session.
        observations: Per-session observations (assertions about speakers).
        session_summaries: Per-session text summaries.
    """

    sample_id: str
    conversation: Conversation
    qa: List[QAAnnotation] = Field(default_factory=list)
    event_summary: EventSummary = Field(default_factory=EventSummary)
    observations: Dict[str, SessionObservations] = Field(default_factory=dict)
    session_summaries: Dict[str, str] = Field(default_factory=dict)

    # ---- QA helpers ----

    @property
    def num_qa(self) -> int:
        return len(self.qa)

    def get_qa_by_category(self, category: QACategory) -> List[QAAnnotation]:
        return [q for q in self.qa if q.category == category.value]

    @property
    def qa_category_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for q in self.qa:
            label = QACategory(q.category).label
            counts[label] = counts.get(label, 0) + 1
        return counts

    # ---- Conversation helpers ----

    @property
    def num_sessions(self) -> int:
        return self.conversation.num_sessions

    @property
    def num_turns(self) -> int:
        return self.conversation.num_turns

    @property
    def speaker_a(self) -> str:
        return self.conversation.speaker_a

    @property
    def speaker_b(self) -> str:
        return self.conversation.speaker_b

    # ---- Serialization for LLM ----

    def get_conversation_text(self, include_captions: bool = True) -> str:
        """Get full conversation as text (for LLM context)."""
        return self.conversation.to_text(include_captions=include_captions)

    def get_observations_text(self, top_k: Optional[int] = None) -> str:
        """Get all observations as text (for RAG context)."""
        lines = []
        for session_key, session_obs in self.observations.items():
            for speaker, obs_list in session_obs.observations.items():
                for obs in obs_list:
                    lines.append(f"[{speaker}] {obs.text}")
                    if top_k and len(lines) >= top_k:
                        return "\n".join(lines)
        return "\n".join(lines)

    def get_session_summaries_text(self) -> str:
        """Get all session summaries as text (for RAG context)."""
        lines = []
        for key in sorted(
            self.session_summaries.keys(),
            key=lambda k: int(k.replace("session_", "").replace("_summary", "")),
        ):
            lines.append(f"[{key}] {self.session_summaries[key]}")
        return "\n".join(lines)


# =============================================================================
# Benchmark Results models
# =============================================================================


class QAPrediction(BaseModel):
    """A single QA prediction from a model."""

    question: str
    predicted_answer: str
    ground_truth: Optional[str] = None
    category: int = 0
    f1_score: float = 0.0
    exact_match: bool = False
    evidence_ids: List[str] = Field(default_factory=list)
    retrieved_context: Optional[str] = None
    retrieval_accuracy: Optional[float] = None


class EventPrediction(BaseModel):
    """A single event summarization prediction from a model."""

    session_key: str
    predicted_events: List[str] = Field(default_factory=list)
    ground_truth_events: List[str] = Field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0


class TaskResult(BaseModel):
    """Aggregated results for a single task on a single sample."""

    sample_id: str
    task_name: str
    overall_score: float = 0.0
    category_scores: Dict[str, float] = Field(default_factory=dict)
    num_predictions: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkResult(BaseModel):
    """Complete benchmark results across all samples and tasks."""

    benchmark_name: str = "LoCoMo"
    model_name: str = ""
    adapter_type: str = ""
    task_results: List[TaskResult] = Field(default_factory=list)
    overall_scores: Dict[str, float] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)

    def add_task_result(self, result: TaskResult) -> None:
        self.task_results.append(result)

    def compute_overall(self) -> None:
        """Compute overall scores from individual task results."""
        by_task: Dict[str, List[float]] = {}
        for tr in self.task_results:
            by_task.setdefault(tr.task_name, []).append(tr.overall_score)
        for task_name, scores in by_task.items():
            if scores:
                self.overall_scores[task_name] = sum(scores) / len(scores)

    def summary(self) -> str:
        """Pretty-print benchmark summary."""
        lines = [
            "=== LoCoMo Benchmark Results ===",
            f"Model: {self.model_name}",
            f"Adapter: {self.adapter_type}",
            f"Samples evaluated: {len(self.task_results)}",
            "",
        ]
        for task_name, score in self.overall_scores.items():
            lines.append(f"  {task_name}: {score:.4f}")
        return "\n".join(lines)
