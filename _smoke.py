"""全接口冒烟:断言前端消费的每个字段都存在。用后即删。"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8123"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
failures = []


def get(path):
    try:
        return json.loads(opener.open(BASE + path, timeout=60).read())
    except Exception as e:
        failures.append("GET " + path + " -> " + str(e))
        return {}


def need(obj, path, label):
    cur = obj
    for key in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                failures.append(label + ": 缺少 " + path)
                return
            continue
        if not isinstance(cur, dict) or key not in cur:
            failures.append(label + ": 缺少 " + path)
            return
        cur = cur[key]


h = get("/api/health")
need(h, "holdout.mae", "health")
need(h, "holdout.mape_pct", "health")
need(h, "holdout.r2", "health")
need(h, "data_freshness.last_snapshot", "health")
need(h, "data_backend", "health")
print("exp:", h.get("exp_id"), "| backend:", h.get("data_backend"))

ov = get("/api/analysis/overview")
need(ov, "n_listings", "overview")
need(ov, "districts_all.0.district", "overview")
need(ov, "districts_all.0.avg_unit_price", "overview")
need(ov, "districts_all.0.n_listings", "overview")
need(ov, "top20_value_share", "overview")

dec = get("/api/analysis/deciles")
if isinstance(dec, list) and dec:
    for k in ("decile", "price_min", "price_max", "avg_unit_price", "avg_area", "n_listings"):
        need(dec[0], k, "deciles")
else:
    failures.append("deciles 非数组或为空")

ch = get("/api/analysis/price-changes")
need(ch, "summary.0.n_changed", "price-changes")
need(ch, "summary.0.avg_pct_change", "price-changes")
need(ch, "summary.0.pct_reduced", "price-changes")
need(ch, "city_compare.0.city", "price-changes")
need(ch, "city_compare.0.rank_by_price", "price-changes")

ta = get("/api/analysis/trend-all")
if isinstance(ta, list) and ta:
    for k in ("city", "snapshot_date", "avg_unit_price", "mom_pct", "n_listings"):
        need(ta[0], k, "trend-all")
    bj = [r for r in ta if r["city"] == "bj"]
    partial = [r.get("n_listings") for r in bj if str(r["snapshot_date"]).startswith("2024-09")]
    print("trend-all bj rows:", len(bj), "| 2024-09 n_listings:", partial)
else:
    failures.append("trend-all 非数组或为空")

da = get("/api/analysis/districts-all")
if isinstance(da, list) and da:
    for k in ("city", "district", "avg_unit_price", "n_listings"):
        need(da[0], k, "districts-all")
else:
    failures.append("districts-all 非数组或为空")

dt = get("/api/analysis/district-trend")
if isinstance(dt, list) and dt:
    for k in ("district", "snapshot_date", "avg_unit_price"):
        need(dt[0], k, "district-trend")
    print("district-trend rows:", len(dt), "keys:", sorted(dt[0].keys()))
else:
    failures.append("district-trend 非数组或为空")

er = get("/api/analysis/errors")
need(er, "overall.within_10pct", "errors")
need(er, "overall.interval_coverage_80", "errors")
need(er, "by_price_band.0.price_band", "errors")
need(er, "by_price_band.0.mae", "errors")
need(er, "by_district.0.district", "errors")
need(er, "by_district.0.mae", "errors")

im = get("/api/features/importance")
if not isinstance(im, dict) or not im:
    failures.append("importance 应为非空 dict")

st = get("/api/predictions/stats")
for k in ("n_total", "avg_p50", "avg_interval_width_pct", "top_districts"):
    need(st, k, "predictions/stats")

body = {
    "district": "朝阳", "bizcircle": None, "rooms": 2, "halls": 1,
    "area_sqm": 80, "build_year": 2010, "floor_pos": "中楼层",
    "total_floors": 20, "dir_main": "南", "renovation": "精装",
}
req = urllib.request.Request(BASE + "/api/predict", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
pr = json.loads(opener.open(req, timeout=120).read())
need(pr, "unit_price.p10", "predict")
need(pr, "unit_price.p50", "predict")
need(pr, "unit_price.p90", "predict")
need(pr, "total_price_wan.p50", "predict")
need(pr, "interval_width_pct", "predict")
need(pr, "comparables.district.district", "predict")
need(pr, "comparables.district.avg_price", "predict")
need(pr, "similar.0.community", "predict")
need(pr, "similar.0.unit_price", "predict")
need(pr, "attribution.baseline_p50", "predict")
need(pr, "attribution.factors.0.name", "predict")
need(pr, "attribution.factors.0.delta", "predict")
need(pr, "model_version", "predict")

for label, bad in [
    ("area=3", dict(body, area_sqm=3)),
    ("year=1800", dict(body, build_year=1800)),
    ("bad-district", dict(body, district="火星")),
]:
    req2 = urllib.request.Request(BASE + "/api/predict", data=json.dumps(bad).encode(),
                                  headers={"Content-Type": "application/json"})
    try:
        opener.open(req2, timeout=120)
        failures.append("边界 " + label + ": 应拒绝却 200")
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            failures.append("边界 " + label + ": 状态 " + str(e.code))
    except Exception as e:
        failures.append("边界 " + label + ": " + str(e))

print("ALL SMOKE CHECKS PASSED" if not failures else "FAILURES:")
for f in failures:
    print("- " + f)
