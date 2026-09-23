-- ============================================================
-- 分析查询集(README 与 /api/analysis 共用)
-- 每个查询演示一类窗口函数/CTE 用法
-- ============================================================

-- 1. 各区挂牌均价排名(RANK 窗口)
-- name: districts_rank
WITH d AS (
    SELECT district,
           COUNT(*)                      AS n_listings,
           ROUND(AVG(unit_price), 0)     AS avg_unit_price,
           ROUND(AVG(area_sqm), 1)       AS avg_area,
           ROUND(AVG(2024 - build_year), 1) AS avg_age
    FROM listings
    WHERE city = 'bj'
    GROUP BY district
)
SELECT district, n_listings, avg_unit_price, avg_area, avg_age,
       RANK() OVER (ORDER BY avg_unit_price DESC) AS price_rank
FROM d
ORDER BY price_rank;

-- 2. 全市挂牌均价随快照日期变化(LAG 环比)
-- name: city_price_trend
WITH t AS (
    SELECT snapshot_date,
           COUNT(*)                  AS n_listings,
           ROUND(AVG(unit_price), 0) AS avg_unit_price
    FROM listings_all
    WHERE city = 'bj'
    GROUP BY snapshot_date
)
SELECT snapshot_date, n_listings, avg_unit_price,
       ROUND(
           (avg_unit_price - LAG(avg_unit_price) OVER (ORDER BY snapshot_date)) * 100.0
           / LAG(avg_unit_price) OVER (ORDER BY snapshot_date), 2) AS mom_pct
FROM t
ORDER BY snapshot_date;

-- 3. 每区均价 TOP3 商圈(ROW_NUMBER 分区排名)
-- name: top_bizcircle_per_district
WITH b AS (
    SELECT district, bizcircle,
           COUNT(*)                  AS n_listings,
           ROUND(AVG(unit_price), 0) AS avg_unit_price
    FROM listings
    WHERE city = 'bj'
    GROUP BY district, bizcircle
    HAVING COUNT(*) >= 30
),
ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY district ORDER BY avg_unit_price DESC) AS rk
    FROM b
)
SELECT district, bizcircle, n_listings, avg_unit_price
FROM ranked
WHERE rk <= 3
ORDER BY district, rk;

-- 4. 单价十分位分组画像(NTILE)
-- name: price_deciles
WITH d AS (
    SELECT unit_price, area_sqm,
           NTILE(10) OVER (ORDER BY unit_price) AS decile
    FROM listings
    WHERE city = 'bj'
)
SELECT decile,
       COUNT(*)                    AS n_listings,
       ROUND(MIN(unit_price), 0)   AS price_min,
       ROUND(MAX(unit_price), 0)   AS price_max,
       ROUND(AVG(unit_price), 0)   AS avg_unit_price,
       ROUND(AVG(area_sqm), 1)     AS avg_area
FROM d
GROUP BY decile
ORDER BY decile;

-- 5. 各区户型均价交叉表(条件聚合透视)
-- name: layout_crosstab
WITH b AS (
    SELECT district,
           CASE WHEN rooms <= 1 THEN '1室'
                WHEN rooms = 2  THEN '2室'
                WHEN rooms = 3  THEN '3室'
                ELSE '4室+' END AS layout,
           unit_price
    FROM listings
    WHERE city = 'bj'
)
SELECT district,
       ROUND(AVG(CASE WHEN layout = '1室' THEN unit_price END), 0) AS avg_1room,
       ROUND(AVG(CASE WHEN layout = '2室' THEN unit_price END), 0) AS avg_2room,
       ROUND(AVG(CASE WHEN layout = '3室' THEN unit_price END), 0) AS avg_3room,
       ROUND(AVG(CASE WHEN layout = '4室+' THEN unit_price END), 0) AS avg_4plus
FROM b
GROUP BY district
ORDER BY district;

-- 6. 挂牌价变动汇总:降价房源占比(基于价格变动视图)
-- name: price_change_summary
SELECT COUNT(*)                                                        AS n_changed,
       ROUND(AVG(pct_change), 2)                                       AS avg_pct_change,
       SUM(CASE WHEN pct_change < 0 THEN 1 ELSE 0 END)                 AS n_reduced,
       ROUND(100.0 * SUM(CASE WHEN pct_change < 0 THEN 1 ELSE 0 END)
             / COUNT(*), 1)                                            AS pct_reduced
FROM v_price_change
WHERE city = 'bj';

-- 7. 降价幅度 TOP20 房源(视图 + 排序)
-- name: biggest_price_drops
SELECT district, bizcircle, community, prev_date, prev_price, last_date, last_price, pct_change
FROM v_price_change
WHERE city = 'bj'
ORDER BY pct_change ASC
LIMIT 20;

-- 8. 多城市均价对比(分组聚合上的 RANK)
-- name: city_compare
SELECT city,
       COUNT(*)                  AS n_listings,
       ROUND(AVG(unit_price), 0) AS avg_unit_price,
       RANK() OVER (ORDER BY AVG(unit_price) DESC) AS rank_by_price
FROM listings
GROUP BY city
ORDER BY rank_by_price;

-- 9. 帕累托:挂牌总价最高的 20% 房源占总挂牌金额比例(窗口思想)
-- name: pareto_value
WITH ranked AS (
    SELECT total_price_wan,
           CASE WHEN ROW_NUMBER() OVER (ORDER BY total_price_wan DESC)
                     <= 0.2 * COUNT(*) OVER ()
                THEN 1 ELSE 0 END AS top20
    FROM listings
    WHERE city = 'bj'
)
SELECT SUM(CASE WHEN top20 = 1 THEN 1 ELSE 0 END) AS n_top20,
       COUNT(*)                                   AS n_all,
       ROUND(100.0 * SUM(CASE WHEN top20 = 1 THEN total_price_wan ELSE 0 END)
             / SUM(total_price_wan), 1)           AS top20_value_share
FROM ranked;

-- 10. 全国各区均价排名(RANK 按城市分区;样本过少的区剔除)
-- name: districts_rank_all
WITH d AS (
    SELECT city, district,
           COUNT(*)                  AS n_listings,
           ROUND(AVG(unit_price), 0) AS avg_unit_price,
           ROUND(AVG(area_sqm), 1)   AS avg_area
    FROM listings
    GROUP BY city, district
    HAVING COUNT(*) >= 30
)
SELECT city, district, n_listings, avg_unit_price, avg_area,
       RANK() OVER (PARTITION BY city ORDER BY avg_unit_price DESC) AS price_rank
FROM d
ORDER BY city, price_rank;

-- 11. 多城市挂牌均价趋势(LAG 按城市分区环比)
-- name: city_price_trend_all
WITH t AS (
    SELECT city, snapshot_date,
           COUNT(*)                  AS n_listings,
           ROUND(AVG(unit_price), 0) AS avg_unit_price
    FROM listings_all
    GROUP BY city, snapshot_date
)
SELECT city, snapshot_date, n_listings, avg_unit_price,
       ROUND(
           (avg_unit_price - LAG(avg_unit_price) OVER (PARTITION BY city ORDER BY snapshot_date)) * 100.0
           / LAG(avg_unit_price) OVER (PARTITION BY city ORDER BY snapshot_date), 2) AS mom_pct
FROM t
ORDER BY city, snapshot_date;
