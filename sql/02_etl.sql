-- ============================================================
-- ETL:从清洗行级表构建建模宽表(窗口函数去重取最新快照)
-- 注意:历史窗口必须与 rn 同层计算,否则会先过滤后聚合得到错误计数
-- ============================================================

INSERT INTO listings
SELECT
    city, hhid, district, bizcircle, community, title,
    total_price_wan, unit_price, rooms, halls, area_sqm,
    floor_pos, floor_ordinal, total_floors,
    dir_main, dir_south, dir_north, dir_east, dir_west, dir_count,
    renovation, build_year, tax, link,
    first_seen, last_seen, n_snapshots
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY hhid ORDER BY snapshot_date DESC) AS rn,
           FIRST_VALUE(snapshot_date) OVER w AS first_seen,
           LAST_VALUE(snapshot_date)  OVER w AS last_seen,
           COUNT(*)                   OVER w AS n_snapshots
    FROM listings_all
    WINDOW w AS (PARTITION BY hhid ORDER BY snapshot_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
WHERE rn = 1;
