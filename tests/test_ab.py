"""A/B 工具:分流确定性、样本量公式、z 检验。"""

from __future__ import annotations

from homevalue.ab import analyze_rows, assign, required_n_per_arm, two_proportion_z_test


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
