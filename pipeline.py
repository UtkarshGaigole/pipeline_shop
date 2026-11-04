"""Shop pipeline - Chapter 3: Reproducible & Validated Data Pipelines.

Run from this folder with:   python pipeline.py

Flow: load -> clean -> validate -> split -> enrich -> output
  data/raw/      read only, never written
  data/output/   fct_orders.csv, quarantine_orders.csv, revenue_by_city.csv,
                 revenue_by_category.csv
  logs/          run_log.txt (one block per run)
"""
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

import rules

BASE = Path(__file__).parent
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "output"
LOG = BASE / "logs" / "run_log.txt"

log_lines = []


def log(msg):
    print(msg)
    log_lines.append(msg)


def code_version():
    """Git commit of the code that ran (+ '-dirty' if there were uncommitted changes)."""
    try:
        git = ["git", "-C", str(BASE)]
        commit = subprocess.run(git + ["rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(git + ["status", "--porcelain", "--", "*.py", "requirements.txt"],
                               capture_output=True, text=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown (not a git checkout)"


def write_log(status):
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"=== run {datetime.now():%Y-%m-%d %H:%M:%S} - {status} ===\n")
        f.write("\n".join(log_lines) + "\n\n")


CENTS_FILES = ["orders_2026_03.csv"]            # exports known to store prices in cents

# ---------- reusable cleaning functions ----------
def parse_mixed_date(col):
    """Dates arrive as YYYY-MM-DD or DD.MM.YYYY - accept both."""
    iso = pd.to_datetime(col, format="%Y-%m-%d", errors="coerce")
    de = pd.to_datetime(col, format="%d.%m.%Y", errors="coerce")
    return iso.fillna(de)


# ---------- steps: one function = one job ----------
def load_raw():
    """Read every orders_*.csv as text and record its source file (lineage)."""
    frames = []
    for f in sorted(RAW.glob("orders_*.csv")):
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        df["source_file"] = f.name
        frames.append(df)
    orders = pd.concat(frames, ignore_index=True)
    customers = pd.read_csv(RAW / "customers.csv", dtype=str, keep_default_na=False)
    log(f"Loaded {len(orders)} order rows from {len(frames)} files, {len(customers)} customers")
    return orders, customers


def clean_orders(orders):
    """Remove exact duplicates, trim text, convert types on purpose."""
    before = len(orders)
    df = orders.drop_duplicates().copy()
    log(f"Removed {before - len(df)} exact duplicate(s): {before} -> {len(df)} rows")
    for c in ["order_id", "customer_id", "category"]:
        df[c] = df[c].str.strip()
    df["order_date"] = parse_mixed_date(df["order_date"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype(float)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").astype(float)
    # price correction: the March export stores prices in cents (see Lab 3.1).
    # Done here, BEFORE validation, so the price rules check the corrected values.
    cents = df["source_file"].isin(CENTS_FILES)
    df.loc[cents, "unit_price"] /= 100
    log(f"Price correction: {int(cents.sum())} row(s) from {', '.join(CENTS_FILES)} divided by 100 (cents -> EUR)")
    return df


COUNTRY_FIXES = {"Germny": "Germany"}          # known typos in the customer master
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"


def clean_customers(customers):
    """Trim text, fix known country typos, flag (not drop) bad emails."""
    df = customers.copy()
    for c in df.columns:
        df[c] = df[c].str.strip()
    typo = df["country"].isin(COUNTRY_FIXES)
    if typo.any():
        log(f"Fixed country typo for {', '.join(df.loc[typo, 'customer_id'])}: "
            f"{', '.join(sorted(set(df.loc[typo, 'country'])))} -> Germany")
    df["country"] = df["country"].replace(COUNTRY_FIXES)
    df["email_flag"] = "ok"
    df.loc[df["email"] == "", "email_flag"] = "missing"
    df.loc[(df["email"] != "") & ~df["email"].str.match(EMAIL_PATTERN), "email_flag"] = "invalid"
    flagged = df[df["email_flag"] != "ok"]
    if len(flagged):
        log("Email flagged (kept): " + ", ".join(f"{r.customer_id} {r.email_flag}" for r in flagged.itertuples()))
    return df


def validate(orders, customers):
    """Critical rules: if any fails, STOP and write nothing."""
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rules.clean_orders_rules.validate(orders, lazy=True)
            rules.clean_customers_rules.validate(customers, lazy=True)
        for w in caught:                      # warning-level rules: log, do not stop
            if issubclass(w.category, pa.errors.SchemaWarning):
                log("Rule warning (no stop): " + " ".join(str(w.message).split())[:160])
    except pa.errors.SchemaErrors as err:
        log("VALIDATION FAILED - pipeline stopped, no outputs written:")
        cases = err.failure_cases[["column", "check", "failure_case", "index"]]
        log(cases.to_string(index=False))
        write_log("FAILED")
        sys.exit(1)
    log("Validation passed: all critical rules OK")


def split(orders, customers):
    """Row-level problems go to quarantine with a reason; the rest is trusted."""
    df = orders.copy()
    reason = pd.Series("", index=df.index)
    reason[df["order_date"].isna()] = "missing order_date"
    reason[df["unit_price"].isna()] = "missing unit_price"
    reason[~df["customer_id"].isin(customers["customer_id"])] = "unknown customer"
    reason[df["quantity"] <= 0] = "quantity <= 0"
    df["reason"] = reason

    quarantine = df[df["reason"] != ""]
    trusted = df[df["reason"] == ""].drop(columns="reason")
    log(f"Split: {len(trusted)} trusted, {len(quarantine)} quarantined")
    return trusted, quarantine


def enrich_orders(trusted, customers):
    """Add the customer's city and segment, the order month and line_total."""
    df = trusted.merge(customers[["customer_id", "city", "segment"]], on="customer_id", how="left")
    df["order_month"] = df["order_date"].dt.strftime("%Y-%m")
    df["line_total"] = (df["quantity"] * df["unit_price"]).round(2)
    return df


def validate_output(fct, trusted, quarantine, rows_after_dedup):
    """Last gate before writing: reconcile row counts and check fct_orders."""
    problems = []
    if len(trusted) + len(quarantine) != rows_after_dedup:
        problems.append(f"row count mismatch: {len(trusted)} trusted + {len(quarantine)} "
                        f"quarantined != {rows_after_dedup} rows after dedup")
    if len(fct) != len(trusted):
        problems.append(f"enrich changed the row count: {len(trusted)} -> {len(fct)} (join duplicates?)")
    try:
        rules.fct_orders_rules.validate(fct, lazy=True)
    except pa.errors.SchemaErrors as err:
        problems.append(err.failure_cases[["column", "check", "failure_case", "index"]].to_string(index=False))
    if problems:
        log("OUTPUT CHECK FAILED - pipeline stopped, no outputs written:")
        for p in problems:
            log(p)
        write_log("FAILED")
        sys.exit(1)
    log(f"Output check passed: {len(trusted)} + {len(quarantine)} = {rows_after_dedup} rows, fct_orders rules OK")


def revenue_by_category(fct):
    """Business summary per product category: orders, items, revenue and share of revenue."""
    out = (fct.groupby("category", as_index=False)
              .agg(orders=("order_id", "nunique"), quantity=("quantity", "sum"),
                   line_total=("line_total", "sum")))
    out["line_total"] = out["line_total"].round(2)
    out["quantity"] = out["quantity"].astype(int)
    out["share_pct"] = (100 * out["line_total"] / out["line_total"].sum()).round(1)
    return out.sort_values("line_total", ascending=False).reset_index(drop=True)


def output(fct, quarantine):
    OUT.mkdir(parents=True, exist_ok=True)
    fct.to_csv(OUT / "fct_orders.csv", index=False)
    quarantine.to_csv(OUT / "quarantine_orders.csv", index=False)
    revenue = (fct.groupby("city", as_index=False)["line_total"].sum().round(2)
                  .sort_values("line_total", ascending=False))
    revenue.to_csv(OUT / "revenue_by_city.csv", index=False)
    by_cat = revenue_by_category(fct)
    by_cat.to_csv(OUT / "revenue_by_category.csv", index=False)
    log(f"Revenue: EUR {fct['line_total'].sum():,.0f}")
    log("By category: " + ", ".join(f"{r.category} EUR {r.line_total:,.2f} ({r.share_pct}%)"
                                    for r in by_cat.itertuples()))
    log("Wrote fct_orders.csv, quarantine_orders.csv, revenue_by_city.csv, revenue_by_category.csv")


def main():
    log(f"Code version: {code_version()}")
    raw_orders, raw_customers = load_raw()
    orders = clean_orders(raw_orders)
    customers = clean_customers(raw_customers)
    validate(orders, customers)
    trusted, quarantine = split(orders, customers)
    fct = enrich_orders(trusted, customers)
    validate_output(fct, trusted, quarantine, len(orders))
    output(fct, quarantine)
    write_log("SUCCESS")


if __name__ == "__main__":
    main()
