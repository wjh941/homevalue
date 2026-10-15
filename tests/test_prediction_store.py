"""PredictionStore 单测:SQLite 追加、SQL 聚合统计与旧 JSONL 导入。"""

from __future__ import annotations

import json

from homevalue.prediction_store import PredictionStore


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


def test_empty_store_stats(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    assert store.stats() == {"n_total": 0}
    store.close()


def test_append_and_stats_aggregates(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    for args in [
        ("2026-01-01T00:00:00+00:00", "朝阳", 60_000.0, 20.0),
        ("2026-01-02T00:00:00+00:00", "朝阳", 62_000.0, 22.0),
        ("2026-01-03T00:00:00+00:00", "海淀", 50_000.0, None),
    ]:
        store.append(_entry(*args))

    s = store.stats()
    assert s["n_total"] == 3
    assert s["avg_p50"] == round((60_000 + 62_000 + 50_000) / 3)
    assert s["median_p50"] == 60_000  # 奇数条取中位
    assert s["avg_interval_width_pct"] == 21.0  # NULL 不计入均值
    assert s["top_districts"] == [{"district": "朝阳", "n": 2}, {"district": "海淀", "n": 1}]
    assert s["last_ts"] == "2026-01-03T00:00:00+00:00"
    store.close()


def test_even_count_median_takes_upper_middle(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    store.append(_entry("t1", "朝阳", 10.0))
    store.append(_entry("t2", "朝阳", 20.0))
    # 偶数条:OFFSET COUNT/2 取上中位(与旧 JSONL 实现 sorted[len//2] 口径一致)
    assert store.stats()["median_p50"] == 20.0
    store.close()


def test_import_jsonl_once_and_rename(tmp_path):
    legacy = tmp_path / "predictions_log.jsonl"
    legacy.write_text(
        "\n".join(
            [json.dumps(_entry("2025-12-01T00:00:00+00:00", "西城", 70_000.0, 18.0)), "{not json"]
        ),
        encoding="utf-8",
    )

    store = PredictionStore(tmp_path / "predictions.db")
    imported = store.import_jsonl(legacy)

    assert imported == 1
    assert store.stats()["n_total"] == 1
    assert not legacy.exists()
    assert legacy.with_suffix(".jsonl.imported").exists()
    # 幂等:原文件已改名,再导入为 0
    assert store.import_jsonl(legacy) == 0
    store.close()
