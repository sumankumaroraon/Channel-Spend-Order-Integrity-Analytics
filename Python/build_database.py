"""
build_database.py
Loads the raw CSVs in ../data/raw/ into a SQLite database (../data/analytics.db)
following sql/schema.sql. This is what lets the SQL audit/KPI queries in
sql/audit_flags.sql and sql/kpi_queries.sql actually run — useful for
reviewers who want to open analytics.db directly (DB Browser for SQLite,
DBeaver, etc.) rather than trust numbers out of a Python script alone.
"""

import os
import sqlite3
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR = os.path.join(ROOT, "data", "raw")
DB_PATH = os.path.join(ROOT, "data", "analytics.db")
SCHEMA_PATH = os.path.join(ROOT, "sql", "schema.sql")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
with open(SCHEMA_PATH) as f:
    conn.executescript(f.read())

customers = pd.read_csv(os.path.join(RAW_DIR, "customers.csv"))
campaigns = pd.read_csv(os.path.join(RAW_DIR, "campaigns.csv"))
spend = pd.read_csv(os.path.join(RAW_DIR, "marketing_spend.csv")).rename(columns={"date": "spend_date"})
orders = pd.read_csv(os.path.join(RAW_DIR, "orders.csv"))

customers.to_sql("dim_customers", conn, if_exists="append", index=False)
campaigns.to_sql("dim_campaigns", conn, if_exists="append", index=False)
spend.to_sql("fact_marketing_spend", conn, if_exists="append", index=False)
orders.to_sql("fact_orders", conn, if_exists="append", index=False)

conn.commit()

counts = {}
for t in ["dim_customers", "dim_campaigns", "fact_marketing_spend", "fact_orders", "policy_rules"]:
    counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

conn.close()

print("Database built:", os.path.abspath(DB_PATH))
for t, c in counts.items():
    print(f"  {t:<24} {c:>7,} rows")
