# Validation: Python vs. SQL vs. Excel

The audit engine and KPI framework were built three separate times, independently, against the same raw data:

- **Python**: `python/audit_engine.py` (pandas)
- **SQL**: `sql/audit_flags.sql` + `sql/kpi_queries.sql` (SQLite views/queries against `data/analytics.db`)
- **Excel**: `excel/Channel_Spend_Order_Integrity_Analytics.xlsx` (native SUMIFS/COUNTIFS/AVERAGE formulas against the raw data tabs, recalculated with LibreOffice — zero formula errors across 100,160 formulas)

Below is the full reconciliation.

## Executive KPIs

| KPI | Python | SQL | Excel |
|---|---:|---:|---:|
| Total Revenue | $1,526,128.54 | $1,526,128.54 | $1,526,128.54 |
| Total Marketing Spend | $611,918.00 | $611,918.00 | $611,918.00 |
| Blended ROAS | 2.49x | 2.49x | 2.49x |
| Total Orders | 16,208 | 16,208 | 16,208 |
| Average Order Value | $97.93 | $97.93 | $97.93 |
| Refund Rate | 5.11% | 5.11% | 5.11% |
| Total Refund Dollars | $75,349.11 | $75,349.11 | — (see note) |
| Chargeback Rate | 0.59% | 0.59% | 0.59% |
| Discount Leakage | $61,119.90 | $61,119.90 | $61,119.90 |
| Blended CAC | $145.69 | $145.69 | $145.69 |
| Repeat Purchase Rate | 91.01% | 91.01% | 91.01% |
| Budget Compliance Rate | 83.33% | 83.33% | 83.33% |
| Campaigns Over Budget | 14 | 14 | 14 |
| Total Flagged Records | 151 | 151 | 151 |
| Total Flagged Dollars | $43,029.83 | $43,029.84 | $43,029.83 |
| Estimated Recoverable Savings | $22,221.09 | $22,221.09 | $22,221.09 |

**Note on the one-cent difference in Total Flagged Dollars**: Python and Excel round each flagged amount to 2 decimals *before* summing (matching how the amounts are stored in `outputs/audit_flags.csv`); the SQL query sums the raw, unrounded `amount` column and rounds once at the end. That ordering difference in rounding is the entire explanation for the $0.01 gap — not a logic discrepancy. Total Refund Dollars isn't reproduced as a single Excel cell in the current workbook (it's derivable from the Orders tab but wasn't added as its own KPI row); everything else is a live formula.

## Channel performance

| Channel | Revenue | Spend | Orders | Refund Rate | ROAS |
|---|---:|---:|---:|---:|---:|
| Organic/Direct | $606,295.49 | $0.00 | 5,965 | 2.77% | N/A |
| Paid Search | $293,870.73 | $205,018.09 | 3,021 | 5.89% | 1.43x |
| Paid Social | $214,286.10 | $163,579.06 | 2,606 | 8.67% | 1.31x |
| Email | $176,880.48 | $35,841.10 | 1,921 | 3.28% | 4.94x |
| Affiliate | $152,358.50 | $89,093.75 | 1,606 | 6.48% | 1.71x |
| Display | $82,437.24 | $118,386.00 | 1,089 | 8.45% | 0.70x |

Identical across all three implementations.

## Audit flag counts

| Flag | Count | $ Impact (Python/Excel) | $ Impact (SQL) |
|---|---:|---:|---:|
| `outlier_order_amount` | 26 | $17,321.07 | $17,321.08 |
| `duplicate_order` | 25 | $2,139.94 | $2,139.94 |
| `excessive_discount` | 18 | $639.95 | $639.95 |
| `wasted_spend_no_orders` | 18 | $6,415.97 | $6,415.97 |
| `repeated_refund_pattern` | 16 | $1,230.28 | $1,230.28 |
| `orphan_campaign_spend` | 15 | $7,405.27 | $7,405.27 |
| `budget_overrun` | 14 | $5,619.96 | $5,619.96 |
| `orphan_customer_id` | 9 | $1,341.79 | $1,341.79 |
| `post_campaign_attribution` | 8 | $782.85 | $782.85 |
| `repeat_chargeback_customer` | 2 | $132.75 | $132.75 |
| **Total** | **151** | **$43,029.83** | **$43,029.84** |

Every count matches exactly. The one flag type with a penny of dollar-amount drift (`outlier_order_amount`, $17,321.07 vs. $17,321.08) is the same floating-point rounding-order effect described above, not a different set of flagged records — the same 26 order IDs are flagged in both.

## How this was checked

1. Built `data/analytics.db` from the same `data/raw/*.csv` files the Python engine reads (`python/build_database.py`).
2. Ran `sql/audit_flags.sql` to materialize the 10 flag views, then compared `SELECT flag, COUNT(*), SUM(amount) FROM v_all_audit_flags GROUP BY flag` against `outputs/audit_flags.csv`'s `value_counts()`.
3. Ran `sql/kpi_queries.sql` and compared each result to `outputs/kpi_summary.json`.
4. Opened the recalculated Excel workbook with `openpyxl` (`data_only=True`) and read back every formula's cached value, comparing to the same JSON.

No manual number entry was used anywhere in this reconciliation — every value above was read directly from each system's own output.
