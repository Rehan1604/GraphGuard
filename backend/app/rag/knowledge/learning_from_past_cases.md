---
title: Learning from earlier reviews
rules: general
---

## Why past decisions matter
- Teams review many alerts of the same kind. What reviewers decided before, and why, is the best guide to how similar alerts should be handled.
- When an earlier alert was dismissed with a clear reason such as a known payroll run, a similar new alert may have the same explanation, but this still has to be checked.
- When an earlier alert was escalated, the reasons given can show which details mattered.

## How this tool uses them
- The assistant searches alerts that were already dismissed or escalated in this workspace and shows those with comments closest in meaning to the question.
- Only the outcome of those cases is ever shared with an outside language model. The reviewer's own words stay on this computer.
- Similar means similar in meaning. It never means the same people or the same accounts.

## Good habits that make this useful
- Write the reason for every dismissal and escalation in plain words, including what was checked.
- Name the kind of activity, for example payroll, supplier payment or refund, so later reviewers can find it.
- Say what could not be verified. Honest gaps help the next reviewer more than confident guesses.
