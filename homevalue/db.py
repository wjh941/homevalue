"""SQLite 仓储层:引擎、SQL 文件加载与查询执行。

SQL 全部放在 sql/ 目录并用 -- name: xxx 注解标记,
分析接口与 README 文档共用同一份查询。
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

QUERY_NAME_RE = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)


def get_engine(db_path: Path | str) -> sa.Engine:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sa.create_engine(f"sqlite+pysqlite:///{path.as_posix()}")


def load_queries(sql_path: Path | str) -> dict[str, str]:
    """解析含 -- name: query_name 标记的 SQL 文件 -> {name: sql}。"""
    text = Path(sql_path).read_text(encoding="utf-8")
    matches = list(QUERY_NAME_RE.finditer(text))
    if not matches:
        raise ValueError(f"{sql_path} 中未找到任何 -- name: 标记")
    queries: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        queries[m.group(1)] = text[m.end() : end].strip().rstrip(";")
    return queries


def execute_script(engine: sa.Engine, sql_path: Path | str) -> None:
    """执行无参数 DDL/ETL 脚本。

    先去掉整行注释再按分号切分,避免注释文本里的分号干扰切分;
    行内尾注(-- xxx)交由 SQLite 解析。
    """
    text = Path(sql_path).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    stmts = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.exec_driver_sql(stmt)


def read_query(engine: sa.Engine, sql: str, params: dict | None = None) -> pd.DataFrame:
    return pd.read_sql_query(sa.text(sql), engine, params=params or {})
