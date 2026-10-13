---
title: Reading the machine-learning triage score
rules: general
---

## What the triage score is
- After the rules raise an alert, a small trained model estimates how likely that alert is to be a genuine pattern rather than a benign look-alike or a coincidence.
- It is shown as a percentage with a verdict: likely a genuine pattern, or likely a benign look-alike.
- The model only looks at the shape and rhythm of the transfers: how even the amounts are, how regular the timing is, which direction money moves, and how much other activity surrounds the same accounts.
- It never creates an alert and never hides one. It helps a reviewer decide which alert to open first.

## How to read it
- A high estimate means the alert resembles patterns the model learned to treat as genuine. It does not mean anyone did anything wrong.
- A low estimate means the alert resembles ordinary activity such as payroll, a shared bill, or a marketplace payout. Low-scored alerts still deserve a quick look when other evidence points the other way.
- The listed drivers show which features moved the estimate for this alert. They describe influence on the model, not cause in the real world.
- The risk score from the rules and the triage estimate are different things. The risk score adds up points for how tight the pattern is. The triage estimate compares the alert with examples the model has seen.

## Limits of the estimate
- The model was trained and checked on synthetic data from a single generator. On real accounts it would need to be retrained and recalibrated.
- It recognises the kinds of benign activity it was shown. A new kind of legitimate activity can look suspicious to it, and a new kind of suspicious activity can look benign.
- Probabilities are calibrated on the benchmark, so treat them as a ranking aid and not as a measured chance of wrongdoing.
- Filtering by the estimate trades recall for precision. Some genuine patterns score low, so a low score is a reason to look later, never a reason to close an alert without reading it.
