"""清洗函数:脏数据过滤、去重、字段解析。"""

from __future__ import annotations

import pandas as pd

from homevalue.data_clean import CLEAN_COLUMNS, clean_snapshot


def make_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "area": ["朝阳区", "海淀区", "朝阳区"],
            "title": ["a", "b", "c"],
            "community": ["x", "y", "z"],
            "position": ["望京", "中关村", "望京"],
            "tax": ["满五年唯一", "", ""],
            "total_price": [500.0, 0.0, 300.0],
            "unit_price": [60000.0, 50000.0, 999999.0],
            "hhid": [1, 2, 2],
            "link": ["", "", ""],
            "hourseType": ["2室1厅", "3室2厅", "2室1厅"],
            "hourseSize": [80.0, 120.0, 120.0],
            "direction": ["南 北", "南", "东"],
            "fitment": ["精装", "毛坯", "其他"],
            "level": ["低楼层(共6层)", "顶层(共28层)", "地下室"],
            "buildTime": ["2005年建", "板楼", "1998年建"],
        }
    )


def test_clean_snapshot_parses_and_dedups():
    out = clean_snapshot(make_raw(), city="bj", snapshot_date="2024-01-01")
    # hhid=2 首条 total_price=0 被过滤;第二条 unit_price 超上限被过滤 -> 只剩 hhid=1
    assert list(out["hhid"]) == [1]
    row = out.iloc[0]
    assert row["rooms"] == 2 and row["halls"] == 1
    assert row["floor_pos"] == "低楼层" and row["total_floors"] == 6
    assert row["dir_south"] == 1 and row["dir_count"] == 2
    assert row["build_year"] == 2005
    assert row["district"] == "朝阳"
    assert row["renovation"] == "精装"
    assert list(out.columns) == CLEAN_COLUMNS


def test_clean_snapshot_drops_bad_rows():
    out = clean_snapshot(make_raw(), city="bj", snapshot_date="2024-01-01")
    assert 0 < out.attrs["dropped_ratio"] < 1
