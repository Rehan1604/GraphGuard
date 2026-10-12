---
title: Reading risk scores
rules: general
---

## What the score means
- The risk score is the sum of points awarded for specific, listed reasons, such as a fast chain or near-equal amounts around a loop.
- It is a way to decide which alerts to read first. Higher scores mean more of the listed signals were present.
- Every point can be traced to a reason, so you can see exactly why a score is what it is.

## What the score does not mean
- It is not a probability that fraud or any other wrongdoing occurred.
- It has not been calibrated against real cases, so a score of 60 does not mean a 60 percent chance of anything.
- Two alerts with the same score can have very different explanations.

## Thresholds and false positives
- Every rule uses thresholds such as time windows and minimum counts. Lower thresholds catch more genuine patterns and also more harmless ones.
- Changing a threshold changes which alerts appear, so compare results before and after.
- Synthetic test data cannot tell you how accurate the rules would be on real banking activity.