-- ============================================================================
-- audit_flags.sql
-- Ten audit checks against fact_orders / fact_marketing_spend, expressed as
-- SQL views so they can be scheduled, queried ad hoc, or unioned into a
-- single exceptions report. Thresholds are pulled from policy_rules rather
-- than hardcoded, so a compliance/finance owner can retune them without a
-- code change. This mirrors python/audit_engine.py check-for-check; the two
-- are kept in sync deliberately as a cross-check of each other.
-- Run against data/analytics.db (built by python/build_database.py).
-- ============================================================================

-- 1. Excessive discount — above policy ceiling
DROP VIEW IF EXISTS v_flag_excessive_discount;
CREATE VIEW v_flag_excessive_discount AS
SELECT
    o.order_id,
    'excessive_discount' AS flag,
    o.discount_amount AS amount,
    o.channel,
    o.order_date
FROM fact_orders o, policy_rules p
WHERE p.rule_key = 'max_discount_pct'
  AND o.discount_pct > p.rule_value;

-- 2. Duplicate order — same customer/channel/amount/day appears more than once
DROP VIEW IF EXISTS v_flag_duplicate_order;
CREATE VIEW v_flag_duplicate_order AS
WITH grouped AS (
    SELECT order_id, customer_id, channel, order_amount, order_date,
           ROW_NUMBER() OVER (
               PARTITION BY customer_id, channel, order_amount, order_date
               ORDER BY order_id
           ) AS rn,
           COUNT(*) OVER (
               PARTITION BY customer_id, channel, order_amount, order_date
           ) AS grp_size
    FROM fact_orders
)
SELECT order_id, 'duplicate_order' AS flag, order_amount AS amount, channel, order_date
FROM grouped
WHERE grp_size > 1 AND rn > 1;

-- 3. Statistical outlier order amount — IQR fence per channel
DROP VIEW IF EXISTS v_flag_outlier_order_amount;
CREATE VIEW v_flag_outlier_order_amount AS
WITH stats AS (
    -- SQLite has no native PERCENTILE_CONT; this approximates Q1/Q3 via NTILE(4)
    -- (fine for an exception scan — see python/audit_engine.py for the exact
    -- pandas .quantile() version used in the numbers reported in the README)
    SELECT channel, order_amount,
           NTILE(4) OVER (PARTITION BY channel ORDER BY order_amount) AS q
    FROM fact_orders
),
q_bounds AS (
    SELECT channel,
           MAX(CASE WHEN q = 1 THEN order_amount END) AS q1_ceiling,
           MIN(CASE WHEN q = 3 THEN order_amount END) AS q3_floor,
           MAX(CASE WHEN q = 3 THEN order_amount END) AS q3_ceiling
    FROM stats
    GROUP BY channel
),
fences AS (
    SELECT channel,
           q3_ceiling + (SELECT rule_value FROM policy_rules WHERE rule_key = 'outlier_iqr_multiplier')
                        * (q3_ceiling - q1_ceiling) AS upper_fence
    FROM q_bounds
)
SELECT o.order_id, 'outlier_order_amount' AS flag, o.order_amount AS amount, o.channel, o.order_date
FROM fact_orders o
JOIN fences f ON f.channel = o.channel
WHERE o.order_amount > f.upper_fence;

-- 4. Orphan / malformed customer_id
DROP VIEW IF EXISTS v_flag_orphan_customer_id;
CREATE VIEW v_flag_orphan_customer_id AS
SELECT o.order_id, 'orphan_customer_id' AS flag, o.order_amount AS amount, o.channel, o.order_date
FROM fact_orders o
LEFT JOIN dim_customers c ON c.customer_id = o.customer_id
WHERE c.customer_id IS NULL;

-- 5. Repeated refund amount — 3+ identical-amount refunds from one customer
DROP VIEW IF EXISTS v_flag_repeated_refund_pattern;
CREATE VIEW v_flag_repeated_refund_pattern AS
WITH refund_counts AS (
    SELECT customer_id, refund_amount, COUNT(*) AS n
    FROM fact_orders
    WHERE refund_flag = 1
    GROUP BY customer_id, refund_amount
    HAVING COUNT(*) >= (SELECT rule_value FROM policy_rules WHERE rule_key = 'repeated_refund_min')
)
SELECT o.order_id, 'repeated_refund_pattern' AS flag, o.refund_amount AS amount, o.channel, o.order_date
FROM fact_orders o
JOIN refund_counts rc ON rc.customer_id = o.customer_id AND rc.refund_amount = o.refund_amount
WHERE o.refund_flag = 1;

-- 6. Chargeback-prone customer — 2+ chargebacks from the same customer
DROP VIEW IF EXISTS v_flag_repeat_chargeback_customer;
CREATE VIEW v_flag_repeat_chargeback_customer AS
WITH cb_counts AS (
    SELECT customer_id, COUNT(*) AS n
    FROM fact_orders
    WHERE chargeback_flag = 1
    GROUP BY customer_id
    HAVING COUNT(*) >= (SELECT rule_value FROM policy_rules WHERE rule_key = 'chargeback_repeat_min')
)
SELECT o.order_id, 'repeat_chargeback_customer' AS flag, o.order_amount AS amount, o.channel, o.order_date
FROM fact_orders o
JOIN cb_counts cb ON cb.customer_id = o.customer_id
WHERE o.chargeback_flag = 1;

-- 7. Campaign misattribution — order dated after its campaign's end_date
DROP VIEW IF EXISTS v_flag_post_campaign_attribution;
CREATE VIEW v_flag_post_campaign_attribution AS
SELECT o.order_id, 'post_campaign_attribution' AS flag, o.order_amount AS amount, o.channel, o.order_date
FROM fact_orders o
JOIN dim_campaigns c ON c.campaign_id = o.campaign_id
WHERE o.order_date > c.end_date;

-- 8. Orphan marketing spend — logged against a campaign_id that doesn't exist
DROP VIEW IF EXISTS v_flag_orphan_campaign_spend;
CREATE VIEW v_flag_orphan_campaign_spend AS
SELECT s.spend_id AS order_id, 'orphan_campaign_spend' AS flag, s.spend_amount AS amount, s.channel, s.spend_date AS order_date
FROM fact_marketing_spend s
LEFT JOIN dim_campaigns c ON c.campaign_id = s.campaign_id
WHERE c.campaign_id IS NULL;

-- 9. Campaign budget overrun — actual spend exceeds approved_budget
DROP VIEW IF EXISTS v_flag_budget_overrun;
CREATE VIEW v_flag_budget_overrun AS
SELECT
    c.campaign_id AS order_id,
    'budget_overrun' AS flag,
    SUM(s.spend_amount) - c.approved_budget AS amount,
    c.channel,
    c.end_date AS order_date
FROM dim_campaigns c
JOIN fact_marketing_spend s ON s.campaign_id = c.campaign_id
GROUP BY c.campaign_id, c.channel, c.approved_budget, c.end_date
HAVING SUM(s.spend_amount) > c.approved_budget;

-- 10. Wasted spend day — meaningful same-day channel spend with zero orders
DROP VIEW IF EXISTS v_flag_wasted_spend_no_orders;
CREATE VIEW v_flag_wasted_spend_no_orders AS
WITH daily_spend AS (
    SELECT channel, spend_date, SUM(spend_amount) AS spend_amount
    FROM fact_marketing_spend
    GROUP BY channel, spend_date
),
daily_orders AS (
    SELECT channel, order_date, COUNT(*) AS n_orders
    FROM fact_orders
    GROUP BY channel, order_date
)
SELECT
    ds.channel || '|' || ds.spend_date AS order_id,
    'wasted_spend_no_orders' AS flag,
    ds.spend_amount AS amount,
    ds.channel,
    ds.spend_date AS order_date
FROM daily_spend ds
LEFT JOIN daily_orders do_ ON do_.channel = ds.channel AND do_.order_date = ds.spend_date
WHERE ds.spend_amount > (SELECT rule_value FROM policy_rules WHERE rule_key = 'wasted_spend_min_dollars')
  AND COALESCE(do_.n_orders, 0) = 0;

-- ----------------------------------------------------------------------------
-- One unioned exceptions report — this is the SQL equivalent of outputs/audit_flags.csv
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_all_audit_flags;
CREATE VIEW v_all_audit_flags AS
SELECT * FROM v_flag_excessive_discount
UNION ALL SELECT * FROM v_flag_duplicate_order
UNION ALL SELECT * FROM v_flag_outlier_order_amount
UNION ALL SELECT * FROM v_flag_orphan_customer_id
UNION ALL SELECT * FROM v_flag_repeated_refund_pattern
UNION ALL SELECT * FROM v_flag_repeat_chargeback_customer
UNION ALL SELECT * FROM v_flag_post_campaign_attribution
UNION ALL SELECT * FROM v_flag_orphan_campaign_spend
UNION ALL SELECT * FROM v_flag_budget_overrun
UNION ALL SELECT * FROM v_flag_wasted_spend_no_orders;

-- Example: exception counts and dollars by flag type
-- SELECT flag, COUNT(*) AS n, ROUND(SUM(amount), 2) AS total_amount
-- FROM v_all_audit_flags
-- GROUP BY flag
-- ORDER BY n DESC;
