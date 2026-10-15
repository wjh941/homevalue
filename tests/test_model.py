"""预测层单元测试:分位单调性、CQR 校准分支与非负下界。

conftest 的微型产物 metadata 不带 conformal 键,因此 CQR 分支
(model.predict_quantiles 的线上校准路径)此前没有任何测试走过——
这里复制一份产物并注入大幅校准值,专门验证该分支。
"""

from __future__ import annotations

import json
import shutil

import pytest

from homevalue.db import get_engine, read_query
from homevalue.model import load_artifacts, predict_quantiles


@pytest.fixture(scope="module")
def conformal_artifacts(micro_artifacts):
    """复制微型模型产物并注入 conformal 校准(q_lo_adj 足够大,可击穿任何正单价)。"""
    art_copy = micro_artifacts.parent / "models_conformal"
    if art_copy.exists():
        shutil.rmtree(art_copy)
    shutil.copytree(micro_artifacts, art_copy)
    meta_path = art_copy / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["conformal"] = {"q_lo_adj": 1_000_000.0, "q_hi_adj": 2_000.0}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return art_copy


def test_predict_quantiles_monotonic_without_conformal(micro_artifacts, tiny_db):
    """无 conformal:p10 <= p50 <= p90。"""
    engine = get_engine(tiny_db)
    df = read_query(engine, "SELECT * FROM listings WHERE city = 'bj' LIMIT 20")
    out = predict_quantiles(load_artifacts(micro_artifacts), df)
    assert (out["p10"] <= out["p50"]).all()
    assert (out["p50"] <= out["p90"]).all()
    assert (out["p10"] >= 0).all()


def test_conformal_calibration_keeps_lower_bound_non_negative(conformal_artifacts, micro_artifacts, tiny_db):
    """CQR 校准外扩后:p10 被钳到 0 以上,分位仍单调。

    q_lo_adj = 1e6 意味着不设防时 p10 必为大幅负数——该断言直接锁定
    "低价房源不得返回负下界单价"的行为。
    """
    engine = get_engine(tiny_db)
    df = read_query(engine, "SELECT * FROM listings WHERE city = 'bj' LIMIT 20")
    out = predict_quantiles(load_artifacts(conformal_artifacts), df)
    assert (out["p10"] >= 0).all(), "conformal 校准后 p10 出现负值"
    assert (out["p10"] <= out["p50"]).all()
    assert (out["p50"] <= out["p90"]).all()
    # 上界确实被外扩了(q_hi_adj=2000),对照无校准产物验证钳位没有吞掉校准
    plain = predict_quantiles(load_artifacts(micro_artifacts), df)
    assert (out["p90"] >= plain["p90"]).all()
