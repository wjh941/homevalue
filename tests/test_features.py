"""特征解析函数的单元测试。"""

from __future__ import annotations

import pandas as pd

from homevalue.features import (
    attach_derived,
    build_feature_frame,
    fit_category_maps,
    floor_ordinal,
    parse_build_year,
    parse_direction,
    parse_district,
    parse_layout,
    parse_level,
)


def test_parse_layout():
    assert parse_layout("2室1厅") == (2, 1)
    assert parse_layout("1室0厅") == (1, 0)
    assert parse_layout("4室2厅2卫") == (4, 2)
    assert parse_layout(None) == (None, None)
    assert parse_layout("未知") == (None, None)


def test_parse_level():
    assert parse_level("低楼层(共6层)").pos == "低楼层"
    assert parse_level("低楼层(共6层)").total == 6
    assert parse_level("6层").pos == "未知"
    assert parse_level("6层").total == 6
    assert parse_level("地下室").pos == "地下室"
    assert parse_level("地下室").total is None
    assert parse_level(None).pos == "未知"
    assert floor_ordinal("顶层") > floor_ordinal("低楼层") > floor_ordinal("地下室")


def test_parse_direction():
    d = parse_direction("南 北")
    assert d.main == "南" and d.south and d.north and not d.east and d.count == 2
    d2 = parse_direction("东南")
    assert d2.south and d2.east and d2.count == 2
    assert parse_direction(None).main == "未知"


def test_parse_build_year_and_district():
    assert parse_build_year("2005年建") == 2005
    assert parse_build_year("1998年建") == 1998
    assert parse_build_year("板楼") is None
    assert parse_district("朝阳区") == "朝阳"
    assert parse_district("通州") == "通州"
    assert parse_district(None) is None


def test_build_feature_frame_schema():
    df = pd.DataFrame(
        {
            "area_sqm": [80.0],
            "rooms": [2],
            "halls": [1],
            "total_floors": [18],
            "floor_ordinal": [0.6],
            "build_year": [2005.0],
            "dir_south": [1],
            "dir_north": [0],
            "dir_east": [0],
            "dir_west": [0],
            "dir_count": [1],
            "district": ["朝阳"],
            "bizcircle": ["望京"],
            "renovation": ["精装"],
        }
    )
    maps = fit_category_maps(df, min_count=1)
    X = build_feature_frame(df, maps)
    assert "halls_per_room" in X.columns
    assert "building_age" in X.columns
    assert X["age_missing"].iloc[0] == 0
    assert X["halls_per_room"].iloc[0] == 0.5
    assert list(X.columns) == list(build_feature_frame(df, maps).columns)


def test_fit_category_maps_folds_rare_to_other():
    df = pd.DataFrame(
        {
            "district": ["朝阳"] * 5 + ["亦庄"],
            "bizcircle": ["望京"] * 6,
            "renovation": ["精装"] * 6,
        }
    )
    maps = fit_category_maps(df, min_count=3)
    assert "朝阳" in maps["district"] and "__other__" in maps["district"]
    assert "亦庄" not in maps["district"]


def test_attach_derived_from_api_payload():
    df = pd.DataFrame([{"floor_pos": "低楼层", "dir_main": "南 北"}])
    out = attach_derived(df)
    assert out["floor_ordinal"].iloc[0] == floor_ordinal("低楼层")
    assert out["dir_south"].iloc[0] == 1 and out["dir_count"].iloc[0] == 2
