"""模型产物加载与预测(服务层与压测脚本共用)。"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .features import apply_target_maps, attach_derived, build_feature_frame


def load_artifacts(artifacts_dir: Path | str) -> dict:
    d = Path(artifacts_dir)
    required = ["main.joblib", "q10.joblib", "q90.joblib", "metadata.json"]
    missing = [f for f in required if not (d / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"缺少模型产物: {missing}(先运行 python scripts/train.py --model lgbm --full-features)"
        )
    metadata = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    te_maps = joblib.load(d / "te_maps.joblib") if metadata.get("te") else None
    return {
        "main": joblib.load(d / "main.joblib"),
        "q10": joblib.load(d / "q10.joblib"),
        "q90": joblib.load(d / "q90.joblib"),
        "metadata": metadata,
        "cat_maps": metadata["cat_maps"],
        "te_maps": te_maps,
    }


def predict_quantiles(art: dict, df: pd.DataFrame) -> dict[str, np.ndarray]:
    """返回原尺度(元/平米)的 p10 / p50 / p90 预测,并保证分位单调。"""
    feats = attach_derived(df)
    X = build_feature_frame(feats, art["cat_maps"])
    if art.get("te_maps") is not None:
        te = apply_target_maps(feats, art["te_maps"])
        for col in te.columns:
            X[col] = te[col].to_numpy()
    # 训练时可能只用了特征子集(如无 build_year 的基线),预测按同列序裁剪
    X = X[art["metadata"]["feature_cols"]]
    p50 = np.maximum(np.expm1(art["main"].predict(X)), 0.0)
    p10 = np.minimum(np.expm1(art["q10"].predict(X)), p50)
    p90 = np.maximum(np.expm1(art["q90"].predict(X)), p50)
    return {"p10": p10, "p50": p50, "p90": p90}
