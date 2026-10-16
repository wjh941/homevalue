"""预测日志存储:SQLite 单表替代 JSONL 全量重读。

此前 /api/predictions/stats 每次请求全量读 JSONL 再在 Python 里聚合,
日志越大端点越慢;改为 SQLite 后统计走 SQL 聚合,追加走单条 INSERT。
兼容:启动时若同目录存在旧 JSONL,自动导入一次并改名 .imported(自部署
用户的历史数据不丢;Render 免费档文件系统本身随实例重建,属平台限制)。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    ts TEXT,
    district TEXT,
    bizcircle TEXT,
    community TEXT,
    area_sqm REAL,
    rooms INTEGER,
    p50 REAL,
    interval_width_pct REAL,
    model_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_predictions_district ON predictions(district);
"""


class PredictionStore:
    """预测日志的 SQLite 存储:append 单条写入,stats 全 SQL 聚合。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, entry: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO predictions (ts, district, bizcircle, community, area_sqm,"
            " rooms, p50, interval_width_pct, model_version)"
            " VALUES (:ts, :district, :bizcircle, :community, :area_sqm, :rooms,"
            " :p50, :interval_width_pct, :model_version)",
            entry,
        )
        self._conn.commit()

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*), AVG(p50), AVG(interval_width_pct) FROM predictions"
        ).fetchone()
        n_total, avg_p50, avg_width = row
        if not n_total:
            return {"n_total": 0}
        median_p50 = self._conn.execute(
            "SELECT p50 FROM predictions WHERE p50 IS NOT NULL"
            " ORDER BY p50 LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM predictions WHERE p50 IS NOT NULL)"
        ).fetchone()
        top = self._conn.execute(
            "SELECT district, COUNT(*) AS n FROM predictions WHERE district IS NOT NULL"
            " GROUP BY district ORDER BY n DESC LIMIT 5"
        ).fetchall()
        last_ts = self._conn.execute(
            "SELECT ts FROM predictions WHERE ts IS NOT NULL ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return {
            "n_total": n_total,
            "avg_p50": round(avg_p50) if avg_p50 is not None else None,
            "median_p50": round(median_p50[0]) if median_p50 else None,
            "avg_interval_width_pct": round(avg_width, 1) if avg_width is not None else None,
            "top_districts": [{"district": d, "n": n} for d, n in top],
            "last_ts": last_ts[0] if last_ts else None,
        }

    def drift_summary(self) -> dict[str, Any]:
        """漂移监控聚合:按天预测量与 p50 均值 + 当前区分布,全部走 SQL。

        predictions_by_day 按天升序(district_mix 按预测量降序);
        空库返回 n=0 的空结构,由 /api/drift/summary 拼装完整漂移报告。
        """
        n_total = self._conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        by_day = self._conn.execute(
            "SELECT SUBSTR(ts, 1, 10) AS day, COUNT(*) AS n, AVG(p50) AS avg_p50,"
            " AVG(interval_width_pct) AS avg_width FROM predictions"
            " WHERE day IS NOT NULL AND day != ''"
            " GROUP BY day ORDER BY day"
        ).fetchall()
        mix = self._conn.execute(
            "SELECT district, COUNT(*) AS n FROM predictions WHERE district IS NOT NULL"
            " GROUP BY district ORDER BY n DESC, district"
        ).fetchall()
        return {
            "n_total": n_total,
            "predictions_by_day": [
                {
                    "day": day,
                    "n": n,
                    "avg_p50": round(avg_p50) if avg_p50 is not None else None,
                    "avg_interval_width_pct": round(w, 1) if w is not None else None,
                }
                for day, n, avg_p50, w in by_day
            ],
            "district_mix": [{"district": d, "n": n} for d, n in mix],
        }

    def import_jsonl(self, jsonl_path: Path) -> int:
        """一次性导入旧 JSONL 日志并把它改名 .imported;返回导入条数。"""
        if not jsonl_path.exists():
            return 0
        imported = 0
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    self.append(json.loads(line))
                    imported += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        jsonl_path.rename(jsonl_path.with_suffix(".jsonl.imported"))
        return imported

    def close(self) -> None:
        self._conn.close()
