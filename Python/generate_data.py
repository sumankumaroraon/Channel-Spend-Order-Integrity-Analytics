"""
generate_data.py
Synthetic data generator for the Channel Spend & Order Integrity Analytics project.

Simulates one fiscal year (2025) of operations for a fictional mid-size
e-commerce retailer, "Northfield Retail Co." All entities, IDs, and amounts
are fabricated for portfolio/demo purposes only.

Outputs (written to ../data/raw/):
    customers.csv
    campaigns.csv
    marketing_spend.csv
    orders.csv

Re-running this script is deterministic (fixed random seed) so the audit
engine and dashboard numbers stay reproducible.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
import os

RNG = np.random.default_rng(42)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(OUT_DIR, exist_ok=True)

YEAR_START = date(2025, 1, 1)
YEAR_END = date(2025, 12, 31)
ALL_DAYS = pd.date_range(YEAR_START, YEAR_END, freq="D")

CHANNELS = ["Paid Search", "Paid Social", "Email", "Affiliate", "Display", "Organic/Direct"]
REGIONS = ["Northeast", "Midwest", "South", "West"]
SEGMENTS = ["New", "Returning", "VIP"]
PAYMENT_METHODS = ["Credit Card", "Debit Card", "PayPal", "Buy Now Pay Later"]

# Channel-level behavior assumptions (kept internally consistent so KPIs make sense).
# daily_orders_mean is calibrated, together with daily_spend_mean, to land the
# simulated business at a realistic blended ROAS (~2.5-3x) rather than an
# arbitrary number — see README for the calibration note.
CHANNEL_PROFILE = {
    "Paid Search":    {"daily_spend_mean": 520, "daily_orders_mean": 8.5,  "aov_mean": 92, "refund_rate": 0.06, "chargeback_rate": 0.006},
    "Paid Social":    {"daily_spend_mean": 410, "daily_orders_mean": 7.0,  "aov_mean": 78, "refund_rate": 0.08, "chargeback_rate": 0.010},
    "Email":          {"daily_spend_mean": 85,  "daily_orders_mean": 5.5,  "aov_mean": 85, "refund_rate": 0.04, "chargeback_rate": 0.003},
    "Affiliate":      {"daily_spend_mean": 230, "daily_orders_mean": 4.5,  "aov_mean": 88, "refund_rate": 0.07, "chargeback_rate": 0.007},
    "Display":        {"daily_spend_mean": 300, "daily_orders_mean": 3.0,  "aov_mean": 70, "refund_rate": 0.09, "chargeback_rate": 0.012},
    "Organic/Direct": {"daily_spend_mean": 0,   "daily_orders_mean": 16.0, "aov_mean": 95, "refund_rate": 0.03, "chargeback_rate": 0.002},
}

# ---------------------------------------------------------------------------
# 1. Customers
# ---------------------------------------------------------------------------
N_CUSTOMERS = 4200
signup_dates = RNG.choice(ALL_DAYS, size=N_CUSTOMERS)
customers = pd.DataFrame({
    "customer_id": [f"CUST-{i:05d}" for i in range(1, N_CUSTOMERS + 1)],
    "signup_date": pd.to_datetime(signup_dates).date,
    "region": RNG.choice(REGIONS, size=N_CUSTOMERS, p=[0.27, 0.24, 0.29, 0.20]),
    "acquisition_channel": RNG.choice(
        CHANNELS, size=N_CUSTOMERS, p=[0.24, 0.20, 0.12, 0.14, 0.10, 0.20]
    ),
    "segment": RNG.choice(SEGMENTS, size=N_CUSTOMERS, p=[0.55, 0.35, 0.10]),
})
# a handful of malformed customer_ids to simulate real-world data quality issues
bad_idx = RNG.choice(customers.index, size=6, replace=False)
customer_ids_master = customers["customer_id"].tolist()
customers.to_csv(os.path.join(OUT_DIR, "customers.csv"), index=False)

# ---------------------------------------------------------------------------
# 2. Campaigns (roughly 2 active campaigns per paid channel per month)
# ---------------------------------------------------------------------------
campaign_rows = []
cid = 1
for month in range(1, 13):
    m_start = date(2025, month, 1)
    m_end = (date(2025, month + 1, 1) - timedelta(days=1)) if month < 12 else YEAR_END
    for ch in CHANNELS:
        if ch == "Organic/Direct":
            continue
        n_campaigns = 2 if ch in ("Paid Search", "Paid Social") else 1
        for n in range(n_campaigns):
            base = CHANNEL_PROFILE[ch]["daily_spend_mean"] * 30
            # Budgets get a modest planning buffer above expected spend, same as a real
            # media plan would — so an overrun is a genuine exception, not the norm.
            approved_budget = round(base * RNG.uniform(1.08, 1.30) / n_campaigns, -1)
            campaign_rows.append({
                "campaign_id": f"CMP-{cid:04d}",
                "campaign_name": f"{ch} - {m_start.strftime('%b %Y')} #{n+1}",
                "channel": ch,
                "start_date": m_start,
                "end_date": m_end,
                "approved_budget": approved_budget,
            })
            cid += 1
campaigns = pd.DataFrame(campaign_rows)
campaigns.to_csv(os.path.join(OUT_DIR, "campaigns.csv"), index=False)

# ---------------------------------------------------------------------------
# 3. Marketing spend (daily, per channel, allocated across that month's campaigns)
# ---------------------------------------------------------------------------
spend_rows = []
sid = 1
for d in ALL_DAYS:
    dd = d.date()
    month_campaigns = campaigns[(campaigns.start_date <= dd) & (campaigns.end_date >= dd)]
    dow_factor = 1.15 if d.dayofweek < 5 else 0.85  # weekday spend slightly higher
    for ch in CHANNELS:
        if ch == "Organic/Direct":
            continue
        prof = CHANNEL_PROFILE[ch]
        daily_amt = max(0, RNG.normal(prof["daily_spend_mean"], prof["daily_spend_mean"] * 0.22) * dow_factor)
        ch_campaigns = month_campaigns[month_campaigns.channel == ch]
        if ch_campaigns.empty:
            continue
        # split the day's spend across that channel's live campaigns
        weights = RNG.dirichlet(np.ones(len(ch_campaigns)))
        for (_, camp), w in zip(ch_campaigns.iterrows(), weights):
            amt = round(daily_amt * w, 2)
            if amt <= 0:
                continue
            spend_rows.append({
                "spend_id": f"SPEND-{sid:06d}",
                "date": dd,
                "channel": ch,
                "campaign_id": camp.campaign_id,
                "spend_amount": amt,
            })
            sid += 1

# Inject ~15 "wasted spend" days: real dollars logged with an inactive/mis-tagged campaign_id
for _ in range(15):
    d = pd.Timestamp(RNG.choice(ALL_DAYS)).date()
    ch = RNG.choice([c for c in CHANNELS if c != "Organic/Direct"])
    spend_rows.append({
        "spend_id": f"SPEND-{sid:06d}",
        "date": d,
        "channel": ch,
        "campaign_id": "CMP-9999",  # does not exist in campaigns.csv -> orphan spend
        "spend_amount": round(RNG.uniform(150, 900), 2),
    })
    sid += 1

marketing_spend = pd.DataFrame(spend_rows)
marketing_spend.to_csv(os.path.join(OUT_DIR, "marketing_spend.csv"), index=False)

# ---------------------------------------------------------------------------
# 4. Orders
# ---------------------------------------------------------------------------
order_rows = []
oid = 1
customer_pool = customers.set_index("customer_id")

for d in ALL_DAYS:
    dd = d.date()
    month_campaigns = campaigns[(campaigns.start_date <= dd) & (campaigns.end_date >= dd)]
    for ch in CHANNELS:
        prof = CHANNEL_PROFILE[ch]
        n_orders = RNG.poisson(prof["daily_orders_mean"])
        ch_campaigns = month_campaigns[month_campaigns.channel == ch]
        for _ in range(n_orders):
            cust_id = RNG.choice(customer_ids_master)
            amt = float(max(12, RNG.lognormal(mean=np.log(prof["aov_mean"]), sigma=0.45)))
            amt = round(amt, 2)

            discount_pct = 0.0
            if RNG.random() < 0.35:
                discount_pct = round(float(RNG.choice([0.05, 0.10, 0.15, 0.20, 0.25], p=[0.35, 0.3, 0.2, 0.1, 0.05])), 2)
            discount_amount = round(amt * discount_pct, 2)

            refund_flag = RNG.random() < prof["refund_rate"]
            refund_amount = round(amt - discount_amount, 2) if refund_flag else 0.0
            refund_date = dd + timedelta(days=int(RNG.integers(2, 21))) if refund_flag else None

            chargeback_flag = RNG.random() < prof["chargeback_rate"]

            campaign_id = None
            if ch != "Organic/Direct" and not ch_campaigns.empty:
                campaign_id = RNG.choice(ch_campaigns.campaign_id.values)

            order_rows.append({
                "order_id": f"ORD-{oid:06d}",
                "order_date": dd,
                "customer_id": cust_id,
                "channel": ch,
                "campaign_id": campaign_id,
                "order_amount": amt,
                "discount_pct": discount_pct,
                "discount_amount": discount_amount,
                "payment_method": RNG.choice(PAYMENT_METHODS, p=[0.55, 0.20, 0.17, 0.08]),
                "refund_flag": bool(refund_flag),
                "refund_amount": refund_amount,
                "refund_date": refund_date,
                "chargeback_flag": bool(chargeback_flag),
            })
            oid += 1

orders = pd.DataFrame(order_rows)

# --- Inject deliberate, labeled data-quality issues for the audit engine to catch ---

# a) Duplicate charges: clone ~25 orders with the same customer/amount/channel, seconds apart
dup_sample = orders.sample(25, random_state=7).copy()
dup_sample["order_id"] = [f"ORD-DUP{i:04d}" for i in range(len(dup_sample))]
orders = pd.concat([orders, dup_sample], ignore_index=True)

# b) Excessive discounts beyond the 25% policy ceiling (~18 rows)
over_disc_idx = orders.sample(18, random_state=11).index
orders.loc[over_disc_idx, "discount_pct"] = RNG.choice([0.30, 0.35, 0.40, 0.50], size=18)
orders.loc[over_disc_idx, "discount_amount"] = round(
    orders.loc[over_disc_idx, "order_amount"] * orders.loc[over_disc_idx, "discount_pct"], 2
)

# c) Orphan / malformed customer_id (~9 rows) - simulates a broken signup/checkout sync
orphan_idx = orders.sample(9, random_state=13).index
orders.loc[orphan_idx, "customer_id"] = [f"CUST-UNKNOWN-{i}" for i in range(9)]

# d) Statistical outlier order amounts (~12 rows), well beyond channel norms
outlier_idx = orders.sample(12, random_state=17).index
orders.loc[outlier_idx, "order_amount"] = orders.loc[outlier_idx, "order_amount"] * RNG.uniform(6, 11, size=12)

# e) Repeated-refund-amount pattern for a small set of customers (possible refund abuse)
abuse_customers = RNG.choice(customer_ids_master, size=4, replace=False)
for cust in abuse_customers:
    repeat_amt = round(float(RNG.uniform(40, 120)), 2)
    for k in range(4):
        d = pd.Timestamp(RNG.choice(ALL_DAYS)).date()
        order_rows_extra = {
            "order_id": f"ORD-ABUSE{cust[-4:]}{k}",
            "order_date": d,
            "customer_id": cust,
            "channel": "Paid Social",
            "campaign_id": None,
            "order_amount": repeat_amt,
            "discount_pct": 0.0,
            "discount_amount": 0.0,
            "payment_method": "Credit Card",
            "refund_flag": True,
            "refund_amount": repeat_amt,
            "refund_date": d + timedelta(days=5),
            "chargeback_flag": False,
        }
        orders = pd.concat([orders, pd.DataFrame([order_rows_extra])], ignore_index=True)

# f) Orders attributed to a campaign after that campaign's end_date (misattribution)
misattr_idx = orders.sample(10, random_state=19).index
camp_lookup = campaigns.set_index("campaign_id")
for i in misattr_idx:
    ch = orders.at[i, "channel"]
    ch_camps = campaigns[campaigns.channel == ch]
    if ch_camps.empty:
        continue
    camp = ch_camps.sample(1, random_state=int(i) % 1000).iloc[0]
    orders.at[i, "campaign_id"] = camp.campaign_id
    orders.at[i, "order_date"] = camp.end_date + timedelta(days=int(RNG.integers(3, 15)))

orders = orders.sort_values("order_date").reset_index(drop=True)
orders.to_csv(os.path.join(OUT_DIR, "orders.csv"), index=False)

print(f"customers:        {len(customers):>6,} rows")
print(f"campaigns:         {len(campaigns):>6,} rows")
print(f"marketing_spend:  {len(marketing_spend):>6,} rows")
print(f"orders:           {len(orders):>6,} rows")
print(f"\nWritten to: {os.path.abspath(OUT_DIR)}")
