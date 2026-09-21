-- ============================================================================
-- schema.sql
-- Channel Spend & Order Integrity Analytics — data warehouse schema
--
-- Star-schema layout: two dimension tables, two fact tables, plus a small
-- policy_rules config table so audit thresholds are data, not hardcoded
-- logic. Written for SQLite (used to build the portfolio demo database) but
-- kept to portable, standard SQL — it will run on Postgres/SQL Server/
-- Snowflake with trivial type-name changes (e.g. TEXT -> VARCHAR).
-- ============================================================================

DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS fact_marketing_spend;
DROP TABLE IF EXISTS dim_customers;
DROP TABLE IF EXISTS dim_campaigns;
DROP TABLE IF EXISTS policy_rules;

-- ----------------------------------------------------------------------------
-- Dimensions
-- ----------------------------------------------------------------------------

CREATE TABLE dim_customers (
    customer_id         TEXT PRIMARY KEY,
    signup_date          DATE NOT NULL,
    region                TEXT NOT NULL,
    acquisition_channel  TEXT NOT NULL,
    segment               TEXT NOT NULL   -- New / Returning / VIP
);

CREATE TABLE dim_campaigns (
    campaign_id     TEXT PRIMARY KEY,
    campaign_name    TEXT NOT NULL,
    channel           TEXT NOT NULL,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    approved_budget  DECIMAL(12,2) NOT NULL
);

-- ----------------------------------------------------------------------------
-- Facts
-- ----------------------------------------------------------------------------

CREATE TABLE fact_marketing_spend (
    spend_id       TEXT PRIMARY KEY,
    spend_date      DATE NOT NULL,
    channel          TEXT NOT NULL,
    campaign_id     TEXT,                  -- intentionally NOT a hard FK: a few rows are
                                            -- orphaned on purpose to exercise the audit engine
    spend_amount    DECIMAL(12,2) NOT NULL
);

CREATE TABLE fact_orders (
    order_id           TEXT PRIMARY KEY,
    order_date          DATE NOT NULL,
    customer_id         TEXT,               -- not a hard FK, same reason as above
    channel              TEXT NOT NULL,
    campaign_id         TEXT REFERENCES dim_campaigns(campaign_id),
    order_amount        DECIMAL(12,2) NOT NULL,
    discount_pct        DECIMAL(5,4) NOT NULL DEFAULT 0,
    discount_amount     DECIMAL(12,2) NOT NULL DEFAULT 0,
    payment_method       TEXT,
    refund_flag          BOOLEAN NOT NULL DEFAULT 0,
    refund_amount        DECIMAL(12,2) NOT NULL DEFAULT 0,
    refund_date          DATE,
    chargeback_flag       BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX idx_orders_customer   ON fact_orders(customer_id);
CREATE INDEX idx_orders_campaign   ON fact_orders(campaign_id);
CREATE INDEX idx_orders_date       ON fact_orders(order_date);
CREATE INDEX idx_spend_campaign    ON fact_marketing_spend(campaign_id);
CREATE INDEX idx_spend_date        ON fact_marketing_spend(spend_date);

-- ----------------------------------------------------------------------------
-- Policy configuration — audit thresholds live here, not buried in SQL/Python
-- ----------------------------------------------------------------------------

CREATE TABLE policy_rules (
    rule_key      TEXT PRIMARY KEY,
    rule_value    DECIMAL(12,4) NOT NULL,
    description    TEXT
);

INSERT INTO policy_rules (rule_key, rule_value, description) VALUES
    ('max_discount_pct',        0.25,  'Discounts above this rate require a manager override'),
    ('outlier_iqr_multiplier',  4.5,   'Order amount fence = Q3 + multiplier * IQR, per channel'),
    ('chargeback_repeat_min',   2,     'Chargeback count from one customer that triggers a risk flag'),
    ('repeated_refund_min',     3,     'Identical-amount refunds from one customer that trigger a flag'),
    ('wasted_spend_min_dollars', 150,  'Minimum same-day channel spend with zero orders to flag as wasted');
