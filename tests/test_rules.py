"""Each test feeds one bad value to one rule and checks that the rule fires.
Run from the project folder with:   python -m pytest -q
"""
import sys
import warnings
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rules  # noqa: E402


def good_order(**changes):
    row = {"order_id": "O101", "order_date": pd.Timestamp("2026-01-04"), "customer_id": "C001",
           "category": "Electronics", "quantity": 1.0, "unit_price": 499.0}
    row.update(changes)
    return pd.DataFrame([row])


def good_customer(**changes):
    row = {"customer_id": "C001", "customer_name": "Anna Weber", "city": "Berlin",
           "country": "Germany", "email": "anna.weber@mail.de", "segment": "Private"}
    row.update(changes)
    return pd.DataFrame([row])


def good_fct(**changes):
    row = {"order_id": "O101", "quantity": 2.0, "unit_price": 19.99, "city": "Berlin",
           "segment": "Private", "order_month": "2026-01", "line_total": 39.98}
    row.update(changes)
    return pd.DataFrame([row])


def test_good_rows_pass():
    rules.clean_orders_rules.validate(good_order())
    rules.clean_customers_rules.validate(good_customer())
    rules.fct_orders_rules.validate(good_fct())


def test_future_order_date_stops():          # custom check
    future = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    with pytest.raises(pa.errors.SchemaError, match="future"):
        rules.clean_orders_rules.validate(good_order(order_date=future))


def test_missing_order_date_is_not_a_stop():  # goes to quarantine instead
    rules.clean_orders_rules.validate(good_order(order_date=pd.NaT))


def test_price_in_cents_stops():
    with pytest.raises(pa.errors.SchemaError, match="2,000"):
        rules.clean_orders_rules.validate(good_order(unit_price=4638.0))


def test_bad_customer_id_format_stops():
    with pytest.raises(pa.errors.SchemaError):
        rules.clean_orders_rules.validate(good_order(customer_id="X99"))


def test_unknown_segment_stops():
    with pytest.raises(pa.errors.SchemaError):
        rules.clean_customers_rules.validate(good_customer(segment="VIP"))


def test_country_typo_stops_if_not_cleaned():
    with pytest.raises(pa.errors.SchemaError):
        rules.clean_customers_rules.validate(good_customer(country="Germny"))


def test_bad_email_only_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rules.clean_customers_rules.validate(good_customer(email="clara.schmidt(at)web.de"))
    assert any(issubclass(w.category, pa.errors.SchemaWarning) for w in caught)


def test_empty_email_is_allowed():
    rules.clean_customers_rules.validate(good_customer(email=""))


def test_wrong_line_total_stops():          # custom table-level check
    with pytest.raises(pa.errors.SchemaError, match="line_total"):
        rules.fct_orders_rules.validate(good_fct(line_total=99.0))
