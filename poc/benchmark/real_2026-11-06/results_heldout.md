# Real-record evaluation — heldout split

Records: 55 (gold: {'N': 25, 'P': 11, 'R': 18, 'U': 1}). Source: live run 42174857442, labelled manually before the relevance filter was written.

| Metric | Old classifier (as run) | New classifier |
|---|---|---|
| Precision@10 (strict, gold R) | 0/10 (0%) | 9/10 (90%) |
| Precision@20 (strict, gold R) | 5/20 (25%) | 14/20 (70%) |
| Precision of surfaced leads (Priority A/B), top 10 | — | 9/10 (90%) |
| Precision of surfaced leads (Priority A/B), top 20 | — | 14/15 (93%) |
| Precision@10 (lenient, R or P) | — | 10/10 (100%) |
| Precision@20 (lenient, R or P) | — | 19/20 (95%) |
| Priority A+B records | 37 (13 gold R) | 15 (14 gold R) |
| False-positive rate (non-R in A/B ÷ all non-R) | 24/37 (65%) | 1/37 (3%) |
| Relevant records missed by relevance/queue errors | — | 2 of 18 |
| Relevant but correctly excluded (closed / awarded) | — | 2 |

Note: full-ranking Precision@k is capped by the number of gold R records in the split (k > #R means < 100% even if perfect).

## Top 20 (new ranking)

| # | id | gold | queue | relevance | title |
|---|---|---|---|---|---|
| 1 | r067 | R | PRIORITY_B | relevant | Norway – Software package and information systems – New customer syste |
| 2 | r062 | R | PRIORITY_B | relevant | Netherlands – Software programming and consultancy services – Data lan |
| 3 | r066 | R | PRIORITY_B | relevant | Austria – Networking developers' software package – IT-Lösung als Date |
| 4 | r022 | R | PRIORITY_B | relevant | Switzerland – Software-related services – Dienstleistung für Microsoft |
| 5 | r024 | R | PRIORITY_B | relevant | Netherlands – IT services: consulting, software development, Internet  |
| 6 | r049 | R | PRIORITY_B | relevant | Malta – IT services: consulting, software development, Internet and su |
| 7 | r051 | P | PRIORITY_B | relevant | Ireland – IT services: consulting, software development, Internet and  |
| 8 | r030 | R | PRIORITY_B | relevant | Romania – Programming services of application software – Servicii solu |
| 9 | r043 | R | PRIORITY_B | relevant | Netherlands – Software programming and consultancy services – CRM-Oplo |
| 10 | r057 | R | PRIORITY_B | relevant | Spain – Miscellaneous software development services and computer syste |
| 11 | r060 | R | PRIORITY_B | relevant | France – Software programming and consultancy services – Mise en place |
| 12 | r061 | R | PRIORITY_B | relevant | Sweden – IT services: consulting, software development, Internet and s |
| 13 | r034 | R | PRIORITY_B | relevant | Germany – IT services: consulting, software development, Internet and  |
| 14 | r068 | R | PRIORITY_B | relevant | Provision of a Multi-Authority Employability, Case Management and Empl |
| 15 | r042 | R | PRIORITY_B | relevant | Germany – Systems and technical consultancy services – Digitalisierung |
| 16 | r048 | P | REVIEW | uncertain | Luxembourg, Belgium, Germany, Malta, Portugal – Library software devel |
| 17 | r082 | P | REVIEW | uncertain | Italy – Software maintenance and repair services – Gara Europea a Proc |
| 18 | r028 | P | WATCHLIST | product_only | Romania – Software supply services – Reînnoire subscripții software Sa |
| 19 | r077 | U | WATCHLIST | product_only | Netherlands – Software package and information systems – Low-code Oplo |
| 20 | r078 | P | WATCHLIST | product_only | Germany – Industrial control software package – Lizensierung einer no  |

## False positives in Priority A/B

- ('r051', 'P', 'Ireland – IT services: consulting, software development, Internet and support – ', 'relevant')

## Missed relevant records (relevance or queue error)

- ('r027', 'Slovakia – Software support services – Zabezpečenie softvérovej podpory licencií', 'product_only', 'WATCHLIST', 'software product / licence purchase with no service scope (vendor or reseller partnership ')
- ('r087', 'Single Point of Access Market Engagement', 'not_relevant', 'EXCLUDED', "procurement unrelated to Solvant's services (unknown)")

## Relevant but correctly excluded (closed / awarded)

- ('r085', 'NAO Case Management Solution for Financial Audits', 'award / modification notice: the contract is already placed')
- ('r052', 'Germany – Software programming and consultancy services – Rahmenvertra', 'award / modification notice: the contract is already placed')

## Relevance verdict vs gold

`{"N->not_relevant": 25, "P->product_only": 7, "P->relevant": 2, "P->uncertain": 2, "R->not_relevant": 1, "R->product_only": 1, "R->relevant": 16, "U->product_only": 1}`
