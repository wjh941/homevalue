"""SQL 分析查询:全部可在微型数仓上执行且结构正确。"""

from __future__ import annotations

import pytest

from homevalue.config import SQL_DIR
from homevalue.db import get_engine, load_queries, read_query


@pytest.fixture(scope="module")
def queries():
    return load_queries(SQL_DIR / "03_analysis.sql")


def test_all_queries_loaded(queries):
    expected = {
        "districts_rank", "city_price_trend", "top_bizcircle_per_district",
        "price_deciles", "layout_crosstab", "price_change_summary",
        "biggest_price_drops", "city_compare", "pareto_value",
        "districts_rank_all", "city_price_trend_all", "district_price_trend",
    }
    assert expected == set(queries)


def test_window_queries_execute(tiny_db, queries):
    engine = get_engine(tiny_db)
    for name, sql in queries.items():
        df = read_query(engine, sql)  # 不抛异常即通过
        assert len(df) >= 0, name


def test_districts_rank_has_rank_column(tiny_db, queries):
    engine = get_engine(tiny_db)
    df = read_query(engine, queries["districts_rank"])
    assert len(df) > 0
    assert {"district", "avg_unit_price", "price_rank"} <= set(df.columns)
    assert df["price_rank"].is_monotonic_increasing


def test_deciles_have_ten_buckets(tiny_db, queries):
    engine = get_engine(tiny_db)
    df = read_query(engine, queries["price_deciles"])
    assert len(df) == 10
