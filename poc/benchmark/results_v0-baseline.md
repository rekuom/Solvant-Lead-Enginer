# Benchmark results — classifier v0-baseline

Items: 62 (2 UNCLEAR excluded from scoring).

| Metric | Value |
|---|---|
| Exact tier accuracy | 47/60 (78%) |
| Within one tier | 57/60 (95%) |
| Real items exact | 23/34 (68%) |
| Synthetic items exact | 24/26 (92%) |
| Actionable (A/B) precision | 0.95 |
| Actionable (A/B) recall | 0.91 |
| False positives (pred A/B, gold C/D/REJECT) | 1 |
| False negatives (gold A/B, pred C/D/REJECT) | 2 |
| Over-scored (pred tier higher than gold) | 4 |
| Under-scored (pred tier lower than gold) | 9 |

## Confusion matrix (rows = gold, cols = predicted)

| gold \ pred | A | B | C | D | REJECT |
|---|---|---|---|---|---|
| A | 6 | 3 | 0 | 0 | 0 |
| B | 0 | 11 | 0 | 0 | 2 |
| C | 0 | 0 | 1 | 1 | 0 |
| D | 0 | 1 | 0 | 6 | 3 |
| REJECT | 0 | 0 | 0 | 3 | 23 |

## Every disagreement

| origin | gold | pred | title | matched evidence | gold note |
|---|---|---|---|---|---|
| real | B | REJECT | 🚀 Hiring: Freelance AI Automation Engineer (Remote) | Hiring: Freelance AI Automation Engineer; Automation | 'Freelance' engagement = buying external help, despite job-title wording. Borderline. |
| real | REJECT | D | Hiring: Sales Tech & Automation Specialist (Ongoing Remote Work, CRM + Databases | Automation; CRM | Ongoing remote role = staffing. |
| real | REJECT | D | Hiring: AI Growth & Automation Specialist | Automation | Employment role. |
| real | REJECT | D | AI Automation Engineer | Automation | URL slug shows a job-seeker; the title alone is ambiguous. |
| real | B | REJECT | Looking For a Part-Time Automation Expert! | Part-Time; Looking For a Part-Time Automation Expert; Automation | Part-time contractor on a hire board. Borderline: could be employment. |
| real | A | B | Build lead capture and booking automation Pro needed | Pro needed; automation; lead capture | Defined deliverable + 'Pro needed'. |
| real | A | B | Provision of Robotic Process Automation Services | public procurement notice; Automation; Robotic Process | Public procurement of RPA services (fit/size unknown). |
| real | D | B | Low Code No Code Platform | public procurement notice; Low Code | Procurement of a software platform (product), not implementation services; large utility. |
| real | D | REJECT | Robotics Process Automation Tool | Robotics; public procurement notice; Automation | Procurement of an RPA tool (product), not services. |
| real | A | B | Intelligent Automation (RPA) Capability Development and Automation Delivery Part | public procurement notice; Automation; Intelligent Automation | Explicit automation delivery partner procurement (intent A; fit poor if £215k). |
| real | D | REJECT | Healthcare AI Solutions | public procurement notice | AI in general; no automation-services scope. |
| synthetic | C | D | Our team spends hours every week copying data from emails into spreadsheets. It' | nightmare |  |
| synthetic | D | REJECT | AI is going to change everything for small businesses. |  |  |

## UNCLEAR items (not scored)

- pred **A** — Workflow Automation for a fee — Could be a buyer offering a fee OR a freelancer offering work for a fee.
- pred **B** — Automation Contract — 'Automation Contract' could be building/industrial automation.
