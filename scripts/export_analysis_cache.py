"""运行全部 SQL 分析查询,把结果导出为 reports/analysis_cache.json。

用途:数据库不上传 git/服务器时,API 仍可提供分析接口(读缓存)。

用法:
    python scripts/export_analysis_cache.py
"""

from __future__ import annotations

import json
import sys
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


def main() -> int:
    engine = get_engine(DB_PATH)
    queries = load_queries(SQL_DIR / "03_analysis.sql")
    cache = {name: to_records(read_query(engine, sql)) for name, sql in queries.items()}
    ANALYSIS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"导出 {len(cache)} 个查询结果 -> {ANALYSIS_CACHE}")
    for name, rows in cache.items():
        print(f"  {name}: {len(rows)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
