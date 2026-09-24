"""FastAPI 服务:/api/predict 估值 + /api/analysis 数据分析 + 静态仪表盘。

启动:
    uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from homevalue.config import (
    ANALYSIS_CACHE,
    API_STATIC_DIR,
    ARTIFACTS_DIR,
    DB_PATH,
    MODEL_CITY,
    MODEL_VERSION,
    PREDICTIONS_LOG,
    REPORTS_DIR,
    SQL_DIR,
)
from homevalue.db import get_engine, load_queries, read_query
from homevalue.model import load_artifacts, predict_quantiles


class PredictIn(BaseModel):
    district: str = Field(min_length=2, max_length=10, description="区,如 朝阳")
    bizcircle: str | None = Field(default=None, max_length=20, description="商圈,如 望京")
    community: str | None = Field(default=None, max_length=30, description="小区,如 望京新城(用于目标编码)")
    rooms: int = Field(ge=0, le=10, description="室")
    halls: int = Field(ge=0, le=10, description="厅")
    area_sqm: float = Field(gt=5, le=1000, description="建筑面积(平米)")
    floor_pos: str = Field(default="中楼层", max_length=10)
    total_floors: int | None = Field(default=None, ge=1, le=120)
    dir_main: str = Field(default="南", max_length=4)
    renovation: str = Field(default="简装", max_length=10)
    build_year: int | None = Field(default=None, ge=1900, le=2026, description="建成年份")


def create_app(
    artifacts_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    cache_path: Path | str | None = None,
    errors_path: Path | str | None = None,
    predictions_log: Path | str | None = None,
) -> FastAPI:
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else ARTIFACTS_DIR
    resolved_db = Path(db_path) if db_path else DB_PATH
    cache_path = Path(cache_path) if cache_path else ANALYSIS_CACHE
    errors_path = Path(errors_path) if errors_path else REPORTS_DIR / "error_analysis.json"
    pred_log_path = Path(predictions_log) if predictions_log else PREDICTIONS_LOG

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.art = load_artifacts(artifacts_dir)  # 启动即加载,失败快速暴露
        app.state.queries = load_queries(SQL_DIR / "03_analysis.sql")
        app.state.engine = get_engine(resolved_db) if resolved_db.exists() else None
        app.state.cache = (
            json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        )
        app.state.errors = (
            json.loads(errors_path.read_text(encoding="utf-8")) if errors_path.exists() else None
        )
        yield

    app = FastAPI(title="HomeValue 估值 API", version=MODEL_VERSION, lifespan=lifespan)

    def analysis_rows(name: str) -> list[dict[str, Any]]:
        """优先实时查库,库不在(如服务器仅部署产物)则读预计算缓存。"""
        if app.state.engine is not None and name in app.state.queries:
            return read_query(app.state.engine, app.state.queries[name]).to_dict("records")
        if name in app.state.cache:
            return app.state.cache[name]
        raise HTTPException(status_code=503, detail=f"分析数据不可用: {name}")

    def similar_rows(district: str, area_sqm: float) -> list[dict[str, Any]]:
        """同区面积最接近输入的 5 套最新在售房源(DB 实时或缓存样本)。"""
        if app.state.engine is not None:
            rows = read_query(
                app.state.engine,
                "SELECT district, community, bizcircle, area_sqm, unit_price, rooms, halls,"
                " build_year, floor_pos, renovation, total_floors FROM listings"
                " WHERE city = :city AND district = :district"
                " ORDER BY ABS(area_sqm - :area) LIMIT 5",
                {"city": MODEL_CITY, "district": district, "area": area_sqm},
            )
            return rows.to_dict("records")
        sample = [r for r in app.state.cache.get("similar_sample", []) if r.get("district") == district]
        sample.sort(key=lambda r: abs((r.get("area_sqm") or 0) - area_sqm))
        return sample[:5]

    def append_prediction_log(entry: dict[str, Any]) -> None:
        """逐条预测日志(输入+输出+延迟),失败静默不影响主流程。"""
        try:
            pred_log_path.parent.mkdir(parents=True, exist_ok=True)
            with pred_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    district_stats_cache: dict[str, dict | None] = {}

    def district_typicals(district: str) -> dict | None:
        """区内典型值(面积/年代/楼层/户型/装修中位数或众数);sqlite 实时算,缓存模式读导出。"""
        if district in district_stats_cache:
            return district_stats_cache[district]
        stats = None
        try:
            if app.state.engine is not None:
                df = read_query(
                    app.state.engine,
                    "SELECT area_sqm, build_year, total_floors, rooms, halls, renovation, floor_pos"
                    " FROM listings WHERE city = :city AND district = :district",
                    {"city": MODEL_CITY, "district": district},
                )
                if len(df):
                    def med(col):
                        s = pd.to_numeric(df[col], errors="coerce").dropna()
                        return round(float(s.median()), 1) if len(s) else None

                    def mode_val(col, default=None):
                        s = df[col].dropna()
                        return (s.mode().iloc[0] if len(s) else default)

                    stats = {
                        "median_area": med("area_sqm"),
                        "median_build_year": med("build_year"),
                        "median_total_floors": med("total_floors"),
                        "mode_rooms": mode_val("rooms"),
                        "mode_halls": mode_val("halls"),
                        "mode_renovation": mode_val("renovation", "简装"),
                        "mode_floor_pos": mode_val("floor_pos", "中楼层"),
                    }
            else:
                for r in app.state.cache.get("district_stats", []):
                    if r.get("district") == district:
                        stats = r
                        break
        except Exception:  # noqa: BLE001
            stats = None
        district_stats_cache[district] = stats
        return stats

    def attribution_for(art: dict, row: dict) -> dict | None:
        """单房归因:以'区内典型房源'为基线,逐因子还原输入,度量对估值的边际影响。"""
        try:
            typical = district_typicals(row["district"])
            if not typical:
                return None
            base = dict(row)
            for k, v in (
                ("area_sqm", typical.get("median_area")),
                ("build_year", typical.get("median_build_year")),
                ("total_floors", typical.get("median_total_floors")),
                ("rooms", typical.get("mode_rooms")),
                ("halls", typical.get("mode_halls")),
                ("renovation", typical.get("mode_renovation")),
                ("floor_pos", typical.get("mode_floor_pos")),
            ):
                base[k] = v
            base["bizcircle"] = None
            base["community"] = None

            def p50_of(r: dict) -> float:
                q = predict_quantiles(art, pd.DataFrame([r]))
                return float(q["p50"][0])

            p_base = p50_of(base)
            factors_spec = [
                ("面积", ["area_sqm"]),
                ("房龄", ["build_year"]),
                ("楼层", ["floor_pos", "total_floors"]),
                ("户型", ["rooms", "halls"]),
                ("装修", ["renovation"]),
                ("商圈/小区", ["bizcircle", "community"]),
            ]
            factors = []
            for name, keys in factors_spec:
                r = dict(base)
                vals = {k: row.get(k) for k in keys}
                if all(v is None for v in vals.values()):
                    continue
                for k, v in vals.items():
                    if v is not None:
                        r[k] = v
                delta = round(p50_of(r) - p_base)
                factors.append({"name": name, "delta": delta})
            factors.sort(key=lambda x: -abs(x["delta"]))
            return {"baseline_p50": round(p_base), "factors": factors}
        except Exception:  # noqa: BLE001 - 归因失败不影响主预测
            return None

    @app.get("/api/health")
    def health() -> dict:
        meta = app.state.cache.get("_meta") or {}
        if app.state.engine is not None:
            try:
                row = read_query(
                    app.state.engine,
                    "SELECT MIN(snapshot_date) AS first, MAX(snapshot_date) AS last,"
                    " COUNT(DISTINCT snapshot_date) AS n FROM listings_all WHERE city = :city",
                    {"city": MODEL_CITY},
                ).to_dict("records")[0]
                meta = {"first_snapshot": row["first"], "last_snapshot": row["last"],
                        "n_snapshots": row["n"]}
            except Exception:  # noqa: BLE001
                pass
        return {
            "status": "ok",
            "model_version": app.state.art["metadata"]["model_version"],
            "exp_id": app.state.art["metadata"]["exp_id"],
            "data_backend": "sqlite" if app.state.engine is not None else "cache",
            "data_freshness": meta,
            "holdout": app.state.art["metadata"]["holdout"],
        }

    known_districts: set | None = None

    def get_known_districts() -> set:
        """北京有效区名(懒加载记忆化);用于拒绝模型从未见过的区。"""
        nonlocal known_districts
        if known_districts is None:
            ds: set = set()
            try:
                if app.state.engine is not None:
                    df = read_query(
                        app.state.engine,
                        "SELECT DISTINCT district FROM listings WHERE city = :city",
                        {"city": MODEL_CITY},
                    )
                    ds = set(df["district"])
                else:
                    for r in app.state.cache.get("districts_rank_all", []):
                        if r.get("city") == MODEL_CITY:
                            ds.add(r["district"])
            except Exception:  # noqa: BLE001
                ds = set()
            known_districts = ds
        return known_districts

    @app.post("/api/predict")
    def predict(payload: PredictIn) -> dict:
        art = app.state.art
        row = payload.model_dump()
        known = get_known_districts()
        if known and row["district"] not in known:
            msg = "未知区:" + row["district"] + ";估值模型仅覆盖北京城区"
            raise HTTPException(status_code=400, detail=msg)
        q = predict_quantiles(art, pd.DataFrame([row]))
        p10, p50, p90 = (float(q[k][0]) for k in ("p10", "p50", "p90"))
        area = row["area_sqm"]

        comps: dict[str, Any] = {}
        try:
            if app.state.engine is not None:
                d = read_query(
                    app.state.engine,
                    "SELECT COUNT(*) AS n, ROUND(AVG(unit_price), 0) AS avg_price,"
                    " ROUND(AVG(area_sqm), 1) AS avg_area FROM listings"
                    " WHERE city = :city AND district = :district",
                    {"city": MODEL_CITY, "district": row["district"]},
                ).to_dict("records")[0]
                if d["n"]:
                    comps["district"] = {"district": row["district"], **d}
                if row["bizcircle"]:
                    b = read_query(
                        app.state.engine,
                        "SELECT COUNT(*) AS n, ROUND(AVG(unit_price), 0) AS avg_price FROM listings"
                        " WHERE city = :city AND district = :district AND bizcircle = :bizcircle",
                        {"city": MODEL_CITY, "district": row["district"], "bizcircle": row["bizcircle"]},
                    ).to_dict("records")[0]
                    if b["n"] and b["n"] > 0:
                        comps["bizcircle"] = {"name": row["bizcircle"], **b}
            else:
                for r in app.state.cache.get("districts_rank", []):
                    if r["district"] == row["district"]:
                        comps["district_avg_price"] = r["avg_unit_price"]
                        break
        except Exception:  # noqa: BLE001 - 可比参照失败不影响主预测
            comps = {"error": "comparables unavailable"}

        try:
            similar = similar_rows(row["district"], row["area_sqm"])
        except Exception:  # noqa: BLE001
            similar = []

        append_prediction_log({
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "district": row["district"],
            "bizcircle": row["bizcircle"],
            "community": row["community"],
            "area_sqm": area,
            "rooms": row["rooms"],
            "p50": round(p50),
            "interval_width_pct": round((p90 - p10) / p50 * 100, 1) if p50 else None,
            "model_version": art["metadata"]["model_version"],
        })

        return {
            "model_version": art["metadata"]["model_version"],
            "input": row,
            "unit_price": {"p10": round(p10), "p50": round(p50), "p90": round(p90)},
            "total_price_wan": {
                "p10": round(p10 * area / 1e4, 1),
                "p50": round(p50 * area / 1e4, 1),
                "p90": round(p90 * area / 1e4, 1),
            },
            "interval_width_pct": round((p90 - p10) / p50 * 100, 1) if p50 else None,
            "comparables": comps,
            "similar": similar,
            "attribution": attribution_for(art, row),
        }

    @app.get("/api/analysis/overview")
    def overview() -> dict:
        pareto = analysis_rows("pareto_value")
        n_all = pareto[0]["n_all"] if pareto else None
        districts = analysis_rows("districts_rank")
        return {
            "city": "北京",
            "n_listings": n_all,
            "top20_value_share": pareto[0].get("top20_value_share") if pareto else None,
            "top_districts": districts[:8],
            "districts_all": districts,
        }

    @app.get("/api/analysis/trend")
    def trend() -> list[dict]:
        return analysis_rows("city_price_trend")

    @app.get("/api/analysis/districts")
    def districts() -> list[dict]:
        return analysis_rows("districts_rank")

    @app.get("/api/analysis/districts-all")
    def districts_all() -> list[dict]:
        return analysis_rows("districts_rank_all")

    @app.get("/api/analysis/trend-all")
    def trend_all() -> list[dict]:
        return analysis_rows("city_price_trend_all")

    @app.get("/api/analysis/district-trend")
    def district_trend() -> list[dict]:
        return analysis_rows("district_price_trend")

    @app.get("/api/analysis/deciles")
    def deciles() -> list[dict]:
        return analysis_rows("price_deciles")

    @app.get("/api/analysis/crosstab")
    def crosstab() -> list[dict]:
        return analysis_rows("layout_crosstab")

    @app.get("/api/analysis/price-changes")
    def price_changes() -> dict:
        return {
            "summary": analysis_rows("price_change_summary"),
            "top_drops": analysis_rows("biggest_price_drops"),
            "city_compare": analysis_rows("city_compare"),
        }

    @app.get("/api/similar")
    def similar_endpoint(district: str, area_sqm: float) -> list[dict]:
        return similar_rows(district, area_sqm)

    @app.get("/api/predictions/stats")
    def prediction_stats() -> dict:
        """预测日志统计(使用量 + 预测分布),是漂移监控与 A/B 分流的数据地基。"""
        if not pred_log_path.exists():
            return {"n_total": 0}
        rows = []
        for line in pred_log_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not rows:
            return {"n_total": 0}
        p50s = sorted(r["p50"] for r in rows if r.get("p50"))
        widths = [r["interval_width_pct"] for r in rows if r.get("interval_width_pct") is not None]
        districts: dict[str, int] = {}
        for r in rows:
            d = r.get("district") or "?"
            districts[d] = districts.get(d, 0) + 1
        top = sorted(districts.items(), key=lambda kv: -kv[1])[:5]
        return {
            "n_total": len(rows),
            "avg_p50": round(sum(p50s) / len(p50s)) if p50s else None,
            "median_p50": p50s[len(p50s) // 2] if p50s else None,
            "avg_interval_width_pct": round(sum(widths) / len(widths), 1) if widths else None,
            "top_districts": [{"district": d, "n": n} for d, n in top],
            "last_ts": rows[-1].get("ts"),
        }

    @app.get("/api/analysis/errors")
    def errors() -> dict:
        if app.state.errors is None:
            raise HTTPException(status_code=404, detail="误差分析报告不存在,先运行 scripts/error_analysis.py")
        return app.state.errors

    @app.get("/api/features/importance")
    def importance() -> dict:
        imp_path = artifacts_dir / "feature_importance.json"
        if imp_path.exists():
            return json.loads(imp_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="特征重要性文件不存在")

    API_STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=API_STATIC_DIR, html=True), name="static")
    return app


app = create_app()
