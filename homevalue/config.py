"""集中管理路径与常量,支持环境变量覆盖(便于测试与部署)。"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

DB_PATH = Path(os.environ.get("HOMEVALUE_DB", DATA_PROCESSED / "listings.db"))
ARTIFACTS_DIR = Path(os.environ.get("HOMEVALUE_ARTIFACTS", PROJECT_ROOT / "models"))
_DEFAULT_CACHE = PROJECT_ROOT / "reports" / "analysis_cache.json"
ANALYSIS_CACHE = Path(os.environ.get("HOMEVALUE_ANALYSIS_CACHE", _DEFAULT_CACHE))
REPORTS_DIR = PROJECT_ROOT / "reports"
SQL_DIR = PROJECT_ROOT / "sql"
API_STATIC_DIR = PROJECT_ROOT / "api" / "static"

MODEL_VERSION = "1.0.0"

# 数据采集基准年,统一房龄口径(跨期训练时避免漂移)
AGE_REF_YEAR = 2024

# 建模主城市;沪/广/深数据用于多城市对比分析
MODEL_CITY = "bj"
