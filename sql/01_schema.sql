-- ============================================================
-- homevalue 数据仓库 schema (SQLite;切换 PostgreSQL 仅需改连接串,
-- 本 schema 全部使用标准 SQL 类型)
-- 三层结构: listings_raw(原始) -> listings_all(清洗行级) -> listings(建模宽表)
-- ============================================================

-- 原始快照:每行 = 某房源在某快照日的抓取记录,字段与源 CSV 一致
CREATE TABLE IF NOT EXISTS listings_raw (
    city          TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,          -- YYYY-MM-DD
    hhid          INTEGER NOT NULL,       -- 房源 ID
    area          TEXT,                   -- 区
    title         TEXT,
    community     TEXT,                   -- 小区
    position      TEXT,                   -- 商圈
    tax           TEXT,
    total_price   REAL,                   -- 万
    unit_price    REAL,                   -- 元/平米
    link          TEXT,
    hourseType    TEXT,                   -- 户型,如 2室1厅
    hourseSize    REAL,                   -- 平米
    direction     TEXT,
    fitment       TEXT,                   -- 装修
    level         TEXT,                   -- 楼层,如 低楼层(共6层)
    buildTime     TEXT                    -- 建成年份,如 2005年建
);
CREATE INDEX IF NOT EXISTS ix_raw_hhid      ON listings_raw(hhid);
CREATE INDEX IF NOT EXISTS ix_raw_city_date ON listings_raw(city, snapshot_date);

-- 快照元数据
CREATE TABLE IF NOT EXISTS snapshots_meta (
    city          TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    rows_raw      INTEGER,
    rows_clean    INTEGER,
    source_file   TEXT
);

-- 清洗后行级表:每行 = 某房源在某快照日的状态(含解析后的特征)
CREATE TABLE IF NOT EXISTS listings_all (
    city          TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    hhid          INTEGER NOT NULL,
    district      TEXT,
    bizcircle     TEXT,
    community     TEXT,
    title         TEXT,
    total_price_wan REAL,
    unit_price    REAL,
    rooms         INTEGER,
    halls         INTEGER,
    area_sqm      REAL,
    floor_pos     TEXT,
    floor_ordinal REAL,
    total_floors  INTEGER,
    dir_main      TEXT,
    dir_south     INTEGER,
    dir_north     INTEGER,
    dir_east      INTEGER,
    dir_west      INTEGER,
    dir_count     INTEGER,
    renovation    TEXT,
    build_year    INTEGER,
    tax           TEXT,
    link          TEXT
);
CREATE INDEX IF NOT EXISTS ix_all_hhid ON listings_all(hhid);
CREATE INDEX IF NOT EXISTS ix_all_city ON listings_all(city);
CREATE INDEX IF NOT EXISTS ix_all_date ON listings_all(snapshot_date);

-- 建模宽表:每个房源仅保留最新快照,附带首次/末次出现与快照次数
CREATE TABLE IF NOT EXISTS listings (
    city          TEXT NOT NULL,
    hhid          INTEGER NOT NULL PRIMARY KEY,
    district      TEXT,
    bizcircle     TEXT,
    community     TEXT,
    title         TEXT,
    total_price_wan REAL,
    unit_price    REAL,
    rooms         INTEGER,
    halls         INTEGER,
    area_sqm      REAL,
    floor_pos     TEXT,
    floor_ordinal REAL,
    total_floors  INTEGER,
    dir_main      TEXT,
    dir_south     INTEGER,
    dir_north     INTEGER,
    dir_east      INTEGER,
    dir_west      INTEGER,
    dir_count     INTEGER,
    renovation    TEXT,
    build_year    INTEGER,
    tax           TEXT,
    link          TEXT,
    first_seen    TEXT,
    last_seen     TEXT,
    n_snapshots   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_list_city     ON listings(city);
CREATE INDEX IF NOT EXISTS ix_list_district ON listings(city, district);

-- 价格变动视图:同一房源相邻两次快照之间的挂牌价变化
CREATE VIEW IF NOT EXISTS v_price_change AS
SELECT
    a.hhid,
    a.city,
    a.district,
    a.bizcircle,
    a.community,
    b.snapshot_date AS prev_date,
    b.unit_price    AS prev_price,
    a.snapshot_date AS last_date,
    a.unit_price    AS last_price,
    ROUND((a.unit_price - b.unit_price) * 100.0 / b.unit_price, 2) AS pct_change
FROM listings_all a
JOIN listings_all b
  ON a.hhid = b.hhid
 AND a.snapshot_date = (SELECT MAX(x.snapshot_date) FROM listings_all x WHERE x.hhid = a.hhid)
 AND b.snapshot_date = (SELECT MAX(y.snapshot_date) FROM listings_all y
                        WHERE y.hhid = a.hhid AND y.snapshot_date < a.snapshot_date)
WHERE a.unit_price <> b.unit_price;
