"""A/B 工具:分流确定性、样本量公式、z 检验、SRM 卡方。"""

from __future__ import annotations

import pytest

from homevalue.ab import (
    analyze_rows,
    assign,
    required_n_per_arm,
    srm_chi_square,
    two_proportion_z_test,
)


def test_assign_is_deterministic_and_balanced():
    assert assign("user-42") == assign("user-42")
    counts = {"control": 0, "treatment": 0}
    for i in range(10_000):
        counts[assign(f"visitor-{i}")] += 1
    ratio = counts["treatment"] / 10_000
    assert 0.47 < ratio < 0.53  # 大样本下接近 50/50


def test_sample_size_matches_textbook_magnitude():
    # 基线 10%,MDE 2pp,alpha=0.05,power=0.8 -> 每臂约 3800(教科书量级)
    r = required_n_per_arm(0.10, 0.02)
    assert 3600 <= r.n_per_arm <= 4000
    assert r.n_per_arm == required_n_per_arm(0.10, 0.02).n_per_arm


def test_sample_size_grows_as_mde_shrinks():
    big = required_n_per_arm(0.10, 0.03).n_per_arm
    small = required_n_per_arm(0.10, 0.01).n_per_arm
    assert small > 3 * big  # MDE 减半,样本量约 4 倍


def test_z_test_detects_lift():
    res = two_proportion_z_test(conv_control=100, n_control=1000, conv_treatment=130, n_treatment=1000)
    assert res.rate_control == 0.10
    assert res.rate_treatment == 0.13
    assert abs(res.z - 2.10) < 0.1
    assert res.p_value < 0.05 and res.significant
    assert res.abs_lift == 0.03


def test_z_test_no_effect_not_significant():
    res = two_proportion_z_test(100, 1000, 102, 1000)
    assert not res.significant


def test_analyze_rows_aggregates():
    rows = [{"variant": "control", "converted": i % 10 == 0} for i in range(1000)]
    rows += [{"variant": "treatment", "converted": i % 7 == 0} for i in range(1000)]
    res = analyze_rows(rows)
    assert res.n_control == 1000 and res.n_treatment == 1000
    assert res.conv_control == 100 and res.conv_treatment == 143
    assert res.significant


def test_srm_balanced_traffic_passes():
    # 均衡流量:卡方=0, p=1
    r = srm_chi_square(500, 500)
    assert r.chi2 == 0.0
    assert r.p_value == 1.0
    assert not r.mismatched


def test_srm_mild_imbalance_within_noise():
    # 486/514 属正常波动(χ²≈0.78, p≈0.38)
    r = srm_chi_square(486, 514)
    assert not r.mismatched
    assert 0.3 < r.p_value < 0.45


def test_srm_severe_imbalance_flagged():
    # 450/550(χ²=10, p≈0.0016)必须报警——分流实现有 bug 的典型信号
    r = srm_chi_square(450, 550)
    assert r.mismatched
    assert r.p_value < 0.01


def test_srm_known_chi2_boundary():
    # 总量 10000 时偏移 d 的 χ² = 2d²/5000。α=0.05 的临界 χ²≈3.8415(即 d≈97.9):
    # d=97(χ²≈3.764, p≈0.0524)放行;d=100(χ²=4.0, p≈0.0455)报警。
    # 不取恰好压线(临界点)的值,避免浮点误差翻转判定
    assert not srm_chi_square(5097, 4903).mismatched
    assert srm_chi_square(5100, 4900).mismatched


def test_srm_non_default_expected_share():
    # 80/20 计划 split:60/40 的实现偏差应被识别(χ²≈25, p 极小)
    r = srm_chi_square(600, 400, expected_share=0.8)
    assert r.mismatched


def test_srm_rejects_degenerate_input():
    with pytest.raises(ValueError):
        srm_chi_square(0, 0)
    with pytest.raises(ValueError):
        srm_chi_square(10, 5, expected_share=1.5)


def test_srm_integrated_with_assign():
    # 真实分流函数跑 1 万 id,SRM 必须通过——把检查接进日常验证链路
    counts = {"control": 0, "treatment": 0}
    for i in range(10_000):
        counts[assign(f"visitor-{i}")] += 1
    assert not srm_chi_square(counts["control"], counts["treatment"]).mismatched
