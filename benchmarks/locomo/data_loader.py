# -*- coding: utf-8 -*-
"""
LoCoMo Dataset Loader.

Parses the LoCoMo JSON dataset into structured Pydantic models for use
in the benchmark evaluation pipeline.

The dataset format follows the LoCoMo release at:
    https://github.com/snap-research/locomo

Usage:
    from benchmarks.locomo.data_loader import LoCoMoDataset

    dataset = LoCoMoDataset.from_file("data/locomo10.json")
    for sample in dataset:
        print(sample.sample_id, sample.num_qa, sample.num_sessions)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from benchmarks.locomo.models import (
    Conversation,
    DialogTurn,
    EventSummary,
    LoCoMoSample,
    Observation,
    QAAnnotation,
    QACategory,
    Session,
    SessionEvents,
    SessionObservations,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SESSION_KEY_RE = re.compile(r"^session_(\d+)$")
_SESSION_DT_KEY_RE = re.compile(r"^session_(\d+)_date_time$")
_OBS_KEY_RE = re.compile(r"^session_(\d+)_observation$")
_SUM_KEY_RE = re.compile(r"^session_(\d+)_summary$")
_EVT_KEY_RE = re.compile(r"^events_session_(\d+)$")


def _parse_dialog_turn(raw: Dict[str, Any]) -> DialogTurn:
    """Parse a single dialog turn from raw JSON."""
    return DialogTurn(
        speaker=raw.get("speaker", ""),
        dia_id=raw.get("dia_id", ""),
        text=raw.get("text", ""),
        img_url=raw.get("img_url"),
        blip_caption=raw.get("blip_caption"),
        query=raw.get("query"),
    )


def _parse_sessions(raw_conv: Dict[str, Any]) -> List[Session]:
    """
    Extract ordered sessions from the raw conversation dict.

    The LoCoMo JSON encodes sessions as:
        "session_1_date_time": "...",
        "session_1": [ ... turns ... ],
        "session_2_date_time": "...",
        "session_2": [ ... turns ... ],
        ...

    Some later sessions may only have a date_time key with no turn data
    (placeholder sessions).  We create Session objects for those too but
    with an empty turns list.
    """
    # Discover all session numbers present in the conversation dict
    session_numbers: set[int] = set()
    for key in raw_conv:
        m = _SESSION_KEY_RE.match(key)
        if m:
            session_numbers.add(int(m.group(1)))
        m = _SESSION_DT_KEY_RE.match(key)
        if m:
            session_numbers.add(int(m.group(1)))

    sessions: List[Session] = []
    for num in sorted(session_numbers):
        dt_key = f"session_{num}_date_time"
        data_key = f"session_{num}"

        date_time = raw_conv.get(dt_key, "")
        raw_turns = raw_conv.get(data_key, [])

        turns: List[DialogTurn] = []
        if isinstance(raw_turns, list):
            for t in raw_turns:
                if isinstance(t, dict):
                    turns.append(_parse_dialog_turn(t))

        sessions.append(
            Session(
                session_id=num,
                date_time=date_time,
                turns=turns,
            )
        )

    return sessions


def _parse_conversation(raw_conv: Dict[str, Any]) -> Conversation:
    """Parse the conversation block from a raw LoCoMo sample."""
    speaker_a = raw_conv.get("speaker_a", "")
    speaker_b = raw_conv.get("speaker_b", "")
    sessions = _parse_sessions(raw_conv)

    return Conversation(
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        sessions=sessions,
    )


def _parse_qa_annotations(raw_qa: List[Dict[str, Any]]) -> List[QAAnnotation]:
    """Parse the QA annotations list."""
    annotations: List[QAAnnotation] = []
    for item in raw_qa:
        # Evidence can contain semicolons separating multiple IDs in one string
        raw_evidence = item.get("evidence", [])
        evidence: List[str] = []
        for e in raw_evidence:
            if isinstance(e, str):
                # Split on semicolons (e.g. "D8:6; D9:17")
                for part in e.split(";"):
                    part = part.strip()
                    if part:
                        evidence.append(part)
            else:
                evidence.append(str(e))

        annotations.append(
            QAAnnotation(
                question=item.get("question", ""),
                answer=item.get("answer"),
                evidence=evidence,
                category=item.get("category", 1),
                adversarial_answer=item.get("adversarial_answer"),
            )
        )
    return annotations


def _parse_event_summary(
    raw_events: Dict[str, Any],
    speaker_a: str,
    speaker_b: str,
) -> EventSummary:
    """Parse the event_summary block."""
    sessions: Dict[str, SessionEvents] = {}

    for key, val in raw_events.items():
        m = _EVT_KEY_RE.match(key)
        if not m or not isinstance(val, dict):
            continue

        a_events = val.get(speaker_a, [])
        b_events = val.get(speaker_b, [])
        date = val.get("date", "")

        if not isinstance(a_events, list):
            a_events = []
        if not isinstance(b_events, list):
            b_events = []

        sessions[key] = SessionEvents(
            speaker_a_events=a_events,
            speaker_b_events=b_events,
            date=date,
            speaker_a_name=speaker_a,
            speaker_b_name=speaker_b,
        )

    return EventSummary(sessions=sessions)


def _parse_observations(
    raw_obs: Dict[str, Any],
) -> Dict[str, SessionObservations]:
    """
    Parse the observation block.

    Observations are keyed by session (e.g. "session_1_observation") and
    each session maps speaker names to lists of [text, evidence_id] pairs.
    """
    result: Dict[str, SessionObservations] = {}

    for key, val in raw_obs.items():
        m = _OBS_KEY_RE.match(key)
        if not m or not isinstance(val, dict):
            continue

        speaker_obs: Dict[str, List[Observation]] = {}
        for speaker_name, obs_list in val.items():
            if not isinstance(obs_list, list):
                continue
            parsed: List[Observation] = []
            for entry in obs_list:
                if isinstance(entry, list) and len(entry) >= 2:
                    text = str(entry[0])
                    evidence = entry[1]
                    # Evidence can be a string or a list of strings
                    if isinstance(evidence, list):
                        evidence_val: Union[str, List[str]] = [str(e) for e in evidence]
                    else:
                        evidence_val = str(evidence)
                    parsed.append(Observation(text=text, evidence=evidence_val))
                elif isinstance(entry, str):
                    parsed.append(Observation(text=entry, evidence=""))
            speaker_obs[speaker_name] = parsed

        result[key] = SessionObservations(observations=speaker_obs)

    return result


def _parse_session_summaries(raw_summaries: Dict[str, Any]) -> Dict[str, str]:
    """Parse the session_summary block into a simple string mapping."""
    result: Dict[str, str] = {}
    for key, val in raw_summaries.items():
        m = _SUM_KEY_RE.match(key)
        if m and isinstance(val, str):
            result[key] = val
    return result


def _parse_sample(raw: Dict[str, Any]) -> LoCoMoSample:
    """Parse a single raw JSON object into a LoCoMoSample."""
    sample_id = raw.get("sample_id", "unknown")

    # Conversation
    raw_conv = raw.get("conversation", {})
    conversation = _parse_conversation(raw_conv)

    # QA
    raw_qa = raw.get("qa", [])
    qa = _parse_qa_annotations(raw_qa)

    # Event summary
    raw_events = raw.get("event_summary", {})
    event_summary = _parse_event_summary(
        raw_events,
        speaker_a=conversation.speaker_a,
        speaker_b=conversation.speaker_b,
    )

    # Observations
    raw_obs = raw.get("observation", {})
    observations = _parse_observations(raw_obs)

    # Session summaries
    raw_summaries = raw.get("session_summary", {})
    session_summaries = _parse_session_summaries(raw_summaries)

    return LoCoMoSample(
        sample_id=sample_id,
        conversation=conversation,
        qa=qa,
        event_summary=event_summary,
        observations=observations,
        session_summaries=session_summaries,
    )


# ---------------------------------------------------------------------------
# Public API — LoCoMoDataset
# ---------------------------------------------------------------------------


class LoCoMoDataset:
    """
    Iterable dataset of LoCoMo conversation samples.

    Loads the LoCoMo JSON file (e.g. ``locomo10.json``) and provides
    convenient access to the parsed samples with filtering by category,
    sample ID, etc.

    Examples
    --------
    >>> dataset = LoCoMoDataset.from_file("data/locomo10.json")
    >>> len(dataset)
    10
    >>> sample = dataset[0]
    >>> sample.sample_id
    'conv-26'
    >>> sample.num_qa
    154
    >>> for s in dataset:
    ...     print(s.sample_id, s.num_sessions, s.num_turns)
    """

    def __init__(self, samples: List[LoCoMoSample]) -> None:
        self._samples = samples
        self._index: Dict[str, int] = {s.sample_id: i for i, s in enumerate(samples)}

    # ---- Factory methods ----

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "LoCoMoDataset":
        """
        Load a LoCoMo dataset from a JSON file.

        Parameters
        ----------
        path : str or Path
            Path to the LoCoMo JSON file (e.g. ``locomo10.json``).

        Returns
        -------
        LoCoMoDataset
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"LoCoMo data file not found: {path}")

        logger.info("Loading LoCoMo dataset from %s", path)
        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if not isinstance(raw_data, list):
            raise ValueError(
                f"Expected a JSON array at the top level, got {type(raw_data).__name__}"
            )

        samples: List[LoCoMoSample] = []
        for i, raw_sample in enumerate(raw_data):
            try:
                sample = _parse_sample(raw_sample)
                samples.append(sample)
            except Exception as exc:
                sid = raw_sample.get("sample_id", f"index-{i}")
                logger.warning("Failed to parse sample %s: %s", sid, exc)

        logger.info(
            "Loaded %d LoCoMo samples (%d total QA, %d total sessions)",
            len(samples),
            sum(s.num_qa for s in samples),
            sum(s.num_sessions for s in samples),
        )
        return cls(samples)

    @classmethod
    def from_json_string(cls, json_str: str) -> "LoCoMoDataset":
        """Load from a JSON string (useful for testing)."""
        raw_data = json.loads(json_str)
        if not isinstance(raw_data, list):
            raw_data = [raw_data]
        samples = [_parse_sample(r) for r in raw_data]
        return cls(samples)

    # ---- Container protocol ----

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, key: Union[int, str]) -> LoCoMoSample:
        if isinstance(key, str):
            idx = self._index.get(key)
            if idx is None:
                raise KeyError(f"Sample '{key}' not found in dataset")
            return self._samples[idx]
        return self._samples[key]

    def __iter__(self) -> Iterator[LoCoMoSample]:
        return iter(self._samples)

    def __contains__(self, sample_id: str) -> bool:
        return sample_id in self._index

    # ---- Accessors ----

    @property
    def samples(self) -> List[LoCoMoSample]:
        return list(self._samples)

    @property
    def sample_ids(self) -> List[str]:
        return [s.sample_id for s in self._samples]

    # ---- Filtering ----

    def filter_by_ids(self, ids: Sequence[str]) -> "LoCoMoDataset":
        """Return a new dataset containing only the given sample IDs."""
        id_set = set(ids)
        filtered = [s for s in self._samples if s.sample_id in id_set]
        return LoCoMoDataset(filtered)

    def get_all_qa(
        self,
        category: Optional[QACategory] = None,
    ) -> List[tuple[str, QAAnnotation]]:
        """
        Collect all QA annotations across all samples.

        Parameters
        ----------
        category : QACategory, optional
            If provided, filter by this category.

        Returns
        -------
        list of (sample_id, QAAnnotation)
        """
        results: List[tuple[str, QAAnnotation]] = []
        for sample in self._samples:
            for qa in sample.qa:
                if category is None or qa.category == category.value:
                    results.append((sample.sample_id, qa))
        return results

    # ---- Statistics ----

    def stats(self) -> Dict[str, Any]:
        """Compute aggregate statistics for the dataset."""
        total_qa = sum(s.num_qa for s in self._samples)
        total_sessions = sum(s.num_sessions for s in self._samples)
        total_turns = sum(s.num_turns for s in self._samples)
        total_events = sum(s.event_summary.total_events for s in self._samples)

        # QA category breakdown
        cat_counts: Dict[str, int] = {}
        for sample in self._samples:
            for label, count in sample.qa_category_counts.items():
                cat_counts[label] = cat_counts.get(label, 0) + count

        return {
            "num_samples": len(self._samples),
            "total_qa": total_qa,
            "total_sessions": total_sessions,
            "total_turns": total_turns,
            "total_events": total_events,
            "avg_sessions_per_conv": (total_sessions / len(self._samples) if self._samples else 0),
            "avg_turns_per_conv": (total_turns / len(self._samples) if self._samples else 0),
            "avg_qa_per_conv": (total_qa / len(self._samples) if self._samples else 0),
            "qa_category_counts": cat_counts,
        }

    def print_stats(self) -> None:
        """Print dataset statistics to stdout."""
        s = self.stats()
        print("=" * 60)
        print("  LoCoMo Dataset Statistics")
        print("=" * 60)
        print(f"  Samples:            {s['num_samples']}")
        print(f"  Total QA:           {s['total_qa']}")
        print(f"  Total sessions:     {s['total_sessions']}")
        print(f"  Total turns:        {s['total_turns']}")
        print(f"  Total events:       {s['total_events']}")
        print(f"  Avg sessions/conv:  {s['avg_sessions_per_conv']:.1f}")
        print(f"  Avg turns/conv:     {s['avg_turns_per_conv']:.1f}")
        print(f"  Avg QA/conv:        {s['avg_qa_per_conv']:.1f}")
        print()
        print("  QA category breakdown:")
        for cat, count in sorted(s["qa_category_counts"].items()):
            print(f"    {cat:20s}  {count}")
        print("=" * 60)
