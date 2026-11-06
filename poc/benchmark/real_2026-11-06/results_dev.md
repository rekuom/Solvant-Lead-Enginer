# Real-record evaluation — dev split

Records: 45 (gold: {'N': 23, 'U': 2, 'P': 6, 'R': 14}). Source: live run 42174857442, labelled manually before the relevance filter was written.

| Metric | Old classifier (as run) | New classifier |
|---|---|---|
| Precision@10 (strict, gold R) | 0/10 (0%) | 10/10 (100%) |
| Precision@20 (strict, gold R) | 2/20 (10%) | 14/20 (70%) |
| Precision of surfaced leads (Priority A/B), top 10 | — | 10/10 (100%) |
| Precision of surfaced leads (Priority A/B), top 20 | — | 11/11 (100%) |
| Precision@10 (lenient, R or P) | — | 10/10 (100%) |
| Precision@20 (lenient, R or P) | — | 18/20 (90%) |
| Priority A+B records | 28 (8 gold R) | 11 (11 gold R) |
| False-positive rate (non-R in A/B ÷ all non-R) | 20/31 (65%) | 0/31 (0%) |
| Relevant records missed by relevance/queue errors | — | 0 of 14 |
| Relevant but correctly excluded (closed / awarded) | — | 3 |

Note: full-ranking Precision@k is capped by the number of gold R records in the split (k > #R means < 100% even if perfect).

## Top 20 (new ranking)

| # | id | gold | queue | relevance | title |
|---|---|---|---|---|---|
| 1 | r045 | R | PRIORITY_B | relevant | Germany – Programming services of application software – Virtuelle Tou |
| 2 | r065 | R | PRIORITY_B | relevant | Low Code No Code Platform |
| 3 | r050 | R | PRIORITY_B | relevant | Sweden – Software supply services – Serviceärendehanteringssystem |
| 4 | r054 | R | PRIORITY_B | relevant | Germany – Public relations consultancy services – Chat-Bot |
| 5 | r055 | R | PRIORITY_B | relevant | Germany – Miscellaneous software development services and computer sys |
| 6 | r046 | R | PRIORITY_B | relevant | Portugal – Helpdesk and support services – Aquisição de serviços espec |
| 7 | r076 | R | PRIORITY_B | relevant | Germany – Software package and information systems – Agent-Assist-Syst |
| 8 | r081 | R | PRIORITY_B | relevant | Austria – IT services: consulting, software development, Internet and  |
| 9 | r058 | R | PRIORITY_B | relevant | Belgium – Environmental services – Supporting moth monitoring under th |
| 10 | r031 | R | PRIORITY_B | relevant | Romania – Software-related services – Servicii de dezvoltare a soluții |
| 11 | r033 | R | PRIORITY_B | relevant | Netherlands – Software programming and consultancy services – CRM-appl |
| 12 | r083 | U | REVIEW | uncertain | Netherlands – IT services: consulting, software development, Internet  |
| 13 | r070 | P | WATCHLIST | product_only | Finland – Software package and information systems – Procurement of Da |
| 14 | r072 | P | WATCHLIST | product_only | Austria – Software package and information systems – CRM-Softwarelösun |
| 15 | r096 | R | EXCLUDED | relevant | Germany – World wide web (www) site operation host services – Webhosti |
| 16 | r089 | R | EXCLUDED | relevant | Healthcare AI Solutions |
| 17 | r088 | R | EXCLUDED | relevant | Poland – Software implementation services – Dostawa, wdrożenie, konfig |
| 18 | r095 | P | EXCLUDED | product_only | Italy – Maintenance of information technology software – SERVIZIO di U |
| 19 | r098 | P | EXCLUDED | not_relevant | Corporate Software & Related Products and Services - ITT |
| 20 | r091 | N | EXCLUDED | not_relevant | Healthy Lives Dynamic Purchasing Vehicle - Category 1 Round 14 - Onboa |

## False positives in Priority A/B


## Missed relevant records (relevance or queue error)

- none

## Relevant but correctly excluded (closed / awarded)

- ('r096', 'Germany – World wide web (www) site operation host services – Webhosti', 'closed (deadline 2026-10-16T00:00:00+00:00 has passed)')
- ('r089', 'Healthcare AI Solutions', 'closed (deadline 2026-06-23T12:00:00+01:00 has passed)')
- ('r088', 'Poland – Software implementation services – Dostawa, wdrożenie, konfig', 'closed (deadline 2026-10-21T00:00:00+00:00 has passed)')

## Relevance verdict vs gold

`{"N->not_relevant": 23, "P->not_relevant": 3, "P->product_only": 3, "R->relevant": 14, "U->not_relevant": 1, "U->uncertain": 1}`
