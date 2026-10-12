# Trade-offs and limitations

Say these before an interviewer finds them.

| Choice | Why | Cost |
|---|---|---|
| Rule-based detection | Explainable, testable, no labelled data needed | Cannot learn new patterns; thresholds are hand-set |
| Synthetic data | Safe and repeatable; ground truth known | Scores do not predict real-world accuracy |
| SQLite | Zero setup, fine for a demo | One writer; not for heavy concurrent load |
| One process | In-memory stream, simulator and rate limiter stay consistent | Cannot scale out without a shared store (e.g. Redis) |
| In-memory rate limiter | Simple | Per process; clients behind one proxy look like one |
| TF-IDF retrieval | Offline, deterministic, no embeddings model | Weaker on paraphrase than embeddings |
| Body limit via Content-Length | Cheap | Does not stop a chunked upload with no length |
| No authentication | Keeps scope on detection | Not safe to expose publicly |

## What the evaluation does and does not show
- Benchmark seed 42: graph engine precision 59/82 (72.0%), recall 40/40 (100%), F1 0.837. Baseline (large transfer, velocity, counterparties): precision 39/168 (23.2%), strict recall 20/40 (50.0%).
- Across 20 seeds: graph precision 0.679-0.740 (mean 0.713); recall always 1.000; baseline precision 0.220-0.259.
- **Recall is 100% by construction**: the planted patterns were written to match the rules. The informative figure is precision, and most false positives are benign look-alikes the rules cannot tell apart.
- Authored by the same person who wrote the detectors, so it is a regression and comparison tool, not proof of real accuracy.

## Not measured, so not claimed
Throughput, latency, memory, scalability, accuracy on real data, any AI-model quality.
