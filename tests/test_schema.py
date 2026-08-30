import pandas as pd
import pytest

from pricelab.schema import (
    KEY_COLUMNS,
    SchemaError,
    coerce_tidy,
    empty_tidy,
    validate_tidy,
)


def _row(**over):
    base = dict(
        date="2020-01-01",
        freq="M",
        region="Pakistan",
        region_level="national",
        commodity="General",
        variable="cpi_index",
        value=100.0,
        unit="index",
        source="unit_test",
        is_imputed=False,
    )
    base.update(over)
    return base


def test_empty_tidy_is_valid():
    df = empty_tidy()
    assert list(df.columns) == list(empty_tidy().columns)
    validate_tidy(df)  # no raise


def test_coerce_and_validate_ok():
    df = coerce_tidy(pd.DataFrame([_row(), _row(commodity="Food")]))
    validate_tidy(df)


def test_missing_column_raises():
    df = pd.DataFrame([_row()]).drop(columns=["unit"])
    with pytest.raises(SchemaError):
        validate_tidy(df)


def test_null_value_raises():
    df = coerce_tidy(pd.DataFrame([_row(value=None)]))
    with pytest.raises(SchemaError):
        validate_tidy(df)


def test_bad_freq_raises():
    df = coerce_tidy(pd.DataFrame([_row(freq="yearly")]))
    with pytest.raises(SchemaError):
        validate_tidy(df)


def test_duplicate_key_raises():
    df = coerce_tidy(pd.DataFrame([_row(), _row(value=101.0)]))
    with pytest.raises(SchemaError):
        validate_tidy(df)
    assert KEY_COLUMNS  # sanity
