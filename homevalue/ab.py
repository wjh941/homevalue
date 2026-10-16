"""A/B 实验工具:确定性分流、样本量估算、双比例 z 检验、多类别卡方拟合优度。

配套设计文档见 experiments/ab_design.md,
仿真演示见 experiments/ab_simulate.py。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
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
class SRMResult:
    n_control: int
    n_treatment: int
    expected_share: float
    chi2: float
    p_value: float
    mismatched: bool


def srm_chi_square(
    n_control: int,
    n_treatment: int,
    expected_share: float = 0.5,
    alpha: float = 0.05,
) -> SRMResult:
    """样本比失配(SRM)卡方检验:两臂流量比显著偏离预期,说明分流实现有 bug,
    此时一切转化率对比都不可信——任何效果分析的前置检查(ab_design.md 的 SRM 约束)。

    卡方拟合优度,自由度 1 时 p = 2(1-Φ(√χ²)),继续零依赖(不用 scipy)。
    """
    if n_control < 0 or n_treatment < 0 or (n_control + n_treatment) == 0:
        raise ValueError("两臂样本数必须 >= 0 且合计 > 0")
    if not 0 < expected_share < 1:
        raise ValueError("expected_share 必须在 (0,1)")
    total = n_control + n_treatment
    e_c = total * expected_share
    e_t = total - e_c
    chi2 = (n_control - e_c) ** 2 / e_c + (n_treatment - e_t) ** 2 / e_t
    p_value = 2 * (1 - NormalDist().cdf(math.sqrt(chi2))) if chi2 > 0 else 1.0
    return SRMResult(n_control, n_treatment, expected_share, chi2, p_value, p_value < alpha)


@dataclass(frozen=True)
class ChiSquareResult:
    chi2: float
    dof: int
    p_value: float
    significant: bool
    n_observed: int
    n_categories: int
    observed: tuple[float, ...]
    expected: tuple[float, ...]


def _gamma_p_series(a: float, x: float, itmax: int = 500, eps: float = 3e-9) -> float:
    """正则化下不完全伽马 P(a,x),级数展开(x < a+1 时收敛快),项全正无相消。"""
    total = delta = 1.0 / a
    ap = a
    for _ in range(itmax):
        ap += 1
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * eps:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_q_fraction(a: float, x: float, itmax: int = 500, eps: float = 3e-9) -> float:
    """正则化上不完全伽马 Q(a,x),修正 Lentz 连分式(DLMF 8.9.2),大 x 区段。"""
    tiny = 1e-300
    f = c = tiny
    d = 0.0
    b = x + 1 - a
    for n in range(1, itmax + 1):
        an = 1.0 if n == 1 else -(n - 1) * (n - 1 - a)
        d = b + an * d
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = c * d
        f *= delta
        if abs(delta - 1) < eps:
            break
        b += 2.0
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * f


def chi2_sf(x: float, dof: int) -> float:
    """卡方分布右尾概率 P(X >= x),自由度 dof。Q(dof/2, x/2),纯标准库实现。"""
    if x <= 0:
        return 1.0
    a, half = dof / 2.0, x / 2.0
    return 1.0 - _gamma_p_series(a, half) if half < a + 1 else _gamma_q_fraction(a, half)


def chi_square_gof(
    observed: Sequence[float],
    expected: Sequence[float],
    alpha: float = 0.05,
) -> ChiSquareResult:
    """多类别卡方拟合优度检验:srm_chi_square 的多类别泛化。

    observed/expected 按类别一一对齐;expected 传计数(与 observed 同总量)
    或占比(自动按 observed 总量缩放)。自由度 = 类别数 - 1,
    p 值用正则化不完全伽马计算,不引入 scipy。典型用途:线上预测的区分布
    是否显著偏离训练集分布(漂移监控 /api/drift/summary)。
    """
    if len(observed) != len(expected) or len(observed) < 2:
        raise ValueError("observed/expected 必须等长且至少 2 个类别")
    n_obs = float(sum(observed))
    n_exp = float(sum(expected))
    if n_obs <= 0:
        raise ValueError("observed 合计必须 > 0")
    if n_exp <= 0:
        raise ValueError("expected 合计必须 > 0")
    scale = n_obs / n_exp
    exp_adj = [e * scale for e in expected]
    if any(e <= 0 for e in exp_adj):
        raise ValueError("每个类别的期望计数必须 > 0")
    chi2 = sum((float(o) - e) ** 2 / e for o, e in zip(observed, exp_adj, strict=True))
    dof = len(observed) - 1
    p_value = chi2_sf(chi2, dof)
    return ChiSquareResult(
        chi2=chi2,
        dof=dof,
        p_value=p_value,
        significant=p_value < alpha,
        n_observed=int(n_obs),
        n_categories=len(observed),
        observed=tuple(float(o) for o in observed),
        expected=tuple(exp_adj),
    )


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
