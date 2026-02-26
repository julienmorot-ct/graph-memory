# 🧪 LoCoMo Benchmark — Long-Term Conversational Memory Evaluation

Implementation of the **LoCoMo** evaluation framework for testing long-term
conversational memory in the **graph-memory** MCP service.

> Based on the paper:
> **"Evaluating Very Long-Term Conversational Memory of LLM Agents"**
> Maharana et al., ACL 2024 ([arXiv:2402.17753](https://arxiv.org/abs/2402.17753))

---

## 📋 Overview

LoCoMo is a benchmark for evaluating how well LLM-based systems remember and
reason over **very long-term conversations** — each encompassing ~300 turns and
~9K tokens across up to 35 sessions.

This implementation adapts the LoCoMo evaluation framework to test the
**graph-memory** knowledge graph + RAG pipeline, comparing it against a
direct-LLM baseline (truncated context window).

### Tasks

| Task | Description | Primary Metric |
|------|-------------|----------------|
| **Question Answering** | Answer questions requiring recall across 5 reasoning categories | F1 (partial match) |
| **Event Summarization** | Extract chronological event graphs from conversation history | FactScore (P / R / F1) |

### QA Reasoning Categories

| # | Category | Description |
|---|----------|-------------|
| 1 | Single-hop | Answer based on a single session |
| 2 | Temporal | Time-related reasoning and date cues |
| 3 | Commonsense | Integration with world/common knowledge |
| 4 | Open-domain | Multi-hop synthesis across multiple sessions |
| 5 | Adversarial | Unanswerable or speaker-swapped trick questions |

---

## 📦 Project Structure

```
benchmarks/locomo/
├── README.md                       # This file
├── __init__.py                     # Package exports
├── models.py                       # Pydantic data models for LoCoMo format
├── data_loader.py                  # JSON dataset parser
├── run_benchmark.py                # CLI entry point
│
├── metrics/
│   └── __init__.py                 # F1, FactScore, retrieval accuracy
│
├── adapters/
│   └── __init__.py                 # BaseAdapter, GraphMemoryAdapter, DirectLLMAdapter
│
└── tasks/
    ├── __init__.py
    ├── question_answering.py       # QA task runner (5 categories)
    └── event_summarization.py      # Event graph extraction task
```

---

## 🚀 Quick Start

### 1. Download the LoCoMo Dataset

```bash
# Clone the official LoCoMo repository
git clone https://github.com/snap-research/locomo.git /tmp/locomo

# Copy the dataset file into your project
cp /tmp/locomo/data/locomo10.json data/locomo10.json
```

The dataset contains **10 conversations** with full annotations for QA and
event summarization tasks.

### 2. Verify Dataset

```bash
# Print dataset statistics (no evaluation, no adapter needed)
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --stats-only
```

Expected output:

```
============================================================
  LoCoMo Dataset Statistics
============================================================
  Samples:            10
  Total QA:           ~1500
  Total sessions:     ~200
  Total turns:        ~3000
  ...
============================================================
```

### 3. Run QA Benchmark with Graph-Memory

Make sure the graph-memory service is running:

```bash
docker compose up -d
docker compose ps   # wait until all services are healthy
```

Then run the benchmark:

```bash
# Use the ADMIN_BOOTSTRAP_KEY from your .env file,
# or a token created via the admin_create_token tool.
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --adapter graph-memory \
    --task qa \
    --graph-memory-url http://localhost:8080 \
    --graph-memory-token "$GRAPH_MEMORY_TOKEN" \
    --context-type dialog \
    --top-k 10 \
    --output results/locomo_qa_graph_memory.json
```

> **Note:** Port `8080` is the WAF reverse-proxy exposed to the host.
> The MCP service itself listens on `8002` but that port is internal to
> Docker only. See `docker-compose.yml` for details.

### 4. Run QA Benchmark with Direct LLM (Baseline)

```bash
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --adapter direct-llm \
    --task qa \
    --llm-api-url https://api.ai.cloud-temple.com \
    --llm-api-key YOUR_API_KEY \
    --llm-model gpt-oss:120b \
    --max-context 4096 \
    --output results/locomo_qa_direct_llm.json
```

### 5. Run Event Summarization

```bash
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --adapter graph-memory \
    --task event-summarization \
    --graph-memory-url http://localhost:8080 \
    --graph-memory-token "$GRAPH_MEMORY_TOKEN" \
    --per-speaker \
    --verbose \
    --output results/locomo_events_graph_memory.json
```

### 6. Run All Tasks

```bash
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --adapter graph-memory \
    --task all \
    --graph-memory-url http://localhost:8080 \
    --graph-memory-token "$GRAPH_MEMORY_TOKEN" \
    --output results/locomo_full_benchmark.json
```

---

## ⚙️ CLI Reference

```
usage: locomo-benchmark [-h] --data DATA
                        [--task {qa,event-summarization,all}]
                        [--adapter {graph-memory,direct-llm}]
                        [--samples [SAMPLES ...]]
                        [--context-type {dialog,observation,summary}]
                        [--top-k TOP_K]
                        [--qa-categories [1-5 ...]]
                        [--per-speaker]
                        [--graph-memory-url URL]
                        [--graph-memory-token TOKEN]
                        [--llm-api-url URL]
                        [--llm-api-key KEY]
                        [--llm-model MODEL]
                        [--max-context TOKENS]
                        [--output PATH]
                        [--verbose]
                        [--stats-only]
                        [--max-concurrent N]
```

### Key Options

| Option | Default | Description |
|--------|---------|-------------|
| `--data` | *(required)* | Path to `locomo10.json` |
| `--task` | `qa` | Task to run: `qa`, `event-summarization`, or `all` |
| `--adapter` | `graph-memory` | Adapter: `graph-memory` or `direct-llm` |
| `--samples` | all | Specific sample IDs to evaluate (e.g. `conv-26 conv-30`) |
| `--context-type` | `dialog` | RAG context type: `dialog`, `observation`, `summary` |
| `--top-k` | `10` | Number of retrieved context chunks |
| `--qa-categories` | all | Category filter (1=single-hop … 5=adversarial) |
| `--per-speaker` | `false` | Evaluate events per-speaker instead of combined |
| `--verbose` | `false` | Log individual question/event results |
| `--max-concurrent` | `5` | Max concurrent adapter calls |
| `--output` | *(none)* | Path for JSON results file |

### Environment Variables

| Variable | Fallback | Description |
|----------|----------|-------------|
| `GRAPH_MEMORY_URL` | `http://localhost:8080` | Graph-memory WAF proxy URL |
| `GRAPH_MEMORY_TOKEN` | *(none)* | Graph-memory auth token |
| `LLMAAS_API_URL` | `https://api.openai.com/v1` | LLM API URL |
| `LLMAAS_API_KEY` | *(none)* | LLM API key |
| `LLMAAS_MODEL` | `gpt-3.5-turbo` | LLM model identifier |

---

## 🏗️ Architecture

### Evaluation Pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  LoCoMo JSON │───▶│  DataLoader  │───▶│ LoCoMoSample │
│  (locomo10)  │    │  (parsing)   │    │  (Pydantic)  │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         │                     │                     │
                    ┌────▼─────┐         ┌─────▼──────┐        ┌────▼────┐
                    │ QA Task  │         │ Event Sum. │        │ (Future)│
                    │ Runner   │         │  Task      │        │ Dialog  │
                    └────┬─────┘         └─────┬──────┘        │ Gen.   │
                         │                     │               └─────────┘
                    ┌────▼─────────────────────▼────┐
                    │         Adapter Layer          │
                    │  ┌────────────┬──────────────┐ │
                    │  │ Graph-     │ Direct LLM   │ │
                    │  │ Memory     │ (baseline)   │ │
                    │  └─────┬──────┴───────┬──────┘ │
                    └────────┼──────────────┼────────┘
                             │              │
                    ┌────────▼──────┐ ┌─────▼──────────┐
                    │  graph-memory │ │ OpenAI-compat  │
                    │  MCP Service  │ │ LLM API        │
                    │  (Neo4j +     │ │                │
                    │   Qdrant +    │ │                │
                    │   LLM)        │ │                │
                    └───────────────┘ └────────────────┘
                             │
                    ┌────────▼──────┐
                    │   Metrics     │
                    │  (F1, Fact-   │
                    │   Score, EM)  │
                    └───────────────┘
```

### Adapters

**GraphMemoryAdapter** — Tests the full graph-memory pipeline:

1. **Ingest**: Creates a memory namespace and ingests the conversation text
   (with BLIP-2 image captions) as a document. Optionally ingests speaker
   observations as a second document.
2. **QA**: Uses the `question_answer` tool which performs Graph-Guided RAG
   (graph entity search → vector similarity search → LLM answer generation).
3. **Event Summarization**: Uses the `memory_query` tool with a prompt
   asking the LLM to extract chronological life events from the knowledge
   graph and vector store context.

**DirectLLMAdapter** — Baseline comparison:

1. **Ingest**: No-op (context is passed inline with each query).
2. **QA**: Truncates the conversation to fit the context window and asks
   the LLM to answer directly.
3. **Event Summarization**: Uses incremental summarization — iteratively
   summarizes preceding sessions and uses that summary as a basis for the
   subsequent session (following the paper's approach).

### Metrics

**QA — F1 Partial Match** (primary metric):
- Normalise both prediction and ground truth (lowercase, remove punctuation
  and articles, collapse whitespace).
- Compute token-level precision, recall, and F1.
- For adversarial questions: check if the model was tricked into giving the
  wrong-speaker answer; reward correct refusals.

**Event Summarization — FactScore**:
- Decompose both prediction and reference into atomic facts (sentences).
- **Precision**: fraction of predicted facts that match a reference fact
  (token-level F1 ≥ 0.5 threshold).
- **Recall**: fraction of reference facts covered by a predicted fact.
- **F1**: harmonic mean of precision and recall.

---

## 📊 Expected Results (Paper Baselines)

From Table 2 & 3 of the paper (F1 scores on the full 50-conversation dataset):

| Model | Single-Hop | Multi-Hop | Temporal | Open-Domain | Adversarial | Overall |
|-------|----------:|----------:|---------:|------------:|------------:|--------:|
| Human | 95.1 | 85.8 | 92.6 | 75.4 | 89.4 | **87.9** |
| GPT-3.5-turbo (4K) | 29.9 | 23.3 | 17.5 | 29.5 | 12.8 | 22.4 |
| GPT-3.5-turbo-16K | 56.4 | 42.0 | 20.3 | 37.2 | 2.1 | 37.8 |
| RAG (observations, k=5) | 44.3 | 30.6 | 41.9 | 40.2 | 44.7 | **41.4** |
| GPT-4-turbo (4K) | 23.4 | 23.4 | 10.4 | 24.6 | 70.2 | 32.1 |

**Key findings from the paper:**
- RAG with observations outperforms long-context LLMs overall.
- Long-context LLMs are vulnerable to adversarial questions (F1 drops to 2%).
- Temporal reasoning is the hardest category across all approaches.
- Graph-memory's combination of knowledge graph + vector RAG is expected to
  perform competitively with observation-based RAG approaches.

---

## 🧩 Programmatic Usage

### Load and inspect the dataset

```python
from benchmarks.locomo.data_loader import LoCoMoDataset
from benchmarks.locomo.models import QACategory

dataset = LoCoMoDataset.from_file("data/locomo10.json")
dataset.print_stats()

# Access a specific sample
sample = dataset["conv-26"]
print(f"Speakers: {sample.speaker_a} & {sample.speaker_b}")
print(f"Sessions: {sample.num_sessions}, Turns: {sample.num_turns}")
print(f"QA questions: {sample.num_qa}")
print(f"QA categories: {sample.qa_category_counts}")

# Get all temporal reasoning questions
temporal_qs = sample.get_qa_by_category(QACategory.TEMPORAL)
for qa in temporal_qs[:3]:
    print(f"  Q: {qa.question}")
    print(f"  A: {qa.answer}")
    print(f"  Evidence: {qa.evidence}")
    print()
```

### Run QA evaluation programmatically

```python
import asyncio
from benchmarks.locomo.data_loader import LoCoMoDataset
from benchmarks.locomo.adapters import GraphMemoryAdapter
from benchmarks.locomo.tasks.question_answering import QATask

async def main():
    dataset = LoCoMoDataset.from_file("data/locomo10.json")
    adapter = GraphMemoryAdapter(
        base_url="http://localhost:8080",
        auth_token="your-token",
    )
    task = QATask(
        adapter=adapter,
        context_type="dialog",
        top_k=10,
        verbose=True,
    )

    await task.setup()
    try:
        result = await task.evaluate(dataset[0])  # Single sample
        print(result.summary())
        print(task.summary_table())
    finally:
        await task.teardown()

asyncio.run(main())
```

### Use metrics directly

```python
from benchmarks.locomo.metrics import (
    compute_f1,
    compute_exact_match,
    compute_qa_metrics,
    compute_factscore,
    evaluate_adversarial,
)

# F1 score for a single QA pair
f1 = compute_f1(
    prediction="she likes painting and hiking",
    ground_truth="painting, hiking",
)
print(f"F1: {f1:.4f}")  # High overlap → high F1

# Adversarial evaluation
result = evaluate_adversarial(
    prediction="I cannot answer this question based on the conversation.",
    adversarial_answer="She went to Paris",
    ground_truth_answer=None,
)
print(f"Tricked: {result['tricked']}, Refused: {result['refused']}, F1: {result['f1']}")

# FactScore for event summarization
scores = compute_factscore(
    prediction="John started a new job in March. He went hiking with friends.",
    reference="John began working at a new company in March 2023. John went on a hike.",
)
print(f"Precision: {scores['precision']:.4f}")
print(f"Recall:    {scores['recall']:.4f}")
print(f"F1:        {scores['f1']:.4f}")
```

---

## 🔧 Extending the Framework

### Adding a New Adapter

Create a new class that extends `BaseAdapter`:

```python
from benchmarks.locomo.adapters import BaseAdapter
from benchmarks.locomo.models import LoCoMoSample, QAPrediction

class MyCustomAdapter(BaseAdapter):
    def __init__(self, **kwargs):
        super().__init__(name="my-adapter", config=kwargs)

    async def ingest(self, sample: LoCoMoSample) -> None:
        # Store conversation in your system
        ...

    async def answer_question(self, sample, question, **kwargs) -> QAPrediction:
        # Retrieve context and generate answer
        answer = ...
        return QAPrediction(question=question, predicted_answer=answer)

    async def summarize_events(self, sample, speaker=None) -> str:
        # Generate event summary
        return ...
```

### Adding New Metrics

Add functions to `benchmarks/locomo/metrics/__init__.py`:

```python
def compute_bertscore(prediction: str, reference: str) -> Dict[str, float]:
    """Compute BERTScore between prediction and reference."""
    # pip install bert-score
    from bert_score import score
    P, R, F1 = score([prediction], [reference], lang="en")
    return {"precision": P.item(), "recall": R.item(), "f1": F1.item()}
```

---

## 📚 References

- **LoCoMo Paper**: Maharana, A., Lee, D.-H., Tulyakov, S., Bansal, M.,
  Barbieri, F., & Fang, Y. (2024). *Evaluating Very Long-Term Conversational
  Memory of LLM Agents*. ACL 2024. [arXiv:2402.17753](https://arxiv.org/abs/2402.17753)
- **LoCoMo Code & Data**: [github.com/snap-research/locomo](https://github.com/snap-research/locomo)
- **FactScore**: Min, S., et al. (2023). *FActScore: Fine-grained Atomic
  Evaluation of Factual Precision in Long Form Text Generation*. EMNLP 2023.
- **Graph-Memory**: [README.md](../../README.md)

---

## 📄 License

This benchmark implementation follows the same license as the graph-memory
project (MIT). The LoCoMo dataset is released under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).