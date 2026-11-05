# Benchmark results — classifier v2

Items: 62 (3 UNCLEAR excluded from scoring).

| Metric | Value |
|---|---|
| Exact tier accuracy | 56/59 (95%) |
| Within one tier | 58/59 (98%) |
| real items exact | 30/33 (91%) |
| synthetic items exact | 26/26 (100%) |
| Actionable (A/B) precision | 1.00 |
| Actionable (A/B) recall | 0.95 |
| False positives (pred A/B, gold C/D/REJECT) | 0 |
| False negatives (gold A/B, pred C/D/REJECT) | 1 |
| Over-scored (pred tier higher than gold) | 1 |
| Under-scored (pred tier lower than gold) | 2 |

## Confusion matrix (rows = gold, cols = predicted)

| gold \ pred | A | B | C | D | REJECT |
|---|---|---|---|---|---|
| A | 8 | 1 | 0 | 0 | 0 |
| B | 0 | 12 | 0 | 0 | 1 |
| C | 0 | 0 | 2 | 0 | 0 |
| D | 0 | 0 | 0 | 9 | 0 |
| REJECT | 0 | 0 | 0 | 1 | 25 |

## Every disagreement

| origin | gold | pred | title | matched evidence | gold note |
|---|---|---|---|---|---|
| real | REJECT | D | AI Automation Engineer | Automation | URL slug shows a job-seeker; the title alone is ambiguous. |
| real | B | REJECT | Looking For a Part-Time Automation Expert! | Part-Time; Looking For a Part-Time Automation Expert; Automation | Part-time contractor on a hire board. Borderline: could be employment. |
| real | A | B | Build lead capture and booking automation Pro needed | Pro needed; automation; lead capture | Defined deliverable + 'Pro needed'. |

## UNCLEAR items (not scored)

- pred **A** — Workflow Automation for a fee — Could be a buyer offering a fee OR a freelancer offering work for a fee.
- pred **B** — Automation Contract — 'Automation Contract' could be building/industrial automation.
- pred **A** — Healthcare AI Solutions — Relabelled 2026-11-05 (was D): AI development/implementation is now in Solvant's scope, and the title alone cannot tell whether the tender buys an AI product or implementation services.
