# Cleaning log

What the pipeline changes in the data on every run, and why. Raw files are never edited: every change happens in code and is visible in `logs/run_log.txt`.

## Data decisions (applied on every run)

| # | Issue found | Rows | Action | Why |
|---|---|---|---|---|
| 1 | Exact duplicate row | O108 (February file, twice) | removed, 17 → 16 rows | same order exported twice; it would count EUR 258 twice |
| 2 | Two date formats | O103 `09.01.2026`, O112 `17.02.2026` | parsed to YYYY-MM-DD | one format, so dates sort and filter correctly |
| 3 | March prices in cents | O114, O115, O116 (`orders_2026_03.csv`) | divided by 100 in `clean_orders()` | without it revenue is EUR 12,565 instead of 4,015 (Lab 3.1); rule 5 (≤ EUR 2,000) now guards this |
| 4 | Country typo | C007 `Germny` | fixed to `Germany` in `clean_customers()` | known typo, one row; it should not stop the whole run (Lab 3.2) |
| 5 | Invalid / missing email | C003 `clara.schmidt(at)web.de`, C008 empty | kept, `email_flag` = invalid / missing, warning in the log | email is not needed for revenue; flag instead of stop (Lab 3.2) |
| 6 | Quantity ≤ 0 | O105 (−1) | quarantine | revenue cannot be computed; ask the shop (return?) |
| 7 | Unknown customer | O109 (C099) | quarantine | customer is missing in the master data, so no city or segment |
| 8 | Missing price | O111 | quarantine | we do not guess prices |
| 9 | Missing order date | O116 | quarantine | the order cannot be placed in a month |

Result: **12 trusted + 4 quarantined = 16 rows after dedup**, revenue **EUR 4,015**
(Electronics EUR 3,782.59 · Accessories EUR 232.41).

## Pipeline changes (Lab 3.3)

| Change | Why |
|---|---|
| Email rule = warning, not stop | one bad contact field should not block every report |
| Country rule checked after the typo fix | a known typo is repaired; an unknown country still stops the run |
| Price correction moved from `split()` to `clean_orders()` | it is cleaning, and the price rules must see EUR values |
| New rules 4, 5, 6, 10 (see README) | future dates, implausible prices, bad customer IDs and unknown segments now stop the run |
| Output check `validate_output()` | proves that no row was lost or duplicated and that `line_total` is correct before anything is written |
| New output `revenue_by_category.csv` | revenue per product category for the manager |
| `segment`, `order_month` in `fct_orders` | allow revenue by segment and by month without another join |
| Code version in the run log | each output can be traced to the exact code that produced it |

## Break test (Lab 3.2, repeated with the new rules)

With `extras/orders_2026_04.csv` copied into `data/raw/`, the run **stops** and writes nothing:
`order_id` O101 not unique (January and April), `A1001` wrong ID format, category `Gadgets`, `unit_price` −5.00.
The file was removed again afterwards; the run log keeps the FAILED block as evidence.
