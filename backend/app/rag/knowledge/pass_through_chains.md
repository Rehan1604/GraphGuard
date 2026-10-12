---
title: Pass-through chains
rules: pass_through_chain
---

## What the pattern is
- A pass-through chain is a run of transfers where each account receives money and sends most of it onward soon afterwards, for example A to B to C to D.
- The accounts in the middle keep very little. The money seems to pass through them.
- GraphGuard flags a chain when every hop happens inside a short time window and forwards a large share of what arrived.

## Why it can matter
- Money moved quickly through several accounts can make it harder to see where it first came from.
- Analysts sometimes call this general idea layering, but a chain on its own does not show anyone's intent.
- A longer chain, with faster and more complete hops, deserves a closer look than a short and slow one.

## Innocent explanations
- A payroll, marketplace or payment-processor account that collects money and pays it out to others.
- A business paying a supplier who then pays a sub-contractor.
- Friends or family splitting a shared cost and forwarding their share.
- A person moving their own money between accounts held at different institutions.

## What to check next
- Do the middle accounts belong to businesses whose normal job is to forward funds?
- Are the amounts and timing typical for these accounts, judging by their earlier history?
- Is there a plausible commercial or personal reason that connects the accounts?
- Has the same chain shape appeared before? Repetition deserves more attention than a one-off.
- Write down what you checked and what you could not verify.