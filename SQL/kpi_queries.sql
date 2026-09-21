-- ============================================================================
-- kpi_queries.sql
-- Executive KPI set — the SQL equivalent of outputs/kpi_summary.json.
-- Run against data/analytics.db after schema.sql + audit_flags.sql.
-- ============================================================================

-- Total revenue, spend, and blended ROAS
SELECT
    ROUND(SUM(order_amount - discount_amount), 2) AS total_revenue,
    (SELECT ROUND(SUM(spend_amount), 2) FROM fact_marketing_spend) AS total_marketing_spend,
    ROUND(
        SUM(order_amount - discount_amount)
        / (SELECT SUM(spend_amount) FROM fact_marketing_spend), 2
    ) AS roas
FROM fact_orders;

-- Average order value, total orders, refund rate, chargeback rate
SELECT
    ROUND(AVG(order_amount), 2) AS average_order_value,
    COUNT(*) AS total_orders,
    ROUND(1.0 * SUM(refund_flag) / COUNT(*), 4) AS refund_rate,
    ROUND(SUM(CASE WHEN refund_flag = 1 THEN refund_amount ELSE 0 END), 2) AS total_refund_dollars,
    ROUND(1.0 * SUM(chargeback_flag) / COUNT(*), 4) AS chargeback_rate,
    ROUND(SUM(discount_amount), 2) AS discount_leakage_dollars
FROM fact_orders;

-- Blended customer acquisition cost (spend / new customers signed up in the period)
SELECT
    ROUND(
        (SELECT SUM(spend_amount) FROM fact_marketing_spend)
        / (SELECT COUNT(*) FROM dim_customers WHERE strftime('%Y', signup_date) = '2025'),
        2
    ) AS blended_cac;

-- Repeat purchase rate (customers with 2+ orders / all customers who ordered)
WITH order_counts AS (
    SELECT customer_id, COUNT(*) AS n_orders
    FROM fact_orders
    GROUP BY customer_id
)
SELECT
    ROUND(1.0 * SUM(CASE WHEN n_orders >= 2 THEN 1 ELSE 0 END) / COUNT(*), 4) AS repeat_purchase_rate
FROM order_counts;

-- Budget compliance rate across campaigns
WITH campaign_actuals AS (
    SELECT c.campaign_id, c.approved_budget, COALESCE(SUM(s.spend_amount), 0) AS actual_spend
    FROM dim_campaigns c
    LEFT JOIN fact_marketing_spend s ON s.campaign_id = c.campaign_id
    GROUP BY c.campaign_id, c.approved_budget
)
SELECT
    ROUND(1.0 * SUM(CASE WHEN actual_spend <= approved_budget THEN 1 ELSE 0 END) / COUNT(*), 4) AS budget_compliance_rate,
    SUM(CASE WHEN actual_spend > approved_budget THEN 1 ELSE 0 END) AS campaigns_over_budget
FROM campaign_actuals;

-- Revenue, spend, ROAS, and refund rate by channel (dashboard "channel performance" page)
SELECT
    o.channel,
    ROUND(SUM(o.order_amount - o.discount_amount), 2) AS revenue,
    ROUND(COALESCE(s.spend, 0), 2) AS spend,
    COUNT(*) AS orders,
    ROUND(1.0 * SUM(o.refund_flag) / COUNT(*), 4) AS refund_rate,
    CASE WHEN COALESCE(s.spend, 0) > 0
         THEN ROUND(SUM(o.order_amount - o.discount_amount) / s.spend, 2)
         ELSE NULL END AS roas
FROM fact_orders o
LEFT JOIN (
    SELECT channel, SUM(spend_amount) AS spend
    FROM fact_marketing_spend
    GROUP BY channel
) s ON s.channel = o.channel
GROUP BY o.channel, s.spend
ORDER BY revenue DESC;

-- Total flagged records and dollars, plus an "estimated recoverable savings"
-- read (the subset of flags that represent avoidable spend, not just data-quality noise)
-- Run after sql/audit_flags.sql has created v_all_audit_flags.
SELECT
    COUNT(*) AS total_flagged_records,
    ROUND(SUM(ABS(amount)), 2) AS total_flagged_dollars
FROM v_all_audit_flags;

SELECT
    ROUND(SUM(ABS(amount)), 2) AS estimated_recoverable_savings
FROM v_all_audit_flags
WHERE flag IN ('excessive_discount', 'duplicate_order', 'orphan_campaign_spend',
               'wasted_spend_no_orders', 'budget_overrun');
