"""误差分析:按城市/价格段/面积段/房龄段/装修分群看模型误差,找失准模式。

输入: reports/holdout_predictions.csv (train.py 产出)
      SQLite listings 表 (分群维度)
输出: reports/error_analysis.json + reports/*.png

用法:
    python scripts/error_analysis.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from homevalue.config import AGE_REF_YEAR, DB_PATH, MODEL_CITY, REPORTS_DIR  # noqa: E402
from homevalue.db import get_engine, read_query  # noqa: E402

for font in ("Microsoft YaHei", "SimHei"):
    try:
        plt.rcParams["font.family"] = font
        break
    except Exception:  # noqa: BLE001
        continue
plt.rcParams["axes.unicode_minus"] = False

PRICE_BANDS = [
    ("0-3万/㎡", 0, 30_000),
    ("3-5万/㎡", 30_000, 50_000),
    ("5-8万/㎡", 50_000, 80_000),
    ("8-12万/㎡", 80_000, 120_000),
    ("12万+/㎡", 120_000, float("inf")),
]
AREA_BANDS = [("≤50㎡", 0, 50), ("50-90㎡", 50, 90), ("90-140㎡", 90, 140), ("140㎡+", 140, float("inf"))]
AGE_BANDS = [("0-5年", 0, 5), ("5-15年", 5, 15), ("15-25年", 15, 25), ("25年+", 25, 200)]


def band_of(value: float, bands) -> str:
    for name, lo, hi in bands:
        if lo <= value < hi:
            return name
    return "未知"


def segment_errors(preds: pd.DataFrame, key: str) -> list[dict]:
    rows = []
    for seg, g in preds.groupby(key, observed=True):
        if len(g) < 30:
            continue
        err = (g["y_pred"] - g["y_true"]).abs()
        rows.append(
            {
                key: str(seg),
                "n": int(len(g)),
                "mae": round(float(err.mean()), 0),
                "mape_pct": round(float((err / g["y_true"]).mean() * 100), 2),
                "bias": round(float((g["y_pred"] - g["y_true"]).mean()), 0),
                "median_ae": round(float(err.median()), 0),
            }
        )
    return sorted(rows, key=lambda r: -r["mape_pct"])


def main() -> int:
    REPORTS_DIR.mkdir(exist_ok=True)
    preds = pd.read_csv(REPORTS_DIR / "holdout_predictions.csv")

    engine = get_engine(DB_PATH)
    listings = read_query(
        engine,
        f"SELECT hhid, district, bizcircle, area_sqm, build_year, renovation, floor_pos, rooms"
        f" FROM listings WHERE city = '{MODEL_CITY}'",
    )
    df = preds.merge(listings, on="hhid", how="left")
    df["price_band"] = df["y_true"].map(lambda p: band_of(p, PRICE_BANDS))
    df["area_band"] = df["area_sqm"].map(lambda a: band_of(a, AREA_BANDS))
    df["age"] = AGE_REF_YEAR - df["build_year"]
    df["age_band"] = df["age"].map(lambda a: band_of(a, AGE_BANDS))
    df["abs_pct_err"] = (df["y_pred"] - df["y_true"]).abs() / df["y_true"] * 100

    overall = {
        "n": int(len(df)),
        "mae": round(float((df["y_pred"] - df["y_true"]).abs().mean()), 0),
        "mape_pct": round(float(df["abs_pct_err"].mean()), 2),
        "median_ape_pct": round(float(df["abs_pct_err"].median()), 2),
        "within_10pct": round(float((df["abs_pct_err"] <= 10).mean()), 4),
        "within_20pct": round(float((df["abs_pct_err"] <= 20).mean()), 4),
    }
    if "p10" in df.columns:
        overall["interval_coverage_80"] = round(
            float(((df["y_true"] >= df["p10"]) & (df["y_true"] <= df["p90"])).mean()), 4
        )

    result = {
        "model_city": MODEL_CITY,
        "overall": overall,
        "by_district": segment_errors(df, "district"),
        "by_price_band": segment_errors(df, "price_band"),
        "by_area_band": segment_errors(df, "area_band"),
        "by_age_band": segment_errors(df, "age_band"),
        "by_renovation": segment_errors(df, "renovation"),
        "by_rooms": segment_errors(df, "rooms"),
    }
    (REPORTS_DIR / "error_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 图表 ----
    sample = df.sample(min(5000, len(df)), random_state=42)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(sample["y_true"] / 1e4, sample["y_pred"] / 1e4, s=6, alpha=0.35, color="#2563eb")
    lim = [0, max(sample["y_true"].max(), sample["y_pred"].max()) / 1e4 * 1.05]
    ax.plot(lim, lim, "r--", lw=1)
    ax.set_xlabel("真实单价 (万/㎡)")
    ax.set_ylabel("预测单价 (万/㎡)")
    ax.set_title("预测 vs 真实(留出集抽样)")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "pred_vs_true.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    resid_pct = (df["y_pred"] - df["y_true"]) / df["y_true"] * 100
    ax.hist(resid_pct.clip(-60, 60), bins=60, color="#2563eb", alpha=0.85)
    ax.axvline(0, color="red", ls="--", lw=1)
    ax.set_xlabel("相对误差 % ((预测-真实)/真实)")
    ax.set_ylabel("房源数")
    ax.set_title("残差分布(截断在 ±60%)")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "residual_hist.png", dpi=120)
    plt.close(fig)

    seg_plots = [
        ("by_price_band", "err_by_price_band.png"),
        ("by_district", "err_by_district.png"),
    ]
    for seg_key, fname in seg_plots:
        rows = sorted(result[seg_key], key=lambda r: r["mae"])
        fig, ax = plt.subplots(figsize=(7, 4))
        labels = [r[next(iter(r))] for r in rows]
        ax.barh(labels, [r["mae"] for r in rows], color="#0ea5e9")
        ax.set_xlabel("MAE (元/㎡)")
        ax.set_title("分群误差 MAE")
        fig.tight_layout()
        fig.savefig(REPORTS_DIR / fname, dpi=120)
        plt.close(fig)

    print(json.dumps(result["overall"], ensure_ascii=False, indent=2))
    print("\nMAPE 最差分群 TOP5:")
    for r in result["by_district"][:5]:
        print(f"  {r['district']}: MAPE {r['mape_pct']}%  MAE {r['mae']:,.0f}  n={r['n']}")
    print("\n按价格段:")
    for r in result["by_price_band"]:
        print(f"  {r['price_band']}: MAPE {r['mape_pct']}%  bias {r['bias']:+,.0f}  n={r['n']}")
    print(f"\n完成 -> {REPORTS_DIR / 'error_analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
