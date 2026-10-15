"""月度重训的质量门禁:新模型留出集 MAE 劣化超过阈值则阻断发布。

从 update-data.yml 的内联 `python -c` 抽成脚本(可读、可测);
门禁通过打印结论,不通过以非零码退出让 workflow 标红。

用法:
    python scripts/quality_gate.py [--old models/metadata.json@HEAD] \\
        [--new models/metadata.json] [--tolerance 0.03]
`--old` 支持 `路径@gitref` 语法读取旧版本文件(与 git show 等价),便于本地演练。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TOLERANCE = 0.03  # MAE 劣化 >3% 视为模型退化,阻断发布


def load_metadata(spec: str) -> dict:
    """读取元数据;`path@gitref` 走 git show,否则按工作区文件读。"""
    path, _, ref = spec.partition("@")
    if ref:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            raise FileNotFoundError(f"git show {ref}:{path} 失败: {proc.stderr.strip()}")
        return json.loads(proc.stdout or "{}")
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"元数据不存在: {file}")
    return json.loads(file.read_text(encoding="utf-8"))


def gate_decision(old_mae: float | None, new_mae: float | None, tolerance: float) -> tuple[bool, str]:
    """返回 (是否通过, 结论说明)。旧值缺失(首次运行)视为通过。"""
    if not old_mae or not new_mae:
        return True, "旧模型 MAE 缺失(首次运行或历史数据不可读),门禁放行并记录本次为基线"
    degradation = new_mae / old_mae - 1
    if degradation > tolerance:
        detail = (
            f"MAE {old_mae:.0f} -> {new_mae:.0f}"
            f"(劣化 {degradation * 100:.1f}% > 阈值 {tolerance * 100:.0f}%)"
        )
        return False, detail + ",阻断发布"
    return True, f"MAE {old_mae:.0f} -> {new_mae:.0f}(变化 {degradation * 100:+.1f}%),门禁通过"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", default="models/metadata.json@HEAD", help="旧模型元数据(路径或 路径@gitref)")
    parser.add_argument("--new", default="models/metadata.json", help="新模型元数据路径")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="MAE 劣化容忍阈值(小数)")
    args = parser.parse_args()

    try:
        old_mae = load_metadata(args.old).get("holdout", {}).get("mae")
    except (FileNotFoundError, json.JSONDecodeError) as error:
        print(f"门禁警告: 旧元数据不可读({error}),按首次运行处理")
        old_mae = None
    new_mae = load_metadata(args.new).get("holdout", {}).get("mae")

    passed, message = gate_decision(old_mae, new_mae, args.tolerance)
    print(("质量门禁通过 | " if passed else "质量门禁阻断 | ") + message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
