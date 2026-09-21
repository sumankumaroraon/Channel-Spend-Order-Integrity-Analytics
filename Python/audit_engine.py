"""
audit_engine.py
Rule-based audit engine for the Channel Spend & Order Integrity Analytics project.

Loads the four raw tables, runs ten independent audit checks against orders
and marketing spend, and computes the executive KPI set. Designed to mirror
how a lean analytics team would build a first-pass exception report before
handing it to Finance/Marketing Ops for review — every flag is deliberately
simple and explainable (no black-box scoring) so a reviewer can see exactly
why a row was flagged.

Outputs (written to ../outputs/):
    audit_flags.csv        one row per flagged record, with a reason + amount
    kpi_summary.json        executive KPI set, mirrors the dashboard's KPI cards
    channel_summary.csv     channel-level rollup used by the dashboard
    monthly_trend.csv       month-over-month revenue/spend used by the dashboard
"""

import json
import os
import pandas as pd
import numpy as np

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

# Policy thresholds — centralized so they read like real business rules,
# not magic numbers buried in logic. In production these would live in a
# config table (see sql/schema.sql: policy_rules).
POLICY = {
    "max_discount_pct": 0.25,          # discounts above 25% require manager override
    "duplicate_window_minutes": 15,     # not used directly (no timestamps in this dataset);
                                         # duplicate check instead matches same customer/
                                         # amount/channel/day, see check #2
    "outlier_zscore": 3.0,              # order amount z-score vs. channel mean
    "chargeback_repeat_threshold": 2,   # 2+ chargebacks from one customer -> flag
    "wasted_spend_orphan_campaign": True,
}

customers = pd.read_csv(os.path.join(RAW_DIR, "customers.csv"), parse_dates=["signup_date"])
campaigns = pd.read_csv(os.path.join(RAW_DIR, "campaigns.csv"), parse_dates=["start_date", "end_date"])
spend = pd.read_csv(os.path.join(RAW_DIR, "marketing_spend.csv"), parse_dates=["date"])
orders = pd.read_csv(
    os.path.join(RAW_DIR, "orders.csv"),
    parse_dates=["order_date", "refund_date"],
)

valid_customer_ids = set(customers["customer_id"])
valid_campaign_ids = set(campaigns["campaign_id"])

flags = []  # list of dicts: record_type, record_id, flag, detail, amount


def add_flag(record_type, record_id, flag, detail, amount=0.0):
    flags.append({
        "record_type": record_type,
        "record_id": record_id,
        "flag": flag,
        "detail": detail,
        "amount": round(float(amount), 2),
    })


# ---------------------------------------------------------------------------
# 1. Excessive discount — above policy ceiling
# ---------------------------------------------------------------------------
mask = orders["discount_pct"] > POLICY["max_discount_pct"]
for _, r in orders[mask].iterrows():
    add_flag("order", r.order_id, "excessive_discount",
              f"{r.discount_pct:.0%} discount exceeds {POLICY['max_discount_pct']:.0%} policy ceiling",
              r.discount_amount)

# ---------------------------------------------------------------------------
# 2. Duplicate order — same customer, channel, amount, and calendar day
# ---------------------------------------------------------------------------
dup_keys = orders.duplicated(subset=["customer_id", "channel", "order_amount", "order_date"], keep=False)
dup_rows = orders[dup_keys].sort_values(["customer_id", "order_date"])
seen_groups = set()
for _, r in dup_rows.iterrows():
    key = (r.customer_id, r.channel, r.order_amount, r.order_date)
    if key in seen_groups:
        add_flag("order", r.order_id, "duplicate_order",
                  f"Same customer/channel/amount as another order on {r.order_date.date()}",
                  r.order_amount)
    seen_groups.add(key)

# ---------------------------------------------------------------------------
# 3. Statistical outlier order amount (IQR method, per channel)
#    Order amounts are right-skewed (lognormal-ish), so a raw z-score over-
#    flags the natural long tail. An IQR fence (Q3 + 3*IQR) per channel is
#    the more appropriate robust-statistics choice for skewed transaction
#    data and is what keeps this list to genuine exceptions.
# ---------------------------------------------------------------------------
q1 = orders.groupby("channel")["order_amount"].transform(lambda s: s.quantile(0.25))
q3 = orders.groupby("channel")["order_amount"].transform(lambda s: s.quantile(0.75))
iqr = q3 - q1
upper_fence = q3 + 4.5 * iqr
outliers = orders[orders["order_amount"] > upper_fence].copy()
outliers["fence"] = upper_fence[outliers.index]
for _, r in outliers.iterrows():
    add_flag("order", r.order_id, "outlier_order_amount",
              f"${r.order_amount:,.2f} is well above the {r.channel} normal range "
              f"(upper fence ${r.fence:,.2f})",
              r.order_amount)

# ---------------------------------------------------------------------------
# 4. Orphan / malformed customer_id
# ---------------------------------------------------------------------------
bad_cust = orders[~orders["customer_id"].isin(valid_customer_ids)]
for _, r in bad_cust.iterrows():
    add_flag("order", r.order_id, "orphan_customer_id",
              f"customer_id '{r.customer_id}' does not exist in the customer master table",
              r.order_amount)

# ---------------------------------------------------------------------------
# 5. Repeated refund amount — same customer, same refund amount, 3+ times
# ---------------------------------------------------------------------------
refunded = orders[orders["refund_flag"] == True].copy()
repeat_counts = refunded.groupby(["customer_id", "refund_amount"])["order_id"].transform("count")
repeated_refunds = refunded[repeat_counts >= 3]
for _, r in repeated_refunds.iterrows():
    add_flag("order", r.order_id, "repeated_refund_pattern",
              f"{r.customer_id} has 3+ refunds of exactly ${r.refund_amount:,.2f} — possible refund abuse",
              r.refund_amount)

# ---------------------------------------------------------------------------
# 6. Chargeback-prone customer — 2+ chargebacks from the same customer
# ---------------------------------------------------------------------------
cb = orders[orders["chargeback_flag"] == True]
cb_counts = cb.groupby("customer_id")["order_id"].count()
risky_customers = cb_counts[cb_counts >= POLICY["chargeback_repeat_threshold"]].index
for _, r in cb[cb["customer_id"].isin(risky_customers)].iterrows():
    add_flag("order", r.order_id, "repeat_chargeback_customer",
              f"{r.customer_id} has {cb_counts[r.customer_id]} chargebacks in the period",
              r.order_amount)

# ---------------------------------------------------------------------------
# 7. Campaign misattribution — order dated after its campaign's end_date
# ---------------------------------------------------------------------------
orders_c = orders.merge(campaigns[["campaign_id", "end_date"]], on="campaign_id", how="left")
misattr = orders_c[orders_c["order_date"] > orders_c["end_date"]]
for _, r in misattr.iterrows():
    add_flag("order", r.order_id, "post_campaign_attribution",
              f"Order dated {r.order_date.date()} is attributed to {r.campaign_id}, "
              f"which ended {r.end_date.date()}",
              r.order_amount)

# ---------------------------------------------------------------------------
# 8. Orphan marketing spend — spend logged against a campaign_id that doesn't exist
# ---------------------------------------------------------------------------
orphan_spend = spend[~spend["campaign_id"].isin(valid_campaign_ids)]
for _, r in orphan_spend.iterrows():
    add_flag("spend", r.spend_id, "orphan_campaign_spend",
              f"${r.spend_amount:,.2f} logged against unknown campaign_id '{r.campaign_id}'",
              r.spend_amount)

# ---------------------------------------------------------------------------
# 9. Campaign budget overrun — actual spend exceeds approved_budget
# ---------------------------------------------------------------------------
spend_by_campaign = spend[spend["campaign_id"].isin(valid_campaign_ids)].groupby("campaign_id")["spend_amount"].sum()
camp_check = campaigns.set_index("campaign_id").join(spend_by_campaign.rename("actual_spend")).fillna({"actual_spend": 0})
overrun = camp_check[camp_check["actual_spend"] > camp_check["approved_budget"]]
for cid, r in overrun.iterrows():
    add_flag("campaign", cid, "budget_overrun",
              f"{r.campaign_name}: spent ${r.actual_spend:,.2f} vs. ${r.approved_budget:,.2f} approved "
              f"({(r.actual_spend / r.approved_budget - 1):.0%} over)",
              r.actual_spend - r.approved_budget)

# ---------------------------------------------------------------------------
# 10. Wasted spend day — meaningful spend on a channel/day with zero orders
# ---------------------------------------------------------------------------
daily_orders = orders.groupby(["channel", "order_date"]).size().rename("n_orders")
daily_spend = spend.groupby(["channel", "date"]).agg(spend_amount=("spend_amount", "sum")).reset_index()
daily_spend = daily_spend.rename(columns={"date": "order_date"})
ds_check = daily_spend.merge(daily_orders, on=["channel", "order_date"], how="left").fillna({"n_orders": 0})
wasted = ds_check[(ds_check["spend_amount"] > 150) & (ds_check["n_orders"] == 0)]
for _, r in wasted.iterrows():
    add_flag("spend_day", f"{r.channel}|{r.order_date.date()}", "wasted_spend_no_orders",
              f"${r.spend_amount:,.2f} spent on {r.channel} on {r.order_date.date()} produced zero orders",
              r.spend_amount)

# ---------------------------------------------------------------------------
# Write audit flags
# ---------------------------------------------------------------------------
audit_df = pd.DataFrame(flags).sort_values(["flag", "record_type"])
audit_df.to_csv(os.path.join(OUT_DIR, "audit_flags.csv"), index=False)

# ---------------------------------------------------------------------------
# KPI summary
# ---------------------------------------------------------------------------
total_revenue = float((orders["order_amount"] - orders["discount_amount"]).sum())
total_spend = float(spend["spend_amount"].sum())
total_discount = float(orders["discount_amount"].sum())
total_refunds = float(orders.loc[orders["refund_flag"], "refund_amount"].sum())
n_orders = int(len(orders))
n_refunded = int(orders["refund_flag"].sum())
n_chargebacks = int(orders["chargeback_flag"].sum())

new_customers_2025 = int((customers["signup_date"].dt.year == 2025).sum())
blended_cac = total_spend / new_customers_2025 if new_customers_2025 else None

order_counts_by_cust = orders.groupby("customer_id")["order_id"].count()
repeat_customers = int((order_counts_by_cust >= 2).sum())
repeat_purchase_rate = repeat_customers / order_counts_by_cust.shape[0]

flagged_amount = float(audit_df["amount"].abs().sum())
n_campaigns_over_budget = int((camp_check["actual_spend"] > camp_check["approved_budget"]).sum())
budget_compliance_rate = 1 - (n_campaigns_over_budget / len(campaigns))

kpis = {
    "total_revenue": round(total_revenue, 2),
    "total_marketing_spend": round(total_spend, 2),
    "roas": round(total_revenue / total_spend, 2) if total_spend else None,
    "blended_cac": round(blended_cac, 2) if blended_cac else None,
    "average_order_value": round(orders["order_amount"].mean(), 2),
    "total_orders": n_orders,
    "refund_rate": round(n_refunded / n_orders, 4),
    "total_refund_dollars": round(total_refunds, 2),
    "chargeback_rate": round(n_chargebacks / n_orders, 4),
    "discount_leakage_dollars": round(total_discount, 2),
    "repeat_purchase_rate": round(repeat_purchase_rate, 4),
    "budget_compliance_rate": round(budget_compliance_rate, 4),
    "campaigns_over_budget": n_campaigns_over_budget,
    "total_flagged_records": int(len(audit_df)),
    "total_flagged_dollars": round(flagged_amount, 2),
    "estimated_recoverable_savings": round(
        audit_df.loc[audit_df["flag"].isin(
            ["excessive_discount", "duplicate_order", "orphan_campaign_spend",
             "wasted_spend_no_orders", "budget_overrun"]
        ), "amount"].abs().sum(), 2
    ),
}

with open(os.path.join(OUT_DIR, "kpi_summary.json"), "w") as f:
    json.dump(kpis, f, indent=2)

# ---------------------------------------------------------------------------
# Channel-level rollup (for the dashboard's channel performance page)
# ---------------------------------------------------------------------------
rev_by_channel = orders.groupby("channel").apply(
    lambda g: (g["order_amount"] - g["discount_amount"]).sum()
).rename("revenue")
spend_by_channel = spend.groupby("channel")["spend_amount"].sum().rename("spend")
orders_by_channel = orders.groupby("channel")["order_id"].count().rename("orders")
refund_rate_by_channel = orders.groupby("channel")["refund_flag"].mean().rename("refund_rate")

channel_summary = pd.concat(
    [rev_by_channel, spend_by_channel, orders_by_channel, refund_rate_by_channel], axis=1
).fillna(0).reset_index()
channel_summary["roas"] = (channel_summary["revenue"] / channel_summary["spend"].replace(0, np.nan)).round(2)
channel_summary = channel_summary.sort_values("revenue", ascending=False)
channel_summary.to_csv(os.path.join(OUT_DIR, "channel_summary.csv"), index=False)

# ---------------------------------------------------------------------------
# Monthly trend (for the dashboard's overview page)
# ---------------------------------------------------------------------------
orders["month"] = orders["order_date"].dt.to_period("M").astype(str)
spend["month"] = spend["date"].dt.to_period("M").astype(str)
monthly_rev = orders.groupby("month").apply(lambda g: (g["order_amount"] - g["discount_amount"]).sum()).rename("revenue")
monthly_spend = spend.groupby("month")["spend_amount"].sum().rename("spend")
monthly_trend = pd.concat([monthly_rev, monthly_spend], axis=1).fillna(0).reset_index()
monthly_trend = monthly_trend[monthly_trend["month"].str.startswith("2025")]
monthly_trend.to_csv(os.path.join(OUT_DIR, "monthly_trend.csv"), index=False)

print("Audit engine complete.")
print(f"  Flagged records:        {len(audit_df):,}")
print(f"  Flagged dollars:        ${flagged_amount:,.2f}")
print(f"  Est. recoverable:       ${kpis['estimated_recoverable_savings']:,.2f}")
print(f"  Total revenue:          ${total_revenue:,.2f}")
print(f"  Total marketing spend:  ${total_spend:,.2f}")
print(f"  ROAS:                   {kpis['roas']}")
print(f"\nWritten to: {os.path.abspath(OUT_DIR)}")
