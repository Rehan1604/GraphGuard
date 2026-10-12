---
title: Many counterparties
rules: fan
---

## What the pattern is
- This pattern is one account dealing with many different other accounts inside a short time window.
- It can point inwards (many accounts paying one account) or outwards (one account paying many accounts), or both.
- GraphGuard counts distinct counterparties, so repeat transfers with the same account count once.

## Why it can matter
- Money gathered from many sources into one place, or spread from one place to many, changes how the network is connected.
- A hub account that suddenly appears can be a sign that funds are being collected or distributed.
- The number of counterparties above the threshold is a rough measure of how unusual the pattern is.

## Innocent explanations
- A shop, charity or event organiser receiving payments from many customers.
- A business paying many suppliers, contractors or staff on the same day.
- A club or society collecting dues and then paying a venue.
- A marketplace or payment platform doing its normal job.

## What to check next
- Does the account type and history match the role of a collecting or paying hub?
- Are the amounts uniform, as with fixed prices or fees, or varied?
- Do many of the counterparties appear for the first time?
- Is money collected from many accounts and then quickly sent on to one place?
- Note which counterparties you could and could not explain.