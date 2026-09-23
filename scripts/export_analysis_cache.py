"""运行全部 SQL 分析查询,把结果导出为 reports/analysis_cache.json。

用途:数据库不上传 git/服务器时,API 仍可提供分析接口(读缓存)。

用法:
    python scripts/export_analysis_cache.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.config import ANALYSIS_CACHE, DB_PATH, SQL_DIR  # noqa: E402
from homevalue.db import get_engine, load_queries, read_query  # noqa: E402


def to_records(df: pd.DataFrame) -> list[dict]:
    def clean(v):
        if pd.isna(v):
            return None
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            return float(v)
        return v

    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")]


SIMILAR_SAMPLE_SQL = (
    "SELECT district, community, bizcircle, area_sqm, unit_price, rooms, halls,"
    " build_year, floor_pos, renovation, total_floors FROM listings WHERE city = 'bj'"
)


def export_similar_sample(engine) -> list[dict]:
    """每区抽 5 套单价最接近区内中位价的在售房源(listings 已是去重后的当前房源池)。"""
    cand = read_query(engine, SIMILAR_SAMPLE_SQL)
    picks = []
    for _district, g in cand.groupby("district"):
        med = g["unit_price"].median()
        g2 = g.assign(_d=(g["unit_price"] - med).abs()).sort_values("_d").head(5).drop(columns="_d")
        picks.append(g2)
    return to_records(pd.concat(picks, ignore_index=True)) if picks else []


def main() -> int:
    engine = get_engine(DB_PATH)
    queries = load_queries(SQL_DIR / "03_analysis.sql")
    cache = {name: to_records(read_query(engine, sql)) for name, sql in queries.items()}
    cache["similar_sample"] = export_similar_sample(engine)
    dates = read_query(
        engine, "SELECT MIN(snapshot_date) AS first, MAX(snapshot_date) AS last,"
        " COUNT(DISTINCT snapshot_date) AS n FROM listings_all WHERE city = 'bj'"
    ).to_dict("records")[0]
    cache["_meta"] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "first_snapshot": dates["first"],
        "last_snapshot": dates["last"],
        "n_snapshots": int(dates["n"]),
    }
    ANALYSIS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"导出 {len(cache)} 个查询结果 -> {ANALYSIS_CACHE}")
    for name, rows in cache.items():
        print(f"  {name}: {len(rows)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
