"""生成合成链家风格快照 CSV(测试 / CI 冒烟 / 离线演示用)。

!!! 数据是合成的,绝不与真实数据混用于正式建模 !!。
列结构、取值形态与真实抓取文件一致,保证 ETL 全链路可跑通。

用法:
    python scripts/make_synth.py --n 5000 --out data/raw
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DISTRICTS = {
    "朝阳": (68000, ["望京", "亚运村", "CBD"]),
    "海淀": (76000, ["中关村", "五道口"]),
    "丰台": (52000, ["方庄", "丽泽"]),
    "通州": (41000, ["梨园", "北苑"]),
    "西城": (105000, ["金融街", "德胜门"]),
    "昌平": (38000, ["回龙观", "天通苑"]),
}
RENOVATION = ["精装", "简装", "毛坯", "其他"]
RENOVATION_P = [0.45, 0.35, 0.08, 0.12]
FLOOR_POS = ["低楼层", "中楼层", "高楼层", "顶层", "底层", "地下室"]
FLOOR_P = [0.22, 0.35, 0.25, 0.10, 0.06, 0.02]


def synth_snapshot(n: int, snapshot_date: str, seed: int, churn: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    districts = rng.choice(list(DISTRICTS), size=n, p=[0.28, 0.18, 0.18, 0.14, 0.07, 0.15])
    base = np.array([DISTRICTS[d][0] for d in districts], dtype=float)

    biz = np.array([rng.choice(DISTRICTS[d][1]) for d in districts])
    community = np.array([f"{b}家园{rng.integers(1, 12)}区" for b in biz])

    area = np.round(np.exp(rng.normal(4.25, 0.35, size=n)), 2).clip(28, 320)  # 对数正态面积
    rooms = np.clip(np.searchsorted([45, 70, 95, 130, 180], area), 0, 5) + 1
    halls = np.clip(rooms - rng.integers(0, 2, size=n), 0, rooms)

    year = rng.integers(1990, 2024, size=n)
    age = 2024 - year

    floor_pos = rng.choice(FLOOR_POS, size=n, p=FLOOR_P)
    total_floors = rng.integers(6, 33, size=n)
    level = [
        f"{p}(共{t}层)" if p != "地下室" else "地下室"
        for p, t in zip(floor_pos, total_floors, strict=False)
    ]

    fitment = rng.choice(RENOVATION, size=n, p=RENOVATION_P)
    direction = rng.choice(["南", "南 北", "东南", "南北", "西南", "东", "北"], size=n)

    floor_ord = np.select(
        [floor_pos == "地下室", floor_pos == "底层", floor_pos == "低楼层",
         floor_pos == "中楼层", floor_pos == "高楼层"],
        [0.0, 0.1, 0.3, 0.55, 0.8],
        default=0.95,
    )

    # 生成价格:地段 + 面积折减 + 房龄折旧 + 装修溢价 + 楼层 + 对数正态噪声
    reno_premium = np.select(
        [fitment == "精装", fitment == "简装", fitment == "毛坯"],
        [0.05, 0.01, -0.03],
        default=0.0,
    )
    log_price = (
        np.log(base)
        - 0.12 * (np.log(area) - np.log(80))
        - 0.008 * (age - 15)
        + reno_premium
        + 0.05 * (floor_ord - 0.5)
        + rng.normal(0, 0.12, size=n)
    )
    unit_price = np.round(np.exp(log_price), 0)
    total_price = np.round(unit_price * area / 10_000, 1)

    # 让一部分房源在下一个快照小幅调价
    if churn > 0:
        mask = rng.random(n) < churn
        unit_price[mask] = np.round(unit_price[mask] * (1 + rng.normal(-0.03, 0.03, mask.sum())), 0)
        total_price = np.round(unit_price * area / 10_000, 1)

    return pd.DataFrame(
        {
            "area": [d + "区" for d in districts],
            "title": [
                f"{c} {int(r)}室{int(h)}厅 {f} 采光好"
                for c, r, h, f in zip(community, rooms, halls, floor_pos, strict=False)
            ],
            "community": community,
            "position": biz,
            "tax": rng.choice(["满五年唯一", "满两年", "不满两年"], size=n, p=[0.55, 0.3, 0.15]),
            "total_price": total_price,
            "unit_price": unit_price,
            "hhid": np.arange(1_000_000, 1_000_000 + n),
            "link": [
                f"https://bj.lianjia.com/ershoufang/{h}.html"
                for h in np.arange(1_000_000, 1_000_000 + n)
            ],
            "hourseType": [f"{int(r)}室{int(h)}厅" for r, h in zip(rooms, halls, strict=False)],
            "hourseSize": area,
            "direction": direction,
            "fitment": fitment,
            "level": level,
            "buildTime": [f"{y}年建" for y in year],
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5000, help="每个快照的行数")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "raw")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i, (date, churn) in enumerate([("20240301", 0.0), ("20240901", 0.25)]):
        df = synth_snapshot(args.n, date, seed=args.seed + i, churn=churn)
        dest = args.out / f"bj__synthetic__{date.replace('-', '')}.csv"
        df.to_csv(dest, index=False, encoding="utf-8")
        print(f"[synth] {dest} rows={len(df):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
