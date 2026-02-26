# -*- coding: utf-8 -*-
"""
Evaluation metrics for the LoCoMo benchmark.

Implements the metrics described in:
    "Evaluating Very Long-Term Conversational Memory of LLM Agents"
    Maharana et al., ACL 2024 (arXiv:2402.17753)

Metrics:
    - F1 partial match score for Question Answering
    - Exact match score for Question Answering
    - FactScore (precision, recall, F1) for Event Summarization
    - ROUGE scores for Event Summarization
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# =============================================================================
# Text Normalization
# =============================================================================


def normalize_answer(text: Union[str, int, float, None]) -> str:
    """
    Normalize an answer string for evaluation.

    Applies the same normalization as the original LoCoMo evaluation:
      - Lowercase
      - Remove punctuation
      - Remove articles (a, an, the)
      - Collapse whitespace

    Parameters
    ----------
    text : str, int, float, or None
        The answer text to normalize. Non-string types are cast to str.

    Returns
    -------
    str
        Normalized answer string.
    """
    if text is None:
        return ""
    s = str(text).lower()
    # Remove punctuation
    s = s.translate(str.maketrans("", "", string.punctuation))
    # Remove articles
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    # Collapse whitespace
    s = " ".join(s.split())
    return s.strip()


def tokenize(text: str) -> List[str]:
    """
    Tokenize a normalized answer string into words.

    Parameters
    ----------
    text : str
        Already-normalized text.

    Returns
    -------
    list of str
        Token list.
    """
    return text.split()


# =============================================================================
# QA Metrics — F1 Partial Match
# =============================================================================


def compute_f1(prediction: str, ground_truth: str) -> float:
    """
    Compute token-level F1 score between a prediction and ground truth.

    This is the primary QA metric in the LoCoMo benchmark. Both inputs
    are normalized before comparison.

    Parameters
    ----------
    prediction : str
        The model's predicted answer.
    ground_truth : str
        The ground-truth answer.

    Returns
    -------
    float
        F1 score in [0.0, 1.0].
    """
    pred_tokens = tokenize(normalize_answer(prediction))
    gold_tokens = tokenize(normalize_answer(ground_truth))

    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_common = sum(common.values())

    if num_common == 0:
        return 0.0

    precision = num_common / len(pred_tokens)
    recall = num_common / len(gold_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1


def compute_exact_match(prediction: str, ground_truth: str) -> bool:
    """
    Check if the normalized prediction exactly matches the ground truth.

    Parameters
    ----------
    prediction : str
        The model's predicted answer.
    ground_truth : str
        The ground-truth answer.

    Returns
    -------
    bool
        True if the normalized strings are identical.
    """
    return normalize_answer(prediction) == normalize_answer(ground_truth)


def compute_precision(prediction: str, ground_truth: str) -> float:
    """
    Compute token-level precision of prediction against ground truth.

    Parameters
    ----------
    prediction : str
        The model's predicted answer.
    ground_truth : str
        The ground-truth answer.

    Returns
    -------
    float
        Precision in [0.0, 1.0].
    """
    pred_tokens = tokenize(normalize_answer(prediction))
    gold_tokens = tokenize(normalize_answer(ground_truth))

    if not pred_tokens:
        return 1.0 if not gold_tokens else 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_common = sum(common.values())
    return num_common / len(pred_tokens) if pred_tokens else 0.0


def compute_recall(prediction: str, ground_truth: str) -> float:
    """
    Compute token-level recall of prediction against ground truth.

    Parameters
    ----------
    prediction : str
        The model's predicted answer.
    ground_truth : str
        The ground-truth answer.

    Returns
    -------
    float
        Recall in [0.0, 1.0].
    """
    pred_tokens = tokenize(normalize_answer(prediction))
    gold_tokens = tokenize(normalize_answer(ground_truth))

    if not gold_tokens:
        return 1.0 if not pred_tokens else 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_common = sum(common.values())
    return num_common / len(gold_tokens) if gold_tokens else 0.0


# =============================================================================
# QA Metrics — Batch / Aggregated
# =============================================================================


def compute_qa_metrics(
    predictions: Sequence[str],
    ground_truths: Sequence[str],
    categories: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """
    Compute aggregated QA metrics over a batch of predictions.

    Parameters
    ----------
    predictions : sequence of str
        Model predictions.
    ground_truths : sequence of str
        Ground-truth answers.
    categories : sequence of int, optional
        QA category for each sample (1-5). If provided, per-category
        metrics are also computed.

    Returns
    -------
    dict
        Dictionary with keys:
        - ``overall_f1``: Mean F1 across all samples.
        - ``overall_em``: Mean exact match across all samples.
        - ``num_samples``: Total number of samples.
        - ``per_category``: Dict mapping category label to category metrics
          (only if ``categories`` is provided).
    """
    assert len(predictions) == len(ground_truths), (
        f"Length mismatch: {len(predictions)} predictions vs {len(ground_truths)} ground truths"
    )

    n = len(predictions)
    if n == 0:
        return {"overall_f1": 0.0, "overall_em": 0.0, "num_samples": 0}

    f1_scores: List[float] = []
    em_scores: List[float] = []

    for pred, gt in zip(predictions, ground_truths):
        f1_scores.append(compute_f1(pred, gt))
        em_scores.append(1.0 if compute_exact_match(pred, gt) else 0.0)

    result: Dict[str, Any] = {
        "overall_f1": sum(f1_scores) / n,
        "overall_em": sum(em_scores) / n,
        "num_samples": n,
    }

    # Per-category breakdown
    if categories is not None:
        assert len(categories) == n
        _CATEGORY_LABELS = {
            1: "single_hop",
            2: "temporal",
            3: "commonsense",
            4: "open_domain",
            5: "adversarial",
        }
        cat_f1: Dict[str, List[float]] = {}
        cat_em: Dict[str, List[float]] = {}

        for f1, em, cat in zip(f1_scores, em_scores, categories):
            label = _CATEGORY_LABELS.get(cat, f"category_{cat}")
            cat_f1.setdefault(label, []).append(f1)
            cat_em.setdefault(label, []).append(em)

        per_category: Dict[str, Dict[str, float]] = {}
        for label in cat_f1:
            scores = cat_f1[label]
            per_category[label] = {
                "f1": sum(scores) / len(scores) if scores else 0.0,
                "em": (sum(cat_em[label]) / len(cat_em[label]) if cat_em[label] else 0.0),
                "count": len(scores),
            }

        result["per_category"] = per_category

    return result


# =============================================================================
# QA Metrics — Adversarial evaluation
# =============================================================================


def evaluate_adversarial(
    prediction: str,
    adversarial_answer: Optional[str] = None,
    ground_truth_answer: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate a prediction on an adversarial question.

    Adversarial questions in LoCoMo are designed to trick the model by
    swapping speakers. The model should either:
      - Correctly refuse to answer / say "unanswerable"
      - Give the correct answer (if one exists, e.g. "No")

    If the model gives the ``adversarial_answer`` (the wrong-speaker answer),
    it has been tricked and receives a score of 0.

    Parameters
    ----------
    prediction : str
        Model's predicted answer.
    adversarial_answer : str, optional
        The wrong answer that would result from speaker confusion.
    ground_truth_answer : str, optional
        The correct answer, if one exists.

    Returns
    -------
    dict
        - ``f1``: F1 score for this adversarial sample.
        - ``tricked``: Whether the model was tricked into giving the
          adversarial answer.
        - ``refused``: Whether the model refused to answer.
    """
    pred_norm = normalize_answer(prediction)

    # Check if model was tricked
    tricked = False
    if adversarial_answer is not None:
        adv_norm = normalize_answer(adversarial_answer)
        if adv_norm and compute_f1(prediction, str(adversarial_answer)) > 0.5:
            tricked = True

    # Check if model refused to answer
    refusal_phrases = [
        # English refusal phrases
        "unanswerable",
        "cannot answer",
        "not enough information",
        "no information",
        "cannot be determined",
        "unable to answer",
        "not mentioned",
        "does not mention",
        "no evidence",
        "impossible to determine",
        "does not contain",
        "no data",
        "not available",
        "not found",
        "no record",
        "not specified",
        "not indicated",
        "not stated",
        # French refusal phrases (graph-memory server responds in French)
        "aucun des documents",
        "aucune information",
        "ne mentionne pas",
        "ne contient pas",
        "ne contient aucune",
        "ne précise pas",
        "pas dinformation",
        "pas mentionné",
        "pas dindication",
        "impossible de déterminer",
        "impossible de répondre",
        "ne permet pas de répondre",
        "aucun des éléments",
        "aucune trace",
        "aucune mention",
        "ne fournit pas",
        "ne mentionne aucune",
        "ne décrit pas",
        "ne rapporte aucune",
        "contexte ne contient",
        "corpus ne mentionne",
        "texte ne mentionne",
        "documents fournis ne",
    ]
    refused = any(phrase in pred_norm for phrase in refusal_phrases)

    # Compute F1 score
    f1 = 0.0
    if ground_truth_answer is not None:
        f1 = compute_f1(prediction, str(ground_truth_answer))
    elif refused and not tricked:
        # No ground truth but model correctly refused — give full score
        f1 = 1.0
    elif tricked:
        f1 = 0.0

    return {
        "f1": f1,
        "tricked": tricked,
        "refused": refused,
    }


# =============================================================================
# Event Summarization Metrics — FactScore-style
# =============================================================================


def _decompose_to_atomic_facts(text: str) -> List[str]:
    """
    Decompose a text into atomic facts (sentences / clauses).

    This is a simplified version of the FactScore decomposition.
    A production implementation would use an LLM for decomposition.

    Parameters
    ----------
    text : str
        Text to decompose.

    Returns
    -------
    list of str
        List of atomic fact strings.
    """
    # Split on sentence boundaries
    sentences = re.split(r"[.!?]+", text)
    facts = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) > 5:  # skip very short fragments
            facts.append(sent)
    return facts


def compute_factscore(
    prediction: str,
    reference: str,
) -> Dict[str, float]:
    """
    Compute a simplified FactScore between prediction and reference.

    Following the LoCoMo paper, this measures:
    - **Precision**: fraction of atomic facts in prediction that match reference.
    - **Recall**: fraction of atomic facts in reference covered by prediction.
    - **F1**: harmonic mean of precision and recall.

    The matching is done via token-level F1 between pairs of atomic facts,
    with a match threshold of 0.5.

    Parameters
    ----------
    prediction : str
        The model's event summary.
    reference : str
        The ground-truth event summary.

    Returns
    -------
    dict
        ``precision``, ``recall``, ``f1`` — each in [0.0, 1.0].
    """
    pred_facts = _decompose_to_atomic_facts(prediction)
    ref_facts = _decompose_to_atomic_facts(reference)

    if not pred_facts and not ref_facts:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred_facts:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    if not ref_facts:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    match_threshold = 0.5

    # Precision: how many predicted facts are supported by reference
    pred_matched = 0
    for pf in pred_facts:
        best_score = max(compute_f1(pf, rf) for rf in ref_facts)
        if best_score >= match_threshold:
            pred_matched += 1

    # Recall: how many reference facts are covered by prediction
    ref_matched = 0
    for rf in ref_facts:
        best_score = max(compute_f1(pf, rf) for pf in pred_facts)
        if best_score >= match_threshold:
            ref_matched += 1

    precision = pred_matched / len(pred_facts)
    recall = ref_matched / len(ref_facts)

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {"precision": precision, "recall": recall, "f1": f1}


def compute_event_summarization_metrics(
    predictions: Sequence[str],
    references: Sequence[str],
) -> Dict[str, float]:
    """
    Compute aggregated event summarization metrics over a batch.

    Parameters
    ----------
    predictions : sequence of str
        Model event summaries.
    references : sequence of str
        Ground-truth event summaries.

    Returns
    -------
    dict
        Mean ``precision``, ``recall``, ``f1`` across all samples.
    """
    assert len(predictions) == len(references)

    if not predictions:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precisions: List[float] = []
    recalls: List[float] = []
    f1s: List[float] = []

    for pred, ref in zip(predictions, references):
        scores = compute_factscore(pred, ref)
        precisions.append(scores["precision"])
        recalls.append(scores["recall"])
        f1s.append(scores["f1"])

    n = len(predictions)
    return {
        "precision": sum(precisions) / n,
        "recall": sum(recalls) / n,
        "f1": sum(f1s) / n,
    }


# =============================================================================
# Retrieval Accuracy
# =============================================================================


def compute_retrieval_accuracy(
    retrieved_ids: Sequence[Sequence[str]],
    ground_truth_ids: Sequence[Sequence[str]],
) -> Dict[str, float]:
    """
    Compute recall@k for retrieval accuracy.

    For each sample, check whether the retrieved context IDs contain the
    ground-truth evidence IDs.

    Parameters
    ----------
    retrieved_ids : sequence of sequence of str
        For each sample, the list of retrieved dialog turn IDs.
    ground_truth_ids : sequence of sequence of str
        For each sample, the list of ground-truth evidence turn IDs.

    Returns
    -------
    dict
        ``recall``: fraction of samples where all evidence was retrieved.
        ``partial_recall``: mean fraction of evidence IDs retrieved per sample.
    """
    assert len(retrieved_ids) == len(ground_truth_ids)

    if not retrieved_ids:
        return {"recall": 0.0, "partial_recall": 0.0}

    full_recalls: List[float] = []
    partial_recalls: List[float] = []

    for ret, gt in zip(retrieved_ids, ground_truth_ids):
        if not gt:
            full_recalls.append(1.0)
            partial_recalls.append(1.0)
            continue

        ret_set = set(ret)
        gt_set = set(gt)
        matched = len(ret_set & gt_set)

        full_recalls.append(1.0 if matched == len(gt_set) else 0.0)
        partial_recalls.append(matched / len(gt_set))

    n = len(retrieved_ids)
    return {
        "recall": sum(full_recalls) / n,
        "partial_recall": sum(partial_recalls) / n,
    }


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "normalize_answer",
    "tokenize",
    "compute_f1",
    "compute_exact_match",
    "compute_precision",
    "compute_recall",
    "compute_qa_metrics",
    "evaluate_adversarial",
    "compute_factscore",
    "compute_event_summarization_metrics",
    "compute_retrieval_accuracy",
]
