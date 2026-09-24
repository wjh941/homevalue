"""前端消费字段全量断言:仪表盘读到的每个字段都必须存在(防接口改型导致前端静默坏)。
与 tests/test_api.py 的功能测试互补;这里只管"字段在不在、位置对不对"。"""

from __future__ import annotations


def _need(obj, path, label, failures):
    cur = obj
    for key in path.split("."):
        if isinstance(cur, list):
            if not cur or int(key) >= len(cur):
                failures.append(label + ": 缺少 " + path)
                return
            cur = cur[int(key)]
            continue
        if not isinstance(cur, dict) or key not in cur:
            failures.append(label + ": 缺少 " + path)
            return
        cur = cur[key]


def _check(failures, label, body, paths):
    for p in paths:
        _need(body, p, label, failures)


def test_frontend_consumed_fields(api_client):
    client = api_client
    failures: list[str] = []

    r = client.get("/api/health")
    assert r.status_code == 200
    _check(failures, "health", r.json(), ["holdout.mae", "holdout.mape_pct", "holdout.r2",
                                          "data_freshness.last_snapshot", "data_backend", "exp_id"])

    r = client.get("/api/analysis/overview")
    assert r.status_code == 200
    _check(failures, "overview", r.json(), [
        "n_listings", "top20_value_share",
        "districts_all.0.district", "districts_all.0.avg_unit_price", "districts_all.0.n_listings"])

    r = client.get("/api/analysis/deciles")
    assert r.status_code == 200
    if r.json():
        _check(failures, "deciles", r.json(), [
            "0.decile", "0.price_min", "0.price_max", "0.avg_unit_price", "0.avg_area", "0.n_listings"])

    r = client.get("/api/analysis/price-changes")
    assert r.status_code == 200
    _check(failures, "price-changes", r.json(), [
        "summary.0.n_changed", "summary.0.avg_pct_change", "summary.0.pct_reduced", "city_compare"])

    r = client.get("/api/analysis/trend-all")
    assert r.status_code == 200
    if r.json():
        _check(failures, "trend-all", r.json(), [
            "0.city", "0.snapshot_date", "0.avg_unit_price", "0.mom_pct", "0.n_listings"])

    r = client.get("/api/analysis/districts-all")
    assert r.status_code == 200
    if r.json():
        _check(failures, "districts-all", r.json(),
               ["0.city", "0.district", "0.avg_unit_price", "0.n_listings"])

    r = client.get("/api/analysis/district-trend")
    assert r.status_code == 200
    if r.json():
        _check(failures, "district-trend", r.json(), [
            "0.district", "0.snapshot_date", "0.avg_unit_price", "0.n_listings"])

    r = client.get("/api/analysis/errors")
    if r.status_code == 200:  # 微型夹具无误差报告文件时 404,属既有设计
        _check(failures, "errors", r.json(), [
            "overall.within_10pct", "overall.interval_coverage_80",
            "by_price_band.0.price_band", "by_price_band.0.mae",
            "by_district.0.district", "by_district.0.mae"])

    r = client.get("/api/features/importance")
    if r.status_code == 200 and (not isinstance(r.json(), dict) or not r.json()):
        failures.append("importance: 应为非空 dict")

    r = client.get("/api/predictions/stats")
    assert r.status_code == 200
    _need(r.json(), "n_total", "predictions/stats", failures)

    payload = {
        "district": "朝阳", "bizcircle": None, "rooms": 2, "halls": 1,
        "area_sqm": 80.0, "build_year": 2005, "floor_pos": "中楼层",
        "total_floors": 18, "dir_main": "南", "renovation": "精装",
    }
    r = client.post("/api/predict", json=payload)
    assert r.status_code == 200
    _check(failures, "predict", r.json(), [
        "unit_price.p10", "unit_price.p50", "unit_price.p90", "total_price_wan.p50",
        "interval_width_pct", "comparables.district.district", "comparables.district.avg_price",
        "similar.0.community", "similar.0.unit_price", "attribution.baseline_p50",
        "attribution.factors.0.name", "attribution.factors.0.delta", "model_version"])

    assert not failures, "前端消费字段缺失:" + "; ".join(failures)
