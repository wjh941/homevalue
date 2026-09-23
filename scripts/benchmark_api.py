"""压测 /api/predict,输出 P50 / P95 / P99 延迟。

用法(先启动服务):
    uvicorn api.main:app --port 8000
    python scripts/benchmark_api.py --n 300 --concurrency 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from homevalue.config import DB_PATH, MODEL_CITY, REPORTS_DIR  # noqa: E402
from homevalue.db import get_engine, read_query  # noqa: E402

PAYLOAD_KEYS = [
    "district", "bizcircle", "rooms", "halls", "area_sqm",
    "floor_pos", "total_floors", "dir_main", "renovation", "build_year",
]

# 绕过系统代理(如 Clash),否则 127.0.0.1 的请求会被代理劫持而超时
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sample_payloads(n: int) -> list[dict]:
    engine = get_engine(DB_PATH)
    df = read_query(
        engine,
        "SELECT district, bizcircle, rooms, halls, area_sqm, floor_pos, total_floors,"
        " dir_main, renovation, build_year FROM listings WHERE city = '" + MODEL_CITY + "'",
    )
    df = df.fillna({"bizcircle": "未知", "total_floors": 6, "build_year": 2005,
                    "floor_pos": "中楼层", "dir_main": "南"})
    df = df.sample(n=min(n, len(df)), random_state=7)
    return [{k: (None if v is np.nan else v) for k, v in row.items()}
            for row in df[PAYLOAD_KEYS].to_dict("records")]


def post_once(base: str, payload: dict, timeout: float = 10.0) -> tuple[bool, float]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/predict", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.perf_counter()
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            resp.read()
        return True, (time.perf_counter() - t0) * 1000
    except Exception:  # noqa: BLE001
        return False, (time.perf_counter() - t0) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    payloads = sample_payloads(args.n)
    print(f"压测 {len(payloads)} 请求,并发 {args.concurrency} -> {args.base}/api/predict")

    latencies: list[float] = []
    errors = 0
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for ok, ms in pool.map(lambda p: post_once(args.base, p), payloads):
            errors += 0 if ok else 1
            latencies.append(ms)
    wall = time.perf_counter() - t0

    arr = np.array(latencies)
    result = {
        "n_requests": len(latencies),
        "concurrency": args.concurrency,
        "errors": errors,
        "wall_seconds": round(wall, 2),
        "rps": round(len(latencies) / wall, 1),
        "p50_ms": round(float(np.percentile(arr, 50)), 1),
        "p95_ms": round(float(np.percentile(arr, 95)), 1),
        "p99_ms": round(float(np.percentile(arr, 99)), 1),
        "mean_ms": round(float(statistics.mean(latencies)), 1),
    }
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "api_benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
