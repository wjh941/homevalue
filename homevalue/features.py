"""从链家原始文本字段解析结构化特征,并构建模型特征矩阵。

所有解析函数都是纯函数,便于单元测试;build_feature_frame 同时服务
训练(train.py)与在线预测(api),保证线上线下特征口径一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .config import AGE_REF_YEAR

# ---------------------------------------------------------------------------
# 楼层
# ---------------------------------------------------------------------------

FLOOR_ORDER = ["地下室", "底层", "低楼层", "中楼层", "高楼层", "顶层"]
# 归一化到 0.0(地下室)~1.0(顶层)
FLOOR_ORDINAL = {name: i / (len(FLOOR_ORDER) - 1) for i, name in enumerate(FLOOR_ORDER)}

_LEVEL_RE = re.compile(r"^([^\(（]*?)[\(（]?(?:共)?(\d+)层[\)）]?$")


@dataclass(frozen=True)
class FloorInfo:
    pos: str  # FLOOR_ORDER 之一,或 "未知"
    total: int | None  # 总层数


def parse_level(text: str | float) -> FloorInfo:
    """解析楼层字段。

    "低楼层(共6层)" -> FloorInfo("低楼层", 6)
    "6层"           -> FloorInfo("未知", 6)
    "地下室"         -> FloorInfo("地下室", None)
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return FloorInfo("未知", None)
    text = str(text).strip()
    m = _LEVEL_RE.match(text)
    if m:
        pos_raw = (m.group(1) or "").strip()
        total = int(m.group(2))
        pos = pos_raw if pos_raw in FLOOR_ORDER else "未知"
        return FloorInfo(pos, total)
    if text in FLOOR_ORDER:
        return FloorInfo(text, None)
    digits = re.search(r"(\d+)", text)
    return FloorInfo("未知", int(digits.group(1)) if digits else None)


def floor_ordinal(pos: str) -> float:
    return FLOOR_ORDINAL.get(pos, 0.5)  # 未知楼层取中位


# ---------------------------------------------------------------------------
# 户型
# ---------------------------------------------------------------------------


def parse_layout(text: str | float) -> tuple[int | None, int | None]:
    """\"2室1厅\" -> (2, 1);解析失败返回 (None, None)。"""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None, None
    text = str(text)
    rooms = re.search(r"(\d+)室", text)
    halls = re.search(r"(\d+)厅", text)
    if not rooms:
        return None, None
    return int(rooms.group(1)), int(halls.group(1)) if halls else 0


# ---------------------------------------------------------------------------
# 朝向
# ---------------------------------------------------------------------------

_CARDINALS = ("东", "南", "西", "北")


@dataclass(frozen=True)
class DirectionInfo:
    main: str  # 第一个出现的基准朝向
    south: bool
    north: bool
    east: bool
    west: bool
    count: int


def parse_direction(text: str | float) -> DirectionInfo:
    """\"南 北\" -> 主朝向南,共 2 个朝向。"""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        chars: list[str] = []
    else:
        chars = [c for c in str(text) if c in _CARDINALS]
    main = chars[0] if chars else "未知"
    return DirectionInfo(
        main=main,
        south="南" in chars,
        north="北" in chars,
        east="东" in chars,
        west="西" in chars,
        count=len(set(chars)),
    )


# ---------------------------------------------------------------------------
# 建成年份 / 区域 / 装修
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"(1[89]\d{2}|20[0-2]\d)")


def parse_build_year(text: str | float) -> int | None:
    """\"2005年建\" -> 2005;\"板楼\"/缺失等 -> None。"""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    m = _YEAR_RE.search(str(text))
    return int(m.group(1)) if m else None


def parse_district(text: str | float) -> str | None:
    """\"朝阳区\" -> \"朝阳\";空值返回 None。"""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    s = str(text).strip()
    for suffix in ("新区", "区", "县", "市"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    return s or None


RENOVATION_MAP = {"精装": "精装", "简装": "简装", "毛坯": "毛坯", "其他": "其他"}

# 北京行政区白名单(亦庄为链家常用的开发区口径,一并保留)。
# 实测约 37% 的记录 area 字段填的是商圈/小区名,统一规整为「其他」或就近修复。
BJ_DISTRICTS = {
    "东城", "西城", "朝阳", "海淀", "丰台", "石景山", "门头沟", "房山",
    "通州", "顺义", "昌平", "大兴", "怀柔", "平谷", "密云", "延庆", "亦庄",
}


def parse_renovation(text: str | float) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return "其他"
    return RENOVATION_MAP.get(str(text).strip(), "其他")


# ---------------------------------------------------------------------------
# 特征矩阵
# ---------------------------------------------------------------------------

OTHER = "__other__"

NUMERIC_FEATURES = [
    "area_sqm",
    "rooms",
    "halls",
    "halls_per_room",
    "total_floors",
    "floor_ordinal",
    "build_year",
    "building_age",
    "age_missing",
    "dir_south",
    "dir_north",
    "dir_east",
    "dir_west",
    "dir_count",
]
CAT_FEATURES = ["district", "bizcircle", "renovation"]
FEATURE_COLS = NUMERIC_FEATURES + CAT_FEATURES

CLEAN_TO_FEATURES = {
    "area_sqm": "area_sqm",
    "rooms": "rooms",
    "halls": "halls",
    "total_floors": "total_floors",
    "floor_ordinal": "floor_ordinal",
    "build_year": "build_year",
    "dir_south": "dir_south",
    "dir_north": "dir_north",
    "dir_east": "dir_east",
    "dir_west": "dir_west",
    "dir_count": "dir_count",
    "district": "district",
    "bizcircle": "bizcircle",
    "renovation": "renovation",
}


def attach_derived(df: pd.DataFrame) -> pd.DataFrame:
    """从 API 原始输入补齐清洗表的派生列(floor_ordinal、dir_* 等)。

    在线预测只有用户填写的少数字段;训练时这些列由 data_clean 生成。
    本函数保证线上输入经过同样的派生逻辑,口径一致。
    """
    df = df.copy()
    if "floor_ordinal" not in df.columns:
        df["floor_ordinal"] = df["floor_pos"].map(floor_ordinal)
    if "dir_south" not in df.columns:
        dirs = df["dir_main"].map(parse_direction)
        df["dir_south"] = [int(d.south) for d in dirs]
        df["dir_north"] = [int(d.north) for d in dirs]
        df["dir_east"] = [int(d.east) for d in dirs]
        df["dir_west"] = [int(d.west) for d in dirs]
        df["dir_count"] = [d.count for d in dirs]
    return df


# ---------------------------------------------------------------------------
# Target Encoding(小区/商圈粒度,折内拟合防泄漏)
# ---------------------------------------------------------------------------

TE_SOURCE_COLS = ["community", "bizcircle"]
TE_SMOOTH_K = 20  # 样本少的小区向全局均价收缩


def fit_target_maps(df: pd.DataFrame, target: str = "unit_price") -> dict:
    """在训练数据上拟合 TE 映射:平滑均值 = (mean*n + k*prior) / (n + k)。"""
    prior = float(df[target].mean())
    maps: dict[str, dict[str, float]] = {}
    for col in TE_SOURCE_COLS:
        g = df.groupby(col, observed=True)[target].agg(["mean", "count"])
        smoothed = (g["mean"] * g["count"] + TE_SMOOTH_K * prior) / (g["count"] + TE_SMOOTH_K)
        maps[col] = smoothed.astype(float).to_dict()
    return {"prior": prior, "k": TE_SMOOTH_K, "maps": maps}


def apply_target_maps(df: pd.DataFrame, te: dict) -> pd.DataFrame:
    """对输入(训练切分或单行线上输入)应用 TE,未见类别取先验。"""
    out = pd.DataFrame(index=df.index)
    for col, m in te["maps"].items():
        series = df[col] if col in df.columns else pd.Series([None] * len(df), index=df.index)
        out["te_" + col] = series.map(m).fillna(te["prior"]).astype(float)
    return out


def fit_category_maps(df: pd.DataFrame, min_count: int = 30) -> dict[str, list[str]]:
    """统计类别列出现次数,低频类别统一折叠到 __other__,防止线上出现未见类别。"""
    maps: dict[str, list[str]] = {}
    for col in CAT_FEATURES:
        counts = df[col].fillna(OTHER).value_counts()
        keep = sorted(str(v) for v in counts[counts >= min_count].index.tolist())
        maps[col] = keep + [OTHER]
    return maps


def build_feature_frame(df: pd.DataFrame, cat_maps: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """清洗表(或单行预测输入)-> 模型特征矩阵,列顺序固定。"""
    out = pd.DataFrame(index=df.index)
    for src, dst in CLEAN_TO_FEATURES.items():
        out[dst] = df[src]

    # 数值列统一强转(单行在线输入可能因 None 变成 object dtype)
    for col in ("area_sqm", "rooms", "halls", "total_floors", "floor_ordinal", "build_year",
                "dir_south", "dir_north", "dir_east", "dir_west", "dir_count"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    rooms = out["rooms"].clip(lower=1)
    out["halls_per_room"] = out["halls"] / rooms
    out["age_missing"] = out["build_year"].isna().astype(int)
    out["building_age"] = AGE_REF_YEAR - out["build_year"]  # 缺失保持 NaN,由模型/管道处理

    if cat_maps is not None:
        for col in CAT_FEATURES:
            known = set(cat_maps[col])
            vals = out[col].fillna(OTHER).astype(object).astype(str)
            out[col] = vals.where(vals.isin(known), OTHER)

    out = out[NUMERIC_FEATURES + CAT_FEATURES]
    if cat_maps is not None:
        # 固定类别顺序,保证在线/离线口径一致
        for col in CAT_FEATURES:
            out[col] = pd.Categorical(out[col], categories=cat_maps[col])
    return out
