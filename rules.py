"""Validation rules for the shop pipeline - one line per rule.

Each rule is a Chapter 2 data-quality check, written once and run on every run.
If a rule here fails, the pipeline STOPS and writes nothing (see pipeline.validate).
Row-level problems (bad quantity, unknown customer, ...) are handled in
pipeline.split() and go to the quarantine file instead.
"""
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Column, Check


# ---------- custom checks (plain functions: one Series in, True/False per row out) ----------
def not_in_future(dates: pd.Series) -> pd.Series:
    """Timeliness / accuracy: an order cannot be placed after today.
    Missing dates pass here - they are a row-level problem and go to quarantine."""
    return dates.isna() | (dates <= pd.Timestamp.today().normalize())


clean_orders_rules = pa.DataFrameSchema({
    "order_id":    Column(str, unique=True, nullable=False,
                          checks=Check.str_matches(r"^[A-Z]\d{3}$")),
    # NEW (custom check): order_date may not be in the future
    "order_date":  Column(nullable=True,
                          checks=Check(not_in_future, error="order_date in the future")),
    "customer_id": Column(str, nullable=False),
    "category":    Column(str, Check.isin(["Accessories", "Electronics"])),
    "quantity":    Column(float, nullable=True),
    # NEW: plausibility - no product in this shop costs more than EUR 2,000.
    # Also guards the cents correction: without it, March prices (e.g. 4638) fail here.
    "unit_price":  Column(float, [Check.ge(0),
                                  Check.le(2000, error="unit_price above EUR 2,000 (cents?)")],
                          nullable=True),
})

clean_customers_rules = pa.DataFrameSchema({
    "customer_id":   Column(str, unique=True, nullable=False,
                            checks=Check.str_matches(r"^C\d{3}$")),
    "customer_name": Column(str, nullable=False),
    "city":          Column(str, nullable=False),
    # Lab 3.2 - email: name@domain.tld or empty. WARNING level: a bad email is
    # flagged (email_flag), it does not stop the run - email is not needed for revenue.
    # Empty cells arrive as "" (read as text), not as null, so "" is allowed explicitly.
    "email":         Column(str, nullable=True,
                            checks=Check.str_matches(r"^$|^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$",
                                                     raise_warning=True,
                                                     error="email format name@domain.tld")),
    # Lab 3.2 - country: DACH only. STOP level, checked AFTER the known typo
    # 'Germny' is fixed in clean_customers(): a new unknown country is a real problem.
    "country":       Column(str,
                            checks=Check.isin(["Germany", "Austria", "Switzerland"])),
})
