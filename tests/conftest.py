"""共享 fixtures:合成数据 -> 微型数仓 -> 微型模型 -> API 客户端。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.config import SQL_DIR  # noqa: E402
from homevalue.data_clean import clean_snapshot  # noqa: E402
from homevalue.db import execute_script, get_engine, read_query  # noqa: E402


@pytest.fixture(scope="session")
def tiny_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """用合成数据(300 行 x 2 期快照)构建微型数仓,复用 build_db 的组件。"""
    from scripts.build_db import parse_file_meta, read_raw, repair_districts
    from scripts.make_synth import synth_snapshot

    tmp_path = tmp_path_factory.mktemp("db")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for date, seed, churn in [("20240301", 1, 0.0), ("20240901", 2, 0.3)]:
        df = synth_snapshot(300, date, seed=seed, churn=churn)
        df.to_csv(raw_dir / ("bj__synthetic__" + date.replace("-", "") + ".csv"),
                  index=False, encoding="utf-8")

    clean_frames = []
    for f in sorted(raw_dir.glob("*.csv")):
        city, snap = parse_file_meta(f)
        raw = read_raw(f)
        clean_frames.append(clean_snapshot(raw, city=city, snapshot_date=snap))

    clean_all = pd.concat(clean_frames, ignore_index=True)
    clean_all, _ = repair_districts(clean_all)

    db = tmp_path / "listings.db"
    engine = get_engine(db)
    execute_script(engine, SQL_DIR / "01_schema.sql")
    clean_all.to_sql("listings_all", engine, if_exists="append", index=False)
    execute_script(engine, SQL_DIR / "02_etl.sql")
    return db


@pytest.fixture(scope="session")
def micro_artifacts(tmp_path_factory: pytest.TempPathFactory, tiny_db: Path) -> Path:
    """在微型数仓上训练极小模型,产出一套可服务的 artifacts。"""
    import joblib
    from lightgbm import LGBMRegressor

    from scripts.train import prepare_xy

    engine = get_engine(tiny_db)
    df = read_query(engine, "SELECT * FROM listings WHERE city = 'bj'")
    df["bizcircle"] = df["bizcircle"].fillna("未知")

    X, y_log, _y_raw, cols, cat_maps = prepare_xy(df, full=True)
    art = tmp_path_factory.mktemp("models")
    main = LGBMRegressor(n_estimators=30, random_state=0, verbose=-1).fit(X, y_log)
    joblib.dump(main, art / "main.joblib")
    q10 = LGBMRegressor(objective="quantile", alpha=0.1, n_estimators=20, random_state=0, verbose=-1)
    q90 = LGBMRegressor(objective="quantile", alpha=0.9, n_estimators=20, random_state=0, verbose=-1)
    joblib.dump(q10.fit(X, y_log), art / "q10.joblib")
    joblib.dump(q90.fit(X, y_log), art / "q90.joblib")
    metadata = {
        "model_version": "test",
        "exp_id": "test",
        "cat_maps": cat_maps,
        "feature_cols": cols,
        "holdout": {"mae": 1234.0, "mape_pct": 5.0, "r2": 0.9},
    }
    (art / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return art


@pytest.fixture()
def api_client(tmp_path: Path, micro_artifacts: Path, tiny_db: Path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    cache = tmp_path / "analysis_cache.json"
    cache.write_text(
        json.dumps(
            {
                "districts_rank": [{"district": "朝阳", "n_listings": 10, "avg_unit_price": 60000,
                                     "avg_area": 80.0, "avg_age": 15.0, "price_rank": 1}],
                "city_price_trend": [],
                "top_bizcircle_per_district": [],
                "price_deciles": [],
                "layout_crosstab": [],
                "price_change_summary": [
                    {"n_changed": 1, "avg_pct_change": -1.0, "n_reduced": 1, "pct_reduced": 100.0}
                ],
                "biggest_price_drops": [],
                "city_compare": [],
                "pareto_value": [{"n_top20": 1, "n_all": 5, "top20_value_share": 40.0}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(
        artifacts_dir=micro_artifacts,
        db_path=tiny_db,
        cache_path=cache,
        errors_path=tmp_path / "errors_none.json",
    )
    with TestClient(app) as client:
        yield client
