"""A/B 设计的蒙特卡洛仿真:验证样本量与检验实现自洽。

运行: python experiments/ab_simulate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.ab import analyze_rows, assign, required_n_per_arm, two_proportion_z_test  # noqa: E402


def run_once(rng: np.random.Generator, n_per_arm: int, p_c: float, p_t: float) -> bool:
    control = rng.random(n_per_arm) < p_c
    treatment = rng.random(n_per_arm) < p_t
    rows = (
        [{"variant": "control", "converted": int(x)} for x in control]
        + [{"variant": "treatment", "converted": int(x)} for x in treatment]
    )
    return analyze_rows(rows).significant


def main() -> int:
    design = required_n_per_arm(p_baseline=0.10, mde=0.02)
    n = design.n_per_arm
    print(f"设计参数: 基线 {design.p_baseline:.0%}, MDE +{design.mde:.0%}, "
          f"alpha={design.alpha}, power={design.power} -> 每臂 {n} 样本")

    rng = np.random.default_rng(42)
    sims = 1000

    sig_effect = sum(run_once(rng, n, 0.10, 0.12) for _ in range(sims))
    print(f"真实效应 +2pp : 经验功效 = {sig_effect / sims:.1%}(目标 ~{design.power:.0%})")

    sig_null = sum(run_once(rng, n, 0.10, 0.10) for _ in range(sims))
    print(f"真实无效应    : 假阳性率 = {sig_null / sims:.1%}(目标 ~{design.alpha:.0%})")

    counts = {"control": 0, "treatment": 0}
    for i in range(10_000):
        counts[assign(f"visitor-{i}")] += 1
    print(f"分流均衡    : {counts}(占比 {counts['treatment'] / 10_000:.1%})")

    demo = two_proportion_z_test(378, n, 446, n)
    print(f"示例分析    : 互动率 {demo.rate_control:.1%} -> {demo.rate_treatment:.1%}, "
          f"提升 {demo.abs_lift:+.1%}, z={demo.z:.2f}, p={demo.p_value:.4f}, "
          f"显著={demo.significant}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
