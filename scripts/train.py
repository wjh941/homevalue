"""训练入口:baseline 线性回归 -> LightGBM -> 调参,统一 5 折 CV + 留出集评估。

每次运行追加一行到 reports/metrics_log.jsonl(实验台账)。

用法:
    python scripts/train.py --model linear --exp-id exp001
    python scripts/train.py --model lgbm   --exp-id exp002
    python scripts/train.py --model lgbm   --exp-id exp003 --full-features
    python scripts/train.py --model lgbm   --exp-id exp004 --full-features --tune
    python scripts/train.py --model lgbm   --exp-id exp005 --full-features --community-te
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.config import (  # noqa: E402
    AGE_REF_YEAR,
    ARTIFACTS_DIR,
    DB_PATH,
    MODEL_CITY,
    MODEL_VERSION,
    REPORTS_DIR,
)
from homevalue.db import get_engine, read_query  # noqa: E402
from homevalue.features import (  # noqa: E402
    CAT_FEATURES,
    TE_SMOOTH_K,
    TE_SOURCE_COLS,
    apply_target_maps,
    build_feature_frame,
    fit_category_maps,
    fit_target_maps,
)

# 特征子集定义
NUM_CORE = [
    "area_sqm", "rooms", "halls", "halls_per_room", "total_floors",
    "floor_ordinal", "building_age", "age_missing",
    "dir_south", "dir_north", "dir_east", "dir_west", "dir_count",
]
CAT_CORE = ["district", "renovation"]          # 基础特征集(不含商圈)
CAT_FULL = CAT_FEATURES                        # 完整特征集(含商圈)

LGBM_BASE_PARAMS = dict(
    objective="regression",
    n_estimators=600,
    learning_rate=0.05,
    num_leaves=63,
    subsample=0.9,
    colsample_bytree=0.9,
    min_child_samples=40,
    random_state=42,
    n_jobs=-1,
    verbose=-1,
)
LGBM_GRID = {
    "num_leaves": [31, 63, 127],
    "learning_rate": [0.05, 0.03],
    "min_child_samples": [40, 80],
}


# ---------------------------------------------------------------------------
# 数据与指标
# ---------------------------------------------------------------------------


def load_data(db_path: Path) -> pd.DataFrame:
    engine = get_engine(db_path)
    df = read_query(
        engine,
        f"SELECT * FROM listings WHERE city = '{MODEL_CITY}' AND unit_price IS NOT NULL",
    )
    df["bizcircle"] = df["bizcircle"].fillna("未知")
    return df


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_pred - y_true
    abs_err = np.abs(err)
    return {
        "mae": float(abs_err.mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "mape_pct": float((abs_err / y_true).mean() * 100),
        "r2": float(1 - (err**2).sum() / ((y_true - y_true.mean()) ** 2).sum()),
        "median_ae": float(np.median(abs_err)),
    }


# ---------------------------------------------------------------------------
# 模型构建
# ---------------------------------------------------------------------------


def make_linear(feature_cols_numeric: list[str], feature_cols_cat: list[str]) -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", SimpleImputer(strategy="median"), feature_cols_numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore"), feature_cols_cat),
        ]
    )
    return Pipeline([("pre", pre), ("reg", LinearRegression())])


def make_lgbm(params: dict | None = None) -> LGBMRegressor:
    p = dict(LGBM_BASE_PARAMS)
    if params:
        p.update(params)
    return LGBMRegressor(**p)


def feature_sets(full: bool) -> tuple[list[str], list[str]]:
    """返回 (numeric_cols, cat_cols)。"""
    return list(NUM_CORE), (CAT_FULL if full else CAT_CORE)


# ---------------------------------------------------------------------------
# 评估流程
# ---------------------------------------------------------------------------


def prepare_xy(df: pd.DataFrame, full: bool):
    numeric, cats = feature_sets(full)
    cat_maps = fit_category_maps(df, min_count=30)
    X_all = build_feature_frame(df, cat_maps)  # 低频类别折叠为 __other__,训练/线上口径一致
    cols = numeric + cats
    X = X_all[cols].copy()
    for c in cats:
        X[c] = X[c].astype("category")
    y_log = np.log1p(df["unit_price"].to_numpy())
    y_raw = df["unit_price"].to_numpy()
    return X, y_log, y_raw, cols, cat_maps


def cv_evaluate(model_factory, X: pd.DataFrame, y_log: np.ndarray, y_raw: np.ndarray,
                folds: int = 5) -> dict[str, float]:
    """在训练集上做 K 折 CV,指标换算回原尺度(元/平米)。"""
    kf = KFold(n_splits=folds, shuffle=True, random_state=42)
    per_fold = []
    for tr_idx, va_idx in kf.split(X):
        m = model_factory()
        m.fit(X.iloc[tr_idx], y_log[tr_idx])
        pred = np.expm1(m.predict(X.iloc[va_idx]))
        per_fold.append(metrics(y_raw[va_idx], pred))
    agg = {}
    for k in per_fold[0]:
        vals = [f[k] for f in per_fold]
        agg[k] = float(np.mean(vals))
        agg[k + "_std"] = float(np.std(vals))
    return agg


def tune_lgbm(X: pd.DataFrame, y_log: np.ndarray, y_raw: np.ndarray) -> dict:
    """3 折 CV 网格搜索,返回最优参数。"""
    keys = list(LGBM_GRID)
    best = (None, float("inf"))
    for combo in itertools.product(*[LGBM_GRID[k] for k in keys]):
        params = dict(zip(keys, combo, strict=True))
        kf = KFold(n_splits=3, shuffle=True, random_state=42)
        maes = []
        for tr_idx, va_idx in kf.split(X):
            m = make_lgbm(params)
            m.fit(X.iloc[tr_idx], y_log[tr_idx])
            pred = np.expm1(m.predict(X.iloc[va_idx]))
            maes.append(np.abs(pred - y_raw[va_idx]).mean())
        mean_mae = float(np.mean(maes))
        print(f"    {params} -> CV MAE {mean_mae:,.0f}")
        if mean_mae < best[1]:
            best = (params, mean_mae)
    print(f"  最优参数: {best[0]} (CV MAE {best[1]:,.0f})")
    return best[0] or {}


def coverage(y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(((y_true >= lo) & (y_true <= hi)).mean())


# ---------------------------------------------------------------------------
# TE 路径:小区/商圈目标编码
# ---------------------------------------------------------------------------

TE_PARAMS = dict(num_leaves=127, learning_rate=0.05, min_child_samples=40)


def build_X_te(df_part: pd.DataFrame, te_maps: dict, cat_maps: dict) -> pd.DataFrame:
    """基础特征 + TE 特征,列序固定。"""
    X = build_feature_frame(df_part, cat_maps)
    te = apply_target_maps(df_part, te_maps)
    for col in te.columns:
        X[col] = te[col].to_numpy()
    for c in CAT_FEATURES:
        X[c] = X[c].astype("category")
    return X


def cv_evaluate_te(df_train: pd.DataFrame, cat_maps: dict, folds: int = 5) -> dict:
    """折内拟合 TE 的 5 折 CV(防泄漏)。"""
    kf = KFold(n_splits=folds, shuffle=True, random_state=42)
    y_all = df_train["unit_price"].to_numpy()
    per_fold = []
    for tr_idx, va_idx in kf.split(df_train):
        te_maps = fit_target_maps(df_train.iloc[tr_idx])
        X_tr = build_X_te(df_train.iloc[tr_idx], te_maps, cat_maps)
        X_va = build_X_te(df_train.iloc[va_idx], te_maps, cat_maps)
        m = make_lgbm(TE_PARAMS)
        m.fit(X_tr, np.log1p(y_all[tr_idx]))
        pred = np.expm1(m.predict(X_va))
        per_fold.append(metrics(y_all[va_idx], pred))
    agg = {}
    for k in per_fold[0]:
        vals = [f[k] for f in per_fold]
        agg[k] = float(np.mean(vals))
        agg[k + "_std"] = float(np.std(vals))
    return agg


def run_te_pipeline(args, df: pd.DataFrame, t0: float) -> int:
    """--community-te:TE 特征训练(参数沿用 exp004 网格最优),保存完整产物。"""
    rng = np.random.default_rng(42)
    test_mask = rng.random(len(df)) < 0.2
    tr_df = df[~test_mask].reset_index(drop=True)
    hold_df = df[test_mask].reset_index(drop=True)
    y_log_tr = np.log1p(tr_df["unit_price"].to_numpy())
    y_raw_hold = hold_df["unit_price"].to_numpy()
    print(f"训练 {len(tr_df):,} / 测试 {len(hold_df):,}(TE 源列: {TE_SOURCE_COLS}, k={TE_SMOOTH_K})")

    cat_maps = fit_category_maps(tr_df, min_count=30)
    print("5 折交叉验证(折内拟合 TE)...")
    cv = cv_evaluate_te(tr_df, cat_maps)
    print("  " + "  ".join(f"{k}={cv[k]:,.4f}" for k in ("mae", "rmse", "mape_pct", "r2")))

    te_maps = fit_target_maps(tr_df)
    X_tr = build_X_te(tr_df, te_maps, cat_maps)
    X_hold = build_X_te(hold_df, te_maps, cat_maps)
    model = make_lgbm(TE_PARAMS)
    model.fit(X_tr, y_log_tr)
    pred_hold = np.expm1(model.predict(X_hold))
    holdout = metrics(y_raw_hold, pred_hold)
    print("留出集: " + "  ".join(f"{k}={holdout[k]:,.4f}" for k in ("mae", "rmse", "mape_pct", "r2")))

    print("训练分位数模型 p10/p90 ...")
    q10 = make_lgbm({**TE_PARAMS, "objective": "quantile", "alpha": 0.1, "n_estimators": 400})
    q90 = make_lgbm({**TE_PARAMS, "objective": "quantile", "alpha": 0.9, "n_estimators": 400})
    q10.fit(X_tr, y_log_tr)
    q90.fit(X_tr, y_log_tr)
    lo = np.minimum(np.expm1(q10.predict(X_hold)), pred_hold)
    hi = np.maximum(np.expm1(q90.predict(X_hold)), pred_hold)
    q_result = {"interval_coverage_80": coverage(y_raw_hold, lo, hi)}
    print(f"  80% 区间覆盖率(留出集): {q_result['interval_coverage_80']:.1%}")

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    joblib.dump(model, ARTIFACTS_DIR / "main.joblib")
    joblib.dump(q10, ARTIFACTS_DIR / "q10.joblib")
    joblib.dump(q90, ARTIFACTS_DIR / "q90.joblib")
    joblib.dump(te_maps, ARTIFACTS_DIR / "te_maps.joblib")

    gain = model.booster_.feature_importance(importance_type="gain")
    names = model.booster_.feature_name()
    order = np.argsort(gain)[::-1]
    feature_importance = {names[i]: float(gain[i]) for i in order}
    total = sum(feature_importance.values()) or 1.0
    feature_importance = {k: round(v / total, 4) for k, v in feature_importance.items()}
    (ARTIFACTS_DIR / "feature_importance.json").write_text(
        json.dumps(feature_importance, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata = {
        "model_version": MODEL_VERSION,
        "exp_id": args.exp_id,
        "model": args.model,
        "params": TE_PARAMS,
        "feature_cols": list(X_tr.columns),
        "cat_maps": cat_maps,
        "te": {"cols": TE_SOURCE_COLS, "k": TE_SMOOTH_K},
        "cv": cv,
        "holdout": holdout,
        "quantiles": q_result,
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_hold)),
        "age_ref_year": AGE_REF_YEAR,
        "trained_at": datetime.now(UTC).isoformat(),
        "train_seconds": round(time.time() - t0, 1),
    }
    (ARTIFACTS_DIR / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"产物已保存 -> {ARTIFACTS_DIR}")

    pred_df = pd.DataFrame(
        {"hhid": df["hhid"].to_numpy()[test_mask], "y_true": y_raw_hold, "y_pred": pred_hold,
         "p10": lo, "p90": hi}
    )
    pred_df.to_csv(REPORTS_DIR / "holdout_predictions.csv", index=False)

    record = {
        "exp_id": args.exp_id,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "features": "full+te",
        "n_features": int(X_tr.shape[1]),
        "params": TE_PARAMS,
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_hold)),
        "cv_mae": round(cv["mae"], 0),
        "cv_mae_std": round(cv["mae_std"], 0),
        "cv_mape_pct": round(cv["mape_pct"], 2),
        "cv_r2": round(cv["r2"], 4),
        "holdout_mae": round(holdout["mae"], 0),
        "holdout_rmse": round(holdout["rmse"], 0),
        "holdout_mape_pct": round(holdout["mape_pct"], 2),
        "holdout_r2": round(holdout["r2"], 4),
        "interval_coverage_80": round(q_result["interval_coverage_80"], 4),
        "seconds": round(time.time() - t0, 1),
    }
    with (REPORTS_DIR / "metrics_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"实验记录已追加 -> reports/metrics_log.jsonl ({round(time.time() - t0, 1)}s)")
    return 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["linear", "lgbm"], required=True)
    parser.add_argument("--exp-id", required=True)
    parser.add_argument("--full-features", action="store_true", help="加入商圈/装修等全部特征")
    parser.add_argument("--tune", action="store_true", help="LGBM 网格搜索(耗时)")
    parser.add_argument("--community-te", action="store_true",
                        help="小区/商圈目标编码(需 --full-features,参数沿用 exp004 最优)")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--save-artifacts", action="store_true", default=None,
                        help="默认:full-features 时保存到 models/")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)
    t0 = time.time()
    df = load_data(args.db)
    print(f"数据: {len(df):,} 行 (city={MODEL_CITY}), 列={df.shape[1]}")

    if args.community_te:
        if not args.full_features:
            print("错误:--community-te 需要搭配 --full-features")
            return 2
        if args.tune:
            print("提示:TE 路径使用 exp004 网格最优参数,忽略 --tune")
        return run_te_pipeline(args, df, t0)

    X, y_log, y_raw, cols, cat_maps = prepare_xy(df, args.full_features)
    rng = np.random.default_rng(42)
    test_mask = rng.random(len(df)) < 0.2
    X_tr, X_te = X[~test_mask], X[test_mask]
    y_log_tr = y_log[~test_mask]
    y_raw_tr, y_raw_te = y_raw[~test_mask], y_raw[test_mask]
    print(f"训练 {len(X_tr):,} / 测试 {len(X_te):,};特征 {len(cols)} 个")

    if args.model == "linear":
        _, cats = feature_sets(args.full_features)
        factory = lambda: make_linear(NUM_CORE, cats)  # noqa: E731
        params: dict = {}
    else:
        params = {}
        if args.tune:
            print("网格搜索中(3 折 CV)...")
            params = tune_lgbm(X_tr, y_log_tr, y_raw_tr)
        factory = lambda: make_lgbm(params)  # noqa: E731

    print(f"5 折交叉验证({args.model})...")
    cv = cv_evaluate(factory, X_tr, y_log_tr, y_raw_tr)
    print("  " + "  ".join(f"{k}={cv[k]:,.4f}" for k in ("mae", "rmse", "mape_pct", "r2")))

    model = factory()
    model.fit(X_tr, y_log_tr)
    pred_te = np.expm1(model.predict(X_te))
    holdout = metrics(y_raw_te, pred_te)
    print("留出集: " + "  ".join(f"{k}={holdout[k]:,.4f}" for k in ("mae", "rmse", "mape_pct", "r2")))

    # 分位数模型(区间预测),仅在完整特征集时训练
    q_result = None
    if args.full_features:
        print("训练分位数模型 p10/p90 ...")
        q10 = make_lgbm({**params, "objective": "quantile", "alpha": 0.1, "n_estimators": 400})
        q90 = make_lgbm({**params, "objective": "quantile", "alpha": 0.9, "n_estimators": 400})
        q10.fit(X_tr, y_log_tr)
        q90.fit(X_tr, y_log_tr)
        lo = np.minimum(np.expm1(q10.predict(X_te)), pred_te)
        hi = np.maximum(np.expm1(q90.predict(X_te)), pred_te)
        q_result = {"interval_coverage_80": coverage(y_raw_te, lo, hi)}
        print(f"  80% 区间覆盖率(留出集): {q_result['interval_coverage_80']:.1%}")

    save = args.save_artifacts if args.save_artifacts is not None else args.full_features
    if save:
        ARTIFACTS_DIR.mkdir(exist_ok=True)
        joblib.dump(model, ARTIFACTS_DIR / "main.joblib")
        if q_result is not None:
            joblib.dump(q10, ARTIFACTS_DIR / "q10.joblib")
            joblib.dump(q90, ARTIFACTS_DIR / "q90.joblib")
        feature_importance = None
        if args.model == "lgbm":
            gain = model.booster_.feature_importance(importance_type="gain")
            names = model.booster_.feature_name()
            order = np.argsort(gain)[::-1]
            feature_importance = {names[i]: float(gain[i]) for i in order}
            total = sum(feature_importance.values()) or 1.0
            feature_importance = {k: round(v / total, 4) for k, v in feature_importance.items()}
            (ARTIFACTS_DIR / "feature_importance.json").write_text(
                json.dumps(feature_importance, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        metadata = {
            "model_version": MODEL_VERSION,
            "exp_id": args.exp_id,
            "model": args.model,
            "params": params,
            "feature_cols": cols,
            "cat_maps": cat_maps,
            "cv": cv,
            "holdout": holdout,
            "quantiles": q_result,
            "n_train": int(len(X_tr)),
            "n_test": int(len(X_te)),
            "age_ref_year": AGE_REF_YEAR,
            "trained_at": datetime.now(UTC).isoformat(),
            "train_seconds": round(time.time() - t0, 1),
        }
        (ARTIFACTS_DIR / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"产物已保存 -> {ARTIFACTS_DIR}")

    # 留出集预测(供误差分析)
    pred_df = pd.DataFrame(
        {"hhid": df["hhid"].to_numpy()[test_mask], "y_true": y_raw_te, "y_pred": pred_te}
    )
    if q_result is not None:
        pred_df["p10"] = lo
        pred_df["p90"] = hi
    pred_df.to_csv(REPORTS_DIR / "holdout_predictions.csv", index=False)

    # 实验台账
    record = {
        "exp_id": args.exp_id,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "features": "full" if args.full_features else "core",
        "n_features": len(cols),
        "params": params,
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "cv_mae": round(cv["mae"], 0),
        "cv_mae_std": round(cv["mae_std"], 0),
        "cv_mape_pct": round(cv["mape_pct"], 2),
        "cv_r2": round(cv["r2"], 4),
        "holdout_mae": round(holdout["mae"], 0),
        "holdout_rmse": round(holdout["rmse"], 0),
        "holdout_mape_pct": round(holdout["mape_pct"], 2),
        "holdout_r2": round(holdout["r2"], 4),
        "interval_coverage_80": round(q_result["interval_coverage_80"], 4) if q_result else None,
        "seconds": round(time.time() - t0, 1),
    }
    with (REPORTS_DIR / "metrics_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"实验记录已追加 -> reports/metrics_log.jsonl ({round(time.time() - t0, 1)}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
