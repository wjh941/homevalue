"""ETL 集成测试:合成数据 -> 数仓 -> 去重/修复/价格历史。"""

from __future__ import annotations

from homevalue.db import get_engine, read_query
from homevalue.features import BJ_DISTRICTS


def test_dedup_keeps_latest_snapshot(tiny_db):
    engine = get_engine(tiny_db)
    n_unique = read_query(engine, "SELECT COUNT(DISTINCT hhid) AS n FROM listings_all")["n"][0]
    n_listings = read_query(engine, "SELECT COUNT(*) AS n FROM listings")["n"][0]
    assert n_listings == n_unique

    obs = read_query(engine, "SELECT MIN(n_snapshots) AS lo, MAX(n_snapshots) AS hi FROM listings")
    assert obs["hi"][0] == 2 and obs["lo"][0] >= 1

    # 保留的是最新快照的价格
    check = read_query(
        engine,
        """
        SELECT l.hhid, l.unit_price AS kept
        FROM listings l
        WHERE l.n_snapshots = 2 AND l.unit_price <> (
            SELECT a.unit_price FROM listings_all a
            WHERE a.hhid = l.hhid
            ORDER BY a.snapshot_date ASC LIMIT 1)
        LIMIT 5
        """,
    )
    assert len(check) > 0  # 存在跨期调价房源,且宽表保留的是最新价


def test_district_repair_bounds_values(tiny_db):
    engine = get_engine(tiny_db)
    districts = set(read_query(engine, "SELECT DISTINCT district FROM listings WHERE city='bj'")["district"])
    assert districts <= (BJ_DISTRICTS | {"其他"})


def test_price_change_view(tiny_db):
    engine = get_engine(tiny_db)
    n_changed = read_query(engine, "SELECT COUNT(*) AS n FROM v_price_change")["n"][0]
    assert n_changed > 0
    rows = read_query(engine, "SELECT prev_price, last_price, pct_change FROM v_price_change LIMIT 10")
    assert (rows["prev_price"] > 0).all()
