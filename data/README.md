# 📂 Data Directory — LoCoMo Benchmark Dataset

This folder holds the **LoCoMo** dataset files used by the benchmark suite at
`benchmarks/locomo/`.

## Download Instructions

### Option 1 — Clone the official repository

```bash
git clone https://github.com/snap-research/locomo.git /tmp/locomo
cp /tmp/locomo/data/locomo10.json data/locomo10.json
```

### Option 2 — Direct download

```bash
curl -L -o data/locomo10.json \
  https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
```

## Expected Structure

```
graph-memory/
└── data/
    ├── README.md          ← this file
    └── locomo10.json      ← LoCoMo dataset (10 conversations)
```

## Dataset Overview

The `locomo10.json` file contains **10 very long-term conversations**, each with:

| Field | Description |
|-------|-------------|
| `sample_id` | Unique conversation identifier (e.g. `conv-26`) |
| `conversation` | Multi-session dialog with timestamps, speakers, text, and images |
| `qa` | Question-answer annotations across 5 reasoning categories |
| `event_summary` | Ground-truth life events per session per speaker |
| `observation` | Speaker assertions extracted from dialog turns |
| `session_summary` | Text summaries for each session |

### Quick Statistics

- **10** conversations
- **~300** turns per conversation (avg.)
- **~9,200** tokens per conversation (avg.)
- **~19** sessions per conversation (avg.)
- **~1,500** total QA annotations
- **5** QA reasoning categories: single-hop, temporal, commonsense, open-domain, adversarial

## Verify the Dataset

Run the following from the `graph-memory/` directory to confirm everything loads correctly:

```bash
python -m benchmarks.locomo.run_benchmark --data data/locomo10.json --stats-only
```

To run the full benchmark against a running graph-memory instance (default: `http://localhost:8080`):

```bash
docker compose up -d
python -m benchmarks.locomo.run_benchmark \
    --data data/locomo10.json \
    --adapter graph-memory \
    --task qa \
    --graph-memory-url http://localhost:8080 \
    --graph-memory-token "$GRAPH_MEMORY_TOKEN"
```

> **Note:** Port `8080` is the WAF reverse-proxy exposed to the host.
> The MCP service itself listens on `8002` internally within Docker.

## License

The LoCoMo dataset is released under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) by Snap Research.

## Reference

> Maharana, A., Lee, D.-H., Tulyakov, S., Bansal, M., Barbieri, F., & Fang, Y. (2024).
> *Evaluating Very Long-Term Conversational Memory of LLM Agents.*
> ACL 2024. [arXiv:2402.17753](https://arxiv.org/abs/2402.17753)