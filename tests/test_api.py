"""API 集成测试:健康检查、预测、分析接口、错误处理。"""

from __future__ import annotations


def test_health(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["data_backend"] == "sqlite"
    assert "holdout" in body


def test_predict_valid(api_client):
    payload = {
        "district": "朝阳",
        "bizcircle": "望京",
        "rooms": 2,
        "halls": 1,
        "area_sqm": 80.0,
        "build_year": 2005,
        "floor_pos": "中楼层",
        "total_floors": 18,
        "dir_main": "南",
        "renovation": "精装",
    }
    r = api_client.post("/api/predict", json=payload)
    assert r.status_code == 200
    body = r.json()
    p = body["unit_price"]
    assert 0 < p["p10"] <= p["p50"] <= p["p90"]
    assert body["total_price_wan"]["p50"] == round(p["p50"] * 80.0 / 1e4, 1)
    assert "comparables" in body


def test_predict_monotonic_quantiles_for_edge_input(api_client):
    payload = {
        "district": "西城",
        "rooms": 3,
        "halls": 2,
        "area_sqm": 140.0,
        "build_year": 1995,
        "floor_pos": "顶层",
        "dir_main": "南",
        "renovation": "毛坯",
    }
    r = api_client.post("/api/predict", json=payload)
    assert r.status_code == 200
    p = r.json()["unit_price"]
    assert p["p10"] <= p["p50"] <= p["p90"]


def test_predict_validates_input(api_client):
    bad = {"district": "朝阳", "rooms": 2, "halls": 1, "area_sqm": 0}
    assert api_client.post("/api/predict", json=bad).status_code == 422
    bad2 = {"district": "朝阳", "rooms": 2, "halls": 1, "area_sqm": 50.0, "build_year": 1600}
    assert api_client.post("/api/predict", json=bad2).status_code == 422


def test_overview_from_db(api_client):
    r = api_client.get("/api/analysis/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["n_listings"] > 0
    assert len(body["districts_all"]) > 0


def test_trend_and_deciles(api_client):
    assert api_client.get("/api/analysis/trend").status_code == 200
    deciles = api_client.get("/api/analysis/deciles").json()
    assert len(deciles) == 10


def test_errors_endpoint_404_without_report(api_client):
    assert api_client.get("/api/analysis/errors").status_code == 404


def test_static_dashboard_served(api_client):
    r = api_client.get("/")
    assert r.status_code == 200
    assert "HomeValue" in r.text


def test_predict_includes_similar_and_stats(api_client):
    payload = {
        "district": "朝阳",
        "bizcircle": "望京",
        "rooms": 2,
        "halls": 1,
        "area_sqm": 80.0,
        "build_year": 2005,
    }
    body = api_client.post("/api/predict", json=payload).json()
    assert isinstance(body.get("similar"), list)

    s = api_client.get("/api/similar", params={"district": "朝阳", "area_sqm": 80.0})
    assert s.status_code == 200
    assert isinstance(s.json(), list)

    stats = api_client.get("/api/predictions/stats").json()
    assert stats["n_total"] >= 1
    assert stats["top_districts"][0]["district"] == "朝阳"
    assert stats["avg_p50"] is not None
