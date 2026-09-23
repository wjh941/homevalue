"""把一份链家快照 DataFrame 清洗成建模/入库标准结构。"""

from __future__ import annotations

import pandas as pd

from .features import (
    floor_ordinal,
    parse_build_year,
    parse_direction,
    parse_district,
    parse_layout,
    parse_level,
    parse_renovation,
)

CLEAN_COLUMNS = [
    "city",
    "snapshot_date",
    "hhid",
    "district",
    "bizcircle",
    "community",
    "title",
    "total_price_wan",
    "unit_price",
    "rooms",
    "halls",
    "area_sqm",
    "floor_pos",
    "floor_ordinal",
    "total_floors",
    "dir_main",
    "dir_south",
    "dir_north",
    "dir_east",
    "dir_west",
    "dir_count",
    "renovation",
    "build_year",
    "tax",
    "link",
]

# 合理价格/面积范围,过滤明显脏数据
UNIT_PRICE_MIN, UNIT_PRICE_MAX = 5_000, 250_000  # 元/平米
AREA_MIN, AREA_MAX = 10.0, 800.0  # 平米
ROOMS_MAX = 10


def clean_snapshot(df: pd.DataFrame, city: str, snapshot_date: str) -> pd.DataFrame:
    """一份原始快照 -> 清洗后的行级表(每行 = 某房源在某快照日的状态)。"""
    df = df.copy()
    # 链家导出文件首列为 BOM/序号,统一丢弃
    df = df.loc[:, ~df.columns.str.contains("Unnamed|^\ufeff")]

    required = {"hhid", "unit_price", "total_price", "hourseSize"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"输入缺少必要列: {sorted(missing)}")

    df["hhid"] = pd.to_numeric(df["hhid"], errors="coerce")
    df = df.dropna(subset=["hhid"])
    df["hhid"] = df["hhid"].astype("int64")

    # 同一快照内 hhid 重复(爬虫翻页重叠),保留首条
    df = df.drop_duplicates(subset=["hhid"], keep="first")

    layout = df["hourseType"].map(parse_layout)
    df["rooms"] = [p[0] for p in layout]
    df["halls"] = [p[1] for p in layout]

    levels = df["level"].map(parse_level)
    df["floor_pos"] = [f.pos for f in levels]
    df["total_floors"] = [f.total for f in levels]
    df["floor_ordinal"] = df["floor_pos"].map(floor_ordinal)

    dirs = df["direction"].map(parse_direction)
    df["dir_main"] = [d.main for d in dirs]
    df["dir_south"] = [int(d.south) for d in dirs]
    df["dir_north"] = [int(d.north) for d in dirs]
    df["dir_east"] = [int(d.east) for d in dirs]
    df["dir_west"] = [int(d.west) for d in dirs]
    df["dir_count"] = [d.count for d in dirs]

    df["build_year"] = df["buildTime"].map(parse_build_year)
    df["district"] = df["area"].map(parse_district)
    df["bizcircle"] = df["position"].astype("string").str.strip()
    df["renovation"] = df["fitment"].map(parse_renovation)

    out = pd.DataFrame(
        {
            "city": city,
            "snapshot_date": snapshot_date,
            "hhid": df["hhid"],
            "district": df["district"],
            "bizcircle": df["bizcircle"],
            "community": df["community"].astype("string").str.strip(),
            "title": df["title"].astype("string").str.strip(),
            "total_price_wan": pd.to_numeric(df["total_price"], errors="coerce"),
            "unit_price": pd.to_numeric(df["unit_price"], errors="coerce"),
            "rooms": df["rooms"],
            "halls": df["halls"],
            "area_sqm": pd.to_numeric(df["hourseSize"], errors="coerce"),
            "floor_pos": df["floor_pos"],
            "floor_ordinal": df["floor_ordinal"],
            "total_floors": df["total_floors"],
            "dir_main": df["dir_main"],
            "dir_south": df["dir_south"],
            "dir_north": df["dir_north"],
            "dir_east": df["dir_east"],
            "dir_west": df["dir_west"],
            "dir_count": df["dir_count"],
            "renovation": df["renovation"],
            "build_year": df["build_year"],
            "tax": df["tax"].astype("string").fillna(""),
            "link": df["link"].astype("string"),
        }
    )

    n0 = len(out)
    out = out.dropna(subset=["unit_price", "area_sqm", "rooms"])
    out = out[
        out["unit_price"].between(UNIT_PRICE_MIN, UNIT_PRICE_MAX)
        & out["area_sqm"].between(AREA_MIN, AREA_MAX)
        & (out["rooms"] <= ROOMS_MAX)
        & out["district"].notna()
        & (out["total_price_wan"] > 0)
    ]
    out = out[CLEAN_COLUMNS].reset_index(drop=True)
    out.attrs["dropped_ratio"] = 1 - len(out) / max(n0, 1)
    return out
