# Trade-offs and limitations

Say these before an interviewer finds them.

| Choice | Why | Cost |
|---|---|---|
| Rule-based detection | Explainable, testable, no labelled data needed | Cannot learn new patterns; thresholds are hand-set |
| Synthetic data | Safe and repeatable; ground truth known | Scores do not predict real-world accuracy |
| SQLite | Zero setup, fine for a demo | One writer; not for heavy concurrent load |
| One process | In-memory stream, simulator and rate limiter stay consistent | Cannot scale out without a shared store (e.g. Redis) |
| In-memory rate limiter | Simple | Per process; clients behind one proxy look like one |
| Swappable embedder (neural when installed, offline LSA otherwise) | Tests and free-tier hosting need no download; one interface | The offline embedder measured no better than keyword TF-IDF on 30 questions; the neural one is unmeasured here |
| ML triage on top of rules | Higher precision (71.7% to 92.7% on held-out synthetic worlds) | Recall falls ~4 points; does not generalise to look-alike types it never saw (0% removed) |
| Shape features, not amount sizes | Avoids fitting the generator's numbers | Lower headline precision than the amount-aware ablation (92.7% vs 99.7%) |
| Body limit via Content-Length | Cheap | Does not stop a chunked upload with no length |
| No authentication | Keeps scope on detection | Not safe to expose publicly |

## What the evaluation does and does not show
- Benchmark seed 42: graph engine precision 52/70 (74.3%), recall 40/40 (100%), F1 0.853. Baseline (large transfer, velocity, counterparties): precision 39/168 (23.2%), strict recall 20/40 (50.0%).
- Across 20 seeds (1-20): graph precision 0.667-0.746 (mean 0.716); recall always 1.000; baseline precision 0.220-0.259. On 20 held-out seeds (101-120, never used while tuning): mean 0.721, range 0.694-0.750. [`--seeds 20 --seed-start 101`]
- **Recall is 100% by construction**: the planted patterns were written to match the rules. The informative figure is precision, and most false positives (16 of 18 on seed 42) are benign look-alikes (payroll, split bills, marketplace payouts) that have the same shape as the patterns, so structure alone cannot separate them.
- Authored by the same person who wrote the detectors, so it is a regression and comparison tool, not proof of real accuracy.

## What the precision work did and did not do
Error analysis found two real defects: loops of unrelated payments counted as cycles, and one burst reported once per account. Fixing them removed all background-traffic false alarms and lifted the simulator stream from 16/21 to 13/13 precision. It did **not** change headline benchmark precision on the held-out seeds (72.2% before, 72.1% after): removing duplicate findings removes true findings too, and the remaining false alarms are benign look-alikes. Improving that needs a new signal (for example, whether the same accounts have paid each other regularly before), not a tighter threshold. Tightening thresholds until the look-alikes disappear would raise the score by fitting my own benchmark.

## Not measured, so not claimed
Throughput, latency, memory, scalability, accuracy on real data, any AI-model quality.
