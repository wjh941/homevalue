"""ETL 入口:读取 data/raw/*.csv -> 清洗 -> 建 SQLite 数仓 -> 执行 ETL SQL。

用法:
    python scripts/build_db.py [--raw data/raw] [--db data/processed/listings.db]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.config import DATA_RAW, DB_PATH, SQL_DIR  # noqa: E402
from homevalue.data_clean import clean_snapshot  # noqa: E402
from homevalue.db import execute_script, get_engine  # noqa: E402
from homevalue.features import BJ_DISTRICTS  # noqa: E402

_DATE_RE = re.compile(r"(\d{8})")
_DROP_COLS_RE = re.compile(r"Unnamed|^\ufeff|^$")


def repair_districts(clean_all: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """修复北京数据中 area 字段填成商圈名的问题。

    思路:area 为合法区的行给出 (商圈 -> 区) 的可信映射(多数票),
    再用该映射修复 area 非法、但商圈可识别的行;仍无法识别的归入「其他」。
    """
    stats = {"repaired": 0, "othered": 0}
    is_bj = clean_all["city"] == "bj"
    valid = is_bj & clean_all["district"].isin(BJ_DISTRICTS)

    vote = (
        clean_all[valid]
        .groupby(["bizcircle", "district"], observed=True)
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=False)
        .drop_duplicates("bizcircle")
    )
    mapping = dict(zip(vote["bizcircle"], vote["district"], strict=False))

    needs = is_bj & ~valid
    fixed = clean_all.loc[needs, "bizcircle"].map(mapping)
    clean_all.loc[needs, "district"] = fixed
    stats["repaired"] = int(fixed.notna().sum())

    # 第二轮:小区 -> 区 多数票(小区与区一一对应,映射更可信)
    valid2 = is_bj & clean_all["district"].isin(BJ_DISTRICTS)
    vote2 = (
        clean_all[valid2]
        .groupby(["community", "district"], observed=True)
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=False)
        .drop_duplicates("community")
    )
    mapping2 = dict(zip(vote2["community"], vote2["district"], strict=False))
    still = is_bj & ~clean_all["district"].isin(BJ_DISTRICTS)
    fixed2 = clean_all.loc[still, "community"].map(mapping2)
    clean_all.loc[still, "district"] = fixed2
    stats["repaired"] += int(fixed2.notna().sum())

    stats["othered"] = int(is_bj.sum() - valid.sum() - stats["repaired"])
    clean_all.loc[is_bj & ~clean_all["district"].isin(BJ_DISTRICTS), "district"] = "其他"
    return clean_all, stats


def discover_files(raw_dir: Path) -> list[Path]:
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"{raw_dir} 下没有 CSV,先运行 scripts/fetch_data.py")
    return files


def parse_file_meta(path: Path) -> tuple[str, str]:
    """从文件名解析 (city, snapshot_date)。例: bj__eroom_time__20220923_detail... -> (bj, 2022-09-23)"""
    city = path.name.split("__", 1)[0]
    m = _DATE_RE.search(path.name)
    if not m:
        raise ValueError(f"文件名中未找到日期: {path.name}")
    d = m.group(1)
    return city, f"{d[:4]}-{d[4:6]}-{d[6:]}"


def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"hhid": "float64"})
    return df.loc[:, ~df.columns.str.contains(_DROP_COLS_RE)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DATA_RAW)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    t0 = time.time()
    files = discover_files(args.raw)
    print(f"发现 {len(files)} 个快照文件")

    engine = get_engine(args.db)

    raw_frames: list[pd.DataFrame] = []
    clean_frames: list[pd.DataFrame] = []
    meta_rows: list[dict] = []

    for f in files:
        city, snap = parse_file_meta(f)
        raw = read_raw(f)
        cleaned = clean_snapshot(raw, city=city, snapshot_date=snap)
        raw["city"] = city
        raw["snapshot_date"] = snap
        raw_frames.append(raw)
        clean_frames.append(cleaned)
        meta_rows.append(
            {
                "city": city,
                "snapshot_date": snap,
                "rows_raw": len(raw),
                "rows_clean": len(cleaned),
                "source_file": f.name,
            }
        )
        print(
            f"  {city} {snap}  raw={len(raw):>7,}  clean={len(cleaned):>7,}"
            f"  dropped={cleaned.attrs['dropped_ratio']:.1%}"
        )

    raw_all = pd.concat(raw_frames, ignore_index=True)
    clean_all = pd.concat(clean_frames, ignore_index=True)
    clean_all, repair_stats = repair_districts(clean_all)
    print(f"district 修复: {repair_stats['repaired']:,} 行由商圈映射, {repair_stats['othered']:,} 行归入其他")

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS listings")
        conn.exec_driver_sql("DROP TABLE IF EXISTS listings_all")
        conn.exec_driver_sql("DROP TABLE IF EXISTS listings_raw")
        conn.exec_driver_sql("DROP TABLE IF EXISTS snapshots_meta")
        conn.exec_driver_sql("DROP VIEW IF EXISTS v_price_change")

    execute_script(engine, SQL_DIR / "01_schema.sql")

    raw_all.to_sql("listings_raw", engine, if_exists="append", index=False, chunksize=10_000)
    clean_all.to_sql("listings_all", engine, if_exists="append", index=False, chunksize=10_000)
    pd.DataFrame(meta_rows).to_sql("snapshots_meta", engine, if_exists="append", index=False)

    execute_script(engine, SQL_DIR / "02_etl.sql")

    n_listings = pd.read_sql_query("SELECT COUNT(*) AS n FROM listings", engine)["n"][0]
    by_city = pd.read_sql_query(
        "SELECT city, COUNT(*) AS n FROM listings GROUP BY city ORDER BY n DESC", engine
    )
    print(f"\nlistings_raw : {len(raw_all):,} 行")
    print(f"listings_all : {len(clean_all):,} 行(清洗后)")
    print(f"listings     : {n_listings:,} 套唯一房源(按 hhid 去重取最新)")
    print(by_city.to_string(index=False))
    print(f"\n完成,耗时 {time.time() - t0:.1f}s -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
