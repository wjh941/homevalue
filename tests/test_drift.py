"""漂移监控:多类别卡方、台账 MAE 序列、PredictionStore.drift_summary、/api/drift/summary。"""

from __future__ import annotations

import json
import math
from statistics import NormalDist

import pytest

from homevalue.ab import chi2_sf, chi_square_gof, srm_chi_square
from homevalue.metrics_log import read_mae_history
from homevalue.prediction_store import PredictionStore


def _sf_odd_df_closed_form(x: float, dof: int) -> float:
    """奇数自由度卡方右尾概率的解析式(教科书恒等式),作 chi2_sf 的独立参照。

    sf(x, 2k+1) = 2(1-Phi(sqrt(x))) + sqrt(2x/pi) e^{-x/2} * sum_j x^j/(1*3*...*(2j+1))
    """
    assert dof % 2 == 1
    nd = NormalDist()
    head = 2 * (1 - nd.cdf(math.sqrt(x)))
    tail_coef, series = math.sqrt(2 * x / math.pi) * math.exp(-x / 2), 0.0
    term = 1.0
    for j in range(dof // 2):
        series += term
        term *= x / (2 * j + 3)
    return head + tail_coef * series


# ---------------- 卡方拟合优度(多类别) ----------------


def test_chi_square_gof_exact_chi2_and_p_value():
    # 期望 10/类,观测 [12,8,10,10,14,6]:偏差平方和 40/10 -> chi2=4.0,自由度 5
    r = chi_square_gof([12, 8, 10, 10, 14, 6], [10] * 6)
    assert r.chi2 == pytest.approx(4.0, abs=1e-12)
    assert r.dof == 5
    assert r.n_observed == 60 and r.n_categories == 6
    assert 0.5 < r.p_value < 0.6
    assert not r.significant
    assert r.observed == (12.0, 8.0, 10.0, 10.0, 14.0, 6.0)
    assert r.expected == pytest.approx((10.0,) * 6)


def test_chi_square_p_matches_odd_df_closed_form():
    # 级数/连分式实现的 p 值对照奇数自由度解析式(独立恒等式,浮点 1e-9 内一致)
    for x, dof in [(4.0, 5), (30.0, 5), (2.0, 1), (7.815, 3), (0.5, 1)]:
        assert chi2_sf(x, dof) == pytest.approx(_sf_odd_df_closed_form(x, dof), rel=1e-9, abs=1e-12)


def test_chi_square_even_df_exact_value():
    # 自由度 2 有精确解:右尾 = e^{-x/2}
    assert chi2_sf(6.0, 2) == pytest.approx(math.exp(-3.0), rel=1e-12)
    assert chi2_sf(0.0, 2) == 1.0


def test_chi_square_df1_matches_srm():
    # 两类别情形必须与 srm_chi_square 完全一致(自由度 1 闭式 2(1-Phi(sqrt(chi2))))
    for a, b in [(450, 550), (486, 514), (0, 100)]:
        gof = chi_square_gof([a, b], [50, 50])
        srm = srm_chi_square(a, b)
        assert gof.chi2 == pytest.approx(srm.chi2, rel=1e-12)
        assert gof.p_value == pytest.approx(srm.p_value, rel=1e-9)


def test_chi_square_accepts_share_weights():
    # expected 传占比(均匀 1/6)与传等额计数同分布,结果一致
    counts = chi_square_gof([12, 8, 10, 10, 14, 6], [10] * 6)
    shares = chi_square_gof([12, 8, 10, 10, 14, 6], [1 / 6] * 6)
    assert shares.chi2 == pytest.approx(counts.chi2, rel=1e-12)
    assert shares.expected == pytest.approx(counts.expected)
    # 非均匀占比:80/20 的期望下 60/40 实现显著偏移
    r = chi_square_gof([600, 400], [0.8, 0.2])
    assert r.significant and r.p_value < 0.01


def test_chi_square_flags_shift():
    # 朝阳过度涌入(观测 50/50 -> 90/10):chi2 大、p 极小
    r = chi_square_gof([90, 10], [50, 50])
    assert r.chi2 == pytest.approx(64.0, rel=1e-12)
    assert r.significant and r.p_value < 1e-10
    # alpha 收紧到 0.001 仍报警;放宽到 0.3 时温和偏移也触发
    assert chi_square_gof([90, 10], [50, 50], alpha=0.001).significant


def test_chi_square_validates_input():
    with pytest.raises(ValueError):
        chi_square_gof([1, 2, 3], [1, 2])  # 等长
    with pytest.raises(ValueError):
        chi_square_gof([5], [5])  # 至少 2 个类别
    with pytest.raises(ValueError):
        chi_square_gof([0, 0], [5, 5])  # 观测合计 > 0
    with pytest.raises(ValueError):
        chi_square_gof([1, 1], [0, 0])  # 期望合计 > 0
    with pytest.raises(ValueError):
        chi_square_gof([10, 5], [3, 0])  # 单类别期望计数 > 0


# ---------------- 实验台账 MAE 序列 ----------------


def test_mae_history_parses_and_skips_bad_rows(tmp_path):
    log = tmp_path / "metrics_log.jsonl"
    rows = [
        {"exp_id": "e1", "ts": "2026-09-24T06:57:05+00:00", "holdout_mae": 5743.0},
        {"exp_id": "bad"},
        {"exp_id": "e2", "ts": "2026-10-03T08:55:46+00:00", "holdout_mae": 5769.0},
    ]
    # 带 BOM 的文件(Windows 产物常见)首行也必须能解析
    log.write_text(
        "\ufeff"
        + json.dumps(rows[0]) + "\n{not json\n" + json.dumps(rows[1]) + "\n" + json.dumps(rows[2]) + "\n",
        encoding="utf-8",
    )
    hist = read_mae_history(log)
    assert hist == [
        {"ts": "2026-09-24T06:57:05+00:00", "exp_id": "e1", "mae": 5743.0},
        {"ts": "2026-10-03T08:55:46+00:00", "exp_id": "e2", "mae": 5769.0},
    ]


def test_mae_history_missing_file_empty(tmp_path):
    assert read_mae_history(tmp_path / "none.jsonl") == []


# ---------------- PredictionStore.drift_summary ----------------


def _entry(ts: str, district: str, p50: float, width: float | None = None) -> dict:
    return {
        "ts": ts,
        "district": district,
        "bizcircle": None,
        "community": None,
        "area_sqm": 80.0,
        "rooms": 2,
        "p50": p50,
        "interval_width_pct": width,
        "model_version": "1.1.0",
    }


def test_drift_summary_empty_store(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    assert store.drift_summary() == {"n_total": 0, "predictions_by_day": [], "district_mix": []}
    store.close()


def test_drift_summary_aggregates_by_day(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    for args in [
        ("2026-01-01T10:00:00+00:00", "朝阳", 60_000.0, 20.0),
        ("2026-01-01T11:00:00+00:00", "朝阳", 62_000.0, 22.0),
        ("2026-01-02T09:00:00+00:00", "海淀", 50_000.0),
    ]:
        store.append(_entry(*args))

    d = store.drift_summary()
    assert d["n_total"] == 3
    assert d["predictions_by_day"] == [
        {"day": "2026-01-01", "n": 2, "avg_p50": 61_000, "avg_interval_width_pct": 21.0},
        {"day": "2026-01-02", "n": 1, "avg_p50": 50_000, "avg_interval_width_pct": None},
    ]
    assert d["district_mix"] == [{"district": "朝阳", "n": 2}, {"district": "海淀", "n": 1}]
    store.close()


# ---------------- /api/drift/summary ----------------


def test_api_drift_summary_empty_structure(api_client):
    r = api_client.get("/api/drift/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_predictions"] == 0
    assert body["predictions_by_day"] == []
    assert body["district_mix"] == []
    assert body["mae_history"] == []
    # 训练集分布来自微型数仓,卡方在无预测数据时不计算,但结构完整且 n=0
    shift = body["district_shift"]
    assert shift["n_pred"] == 0
    assert shift["chi2"] is None and shift["p_value"] is None
    assert shift["significant"] is False
    assert shift["n_train"] > 0
    assert body["train_mix"]


def test_api_drift_summary_after_predict(api_client, tmp_path):
    (tmp_path / "metrics_log.jsonl").write_text(
        json.dumps({"exp_id": "e1", "ts": "2026-09-24T06:57:05+00:00", "holdout_mae": 5743.0})
        + "\n"
        + json.dumps({"exp_id": "e2", "ts": "2026-10-03T08:55:46+00:00", "holdout_mae": 5769.0})
        + "\n",
        encoding="utf-8",
    )
    payload = {"district": "朝阳", "rooms": 2, "halls": 1, "area_sqm": 80.0}
    assert api_client.post("/api/predict", json=payload).status_code == 200

    body = api_client.get("/api/drift/summary").json()
    assert body["n_predictions"] == 1
    assert len(body["predictions_by_day"]) == 1
    day = body["predictions_by_day"][0]
    assert day["n"] == 1 and len(day["day"]) == 10 and day["avg_p50"] > 0
    assert {"district": "朝阳", "n": 1} in body["district_mix"]

    shift = body["district_shift"]
    assert shift["n_pred"] == 1 and shift["n_train"] > 0
    assert shift["chi2"] >= 0 and 0 <= shift["p_value"] <= 1
    assert shift["dof"] == len(shift["categories"]) - 1
    assert isinstance(shift["significant"], bool)
    assert len(shift["observed"]) == len(shift["categories"]) == len(shift["train_share"])

    assert [h["exp_id"] for h in body["mae_history"]] == ["e1", "e2"]
    assert body["mae_history"][0]["mae"] == 5743.0
