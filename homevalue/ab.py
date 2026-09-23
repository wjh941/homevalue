"""A/B 实验工具:确定性分流、样本量估算、双比例 z 检验。

配套设计文档见 experiments/ab_design.md,
仿真演示见 experiments/ab_simulate.py。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from statistics import NormalDist

VARIANTS = ("control", "treatment")


def assign(visitor_id: str, salt: str = "interval-vs-point-v1") -> str:
    """确定性 50/50 分流:同一 visitor_id 永远落在同一变体。"""
    digest = hashlib.md5(f"{salt}:{visitor_id}".encode()).hexdigest()
    return VARIANTS[int(digest, 16) % len(VARIANTS)]


@dataclass(frozen=True)
class SampleSizeResult:
    n_per_arm: int
    p_baseline: float
    mde: float
    alpha: float
    power: float


def required_n_per_arm(
    p_baseline: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> SampleSizeResult:
    """双比例检验每臂所需样本量(正态近似)。

    n = (z_{1-a/2} * sqrt(2*p*(1-p)) + z_power * sqrt(p1(1-p1)+p2(1-p2)))^2 / (p2-p1)^2
    其中 p = (p1+p2)/2。
    """
    if not 0 < p_baseline < 1 or mde <= 0:
        raise ValueError("需要 0 < p_baseline < 1 且 mde > 0")
    p1, p2 = p_baseline, p_baseline + mde
    if p2 >= 1:
        raise ValueError("p_baseline + mde 必须 < 1")
    nd = NormalDist()
    z_alpha = nd.inv_cdf(1 - alpha / 2)
    z_power = nd.inv_cdf(power)
    p_bar = (p1 + p2) / 2
    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_power * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    return SampleSizeResult(math.ceil(numerator / (p2 - p1) ** 2), p_baseline, mde, alpha, power)


@dataclass(frozen=True)
class ABResult:
    n_control: int
    conv_control: int
    n_treatment: int
    conv_treatment: int
    rate_control: float
    rate_treatment: float
    abs_lift: float
    z: float
    p_value: float
    significant: bool


def two_proportion_z_test(
    conv_control: int,
    n_control: int,
    conv_treatment: int,
    n_treatment: int,
    alpha: float = 0.05,
) -> ABResult:
    """双侧双比例 z 检验(合并比例估计方差)。"""
    if min(n_control, n_treatment) <= 0:
        raise ValueError("两组样本量都必须 > 0")
    r_c, r_t = conv_control / n_control, conv_treatment / n_treatment
    pooled = (conv_control + conv_treatment) / (n_control + n_treatment)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_control + 1 / n_treatment))
    z = 0.0 if se == 0 else (r_t - r_c) / se
    nd = NormalDist()
    p_value = 2 * (1 - nd.cdf(abs(z)))
    return ABResult(
        n_control,
        conv_control,
        n_treatment,
        conv_treatment,
        r_c,
        r_t,
        r_t - r_c,
        z,
        p_value,
        p_value < alpha,
    )


def analyze_rows(rows: list[dict], alpha: float = 0.05) -> ABResult:
    """分析实验日志,rows 元素形如 {"variant": "...", "converted": 0/1}。"""
    agg: dict[str, list[int]] = {v: [0, 0] for v in VARIANTS}  # variant -> [n, conversions]
    for r in rows:
        variant = r["variant"]
        if variant not in agg:
            raise ValueError(f"未知变体: {variant}")
        agg[variant][0] += 1
        agg[variant][1] += int(r["converted"])
    return two_proportion_z_test(
        agg["control"][1], agg["control"][0], agg["treatment"][1], agg["treatment"][0], alpha
    )
