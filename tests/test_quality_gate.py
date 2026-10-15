"""质量门禁单元测试:MAE 劣化判定与边界。"""

from __future__ import annotations

import pytest

from scripts.quality_gate import gate_decision


def test_first_run_without_old_mae_passes():
    passed, msg = gate_decision(None, 5700.0, 0.03)
    assert passed
    assert "首次运行" in msg


def test_improvement_passes():
    passed, msg = gate_decision(6000.0, 5700.0, 0.03)
    assert passed
    assert "-5.0%" in msg


def test_within_tolerance_passes():
    passed, msg = gate_decision(6000.0, 6100.0, 0.03)
    assert passed
    assert "+1.7%" in msg


def test_degradation_beyond_tolerance_blocks():
    passed, msg = gate_decision(6000.0, 6300.0, 0.03)
    assert not passed
    assert "阻断" in msg


def test_exactly_at_tolerance_passes():
    # 恰好在阈值上不算劣化——判定条件是严格大于
    # (用二进制可精确表示的 0.5/1000/1500,避免 1.03 这类浮点不可精确表示值干扰边界)
    passed, _msg = gate_decision(1000.0, 1500.0, 0.5)
    assert passed


def test_zero_new_mae_treated_as_missing():
    passed, msg = gate_decision(6000.0, 0, 0.03)
    assert passed
    assert "首次运行" in msg


@pytest.mark.parametrize("bad", [None, 0])
def test_zero_or_none_old_mae_passes(bad):
    passed, _msg = gate_decision(bad, 5700.0, 0.03)
    assert passed
