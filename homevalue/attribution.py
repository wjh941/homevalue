"""单房归因与区内典型值(从 api/main.py 抽出,纯逻辑、可独立测试)。

区内典型值是"训练/分析/线上归因"三方共用的口径:
- scripts/export_analysis_cache.py 用 typical_stats 生成预计算缓存;
- api 在有库时实时调用同一函数,无库时读缓存;
- 归因以典型房源为基线,逐因子还原输入,度量对估值的边际影响。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pandas as pd

from homevalue.db import read_query
from homevalue.model import predict_quantiles

logger = logging.getLogger(__name__)

# 归因因子:名称 -> 涉及的输入字段(全部还原为区内典型值即得基线)
FACTOR_SPEC: list[tuple[str, tuple[str, ...]]] = [
    ("面积", ("area_sqm",)),
    ("房龄", ("build_year",)),
    ("楼层", ("floor_pos", "total_floors")),
    ("户型", ("rooms", "halls")),
    ("装修", ("renovation",)),
    ("商圈/小区", ("bizcircle", "community")),
]

_TYPICAL_FIELDS = (
    "area_sqm", "build_year", "total_floors", "rooms", "halls", "renovation", "floor_pos",
)


def typical_stats(df: pd.DataFrame) -> dict[str, Any] | None:
    """一组房源的典型值:数值列取中位数(1 位小数),类别列取众数。"""
    if not len(df):
        return None

    def med(col: str) -> float | None:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return round(float(s.median()), 1) if len(s) else None

    def mode_val(col: str, default: Any = None) -> Any:
        s = df[col].dropna()
        return (s.mode().iloc[0] if len(s) else default)

    return {
        "median_area": med("area_sqm"),
        "median_build_year": med("build_year"),
        "median_total_floors": med("total_floors"),
        "mode_rooms": mode_val("rooms"),
        "mode_halls": mode_val("halls"),
        "mode_renovation": mode_val("renovation", "简装"),
        "mode_floor_pos": mode_val("floor_pos", "中楼层"),
    }


def make_typicals_lookup(
    engine: Any | None,
    cache_rows: list[dict[str, Any]],
    city: str,
) -> Callable[[str], dict[str, Any] | None]:
    """区内典型值查询(带记忆化):sqlite 实时算,无库时读预计算导出。"""
    cache: dict[str, dict[str, Any] | None] = {}

    def lookup(district: str) -> dict[str, Any] | None:
        if district in cache:
            return cache[district]
        stats: dict[str, Any] | None = None
        try:
            if engine is not None:
                df = read_query(
                    engine,
                    f"SELECT {', '.join(_TYPICAL_FIELDS)}"
                    " FROM listings WHERE city = :city AND district = :district",
                    {"city": city, "district": district},
                )
                stats = typical_stats(df)
            else:
                for r in cache_rows:
                    if r.get("district") == district:
                        stats = r
                        break
        except Exception:  # noqa: BLE001 - 典型值失败只降级归因,不影响主预测
            logger.warning("district typicals failed | district=%s", district, exc_info=True)
            stats = None
        cache[district] = stats
        return stats

    return lookup


def _baseline_row(row: dict[str, Any], typical: dict[str, Any]) -> dict[str, Any]:
    base = dict(row)
    for k, v in (
        ("area_sqm", typical.get("median_area")),
        ("build_year", typical.get("median_build_year")),
        ("total_floors", typical.get("median_total_floors")),
        ("rooms", typical.get("mode_rooms")),
        ("halls", typical.get("mode_halls")),
        ("renovation", typical.get("mode_renovation")),
        ("floor_pos", typical.get("mode_floor_pos")),
    ):
        base[k] = v
    base["bizcircle"] = None
    base["community"] = None
    return base


def attribution_for(
    art: dict,
    row: dict[str, Any],
    typicals: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """单房归因:基线(区内典型房)与各因子行合并成一个 batch,
    一次 predict_quantiles 完成全部推理(替代旧的 7 次串行调用)。"""
    try:
        typical = typicals(row["district"])
        if not typical:
            return None
        base = _baseline_row(row, typical)

        factor_rows: list[tuple[str, dict[str, Any]]] = []
        for name, keys in FACTOR_SPEC:
            r = dict(base)
            vals = {k: row.get(k) for k in keys}
            if all(v is None for v in vals.values()):
                continue
            for k, v in vals.items():
                if v is not None:
                    r[k] = v
            factor_rows.append((name, r))

        batch = pd.DataFrame([base, *[r for _name, r in factor_rows]])
        p50s = predict_quantiles(art, batch)["p50"]
        p_base = float(p50s[0])
        factors = [
            {"name": name, "delta": round(float(p50s[i + 1]) - p_base)}
            for i, (name, _r) in enumerate(factor_rows)
        ]
        factors.sort(key=lambda x: -abs(x["delta"]))
        return {"baseline_p50": round(p_base), "factors": factors}
    except Exception:  # noqa: BLE001 - 归因失败不影响主预测,但必须可见
        logger.warning("attribution failed | district=%s", row.get("district"), exc_info=True)
        return None
