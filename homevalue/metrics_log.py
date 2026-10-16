"""实验台账读取:metrics_log.jsonl -> holdout_mae 时间序列(漂移监控用)。

台账由训练入口每次训练追加一行(含 holdout_mae/holdout_mape_pct/holdout_r2
/ts/exp_id/split);本模块只读,封装成纯函数便于单测。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_mae_history(path: Path | str) -> list[dict[str, Any]]:
    """读台账,返回 holdout_mae 时间序列(文件序即时间序)。

    坏行、缺 holdout_mae 的行跳过;文件不存在返回 []。
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    # utf-8-sig 兼容带 BOM 的台账(Windows 产物常见);无 BOM 时行为与 utf-8 一致
    with p.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("holdout_mae") is None:
                continue
            out.append(
                {
                    "ts": row.get("ts"),
                    "exp_id": row.get("exp_id"),
                    "mae": float(row["holdout_mae"]),
                }
            )
    return out
