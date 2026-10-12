---
title: Circular flows
rules: cycle
---

## What the pattern is
- A circular flow is money that leaves an account and, after passing through other accounts, comes back to the account it started from, for example A to B to C to A.
- GraphGuard looks for loops that finish inside a time window and contain a small number of transfers.
- The amounts around the loop are often similar, because little is lost or kept along the way.

## Why it can matter
- A loop moves a lot of money while leaving the starting account in roughly the same position, so it can make activity look bigger than the underlying business.
- Analysts sometimes call this round-tripping. It is a reason to look closer, not a conclusion.
- Tight loops with near-equal amounts are more unusual than loose loops with varied amounts.

## Innocent explanations
- Groups of friends or flatmates settling shared expenses in several directions.
- Refunds, reversals and chargebacks that send money back along the path it came from.
- Businesses that trade with each other in both directions as part of normal supply arrangements.
- A person moving money between their own accounts and back again.

## What to check next
- Is there a documented relationship between the accounts, such as shared ownership or a contract?
- Do the amounts match a refund, a settlement or an invoice, or do they look arbitrary?
- Does the loop repeat at regular intervals or with growing amounts?
- Compare with the accounts' earlier behaviour: is two-way traffic normal for them?
- Record the reasoning behind your decision, including what could not be confirmed.